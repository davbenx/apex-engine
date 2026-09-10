"""
backend_decision_preview.py — Anteprima in SOLA LETTURA di cosa calcolerebbe
backend.py.main() con i dati di mercato di oggi, richiesta esplicitamente
dall'utente dopo aver chiesto perche' non fosse possibile forzare un run di
produzione reale da questa sessione (risposta: muta stato reale di
portafoglio/ordini, puo' inviare notifiche Telegram, e puo' disallineare la
macchina a stati venerdi'-decide/lunedi'-esegue dal sistema di produzione
vero, con cui questa sandbox non puo' verificare di essere sincronizzata).

Questo script fa SOLO fetch e calcolo, MAI scrittura:
- legge (non scrive) apex_data.json/portfolio.json per il contesto (isteresi
  precedente, basket detenuto) — load_json_safe, mai save_json_atomic;
- fa fetch LIVE dei prezzi (stessa fetch_bulk_parallel/get_sp500_tickers/
  fetch_sector_map di produzione) — nessun effetto collaterale, sono letture;
- chiama compute_v2_macro_signal/select_low_beta_basket (le stesse funzioni
  di produzione, nessuna duplicazione di logica) e STAMPA il risultato;
- NON chiama save_json_atomic, NON chiama send_telegram_alert, NON tocca
  in alcun modo portfolio.json/apex_data.json/equity.json.

Nota: calcola SEMPRE l'allocazione/basket che risulterebbero OGGI, anche nei
giorni in cui backend.py in produzione non prenderebbe una nuova decisione
(should_decide=False) — e' un'anteprima diagnostica, non una simulazione
esatta del "cosa succederebbe se girasse ora" (quella dipende anche da
should_decide/deciding_new/executing_pending, stato che qui non alteriamo).
"""

from __future__ import annotations

from backend import (
    compute_v2_macro_signal, select_low_beta_basket, V2_CLASS_TICKER, V2_EQUITY_TOP_N,
    fetch_bulk_parallel, get_sp500_tickers, fetch_sector_map,
    DISPLAY_TICKERS, MAX_WORKERS_CRYPTO, MAX_WORKERS_DEFAULT,
    APEX_DATA_FILE, PORTFOLIO_FILE, load_json_safe,
)


def main():
    print("=" * 78)
    print("ANTEPRIMA SOLA LETTURA — nessuna scrittura, nessuna notifica Telegram")
    print("=" * 78)

    old_data = load_json_safe(APEX_DATA_FILE, default=None)
    prev_state = (old_data or {}).get("v2_state", {}) or {}
    prev_hysteresis = prev_state.get("hysteresis", {})
    prev_basket = prev_state.get("basket", [])

    pf = load_json_safe(PORTFOLIO_FILE, default={"open_positions": {}, "trade_history": []})
    held_eq = [t for t in pf.get("open_positions", {}).keys() if t not in ("IEF", "GLD", "BTC")]

    print("\n[1/3] Fetch live segnale macro (SPY/IEF/GLD/BTC-USD)...")
    signal_tickers = list(dict.fromkeys(list(V2_CLASS_TICKER.values()) + DISPLAY_TICKERS))
    b_data = fetch_bulk_parallel(signal_tickers, max_workers=MAX_WORKERS_CRYPTO)

    for t in V2_CLASS_TICKER.values():
        if t in b_data and not b_data[t].empty:
            print(f"  {t}: {float(b_data[t]['Close'].iloc[-1]):.2f} (ultima chiusura {b_data[t].index[-1].date()})")
        else:
            print(f"  {t}: dati non disponibili")

    print("\n[2/3] compute_v2_macro_signal (stessa funzione di produzione, default 50%/22%)...")
    alloc, new_hysteresis, debug = compute_v2_macro_signal(b_data, prev_hysteresis_state=prev_hysteresis)
    print(f"  Allocazione risultante: {alloc}")
    for cls, info in debug.items():
        if cls.startswith("_"):
            continue
        print(f"    {cls}: {info}")

    if alloc.get("Equities", 0) > 0:
        print(f"\n[3/3] Classe Equity attiva ({alloc['Equities']:.1f}%) — fetch live S&P 500 + settori per anteprima basket low-beta...")
        eq_ticks = list(set(get_sp500_tickers() + held_eq))
        eq_data = fetch_bulk_parallel(eq_ticks, max_workers=MAX_WORKERS_DEFAULT)
        sector_of = fetch_sector_map(list(eq_data.keys()), max_workers=MAX_WORKERS_DEFAULT)
        spy_df = b_data.get("SPY")
        basket = select_low_beta_basket(eq_data, spy_df, top_n=V2_EQUITY_TOP_N, prev_tickers=set(held_eq), sector_of=sector_of)
        print(f"\n  Basket low-beta risultante OGGI ({len(basket)} titoli):")
        for row in basket:
            print(f"    {row['Ticker']:<8} beta vs SPY: {row['Beta (vs SPY)']:>7.3f}   prezzo: ${row['Prezzo ($)']:.2f}")
        prev_set = {b["Ticker"] for b in prev_basket} if isinstance(prev_basket, list) else set()
        new_set = {b["Ticker"] for b in basket}
        added, removed = new_set - prev_set, prev_set - new_set
        if added or removed:
            print(f"\n  Rispetto al basket precedentemente registrato: +{sorted(added)}  -{sorted(removed)}")
        else:
            print("\n  Nessuna variazione rispetto al basket precedentemente registrato.")
    else:
        print("\n[3/3] Classe Equity NON attiva nell'allocazione risultante — nessun basket da mostrare.")

    print("\n" + "=" * 78)
    print("FINE ANTEPRIMA — nessun file scritto, nessuna notifica inviata.")
    print("=" * 78)


if __name__ == "__main__":
    main()
