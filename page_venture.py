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
import sys
import datetime
import glob
import json
import urllib.request
import importlib
from typing import Optional
import pandas as pd
import streamlit as st

_current_dir = os.path.dirname(os.path.abspath(__file__))
if _current_dir not in sys.path:
    sys.path.insert(0, _current_dir)

import altcoin_venture_engine
try:
    importlib.reload(altcoin_venture_engine)
except Exception:
    pass

try:
    from altcoin_venture_engine import (
        VentureAltcoinEngine,
        screen_venture_candidates,
        load_crypto_universe_data,
        get_telegram_credentials,
        send_venture_telegram_alert,
        YAHOO_CRYPTO_MAP,
        BREAKOUT_LOOKBACK_DAYS,
        RS_LOOKBACK_DAYS
    )
except ImportError:
    importlib.reload(altcoin_venture_engine)
    from altcoin_venture_engine import (
        VentureAltcoinEngine,
        screen_venture_candidates,
        load_crypto_universe_data,
        get_telegram_credentials,
        send_venture_telegram_alert,
        YAHOO_CRYPTO_MAP,
        BREAKOUT_LOOKBACK_DAYS,
        RS_LOOKBACK_DAYS
    )



def fetch_live_crypto_price(ticker: str) -> Optional[float]:
    """
    Recupera la quotazione live di un ticker crypto (es. 'SOL' o 'SOL-USD')
    usando l'endpoint leggero standard HTTP via urllib, con mapping accurato dei contratti.
    """
    clean_tick = ticker.replace("-USD", "").upper().strip()
    yf_ticker = YAHOO_CRYPTO_MAP.get(clean_tick, f"{clean_tick}-USD")
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{yf_ticker}?range=2d&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=6) as res:
            data = json.loads(res.read().decode())
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            last = next(c for c in reversed(closes) if c is not None)
            return float(last)
    except Exception:
        pass

    try:
        import yfinance as yf
        data = yf.Ticker(yf_ticker).history(period="1d")
        if not data.empty:
            return float(data["Close"].iloc[-1])
    except Exception:
        pass

    return None


@st.cache_data(ttl=1800)
def load_screener_crypto_data(force_live: bool = False):
    """
    Carica i dati storici giornalieri dell'universo crypto con cache Streamlit (30m).
    Utilizza l'architettura multi-tier (bundle offline JSON + overlay live Yahoo).
    """
    return load_crypto_universe_data(force_live=force_live)


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

# Barra di controllo rapida
col_ctrl1, col_ctrl2 = st.columns([1, 3])
with col_ctrl1:
    if st.button("Aggiorna Prezzi Live", use_container_width=True):
        load_screener_crypto_data.clear()
        with st.spinner("Sincronizzazione quotazioni live da Kraken Futures..."):
            updated_count = 0
            for sym in list(engine.state["positions"].keys()):
                px = fetch_live_crypto_price(sym)
                if px is not None and px > 0:
                    engine.update_price(sym, px)
                    updated_count += 1
            engine.save_portfolio()
            load_screener_crypto_data(force_live=True)
            if updated_count > 0:
                st.success(f"Aggiornati prezzi per {updated_count} token.")
            else:
                st.success("Universo Kraken Futures sincronizzato.")
            st.rerun()

with col_ctrl2:
    st.markdown("""
    <div style="background: rgba(255, 247, 237, 0.03); border: 1px solid rgba(255, 247, 237, 0.08); border-radius: 6px; padding: 7px 14px; font-size: 11.5px; opacity: 0.85; font-family: 'JetBrains Mono', monospace;">
        SISTEMA VENTURE: Contratti Perpetual Kraken Futures a Leva 1x · Budget 10.000 EUR (10 Slot da 1.000 EUR) · Notifiche Telegram automatiche via GitHub Actions
    </div>
    """, unsafe_allow_html=True)


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
# ==============================================================================
# SCHEDE PRINCIPALI
# ==============================================================================
tab_screen, tab_pos, tab_add, tab_history, tab_rules = st.tabs([
    "Opportunita' di Ingresso (Acquistabili & Finestra Ottimale)",
    "Posizioni Attive & Monitoraggio Free-Ride",
    "Apertura Manuale Slot",
    "Registro Storico Operazioni",
    "Regole e Protocollo Asimmetrico"
])

with tab_screen:
    crypto_dict, btc_s = load_screener_crypto_data()
    if btc_s is None or len(btc_s) == 0:
        st.warning("Dati storici non disponibili. Clicca su 'Aggiorna Prezzi Live' in alto.")
    else:
        screen_res = screen_venture_candidates(crypto_dict, btc_s, cross_kraken_futures=True)
        macro_active = screen_res["macro_gate_active"]
        btc_px = screen_res.get("btc_price_usd", 0.0)
        btc_ma40 = screen_res.get("btc_ma40w_usd", 0.0)
        btc_ma20 = screen_res.get("btc_ma20w_usd", 0.0)
        breadth_val = screen_res.get("altcoin_breadth_pct", 0.0)
        breadth_regime = screen_res.get("altcoin_breadth_regime", "N/D")
        dyn_target = engine.get_dynamic_allocation_target(breadth_val, macro_active)

        if macro_active:
            st.markdown(f"""
            <div style="background: rgba(120, 182, 142, 0.08); border: 1px solid rgba(120, 182, 142, 0.28); border-radius: 6px; padding: 8px 14px; margin-bottom: 12px; font-size: 12.5px; display: flex; justify-content: space-between; align-items: center;">
                <div>
                    <strong style="color: #78B68E;">[GATE MACRO BITCOIN: ATTIVO]</strong>
                    <span style="margin-left: 8px; opacity: 0.90;">BTC a <strong>{btc_px:,.2f} $</strong> > MA 40w ({btc_ma40:,.2f} $) e MA 20w ({btc_ma20:,.2f} $). Nuovi ingressi autorizzati.</span>
                </div>
                <div style="font-family: 'JetBrains Mono', monospace; opacity: 0.85;">
                    Breadth: <strong>{breadth_val:.1f}%</strong> sopra SMA 20w · Target Sleeve: <strong>{dyn_target['target_pct']*100:.1f}%</strong> ({dyn_target['target_eur']:,.0f} €)
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.markdown(f"""
            <div style="background: rgba(224, 86, 76, 0.10); border: 1px solid rgba(224, 86, 76, 0.35); border-radius: 6px; padding: 8px 14px; margin-bottom: 12px; font-size: 12.5px; color: #E0564C;">
                <strong>[GATE MACRO BITCOIN: BLOCCATO]</strong>
                BTC a {btc_px:,.2f} $ e' sotto la MA 40w ({btc_ma40:,.2f} $) o la MA 20w ({btc_ma20:,.2f} $). Nuovi acquisti tassativamente congelati (100% Cassa / Riserva Protetta).
            </div>
            """, unsafe_allow_html=True)

        ranked = screen_res.get("ranked_universe", [])

        # FILTRO ULTRA-LEAN: SOLO LE OPPORTUNITA' ACQUISTABILI O NELLA FINESTRA OTTIMALE
        actionable_tokens = []
        for r in ranked:
            is_bo = r.get("is_breakout", False)
            dist = r.get("dist_breakout_pct", -99.0)
            rs_exc = r.get("rs_excess_vs_btc_pct", -99.0)
            trend_ok = r.get("above_sma20w", False)
            p_cur = r.get("price_usd", 0.0)
            p_bo = r.get("breakout_level_usd", 0.0)
            vol_24h = r.get("vol24h", 0.0)

            if is_bo and rs_exc > 0:
                cat_label = "ACQUISTABILE ORA"
                cat_order = 1
            elif dist >= -7.0 and rs_exc > 0 and trend_ok:
                cat_label = f"FINESTRA OTTIMALE ({dist:+.1f}%)"
                cat_order = 2
            else:
                continue

            stop_px = round(p_cur * 0.60, 4)
            t1_px = round(p_cur * 2.25, 4)
            t2_px = round(p_cur * 4.00, 4)

            actionable_tokens.append({
                "cat_order": cat_order,
                "Stato": cat_label,
                "Ticker": r["ticker"],
                "Contratto": r.get("kraken_symbol", f"PF_{r['ticker']}USD"),
                "Prezzo ($)": p_cur,
                "Breakout 30d ($)": p_bo,
                "Distanza": f"{dist:+.1f}%",
                "Allocazione Slot": "10.0% (1.000 €)",
                "Stop Loss -40% ($)": stop_px,
                "Target 1 Free-Ride (2.25x)": f"{t1_px:.4f} (+125%)",
                "Target 2 (4.0x)": f"{t2_px:.4f} (+300%)",
                "RS vs BTC (20d)": f"{rs_exc:+.1f}%",
                "Volume 24h": f"{vol_24h:,.0f} $" if vol_24h > 0 else "N/D",
                "Trend SMA 20w": "SOPRA" if trend_ok else "SOTTO",
                "_raw_ticker": r["ticker"],
                "_raw_contract": r.get("kraken_symbol", f"PF_{r['ticker']}USD"),
                "_raw_price": p_cur,
                "_raw_stop": stop_px,
                "_raw_t1": t1_px,
                "_raw_t2": t2_px,
                "_raw_vol": vol_24h,
                "_raw_order": cat_order,
                "_raw_rs": rs_exc
            })

        actionable_tokens.sort(key=lambda x: (x["_raw_order"], -x["_raw_rs"]))

        bo_count = sum(1 for t in actionable_tokens if t["_raw_order"] == 1)
        opt_count = sum(1 for t in actionable_tokens if t["_raw_order"] == 2)

        st.markdown(f"##### Altcoin Disponibili su Kraken Futures Conformi ai Filtri ({len(actionable_tokens)} contratti)")
        st.caption(f"Universo Kraken Futures scansionato: {bo_count} token in Breakout Attivo (Acquistabili Subito) e {opt_count} in Finestra Ottimale (<7% dal breakout con eccesso di forza relativa vs BTC e trend sopra SMA 20w).")

        # Filtri di raffinamento rapidi
        col_f1, col_f2, col_f3 = st.columns([2, 2, 2])
        with col_f1:
            sel_tipo = st.selectbox("Filtra per Stato Operativo:", ["Tutte le Opportunita' Qualificate", f"Solo Breakout Attivi ({bo_count})", f"Solo Finestra Ottimale ({opt_count})"])
        with col_f2:
            sel_liq = st.selectbox("Filtra per Liquidita' 24h:", ["Tutti i Volumi", "Volume 24h >= 500.000 $", "Volume 24h >= 1.000.000 $", "Volume 24h >= 2.000.000 $"])
        with col_f3:
            inp_search = st.text_input("Cerca Ticker:", placeholder="es. SOL, ARB, UNI, NEAR...").upper().strip()

        filtered_tokens = actionable_tokens
        if sel_tipo.startswith("Solo Breakout"):
            filtered_tokens = [t for t in filtered_tokens if t["_raw_order"] == 1]
        elif sel_tipo.startswith("Solo Finestra"):
            filtered_tokens = [t for t in filtered_tokens if t["_raw_order"] == 2]

        if "500.000" in sel_liq:
            filtered_tokens = [t for t in filtered_tokens if t["_raw_vol"] >= 500000.0]
        elif "1.000.000" in sel_liq:
            filtered_tokens = [t for t in filtered_tokens if t["_raw_vol"] >= 1000000.0]
        elif "2.000.000" in sel_liq:
            filtered_tokens = [t for t in filtered_tokens if t["_raw_vol"] >= 2000000.0]

        if inp_search:
            filtered_tokens = [t for t in filtered_tokens if inp_search in t["Ticker"]]

        if filtered_tokens:
            df_display = pd.DataFrame([
                {k: v for k, v in item.items() if not k.startswith("_")}
                for item in filtered_tokens
            ])
            st.dataframe(
                df_display,
                column_config={
                    "Stato": st.column_config.TextColumn("Stato Operativo", width="medium"),
                    "Ticker": st.column_config.TextColumn("Ticker", width="small"),
                    "Contratto": st.column_config.TextColumn("Contratto Kraken Futures"),
                    "Prezzo ($)": st.column_config.NumberColumn("Prezzo ($)", format="%.4f"),
                    "Breakout 30d ($)": st.column_config.NumberColumn("Breakout 30d ($)", format="%.4f"),
                    "Distanza": st.column_config.TextColumn("Distanza"),
                    "Allocazione Slot": st.column_config.TextColumn("Allocazione Slot"),
                    "Stop Loss -40% ($)": st.column_config.NumberColumn("Stop Loss -40% ($)", format="%.4f"),
                    "Target 1 Free-Ride (2.25x)": st.column_config.TextColumn("Target 1 Free-Ride (2.25x)"),
                    "Target 2 (4.0x)": st.column_config.TextColumn("Target 2 (4.0x)"),
                    "RS vs BTC (20d)": st.column_config.TextColumn("RS vs BTC (20d)"),
                    "Volume 24h": st.column_config.TextColumn("Volume 24h ($)"),
                    "Trend SMA 20w": st.column_config.TextColumn("Trend SMA 20w")
                },
                hide_index=True,
                use_container_width=True
            )

            # Modulo di registrazione rapida a 1-click
            st.markdown("---")
            st.markdown("##### Registrazione Rapida Slot su Altcoin Proposta")
            c_sel1, c_sel2 = st.columns([3, 1])
            with c_sel1:
                options_tokens = [t["Ticker"] for t in filtered_tokens]
                selected_tok = st.selectbox(
                    "Seleziona l'altcoin proposta per configurare l'apertura dello slot (1.000 €):",
                    options=options_tokens,
                    format_func=lambda t: next((f"{t} ({item['Contratto']}) — {item['Stato']} | Prezzo: {item['Prezzo ($)']:.4f} $ | Stop: {item['Stop Loss -40% ($)']:.4f} $ | Target 1: {item['Target 1 Free-Ride (2.25x)']}" for item in filtered_tokens if item["Ticker"] == t), t)
                )

            matched_tok = next((t for t in filtered_tokens if t["Ticker"] == selected_tok), None)
            if matched_tok:
                # Parametri calcolati
                c_p1, c_p2, c_p3, c_p4 = st.columns(4)
                with c_p1:
                    st.markdown(f"""
                    <div class="glass-card">
                        <div style="font-size: 11px; opacity: 0.65; text-transform: uppercase;">Capitale Allocato</div>
                        <div style="font-size: 18px; font-weight: 700; color: #FAF8F5;">1.000,00 €</div>
                        <div style="font-size: 10px; opacity: 0.55;">10.0% Budget / 0.50% NW</div>
                    </div>
                    """, unsafe_allow_html=True)
                with c_p2:
                    st.markdown(f"""
                    <div class="glass-card">
                        <div style="font-size: 11px; opacity: 0.65; text-transform: uppercase;">Prezzo di Carico</div>
                        <div style="font-size: 18px; font-weight: 700; color: #FAF8F5;">{matched_tok['Prezzo ($)']:.4f} $</div>
                        <div style="font-size: 10px; opacity: 0.55;">Contratto {matched_tok['Contratto']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                with c_p3:
                    st.markdown(f"""
                    <div class="glass-card">
                        <div style="font-size: 11px; opacity: 0.65; text-transform: uppercase;">Hard Stop Loss (-40%)</div>
                        <div style="font-size: 18px; font-weight: 700; color: #E0564C;">{matched_tok['Stop Loss -40% ($)']:.4f} $</div>
                        <div style="font-size: 10px; opacity: 0.55;">Perdita Max: -400,00 € (-0.20% NW)</div>
                    </div>
                    """, unsafe_allow_html=True)
                with c_p4:
                    st.markdown(f"""
                    <div class="glass-card">
                        <div style="font-size: 11px; opacity: 0.65; text-transform: uppercase;">Target Free-Ride (2.25x)</div>
                        <div style="font-size: 18px; font-weight: 700; color: #78B68E;">{matched_tok['_raw_t1']:.4f} $</div>
                        <div style="font-size: 10px; opacity: 0.55;">Vendi 44.4% -> Incassa 1.000 €</div>
                    </div>
                    """, unsafe_allow_html=True)

                with c_sel2:
                    st.write("")
                    st.write("")
                    if st.button("Conferma Apertura Slot (1.000 €)", type="primary", use_container_width=True):
                        if not macro_active:
                            st.error("Impossibile aprire: Gate Macro Bitcoin e' bloccato (BTC sotto MA 40w o MA 20w).")
                        elif summary["cash_available_eur"] < 1000.0:
                            st.error(f"Cassa disponibile insufficiente ({summary['cash_available_eur']:,.2f} €) per aprire un nuovo slot intero da 1.000 €.")
                        elif matched_tok["Ticker"] in engine.state["positions"]:
                            st.warning(f"Posizione {matched_tok['Ticker']} gia' presente nel portafoglio.")
                        else:
                            try:
                                engine.open_position(
                                    ticker=matched_tok["Ticker"],
                                    name=matched_tok["Ticker"],
                                    entry_price_usd=float(matched_tok["_raw_price"]),
                                    sector="Kraken Futures Perp",
                                    custom_capital_eur=1000.0,
                                    entry_date=datetime.date.today().strftime("%Y-%m-%d"),
                                    eur_usd_rate=eur_usd_rate
                                )
                                st.success(f"Posizione {matched_tok['Ticker']} aperta con successo (1.000 €). Stop Loss a {matched_tok['Stop Loss -40% ($)']:.4f} $, Target Free-Ride a {matched_tok['_raw_t1']:.4f} $.")
                                st.rerun()
                            except Exception as ex:
                                st.error(f"Errore durante l'apertura della posizione: {ex}")
        else:
            st.info("Nessuna altcoin corrisponde ai filtri selezionati. Modifica i parametri di ricerca o la soglia di liquidita'.")

with tab_pos:
    st.markdown("#### Monitoraggio Posizioni Attive e Free-Ride")
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
        st.info("Nessuna posizione aperta nel Satellite Frontier Venture. Utilizza la prima scheda 'Opportunita' di Ingresso' per registrare un nuovo slot da 1.000 €.")

with tab_add:
    st.markdown("#### Registrazione Ingresso Nuovo Token")
    st.markdown(f"Lo slot standard è impostato a **{engine.get_slot_size_eur():,.2f} €** su un totale di {engine.state['max_slots']} slot (Budget: {engine.state['budget_total_eur']:,.0f} €).")

    prefill_sym = st.session_state.get("venture_prefill_ticker", "")
    prefill_px = st.session_state.get("venture_prefill_price", 10.0)

    if prefill_sym:
        st.success(f"Candidato selezionato dallo scanner: **{prefill_sym}** a **{prefill_px:.4f} $**. Verifica i parametri di carico e clicca sul pulsante sottostante per confermare.")

    col_in1, col_in2, col_in3 = st.columns(3)
    with col_in1:
        new_ticker = st.text_input("Ticker Token (es. SOL, AVAX, NEAR, SUI)", value=prefill_sym).upper().strip()
        new_name = st.text_input("Nome Progetto (es. Solana)", value=prefill_sym if prefill_sym else "")
    with col_in2:
        new_price = st.number_input("Prezzo di Ingresso in USD ($)", min_value=0.0001, value=float(prefill_px if prefill_px > 0 else 10.0), step=0.1, format="%.4f")
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
                if "venture_prefill_ticker" in st.session_state:
                    del st.session_state["venture_prefill_ticker"]
                if "venture_prefill_price" in st.session_state:
                    del st.session_state["venture_prefill_price"]
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
    st.markdown(r"""
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
       - **Drawdown Kill-Switch**: Se il valore totale del satellite scende a **6.000 €** (-40% dal budget iniziale di 10.000 €), tutti i contratti vengono liquidati e l'operatività viene congelata per 180 giorni.
       - **Relative Lag Kill-Switch**: Se su un intero ciclo rialzista il satellite sotto-performa Bitcoin Buy & Hold di oltre **15 punti percentuali netti**, il satellite viene azzerato e il capitale residuo riassorbito nella quota Bitcoin di Apex Engine.

    5. **Efficienza Fiscale ed Esecutiva (Kraken Futures 1x)**:
       - Esecuzione esclusiva su contratti Perpetual di Kraken Futures a **leva 1x** (zero margine aggiuntivo, zero rischio liquidazione).
       - Inquadramento fiscale come contratti differenziali (art. 67, c. 1, lett. c-quater TUIR) tassati al **26%** con compensazione quadriennale delle minusvalenze, contro il 33% delle crypto spot.
       - Esclusione tassativa di stablecoin, token wrapped e staking derivati.
    """)
