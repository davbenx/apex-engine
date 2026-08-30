"""
test_backend.py — Test su dati sintetici per il tracking del NAV in backend.py,
introdotti dopo aver trovato un bug reale in produzione: il NAV veniva ricalcolato
ogni notte da zero (capitale iniziale + P&L storico su base di capitale fissa),
ignorando la crescita composta — causa di un crollo fittizio del NAV mostrato in
dashboard il giorno della migrazione v1->v2 (vedi APEX_V2_SPEC.md §8.3-bis).
"""
import datetime
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


def test_position_weight_drifts_with_price_between_rebalances():
    """
    "weight" non deve restare congelato al target dell'ultimo ribilanciamento — un
    vincitore deve pesare di piu' nei giorni successivi, non essere sempre trattato
    al suo peso originale. Verificato a mano: A e B partono al 50%, A guadagna 10%
    per 2 giorni consecutivi, B resta piatta -> NAV vero $110,50 (non $110,25, che
    sarebbe il risultato del vecchio bug a peso congelato).
    """
    pf = {
        "nav_usd": 100.0,
        "open_positions": {
            "A": {"weight": 0.5, "current_price": 100.0, "entry_price": 100.0, "is_crypto": False},
            "B": {"weight": 0.5, "current_price": 100.0, "entry_price": 100.0, "is_crypto": False},
        },
        "trade_history": [],
    }
    nav1 = backend.mark_to_market_and_compound_nav(pf, {"A": 110.0, "B": 100.0})
    assert abs(nav1 - 105.0) < 1e-9
    assert abs(pf["open_positions"]["A"]["weight"] - 55.0 / 105.0) < 1e-9, "il peso di A deve crescere con il suo guadagno"
    assert abs(pf["open_positions"]["B"]["weight"] - 50.0 / 105.0) < 1e-9, "il peso di B deve scendere (stesso valore, NAV totale piu' grande)"

    nav2 = backend.mark_to_market_and_compound_nav(pf, {"A": 121.0, "B": 100.0})
    assert abs(nav2 - 110.5) < 1e-6, f"atteso 110.5 (compounding vero), ottenuto {nav2}"


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


def test_update_equity_curve_marks_new_entries_as_live(tmp_path):
    """generate_v2_track_record.py (replay storico) scrive le sue voci
    direttamente, mai tramite update_equity_curve, quindi non porta mai
    "live" -> app.py usa questo campo per distinguere onestamente
    simulazione da forward-tracking reale (vedi APEX_V2_SPEC.md §24)."""
    _isolate_files(str(tmp_path))

    backend.update_equity_curve(100000.0, "2026-08-25")
    eq = json.load(open(backend.EQUITY_FILE))
    assert eq["history"][0]["live"] is True

    backend.update_equity_curve(101000.0, "2026-08-26")
    eq = json.load(open(backend.EQUITY_FILE))
    assert len(eq["history"]) == 2
    assert eq["history"][1]["live"] is True
    assert eq["history"][1]["open"] == 100000.0, "l'apertura del nuovo giorno deve partire dalla chiusura precedente"

    # stesso giorno rieseguito (es. piu' run nella stessa giornata) -> aggiorna
    # l'ultima voce e la mantiene marcata live, non ne crea una nuova.
    backend.update_equity_curve(101500.0, "2026-08-26")
    eq = json.load(open(backend.EQUITY_FILE))
    assert len(eq["history"]) == 2
    assert eq["history"][1]["live"] is True
    assert eq["history"][1]["close"] == 101500.0


def test_should_decide_fires_once_in_month_end_window_even_if_execution_slips():
    # Bug reale trovato in produzione (APEX_V2_SPEC.md §8.13): un'esecuzione schedulata
    # pensata per l'ultimo venerdi' del mese puo' slittare oltre mezzanotte UTC e finire
    # per partire di sabato. Con un controllo sul solo "e' venerdi' adesso" la decisione
    # mensile verrebbe saltata per l'intero mese. La finestra deve catturarla comunque.
    last_friday_of_aug_2026 = datetime.datetime(2026, 8, 28, 6, 27)  # slittato da venerdi' 23:00 UTC
    saturday_after = datetime.datetime(2026, 8, 29, 3, 58)
    prev_state = {"last_decision_month": None}

    assert backend.compute_should_decide(last_friday_of_aug_2026, prev_state, just_migrating=False) is True
    # dopo la decisione, lo stato persiste il mese gestito: la stessa finestra non
    # ridecide una seconda volta nello stesso mese, anche se l'esecuzione successiva
    # cade ancora dentro gli ultimi giorni del mese.
    prev_state["last_decision_month"] = "2026-08"
    assert backend.compute_should_decide(saturday_after, prev_state, just_migrating=False) is False


def test_should_decide_false_mid_month():
    mid_month = datetime.datetime(2026, 8, 15, 12, 0)
    assert backend.compute_should_decide(mid_month, {"last_decision_month": None}, just_migrating=False) is False


def test_should_decide_true_when_just_migrating_regardless_of_date():
    mid_month = datetime.datetime(2026, 8, 15, 12, 0)
    assert backend.compute_should_decide(mid_month, {"last_decision_month": "2026-08"}, just_migrating=True) is True


def test_executing_pending_waits_for_a_real_new_market_bar():
    # Bug reale trovato in produzione (APEX_V2_SPEC.md §8.14): il motore decideva ed
    # eseguiva nella STESSA esecuzione, usando l'ultima chiusura disponibile — se
    # l'esecuzione cade di venerdi' (il caso comune), decisione ed esecuzione usano lo
    # STESSO prezzo di chiusura, un ritardo zero mai testato/validato nei backtest
    # (che usano sempre almeno un giorno di borsa di ritardo tra segnale ed esecuzione).
    pending = {"decided_date": "2026-08-28", "allocations": {"Equities": 20.0}}

    # nessuna decisione in attesa -> mai in esecuzione
    assert backend.compute_executing_pending(None, "2026-08-31") is False

    # stessa barra del giorno della decisione (es. esecuzione ritardata nel weekend,
    # nessun nuovo giorno di borsa e' ancora passato) -> resta in attesa
    assert backend.compute_executing_pending(pending, "2026-08-28") is False

    # nessun dato di mercato disponibile -> resta in attesa, non esegue alla cieca
    assert backend.compute_executing_pending(pending, None) is False

    # prima barra di borsa realmente successiva (il lunedi' seguente) -> esegue
    assert backend.compute_executing_pending(pending, "2026-08-31") is True


def test_weekly_due_tolerates_scheduling_delay_past_a_weekday_boundary():
    # Stesso bug lato notifica Telegram: l'heartbeat settimanale non deve dipendere da
    # "e' venerdi' adesso" (falso se l'esecuzione slitta di sabato), ma dai giorni
    # trascorsi dall'ultimo invio riuscito.
    assert backend.compute_weekly_due("2026-08-29", "2026-08-22") is True  # 7gg, dovuto
    assert backend.compute_weekly_due("2026-08-25", "2026-08-22") is False  # 3gg, non ancora
    assert backend.compute_weekly_due("2026-08-29", None) is True  # mai inviato prima


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
