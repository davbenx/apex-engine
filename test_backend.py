"""
test_backend.py — Test su dati sintetici per il tracking del NAV in backend.py,
introdotti dopo aver trovato un bug reale in produzione: il NAV veniva ricalcolato
ogni notte da zero (capitale iniziale + P&L storico su base di capitale fissa),
ignorando la crescita composta — causa di un crollo fittizio del NAV mostrato in
dashboard il giorno della migrazione v1->v2 (vedi APEX_V2_SPEC.md §8.3-bis).
"""
import json
import os

import backend


def _isolate_files(tmp_dir):
    os.makedirs(tmp_dir, exist_ok=True)
    backend.PORTFOLIO_FILE = os.path.join(tmp_dir, "portfolio.json")
    backend.EQUITY_FILE = os.path.join(tmp_dir, "equity.json")


def test_nav_compounds_with_weighted_daily_return():
    pf = {
        "nav_usd": 100000.0,
        "open_positions": {"AAPL": {"weight": 0.5, "current_price": 100.0, "entry_price": 100.0, "is_crypto": False}},
        "trade_history": [],
    }
    nav = backend.mark_to_market_and_compound_nav(pf, {"AAPL": 110.0})
    assert abs(nav - 105000.0) < 1e-6, f"atteso 105000.0, ottenuto {nav}"
    assert pf["open_positions"]["AAPL"]["current_price"] == 110.0


def test_nav_bootstraps_from_equity_history_when_missing(tmp_path=None):
    _isolate_files("/tmp/apex_test_backend_bootstrap")
    json.dump({"history": [{"date": "2026-01-01", "value": 50000.0}]}, open(backend.EQUITY_FILE, "w"))
    pf = {"open_positions": {}, "trade_history": []}
    nav = backend.mark_to_market_and_compound_nav(pf, {})
    assert nav == 50000.0


def test_rotation_deducts_turnover_cost_from_nav():
    _isolate_files("/tmp/apex_test_backend_rotation")
    json.dump({
        "v2_migrated": True,
        "nav_usd": 100000.0,
        "open_positions": {
            "AAPL": {"weight": 0.5, "entry_price": 100.0, "current_price": 100.0, "is_crypto": False, "stop_loss": 0.0, "entry_date": "2026-01-01"},
        },
        "trade_history": [],
    }, open(backend.PORTFOLIO_FILE, "w"))

    allocations = {"Equities": 0.0, "Bonds": 0.0, "Gold": 0.0, "Crypto": 100.0}
    backend.update_portfolio(allocations, [], {"BTC-USD": 50000.0}, "2026-01-08")
    pf_after = json.load(open(backend.PORTFOLIO_FILE))

    expected_cost_frac = 0.5 * (10.0 / 10000.0) + 1.0 * (8.0 / 10000.0)  # chiude AAPL (10bps) + apre BTC (8bps)
    expected_nav = 100000.0 * (1.0 - expected_cost_frac)
    assert abs(pf_after["nav_usd"] - expected_nav) < 1e-6, f"atteso {expected_nav}, ottenuto {pf_after['nav_usd']}"


def test_rotation_without_turnover_leaves_nav_unchanged():
    _isolate_files("/tmp/apex_test_backend_no_rotation")
    json.dump({
        "v2_migrated": True,
        "nav_usd": 77777.0,
        "open_positions": {
            "BTC": {"weight": 1.0, "entry_price": 50000.0, "current_price": 50000.0, "is_crypto": True, "stop_loss": 0.0, "entry_date": "2026-01-01"},
        },
        "trade_history": [],
    }, open(backend.PORTFOLIO_FILE, "w"))

    allocations = {"Equities": 0.0, "Bonds": 0.0, "Gold": 0.0, "Crypto": 100.0}
    backend.update_portfolio(allocations, [], {"BTC-USD": 51000.0}, "2026-01-08")
    pf_after = json.load(open(backend.PORTFOLIO_FILE))
    assert pf_after["nav_usd"] == 77777.0  # nessuna rotazione (stesso peso target) -> nessun costo


def test_weight_increase_blends_pmc_and_costs_only_the_delta():
    """
    Aumento di peso 5%->8%, entry 100 -> prezzo attuale 120: deve comprare SOLO il
    3% aggiuntivo (non richiudere l'intera posizione all'8%), aggiornare il costo
    medio ponderato (PMC) sulle azioni combinate, e mantenere entry_date invariata.
    Verifica indipendente: 500 azioni a costo 100 ($50k su NAV $1M) + 250 nuove
    azioni a $120 ($30k) = 750 azioni, costo totale $80k -> PMC $106.667/azione.
    """
    _isolate_files("/tmp/apex_test_backend_pmc_increase")
    json.dump({
        "v2_migrated": True, "nav_usd": 1000000.0,
        "open_positions": {
            "AAPL": {"weight": 0.05, "entry_price": 100.0, "current_price": 100.0, "is_crypto": False, "stop_loss": 0.0, "entry_date": "2026-01-01"},
        },
        "trade_history": [],
    }, open(backend.PORTFOLIO_FILE, "w"))

    allocations = {"Equities": 8.0, "Bonds": 0.0, "Gold": 0.0, "Crypto": 0.0}
    backend.update_portfolio(allocations, [{"Ticker": "AAPL"}], {"AAPL": 120.0}, "2026-02-01")
    pf_after = json.load(open(backend.PORTFOLIO_FILE))
    pos = pf_after["open_positions"]["AAPL"]

    assert abs(pos["entry_price"] - 106.6667) < 0.01, f"PMC atteso ~106.67, ottenuto {pos['entry_price']}"
    assert pos["entry_date"] == "2026-01-01", "l'incremento non deve azzerare la data di ingresso originale"
    assert pos["weight"] == 0.08
    assert pf_after["trade_history"] == [], "un incremento non e' una vendita: nessun evento tassabile da registrare"

    expected_cost_frac = 0.03 * (10.0 / 10000.0)  # solo il 3% aggiunto, non l'8% totale
    expected_nav = 1000000.0 * (1.0 - expected_cost_frac)
    assert abs(pf_after["nav_usd"] - expected_nav) < 1e-3, f"atteso {expected_nav}, ottenuto {pf_after['nav_usd']}"


def test_weight_decrease_trims_partially_and_preserves_cost_basis():
    """
    Riduzione di peso 10%->6%, entry 100 -> prezzo attuale 150: deve vendere SOLO
    il 4% in eccesso (non l'intera posizione), realizzare la plusvalenza solo su
    quella quota, e lasciare le azioni restanti con costo/data d'ingresso originali
    — cosi' la tassazione viene rinviata sulla parte non venduta, non anticipata.
    """
    _isolate_files("/tmp/apex_test_backend_pmc_decrease")
    json.dump({
        "v2_migrated": True, "nav_usd": 1000000.0,
        "open_positions": {
            "MSFT": {"weight": 0.10, "entry_price": 100.0, "current_price": 100.0, "is_crypto": False, "stop_loss": 0.0, "entry_date": "2026-01-01"},
        },
        "trade_history": [],
    }, open(backend.PORTFOLIO_FILE, "w"))

    allocations = {"Equities": 6.0, "Bonds": 0.0, "Gold": 0.0, "Crypto": 0.0}
    backend.update_portfolio(allocations, [{"Ticker": "MSFT"}], {"MSFT": 150.0}, "2026-02-01")
    pf_after = json.load(open(backend.PORTFOLIO_FILE))
    pos = pf_after["open_positions"]["MSFT"]

    assert pos["entry_price"] == 100.0, "il costo medio delle azioni RIMASTE non deve cambiare al trim"
    assert pos["entry_date"] == "2026-01-01", "il trim parziale non deve azzerare la data di ingresso"
    assert pos["weight"] == 0.06

    assert len(pf_after["trade_history"]) == 1
    trade = pf_after["trade_history"][0]
    assert abs(trade["weight"] - 0.04) < 1e-9, "deve registrare solo la quota VENDUTA (4%), non l'intera posizione (10%)"
    assert trade["profit_pct"] == 50.0
    assert trade["reason"] == "⚖️ Ribilanciamento mensile (trim parziale)"

    expected_cost_frac = 0.04 * (10.0 / 10000.0)  # solo il 4% venduto, non il 10% totale
    expected_nav = 1000000.0 * (1.0 - expected_cost_frac)
    assert abs(pf_after["nav_usd"] - expected_nav) < 1e-3


def test_full_exit_still_logs_the_entire_position():
    _isolate_files("/tmp/apex_test_backend_full_exit")
    json.dump({
        "v2_migrated": True, "nav_usd": 100000.0,
        "open_positions": {
            "TSLA": {"weight": 0.05, "entry_price": 200.0, "current_price": 200.0, "is_crypto": False, "stop_loss": 0.0, "entry_date": "2026-01-01"},
        },
        "trade_history": [],
    }, open(backend.PORTFOLIO_FILE, "w"))

    allocations = {"Equities": 0.0, "Bonds": 0.0, "Gold": 0.0, "Crypto": 0.0}
    backend.update_portfolio(allocations, [], {"TSLA": 250.0}, "2026-02-01")
    pf_after = json.load(open(backend.PORTFOLIO_FILE))

    assert "TSLA" not in pf_after["open_positions"]
    assert len(pf_after["trade_history"]) == 1
    trade = pf_after["trade_history"][0]
    assert abs(trade["weight"] - 0.05) < 1e-9, "l'uscita totale deve registrare l'intera posizione"
    assert trade["profit_pct"] == 25.0
    assert trade["reason"] == "🔄 Uscito da basket/classe disattivata"


def test_tiny_weight_change_within_eps_does_not_trade():
    _isolate_files("/tmp/apex_test_backend_eps")
    json.dump({
        "v2_migrated": True, "nav_usd": 100000.0,
        "open_positions": {
            "NVDA": {"weight": 0.05, "entry_price": 100.0, "current_price": 100.0, "is_crypto": False, "stop_loss": 0.0, "entry_date": "2026-01-01"},
        },
        "trade_history": [],
    }, open(backend.PORTFOLIO_FILE, "w"))

    allocations = {"Equities": 5.0000001, "Bonds": 0.0, "Gold": 0.0, "Crypto": 0.0}
    backend.update_portfolio(allocations, [{"Ticker": "NVDA"}], {"NVDA": 110.0}, "2026-02-01")
    pf_after = json.load(open(backend.PORTFOLIO_FILE))
    pos = pf_after["open_positions"]["NVDA"]

    assert pf_after["trade_history"] == []
    assert pos["entry_price"] == 100.0
    assert pos["current_price"] == 110.0, "il prezzo di mercato deve comunque aggiornarsi anche senza ribilanciare"
    assert pf_after["nav_usd"] == 100000.0, "nessun ribilanciamento -> nessun costo"


if __name__ == "__main__":
    import inspect
    fns = [f for name, f in list(globals().items()) if name.startswith("test_") and inspect.isfunction(f)]
    failed = 0
    for f in fns:
        try:
            f()
            print("PASS", f.__name__)
        except Exception as e:
            failed += 1
            print("FAIL", f.__name__, "->", repr(e))
    print(f"{len(fns)} tests, failed: {failed}")
