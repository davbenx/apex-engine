"""
page_venture.py — Dashboard Venture Satellite Altcoin
================================================================================
Interfaccia istituzionale dark glassmorphism per la gestione del portafoglio
Venture Satellite Altcoin asimmetrico:
- Controllo del budget ring-fenced (default 2% Net Worth)
- Monitoraggio delle posizioni e stato Free-Ride (+100% / 2x)
- Alert automatici delle Milestone (+300%, +700%, +1500%) e Trailing Stop
- Registrazione nuovi ingressi slot e modulo di riciclo profitti
================================================================================
"""

import os
import datetime
import glob
import pandas as pd
import streamlit as st
import yfinance as yf

import altcoin_venture_engine
from altcoin_venture_engine import (
    VentureAltcoinEngine,
    screen_venture_candidates,
    BREAKOUT_LOOKBACK_DAYS,
    RS_LOOKBACK_DAYS
)

CACHE_DAILY_DIR = "/home/davide/Scaricati/trading/cache_daily"

@st.cache_data(ttl=1800)
def load_screener_crypto_data():
    if not os.path.exists(CACHE_DAILY_DIR):
        return {}, None
    files = sorted(glob.glob(os.path.join(CACHE_DAILY_DIR, "*-USD.csv")))
    dfs = {}
    for f in files:
        sym = os.path.basename(f).replace(".csv", "")
        try:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
            c = "close" if "close" in df.columns else "Close"
            if c in df.columns:
                dfs[sym] = df[c].dropna()
        except Exception:
            pass
    btc = dfs.get("BTC-USD", dfs.get("BTC", None))
    return dfs, btc

# ==============================================================================
# HTML RENDERING HELPERS & STYLING (DARK GLASSMORPHISM)
# ==============================================================================
def st_html(html_str):
    cleaned = "\n".join(line.strip() for line in html_str.strip().splitlines())
    st.markdown(cleaned, unsafe_allow_html=True)


st_html("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=JetBrains+Mono:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"], .stApp {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        letter-spacing: -0.01em;
    }

    [data-testid="stMetricValue"], [data-testid="stMetricLabel"], .stDataFrame, div[data-testid="stTable"], table {
        font-family: 'JetBrains Mono', monospace !important;
        font-variant-numeric: tabular-nums !important;
    }

    .stTabs [data-baseweb="tab-list"] {
        gap: 6px;
        border-bottom: 1px solid rgba(255,247,237,0.12);
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 18px;
        border-radius: 8px 8px 0px 0px;
        font-weight: 600;
        font-size: 13.5px;
    }

    .glass-card {
        background: rgba(255, 247, 237, 0.045);
        border: 1px solid rgba(255, 247, 237, 0.09);
        border-radius: 8px;
        padding: 14px 16px;
        margin-bottom: 16px;
    }
    .glass-card-accent {
        background: rgba(201, 164, 76, 0.10);
        border: 1px solid rgba(201, 164, 76, 0.35);
        border-radius: 8px;
        padding: 14px 16px;
        margin-bottom: 16px;
    }
</style>
""")

# ==============================================================================
# TITOLO E INTRODUZIONE
# ==============================================================================
st.markdown("""
<div style="display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 16px;">
    <div>
        <h1 style="font-family: 'Fraunces', Georgia, serif; font-size: 26px; font-weight: 600; margin: 0; color: #FAF8F5;">
            Frontier Venture
        </h1>
        <div style="font-size: 12.5px; opacity: 0.70; margin-top: 4px; color: #E8E2D9;">
            Convessità asimmetrica Power-Law · Contratti Perpetual Kraken Futures a Leva 1x · Tassazione 26% · Riciclo utili su Bitcoin e Apex/Convex
        </div>
    </div>
    <div style="text-align: right;">
        <span style="display: inline-block; padding: 4px 10px; border-radius: 6px; font-size: 11px; font-weight: 700; letter-spacing: 0.5px; text-transform: uppercase; background: rgba(201, 164, 76, 0.18); color: #E6C575; border: 1px solid rgba(201, 164, 76, 0.40);">
            SATELLITE ISOLATO (5.0% NET WORTH · 10.000 €)
        </span>
    </div>
</div>
""", unsafe_allow_html=True)

engine = VentureAltcoinEngine()
eur_usd_rate = 1.0850

# Barra di controllo e notifiche
col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 2])
with col_btn1:
    if st.button("Aggiorna Prezzi Live", use_container_width=True):
        with st.spinner("Aggiornamento quotazioni live via Yahoo Finance..."):
            updated_count = 0
            for sym in list(engine.state["positions"].keys()):
                yf_ticker = f"{sym}-USD" if not sym.endswith("-USD") else sym
                try:
                    data = yf.Ticker(yf_ticker).history(period="1d")
                    if not data.empty:
                        px = float(data["Close"].iloc[-1])
                        engine.update_price(sym, px)
                        updated_count += 1
                except Exception as e:
                    pass
            engine.save_portfolio()
            if updated_count > 0:
                st.success(f"Aggiornati prezzi per {updated_count} token.")

with col_btn2:
    if st.button("Notifica Telegram (Test)", use_container_width=True):
        dfs_scr, btc_scr = load_screener_crypto_data()
        from altcoin_venture_engine import send_venture_telegram_alert
        ok, res_msg = send_venture_telegram_alert(crypto_close_dict=dfs_scr, btc_series=btc_scr)
        if ok:
            st.success("Notifica Telegram inviata con successo al canale configurato.")
        else:
            st.warning(f"Avviso: {res_msg}")

summary = engine.get_portfolio_summary(eur_usd_rate=eur_usd_rate)

# ==============================================================================
# KPI CARDS BAR
# ==============================================================================
kpi1, kpi2, kpi3, kpi4, kpi5, kpi6 = st.columns(6)

with kpi1:
    st.markdown(f"""
    <div class="glass-card">
        <div style="font-size: 11px; font-weight: 600; opacity: 0.65; text-transform: uppercase;">Budget Totale</div>
        <div style="font-size: 20px; font-weight: 700; color: #FAF8F5; margin-top: 4px;">{summary['budget_total_eur']:,.0f} €</div>
        <div style="font-size: 10.5px; opacity: 0.55; margin-top: 2px;">5.0% Net Worth (200k)</div>
    </div>
    """, unsafe_allow_html=True)

with kpi2:
    st.markdown(f"""
    <div class="glass-card">
        <div style="font-size: 11px; font-weight: 600; opacity: 0.65; text-transform: uppercase;">Cassa Disponibile</div>
        <div style="font-size: 20px; font-weight: 700; color: #78B68E; margin-top: 4px;">{summary['cash_available_eur']:,.0f} €</div>
        <div style="font-size: 10.5px; opacity: 0.55; margin-top: 2px;">{int(summary['cash_available_eur']/engine.get_slot_size_eur())} slot liberi</div>
    </div>
    """, unsafe_allow_html=True)

with kpi3:
    st.markdown(f"""
    <div class="glass-card">
        <div style="font-size: 11px; font-weight: 600; opacity: 0.65; text-transform: uppercase;">Valore Posizioni</div>
        <div style="font-size: 20px; font-weight: 700; color: #FAF8F5; margin-top: 4px;">{summary['total_current_val_eur']:,.0f} €</div>
        <div style="font-size: 10.5px; opacity: 0.55; margin-top: 2px;">{summary['open_positions_count']} token aperti</div>
    </div>
    """, unsafe_allow_html=True)

with kpi4:
    pnl_col = "#78B68E" if summary['unrealized_pnl_eur'] >= 0 else "#D66B6B"
    st.markdown(f"""
    <div class="glass-card">
        <div style="font-size: 11px; font-weight: 600; opacity: 0.65; text-transform: uppercase;">P&L Non Realizzato</div>
        <div style="font-size: 20px; font-weight: 700; color: {pnl_col}; margin-top: 4px;">{summary['unrealized_pnl_eur']:+,.0f} €</div>
        <div style="font-size: 10.5px; opacity: 0.55; margin-top: 2px;">Valore su carta</div>
    </div>
    """, unsafe_allow_html=True)

with kpi5:
    st.markdown(f"""
    <div class="glass-card">
        <div style="font-size: 11px; font-weight: 600; opacity: 0.65; text-transform: uppercase;">Free-Rides Attivi</div>
        <div style="font-size: 20px; font-weight: 700; color: #E6C575; margin-top: 4px;">{summary['free_rides_count']}</div>
        <div style="font-size: 10.5px; opacity: 0.55; margin-top: 2px;">Rischio zero rovina</div>
    </div>
    """, unsafe_allow_html=True)

with kpi6:
    st.markdown(f"""
    <div class="glass-card">
        <div style="font-size: 11px; font-weight: 600; opacity: 0.65; text-transform: uppercase;">Profitti Riciclati</div>
        <div style="font-size: 20px; font-weight: 700; color: #78B68E; margin-top: 4px;">{summary['recycled_profits_eur']:,.0f} €</div>
        <div style="font-size: 10.5px; opacity: 0.55; margin-top: 2px;">Bonificati su BTC/Apex</div>
    </div>
    """, unsafe_allow_html=True)

# Status Kill-Switch Pre-committato
ks_info = engine.check_kill_switch(eur_usd_rate=eur_usd_rate)
if ks_info["triggered"]:
    st.error(f"[KILL-SWITCH ATTIVATO] {ks_info['reason']} -> AZIONE: {ks_info['action']}")
else:
    st.markdown(f"""
    <div style="background: rgba(120, 182, 142, 0.08); border: 1px solid rgba(120, 182, 142, 0.25); border-radius: 6px; padding: 7px 14px; margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center; font-size: 12px;">
        <div>
            <strong style="color: #78B68E;">[KILL-SWITCH PRE-COMMITTATO: NORMALE]</strong>
            <span style="opacity: 0.85; margin-left: 8px;">Floor di liquidazione capitale: <strong>{ks_info['floor_equity_eur']:,.0f} €</strong> (Max DD tollerabile -40% sul satellite / 2.0% Net Worth)</span>
        </div>
        <div style="opacity: 0.70; font-family: 'JetBrains Mono', monospace;">
            Drawdown attuale: {ks_info['drawdown_pct']:+.1f}% · Relative Lag vs BTC: {ks_info['relative_lag_pct']:+.1f}%
        </div>
    </div>
    """, unsafe_allow_html=True)

# ==============================================================================
# SEGNALI ED EVENTI OPERATIVI (ALERT BOX)
# ==============================================================================
signals = engine.evaluate_signals(eur_usd_rate=eur_usd_rate)
if signals:
    st.markdown("### Segnali Operativi Rilevati")
    for s in signals:
        col_sig, col_act = st.columns([4, 1])
        with col_sig:
            st.warning(f"**{s['ticker']}**: {s['reason']}")
        with col_act:
            if st.button(f"Esegui {s['ticker']}", key=f"btn_exec_{s['ticker']}"):
                engine.execute_sell_signal(s, eur_usd_rate=eur_usd_rate)
                st.success(f"Esecuzione completata per {s['ticker']}.")
                st.rerun()

# ==============================================================================
# SCHEDE PRINCIPALI
# ==============================================================================
tab_pos, tab_screen, tab_add, tab_history, tab_rules = st.tabs([
    "Posizioni e Milestone",
    "Scanner Segnali Giornalieri",
    "Apertura Nuovo Slot",
    "Registro Storico Operazioni",
    "Regole e Protocollo Asimmetrico"
])

with tab_pos:
    if summary["positions_table"]:
        df_pos = pd.DataFrame(summary["positions_table"])
        st.dataframe(
            df_pos,
            column_config={
                "Ticker": st.column_config.TextColumn("Ticker", width="small"),
                "Nome": st.column_config.TextColumn("Nome"),
                "Settore": st.column_config.TextColumn("Settore"),
                "Prezzo Carico ($)": st.column_config.NumberColumn("Carico ($)", format="%.4f"),
                "Prezzo Attuale ($)": st.column_config.NumberColumn("Attuale ($)", format="%.4f"),
                "Moltiplicatore": st.column_config.TextColumn("Mult."),
                "P&L Non Real. (%)": st.column_config.TextColumn("P&L (%)"),
                "Valore Posizione (€)": st.column_config.NumberColumn("Valore (€)", format="%.2f €"),
                "Stato": st.column_config.TextColumn("Stato"),
                "Prossimo Target ($)": st.column_config.NumberColumn("Target ($)", format="%.4f"),
                "Azione al Target": st.column_config.TextColumn("Azione al Target"),
                "Capitale Iniziale (€)": st.column_config.NumberColumn("Capitale Iniz. (€)", format="%.2f €"),
                "Capitale Recuperato (€)": st.column_config.NumberColumn("Capitale Rec. (€)", format="%.2f €")
            },
            hide_index=True,
            use_container_width=True
        )
    else:
        st.info("Nessuna posizione aperta nel Satellite Venture. Utilizza la scheda 'Apertura Nuovo Slot' per iniziare.")

with tab_screen:
    st.markdown("#### Scanner Segnali Giornalieri (Breakout 30d + Forza Relativa)")
    st.markdown("""
    Valutazione quantitativa quotidiana a 3 filtri:
    1. **Gate Macro Bitcoin**: BTC > MA 40w e MA 20w (Trend Bullish di mercato).
    2. **Breakout Tecnico**: Prezzo Close > Massimo a 30 giorni.
    3. **Forza Relativa ($RS_{20d}$)**: Rendimento a 20 giorni superiore a Bitcoin.
    """)

    crypto_dict, btc_s = load_screener_crypto_data()
    if btc_s is None or btc_s.empty:
        st.warning("Dati storici giornalieri non disponibili nella cache locale.")
    else:
        screen_res = screen_venture_candidates(crypto_dict, btc_s)
        macro_active = screen_res["macro_gate_active"]

        if macro_active:
            st.success(f"GATE MACRO ATTIVO: Bitcoin ({screen_res['btc_price_usd']:,.2f} $) si trova sopra la MA 40w ({screen_res['btc_ma40w_usd']:,.2f} $) e la MA 20w ({screen_res['btc_ma20w_usd']:,.2f} $). Gli acquisti per nuovi slot sono permessi.")
        else:
            st.error(f"GATE MACRO BLOCCATO: Bitcoin ({screen_res['btc_price_usd']:,.2f} $) è sotto la MA 40w ({screen_res['btc_ma40w_usd']:,.2f} $) o la MA 20w ({screen_res['btc_ma20w_usd']:,.2f} $). Nuovi acquisti tassativamente congelati (100% Cash / Riserva).")

        breadth_val = screen_res.get("altcoin_breadth_pct", 0.0)
        breadth_regime = screen_res.get("altcoin_breadth_regime", "N/D")
        dyn_target = engine.get_dynamic_allocation_target(breadth_val, macro_active)
        st.markdown(f"""
        <div style="background: rgba(255, 247, 237, 0.03); border: 1px solid rgba(255, 247, 237, 0.08); border-radius: 6px; padding: 6px 12px; margin-bottom: 12px; font-size: 12px; display: flex; justify-content: space-between;">
            <div><strong>ALTCOIN BREADTH:</strong> {breadth_val:.1f}% sopra SMA 20w (140d) · <em>{breadth_regime}</em></div>
            <div><strong>TARGET SLEEVE:</strong> {dyn_target['target_pct']*100:.1f}% ({dyn_target['target_eur']:,.0f} € · {dyn_target['slots_max']} slot)</div>
        </div>
        """, unsafe_allow_html=True)

        candidates = screen_res.get("candidates", [])
        if candidates:
            st.markdown(f"##### Token Qualificati Oggi ({len(candidates)} candidati)")
            df_cand = pd.DataFrame(candidates)
            st.dataframe(
                df_cand,
                column_config={
                    "ticker": st.column_config.TextColumn("Ticker"),
                    "kraken_symbol": st.column_config.TextColumn("Contratto Kraken Futures"),
                    "price_usd": st.column_config.NumberColumn("Prezzo Attuale ($)", format="%.4f"),
                    "breakout_level_usd": st.column_config.NumberColumn("Livello Breakout 30d ($)", format="%.4f"),
                    "breakout_pct": st.column_config.NumberColumn("Superamento Breakout (%)", format="+%.1f%%"),
                    "alt_ret_20d_pct": st.column_config.NumberColumn("Rendimento Alt 20d (%)", format="+%.1f%%"),
                    "btc_ret_20d_pct": st.column_config.NumberColumn("Rendimento BTC 20d (%)", format="+%.1f%%"),
                    "rs_excess_vs_btc_pct": st.column_config.NumberColumn("Eccesso RS vs BTC (%)", format="+%.1f%%"),
                    "vol_ratio_30d": st.column_config.NumberColumn("Volume / Mediana 30d", format="%.2fx"),
                    "vol_confirmed": st.column_config.CheckboxColumn("Volume Conf."),
                    "is_crowded": st.column_config.CheckboxColumn("Crowded Pump")
                },
                hide_index=True,
                use_container_width=True
            )
            st.info("I token sono filtrati per disponibilità su contratti Perpetual di Kraken Futures (senza wrapped e stablecoin) e ordinati per eccesso di forza relativa vs BTC. Apri la posizione sul primo candidato disponibile.")
        else:
            st.info("Nessun token dell'universo crypto soddisfa congiuntamente il Breakout a 30 giorni e l'eccesso di forza relativa vs BTC alla data odierna.")

with tab_add:
    st.markdown("#### Registrazione Ingresso Nuovo Token")
    st.markdown(f"Lo slot standard è impostato a **{engine.get_slot_size_eur():,.2f} €** su un totale di {engine.state['max_slots']} slot (Budget: {engine.state['budget_total_eur']:,.0f} €).")

    col_in1, col_in2, col_in3 = st.columns(3)
    with col_in1:
        new_ticker = st.text_input("Ticker Token (es. SOL, AVAX, NEAR, SUI)", value="").upper().strip()
        new_name = st.text_input("Nome Progetto (es. Solana)", value="")
    with col_in2:
        new_price = st.number_input("Prezzo di Ingresso in USD ($)", min_value=0.0001, value=10.0, step=0.1, format="%.4f")
        new_sector = st.selectbox("Comparto Narrativo", [
            "Layer 1 / Layer 2",
            "AI / Decentralized Compute",
            "DeFi 2.0 / Liquid Staking",
            "Real World Assets (RWA)",
            "DePIN / Infrastructure",
            "Altro"
        ])
    with col_in3:
        new_capital = st.number_input("Capitale Allocato in EUR (€)", min_value=50.0, max_value=float(summary["cash_available_eur"]), value=min(engine.get_slot_size_eur(), float(summary["cash_available_eur"])), step=50.0)
        new_date = st.date_input("Data di Ingresso", value=datetime.date.today())

    if st.button("Registra Posizione nel Satellite", type="primary"):
        if not new_ticker:
            st.error("Inserire un ticker valido.")
        elif new_ticker in engine.state["positions"]:
            st.error(f"Posizione {new_ticker} già presente.")
        else:
            try:
                engine.open_position(
                    ticker=new_ticker,
                    name=new_name if new_name else new_ticker,
                    entry_price_usd=float(new_price),
                    sector=new_sector,
                    custom_capital_eur=float(new_capital),
                    entry_date=new_date.strftime("%Y-%m-%d"),
                    eur_usd_rate=eur_usd_rate
                )
                st.success(f"Posizione {new_ticker} registrata con successo ({new_capital:.2f} €).")
                st.rerun()
            except Exception as e:
                st.error(f"Errore durante l'apertura: {e}")

with tab_history:
    st.markdown("#### Registro Storico Ordini ed Esecuzioni")
    hist = engine.state.get("trade_history", [])
    if hist:
        df_hist = pd.DataFrame(hist)
        st.dataframe(df_hist, hide_index=True, use_container_width=True)
    else:
        st.info("Nessuna transazione storica registrata.")

with tab_rules:
    st.markdown("""
    ### Il Protocollo Quantitativo Frontier Venture (VENTURE_ALTCOIN_SPEC.md)

    1. **Ring-Fencing Assoluto e Dimensionamento (5.0% - 7.5% Net Worth)**:
       - Il capitale del satellite è vincolato al **5.0% del patrimonio totale di 200k € (10.000 €)**, suddiviso in **10 slot da 1.000 €**.
       - La perdita massima su un singolo slot è limitata a 1.000 € (pari allo **0.50% del patrimonio totale**).
       - Struttura Barbell: 70-80% su altcoin liquide (Kraken Perps), 15-20% su scommesse asimmetriche ad alto beta, 10-15% cassa/riserva.

    2. **Protocollo Free-Ride a 2.25x (+125%)**:
       - Al raggiungimento di **2.25x (+125%)**, scatta la vendita automatica del **44.4% della posizione**.
       - Questa cessione recupera esattamente il **100% del capitale iniziale** (1.000 €), azzerando istantaneamente il rischio contabile.
       - La quota residua (55.6%) diventa un **Free-Ride puro a rischio zero**.

    3. **Ladder di Prese di Profitto e Trailing Stop Meccanico**:
       - **Milestone 2 (+300% / 4x)**: Liquidazione del 20% della quota residua.
       - **Milestone 3 (+700% / 8x)**: Liquidazione del 25% della quota residua.
       - **Milestone 4 (+1500% / 16x)**: Liquidazione del 50% della quota residua.
       - **Trailing Stop Meccanico (-30%)**: Dal massimo relativo toccato dopo il Free-Ride, trailing stop rigido al -30% inserito a mercato (eliminazione dello stop mentale).
       - **Hard Stop Iniziale (-40%)**: Troncamento immediato della coda sinistra sui trade falliti.

    4. **Kill-Switch Quantitativo Pre-committato**:
       - **Drawdown Kill-Switch**: Se il valore totale del satellite scende a **6.000 €** ($-40\%$ dal budget iniziale di 10.000 €), tutti i contratti vengono liquidati e l'operatività viene congelata per 180 giorni.
       - **Relative Lag Kill-Switch**: Se su un intero ciclo rialzista il satellite sotto-performa Bitcoin Buy & Hold di oltre **15 punti percentuali netti**, il satellite viene azzerato e il capitale residuo riassorbito nella quota Bitcoin di Apex Engine.

    5. **Efficienza Fiscale ed Esecutiva (Kraken Futures 1x)**:
       - Esecuzione esclusiva su contratti Perpetual di Kraken Futures a **leva 1x** (zero margine aggiuntivo, zero rischio liquidazione).
       - Inquadramento fiscale come contratti differenziali (art. 67, c. 1, lett. c-quater TUIR) tassati al **26%** con compensazione quadriennale delle minusvalenze, contro il 33% delle crypto spot.
       - Esclusione tassativa di stablecoin, token wrapped e staking derivati.
    """)
