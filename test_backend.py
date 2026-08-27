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
