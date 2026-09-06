"""
page_venture.py — Dashboard Venture Satellite Altcoin (Lean & Frictionless)
================================================================================
Interfaccia istituzionale dark glassmorphism ultra-lean per la gestione operativa:
- Monitoraggio sintetico del budget isolato (10.000 EUR · 10 slot da 1.000 EUR)
- Proposta immediata delle altcoin acquistabili su Kraken Futures (Leva 1x)
- Parametri quantitativi esatti per ogni token: Prezzo, Stop Loss, Target 1, Target 2
- Esecuzione slot a 1-click senza frizione o moduli complessi
- Monitoraggio posizioni aperte, trailing stop e riciclo utili su Bitcoin e Apex
================================================================================
"""

import os
import sys
import datetime
import json
import urllib.request
import importlib
from typing import Optional, Dict, Any, List
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

from altcoin_venture_engine import (
    VentureAltcoinEngine,
    screen_venture_candidates,
    load_crypto_universe_data,
    YAHOO_CRYPTO_MAP,
    BREAKOUT_LOOKBACK_DAYS,
    RS_LOOKBACK_DAYS,
    MAX_BREAKOUT_EXTENSION_PCT,
    HARD_STOP_LOSS_PCT,
    FREE_RIDE_MULTIPLIER,
    FREE_RIDE_SELL_FRACTION
)


def fetch_live_crypto_price(ticker: str) -> Optional[float]:
    clean_tick = ticker.replace("-USD", "").upper().strip()
    yf_ticker = YAHOO_CRYPTO_MAP.get(clean_tick, f"{clean_tick}-USD")
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{yf_ticker}?range=2d&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            data = json.loads(res.read().decode())
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            last = next(c for c in reversed(closes) if c is not None)
            return float(last)
    except Exception:
        pass
    return None


@st.cache_data(ttl=1800)
def load_screener_crypto_data(force_live: bool = False):
    return load_crypto_universe_data(force_live=force_live)


# STILI DARK GLASSMORPHISM
st.markdown("""
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
        background: rgba(255, 247, 237, 0.04);
        border: 1px solid rgba(255, 247, 237, 0.09);
        border-radius: 8px;
        padding: 12px 14px;
        margin-bottom: 12px;
    }
    .glass-card-focus {
        background: rgba(201, 164, 76, 0.08);
        border: 1px solid rgba(201, 164, 76, 0.30);
        border-radius: 8px;
        padding: 12px 14px;
        margin-bottom: 12px;
    }
    .badge-pill {
        display: inline-block;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.4px;
        font-family: 'JetBrains Mono', monospace;
    }
    .badge-green {
        background: rgba(120, 182, 142, 0.15);
        color: #78B68E;
        border: 1px solid rgba(120, 182, 142, 0.40);
    }
    .badge-gold {
        background: rgba(201, 164, 76, 0.15);
        color: #E6C575;
        border: 1px solid rgba(201, 164, 76, 0.40);
    }
</style>
""", unsafe_allow_html=True)

engine = VentureAltcoinEngine()
eur_usd_rate = 1.0850
summary = engine.get_portfolio_summary(eur_usd_rate=eur_usd_rate)

# HEADER COMPATTO & BARRA DI STATO LEAN
col_title, col_sync = st.columns([4, 1])
with col_title:
    st.markdown("""
    <div style="display: flex; align-items: baseline; gap: 14px;">
        <h1 style="font-family: 'Fraunces', Georgia, serif; font-size: 24px; font-weight: 600; margin: 0; color: #FAF8F5;">
            Frontier Venture
        </h1>
        <span style="font-size: 12px; color: #C9A44C; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">
            Satellite Asimmetrico (Kraken Futures 1x · Budget 10.000 € · 10 Slot da 1.000 €)
        </span>
    </div>
    """, unsafe_allow_html=True)
with col_sync:
    if st.button("Sincronizza Live", use_container_width=True):
        load_screener_crypto_data.clear()
        with st.spinner("Aggiornamento live Kraken Futures..."):
            for sym in list(engine.state["positions"].keys()):
                px = fetch_live_crypto_price(sym)
                if px and px > 0:
                    engine.update_price(sym, px)
            engine.save_portfolio()
            load_screener_crypto_data(force_live=True)
            st.rerun()

st.warning(
    "STATO MODULO: SPERIMENTALE IN FASE DI REVISIONE QUANTITATIVA — OPERATIVITA' REALE SOSPESA.\n"
    "I filtri di Tokenomics (MC/FDV > 0.40, CoinGecko) e Fondamentale (TVL a 90gg, DefiLlama) sono ora attivi e "
    "collegati alla qualificazione dei candidati: escludono i casi di collasso conclamato (es. Terra/Luna, FTX/FTT, "
    "Celsius) prima che il danno si materializzi. Ma il test storico 2018-2026, ripetuto con questi filtri attivi, "
    "mostra che il problema di fondo resta: nei regimi altcoin laterali/bear (2024-2025) il tasso di stop-loss resta "
    "sopra l'85% anche filtrando solo progetti con fondamentali solidi — non e' una questione di quali token, ma di "
    "quando. Manca ancora un filtro di regime di mercato prolungato (non solo il gate macro BTC istantaneo). "
    "Il modulo e' puramente a scopo di ricerca/studio."
)

# 5 Metriche Compatte in Riga Singola
c_kpi1, c_kpi2, c_kpi3, c_kpi4, c_kpi5 = st.columns(5)
with c_kpi1:
    slots_free = int(summary["cash_available_eur"] / engine.get_slot_size_eur())
    st.metric("Cassa Disponibile", f"{summary['cash_available_eur']:,.0f} €", f"{slots_free} slot liberi")
with c_kpi2:
    st.metric("Posizioni Aperte", f"{summary['open_positions_count']} / 10", f"Valore: {summary['total_current_val_eur']:,.0f} €")
with c_kpi3:
    pnl_val = summary["unrealized_pnl_eur"]
    st.metric("P&L Non Realizzato", f"{pnl_val:+,.0f} €")
with c_kpi4:
    st.metric("Free-Rides Attivi", f"{summary['free_rides_count']}", "Rischio zero contabile")
with c_kpi5:
    st.metric("Utili Riciclati", f"{summary['recycled_profits_eur']:,.0f} €", "Travaso BTC/Apex")

# Dati di screening
crypto_dict, btc_s = load_screener_crypto_data()
screen_res = screen_venture_candidates(crypto_dict, btc_s, cross_kraken_futures=True) if btc_s is not None else {"macro_gate_active": True, "candidates": [], "ranked_universe": []}
macro_active = screen_res.get("macro_gate_active", True)
btc_px = screen_res.get("btc_price_usd", 0.0)
breadth_val = screen_res.get("altcoin_breadth_pct", 0.0)
breadth_regime = screen_res.get("altcoin_breadth_regime", "N/D")

# Riga di Regime di Mercato & Kill-Switch
ks_info = engine.check_kill_switch(eur_usd_rate=eur_usd_rate)
gate_label = "ATTIVO (Trend Bullish)" if macro_active else "BLOCCATO (Acquisti Congelati)"
gate_color = "#78B68E" if macro_active else "#E0564C"

st.markdown(f"""
<div style="background: rgba(255, 247, 237, 0.03); border: 1px solid rgba(255, 247, 237, 0.08); border-radius: 6px; padding: 6px 12px; margin-bottom: 12px; font-size: 11.5px; display: flex; justify-content: space-between; align-items: center; font-family: 'JetBrains Mono', monospace;">
    <div>
        <strong>GATE MACRO BTC:</strong> <span style="color: {gate_color}; font-weight: 700;">{gate_label}</span> (BTC ${btc_px:,.0f}) · <strong>BREADTH:</strong> {breadth_val:.1f}% sopra SMA 20w ({breadth_regime})
    </div>
    <div style="opacity: 0.85;">
        <strong>KILL-SWITCH:</strong> Normale (Floor {ks_info['floor_equity_eur']:,.0f} € · Drawdown {ks_info['drawdown_pct']:+.1f}%)
    </div>
</div>
""", unsafe_allow_html=True)

# Eventi operativi (Take-Profit o Stop-Loss in attesa)
signals = engine.evaluate_signals(eur_usd_rate=eur_usd_rate)
if signals:
    st.markdown("### Segnali Operativi in Attesa di Esecuzione")
    for s in signals:
        col_sig, col_act = st.columns([4, 1])
        with col_sig:
            st.warning(f"**{s['ticker']}**: {s['reason']}")
        with col_act:
            if st.button(f"Esegui {s['ticker']}", key=f"btn_exec_{s['ticker']}"):
                engine.execute_sell_signal(s, eur_usd_rate=eur_usd_rate)
                st.success(f"Esecuzione completata per {s['ticker']}.")
                st.rerun()

# STRUTTURA A 3 SCHEDE LEAN
tab_screen, tab_pos, tab_history = st.tabs([
    "Opportunita' di Ingresso (Acquistabili & Finestra Ottimale)",
    "Posizioni Attive & Free-Ride",
    "Storico & Regole"
])

# TAB 1: OPPORTUNITA DI INGRESSO
with tab_screen:
    ranked = screen_res.get("ranked_universe", [])

    actionable_tokens = []
    for r in ranked:
        is_bo = r.get("is_breakout", False)
        dist = r.get("dist_breakout_pct", -99.0)
        rs_exc = r.get("rs_excess_vs_btc_pct", -99.0)
        trend_ok = r.get("above_sma20w", False)
        p_cur = r.get("price_usd", 0.0)
        p_bo = r.get("breakout_level_usd", 0.0)
        vol_24h = r.get("vol24h", 0.0)
        is_crowded = r.get("is_crowded", False) or (dist > (MAX_BREAKOUT_EXTENSION_PCT * 100.0))

        if is_bo and rs_exc > 0 and trend_ok and not is_crowded:
            cat_label = "ACQUISTABILE ORA"
            cat_order = 1
        elif dist >= -7.0 and dist <= 0.0 and rs_exc > 0 and trend_ok:
            cat_label = f"FINESTRA OTTIMALE ({dist:+.1f}%)"
            cat_order = 2
        elif is_bo and rs_exc > 0 and trend_ok and is_crowded:
            cat_label = f"ESTESO CROWDED ({dist:+.1f}%)"
            cat_order = 3
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
            "Allocazione": "10.0% (1.000 €)",
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

    top_breakouts = [t for t in actionable_tokens if t["_raw_order"] == 1][:4]
    top_near = [t for t in actionable_tokens if t["_raw_order"] == 2][:4]

    def _execute_instant_slot_buy(tok_dict):
        sym = tok_dict["_raw_ticker"]
        px = float(tok_dict["_raw_price"])
        if not macro_active:
            st.error("Gate Macro Bitcoin bloccato: acquisti congelati da protocollo.")
            return
        if summary["cash_available_eur"] < 1000.0:
            st.error(f"Cassa insufficiente ({summary['cash_available_eur']:,.2f} €) per aprire un nuovo slot da 1.000 €.")
            return
        if sym in engine.state["positions"]:
            st.warning(f"Posizione {sym} gia' aperta nel satellite.")
            return
        engine.open_position(
            ticker=sym,
            name=sym,
            entry_price_usd=px,
            sector="Kraken Futures Perp",
            custom_capital_eur=1000.0,
            entry_date=datetime.date.today().strftime("%Y-%m-%d"),
            eur_usd_rate=eur_usd_rate
        )
        st.toast(f"Slot {sym} aperto con successo: 1.000 € allocati a {px:.4f} $")
        st.rerun()

    # SEZIONE 1: TOP CANDIDATI IN BREAKOUT ATTIVO
    st.markdown("##### 1. Breakout Attivi Oggi — Acquistabili Subito (Top Leader di Forza Relativa)")
    if top_breakouts:
        c_grid = st.columns(len(top_breakouts))
        for i, c_tok in enumerate(top_breakouts):
            with c_grid[i]:
                st.markdown(f"""
                <div class="glass-card-focus">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <span style="font-size: 16px; font-weight: 700; color: #FAF8F5;">{c_tok['Ticker']}</span>
                        <span class="badge-pill badge-green">ACQUISTABILE</span>
                    </div>
                    <div style="font-size: 10.5px; opacity: 0.65; font-family: 'JetBrains Mono', monospace; margin-bottom: 8px;">
                        {c_tok['Contratto']} · Vol 24h: {c_tok['Volume 24h']}
                    </div>
                    <div style="font-size: 20px; font-weight: 700; color: #FAF8F5; font-family: 'JetBrains Mono', monospace;">
                        {c_tok['Prezzo ($)']:.4f} $
                    </div>
                    <div style="font-size: 11px; opacity: 0.70; margin-bottom: 8px;">
                        Breakout: {c_tok['Breakout 30d ($)']:.4f} $ ({c_tok['Distanza']}) · RS: <strong style="color: #78B68E;">{c_tok['RS vs BTC (20d)']}</strong>
                    </div>
                    <div style="border-top: 1px solid rgba(255,247,237,0.08); padding-top: 8px; font-size: 11px; line-height: 1.5;">
                        <div>• Allocazione: <strong>1.000 €</strong> (10%)</div>
                        <div>• Stop Loss (-40%): <strong style="color: #E0564C;">{c_tok['Stop Loss -40% ($)']:.4f} $</strong> (-400 €)</div>
                        <div>• Target 1 (2.25x): <strong style="color: #78B68E;">{c_tok['_raw_t1']:.4f} $</strong> (Sell 44.4%)</div>
                        <div>• Target 2 (4.0x): <strong>{c_tok['_raw_t2']:.4f} $</strong> (+300%)</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                if st.button(f"Compra Slot {c_tok['Ticker']} (1.000 €)", key=f"btn_card_bo_{c_tok['Ticker']}", type="primary", use_container_width=True):
                    _execute_instant_slot_buy(c_tok)
    else:
        st.info("Nessun token in fase di nuovo breakout a 30 giorni oggi.")

    # SEZIONE 2: TOP TOKEN NELLA FINESTRA OTTIMALE
    st.markdown("##### 2. Finestra Ottimale di Ingresso (<7% dal Breakout + Trend Sopra SMA 20w)")
    if top_near:
        c_near_grid = st.columns(len(top_near))
        for j, n_tok in enumerate(top_near):
            with c_near_grid[j]:
                st.markdown(f"""
                <div class="glass-card">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <span style="font-size: 16px; font-weight: 700; color: #FAF8F5;">{n_tok['Ticker']}</span>
                        <span class="badge-pill badge-gold">{n_tok['Distanza']}</span>
                    </div>
                    <div style="font-size: 10.5px; opacity: 0.65; font-family: 'JetBrains Mono', monospace; margin-bottom: 8px;">
                        {n_tok['Contratto']} · Vol 24h: {n_tok['Volume 24h']}
                    </div>
                    <div style="font-size: 20px; font-weight: 700; color: #FAF8F5; font-family: 'JetBrains Mono', monospace;">
                        {n_tok['Prezzo ($)']:.4f} $
                    </div>
                    <div style="font-size: 11px; opacity: 0.70; margin-bottom: 8px;">
                        Target BO: {n_tok['Breakout 30d ($)']:.4f} $ · RS vs BTC: <strong style="color: #78B68E;">{n_tok['RS vs BTC (20d)']}</strong>
                    </div>
                    <div style="border-top: 1px solid rgba(255,247,237,0.08); padding-top: 8px; font-size: 11px; line-height: 1.5;">
                        <div>• Allocazione: <strong>1.000 €</strong> (10%)</div>
                        <div>• Stop Loss (-40%): <strong style="color: #E0564C;">{n_tok['Stop Loss -40% ($)']:.4f} $</strong> (-400 €)</div>
                        <div>• Target 1 (2.25x): <strong style="color: #78B68E;">{n_tok['_raw_t1']:.4f} $</strong> (Sell 44.4%)</div>
                        <div>• Target 2 (4.0x): <strong>{n_tok['_raw_t2']:.4f} $</strong> (+300%)</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                if st.button(f"Compra Slot {n_tok['Ticker']} (1.000 €)", key=f"btn_card_near_{n_tok['Ticker']}", use_container_width=True):
                    _execute_instant_slot_buy(n_tok)

    st.markdown("---")

    # SEZIONE 3: CATALOGO COMPLETO KRAKEN FUTURES (79 CONTRATTI QUALIFICATI)
    with st.expander(f"Catalogo Completo Contratti Qualificati su Kraken Futures ({len(actionable_tokens)} token)", expanded=False):
        col_fil1, col_fil2 = st.columns([2, 2])
        with col_fil1:
            f_tipo = st.selectbox("Filtra Stato:", ["Tutti i Qualificati", "Solo Breakout Attivi (<=10%)", "Solo Finestra Ottimale ([-7%, 0%])", "Solo Estesi Crowded (>10%)"])
        with col_fil2:
            f_search = st.text_input("Cerca Ticker:", placeholder="es. SOL, SUI, AVAX, NEAR...").upper().strip()

        view_tokens = actionable_tokens
        if f_tipo == "Solo Breakout Attivi (<=10%)":
            view_tokens = [t for t in view_tokens if t["_raw_order"] == 1]
        elif f_tipo == "Solo Finestra Ottimale ([-7%, 0%])":
            view_tokens = [t for t in view_tokens if t["_raw_order"] == 2]
        elif f_tipo == "Solo Estesi Crowded (>10%)":
            view_tokens = [t for t in view_tokens if t["_raw_order"] == 3]

        if f_search:
            view_tokens = [t for t in view_tokens if f_search in t["Ticker"]]

        if view_tokens:
            df_full = pd.DataFrame([
                {k: v for k, v in item.items() if not k.startswith("_")}
                for item in view_tokens
            ])
            st.dataframe(
                df_full,
                column_config={
                    "Stato": st.column_config.TextColumn("Stato", width="medium"),
                    "Ticker": st.column_config.TextColumn("Ticker", width="small"),
                    "Contratto": st.column_config.TextColumn("Contratto Kraken Futures"),
                    "Prezzo ($)": st.column_config.NumberColumn("Prezzo ($)", format="%.4f"),
                    "Breakout 30d ($)": st.column_config.NumberColumn("Breakout 30d ($)", format="%.4f"),
                    "Distanza": st.column_config.TextColumn("Distanza"),
                    "Allocazione": st.column_config.TextColumn("Allocazione Slot"),
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

            # Esecuzione 1-click dal catalogo completo
            c_cat1, c_cat2 = st.columns([3, 1])
            with c_cat1:
                sel_cat_tok = st.selectbox(
                    "Seleziona qualsiasi altcoin dal catalogo per aprire lo slot:",
                    options=[t["Ticker"] for t in view_tokens],
                    format_func=lambda t: next((f"{t} ({item['Contratto']}) — {item['Stato']} · Prezzo: {item['Prezzo ($)']:.4f} $ · Stop: {item['Stop Loss -40% ($)']:.4f} $ · Target 1: {item['Target 1 Free-Ride (2.25x)']}" for item in view_tokens if item["Ticker"] == t), t)
                )
            with c_cat2:
                st.write("")
                st.write("")
                if st.button("Conferma Acquisto Slot (1.000 €)", type="primary", use_container_width=True):
                    matched = next((t for t in view_tokens if t["Ticker"] == sel_cat_tok), None)
                    if matched:
                        _execute_instant_slot_buy(matched)

    # SEZIONE 4: MODULO OPZIONALE PERSONALIZZATO
    with st.expander("Apertura Slot con Parametri Personalizzati (Avanzato)", expanded=False):
        c_in1, c_in2, c_in3 = st.columns(3)
        with c_in1:
            adv_ticker = st.text_input("Ticker Altcoin:", placeholder="es. SOL, SUI").upper().strip()
            adv_name = st.text_input("Nome Progetto:", placeholder="es. Solana")
        with c_in2:
            adv_px = st.number_input("Prezzo di Ingresso in USD ($):", min_value=0.0001, value=10.0, step=0.1, format="%.4f")
            adv_sec = st.selectbox("Comparto Narrativo:", ["Layer 1 / Layer 2", "AI / Decentralized Compute", "DeFi 2.0 / Liquid Staking", "Real World Assets (RWA)", "DePIN / Infrastructure", "Altro"])
        with c_in3:
            adv_eur = st.number_input("Capitale Allocato in EUR (€):", min_value=50.0, max_value=float(summary["cash_available_eur"]), value=min(1000.0, float(summary["cash_available_eur"])), step=50.0)
            adv_dt = st.date_input("Data Ingresso:", value=datetime.date.today())

        if st.button("Registra Slot Personalizzato", type="primary"):
            if not adv_ticker:
                st.error("Inserisci un ticker valido.")
            elif adv_ticker in engine.state["positions"]:
                st.error(f"Posizione {adv_ticker} gia' presente.")
            else:
                try:
                    engine.open_position(
                        ticker=adv_ticker,
                        name=adv_name if adv_name else adv_ticker,
                        entry_price_usd=float(adv_px),
                        sector=adv_sec,
                        custom_capital_eur=float(adv_eur),
                        entry_date=adv_dt.strftime("%Y-%m-%d"),
                        eur_usd_rate=eur_usd_rate
                    )
                    st.success(f"Slot {adv_ticker} aperto con successo ({adv_eur:.2f} €).")
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore: {e}")

# TAB 2: POSIZIONI ATTIVE & FREE-RIDE
with tab_pos:
    st.markdown("#### Posizioni Aperte e Monitoraggio Asimmetrico Free-Ride")
    positions = summary["positions_table"]
    if positions:
        df_pos = pd.DataFrame(positions)
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

        st.markdown("---")
        st.markdown("##### Gestione Operativa Diretta Posizioni")
        for pos_item in positions:
            p_sym = pos_item["Ticker"]
            raw_pos = engine.state["positions"].get(p_sym)
            if not raw_pos:
                continue

            c_p_info, c_p_btn = st.columns([3, 1])
            with c_p_info:
                badge_st = '<span class="badge-pill badge-green">FREE-RIDE ATTIVO</span>' if raw_pos.get("is_free_ride") else '<span class="badge-pill badge-gold">IN ACCUMULO</span>'
                st.markdown(f"""
                <div style="font-size: 13.5px; padding: 4px 0;">
                    <strong>{p_sym}</strong> ({raw_pos.get('name', p_sym)}) {badge_st} · Carico: <strong>{raw_pos['entry_price_usd']:.4f} $</strong> · Attuale: <strong>{raw_pos['current_price_usd']:.4f} $</strong> (Mult: <strong>{raw_pos['current_price_usd']/raw_pos['entry_price_usd']:.2f}x</strong>) · Prossimo: <strong>{raw_pos.get('next_target_label', 'Target')}</strong>
                </div>
                """, unsafe_allow_html=True)
            with c_p_btn:
                if st.button(f"Chiudi Posizione {p_sym}", key=f"btn_close_pos_{p_sym}"):
                    cur_px = raw_pos["current_price_usd"]
                    sh = raw_pos["current_shares"]
                    proceeds_eur = (sh * cur_px) / eur_usd_rate
                    engine.state["cash_available_eur"] = round(engine.state["cash_available_eur"] + proceeds_eur, 2)
                    engine.state["trade_history"].append({
                        "date": datetime.date.today().strftime("%Y-%m-%d"),
                        "ticker": p_sym,
                        "action": "CLOSE_MANUAL",
                        "price_usd": cur_px,
                        "shares": sh,
                        "total_eur": proceeds_eur,
                        "note": "Chiusura manuale da dashboard"
                    })
                    del engine.state["positions"][p_sym]
                    engine.save_portfolio()
                    st.success(f"Posizione {p_sym} liquidata a {cur_px:.4f} $ (+{proceeds_eur:,.2f} €).")
                    st.rerun()
    else:
        st.info("Nessuna posizione aperta nel Satellite Frontier Venture. Utilizza la prima scheda 'Opportunita' di Ingresso' per cliccare su [+ Compra Slot (1.000 €)] e aprire il tuo primo slot.")

# TAB 3: STORICO ESECUZIONI & REGOLE QUANTITATIVE
with tab_history:
    st.markdown("#### Registro Storico Operazioni ed Esecuzioni")
    hist = engine.state.get("trade_history", [])
    if hist:
        df_hist = pd.DataFrame(hist)
        st.dataframe(df_hist, hide_index=True, use_container_width=True)
    else:
        st.info("Nessuna transazione storica registrata.")

    st.markdown("---")
    st.markdown("#### Protocollo Asimmetrico Frontier Venture (Specifiche Quantitative)")
    st.markdown(r"""
    1. **Ring-Fencing Assoluto e Dimensionamento (5.0% Net Worth)**:
       - Il capitale del satellite e' vincolato al **5.0% del patrimonio totale di 200k € (10.000 €)**, suddiviso in **10 slot da 1.000 €**.
       - La perdita massima per trade e' limitata a **-400 €** (-40% dello slot, pari allo **0.20% del patrimonio totale**).

    2. **Protocollo Free-Ride a 2.25x (+125%)**:
       - Al raggiungimento di **2.25x (+125%)**, scatta la vendita automatica del **44.4% della posizione**.
       - Questa cessione recupera esattamente il **100% del capitale iniziale investito (1.000 €)**, azzerando il rischio contabile.
       - La quota rimanente (55.6%) diventa un **Free-Ride puro a costo zero**.

    3. **Ladder di Prese di Profitto e Trailing Stop Meccanico**:
       - **Milestone 2 (+300% / 4.0x)**: Liquidazione del 20% della quota residua.
       - **Milestone 3 (+700% / 8.0x)**: Liquidazione del 25% della quota residua.
       - **Milestone 4 (+1500% / 16.0x)**: Liquidazione del 50% della quota residua.
       - **Trailing Stop Meccanico (-30%)**: Dal massimo relativo toccato post-Milestone 2, trailing stop rigido al -30% a mercato.
       - **Hard Stop Iniziale (-40%)**: Troncamento immediato della coda sinistra sui trade falliti.

    4. **Kill-Switch Quantitativo Pre-committato**:
       - **Drawdown Kill-Switch**: Se il valore totale del satellite scende a **6.000 €** (-40% dal budget iniziale), tutti i contratti vengono liquidati e l'operativita' viene congelata per 180 giorni.
       - **Relative Lag Kill-Switch**: Se su un intero ciclo rialzista il satellite sotto-performa Bitcoin Buy & Hold di oltre **15 punti percentuali netti**, il satellite viene azzerato e il capitale residuo riassorbito nella quota Bitcoin di Apex Engine.

    5. **Efficienza Fiscale ed Esecutiva (Kraken Futures 1x)**:
       - Esecuzione esclusiva su contratti Perpetual di Kraken Futures a **leva 1x** (zero margine aggiuntivo, zero rischio liquidazione).
       - Inquadramento fiscale come contratti differenziali (art. 67, c. 1, lett. c-quater TUIR) tassati al **26%** con compensazione quadriennale delle minusvalenze.
    """)
