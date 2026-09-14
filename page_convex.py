"""
page_convex.py — Pagina Convex Stack (navigazione multipagina, vedi main.py)
==================================================================================
Solo Convex Stack: portafoglio multi-asset a leva sistematica, accumulo
tramite PAC mensile. Principi guida: lean, senza attrito, robusto, semplice
da mantenere. Stesso impianto visivo di app.py (Apex Engine reale,
davbenx/apex-engine su GitHub): stessi font/colori, stessa struttura a 3
schede (Portafoglio, Metriche, Guida), stesso selettore di periodo sul
grafico, stessa assenza di emoji decorative — Apex Engine reale non ne usa,
solo l'icona di pagina.
==================================================================================
"""

import datetime
import json
import os
import urllib.request

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import importlib
import convex_engine
import portfolio_manager

try:
    importlib.reload(portfolio_manager)
    importlib.reload(convex_engine)
except Exception as _reload_err:
    print(f"[WARN] importlib.reload fallito: {_reload_err}")

# st.set_page_config() rimosso: la pagina gira dentro main.py (st.navigation), che lo imposta una sola volta.

# ==============================================================================
# HTML RENDERING HELPERS & STYLING (DA UI_COMPONENTS CONDIVISO)
# ==============================================================================
from ui_components import (
    st_html, inject_page_styles, section_title, sub_hero_metric,
    render_monthly_returns_html_table,
    POS, NEG, MUTED_DOT, ACCENT, ACCENT_SOFT, SURFACE, BORDER, BORDER_STRONG,
    BORDER_GOLD, MUTED, MUTED_2, BADGE_TEXT, FRAUNCES, MONO, MESI_IT
)

inject_page_styles()

BADGE_POS_BG = "#1D5F42"
BADGE_NEG_BG = "#7B2836"
BADGE_NEUTRAL_BG = "rgba(255,247,237,0.1)"

_COLOR_MAP = {
    "NTSG": portfolio_manager.get_class_color("Azioni"),
    "AVWS": portfolio_manager.get_class_color("Azioni"),
    "DBMFE": portfolio_manager.get_class_color("Futures gestiti"),
    "PPFB": portfolio_manager.get_class_color("Oro"),
    "WBTC": portfolio_manager.get_class_color("Cryptovalute"),
    "Liquidità": portfolio_manager.get_class_color("Liquidità"),
}


def get_convex_class_svg(strumento, size=16, color="currentColor", style=""):
    """Icona SVG vettoriale per ciascuno dei 5 strumenti Convex — stesso
    linguaggio visivo (stroke, viewBox 24x24) delle icone di Apex Engine.
    PPFB/WBTC riusano letteralmente i path Oro/Bitcoin di Apex, essendo
    lo stesso identico sottostante."""
    inline_style = f"display:inline-block; vertical-align:middle; flex-shrink:0; {style}"
    if strumento == "NTSG":
        # Layers: nucleo azionario+obbligazionario a leva
        return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{inline_style}"><polygon points="12 2 2 7 12 12 22 7 12 2"></polygon><polyline points="2 17 12 22 22 17"></polyline><polyline points="2 12 12 17 22 12"></polyline></svg>'
    if strumento == "AVWS":
        # Tag: fattore value
        return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{inline_style}"><path d="M20.59 13.41 11 3.83A1.83 1.83 0 0 0 9.7 3.3H4a1.83 1.83 0 0 0-1.83 1.83V9.7c0 .48.19.96.54 1.3l9.58 9.58a2 2 0 0 0 2.83 0l6.47-6.47a2 2 0 0 0 0-2.83Z"></path><circle cx="7.5" cy="7.5" r="1"></circle></svg>'
    if strumento == "DBMFE":
        # Compass: trend-following sistematico multi-asset
        return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{inline_style}"><circle cx="12" cy="12" r="10"></circle><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"></polygon></svg>'
    if strumento == "PPFB":
        return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="{inline_style}"><polygon points="8.5 6 15.5 6 17 12 7 12" /><polygon points="2.5 13 9.5 13 11 19 1 19" /><polygon points="14.5 13 21.5 13 23 19 13 19" /></svg>'
    if strumento == "WBTC":
        return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{inline_style}"><path d="M7 6h6a3 3 0 0 1 0 6H7zm0 6h7a3 3 0 0 1 0 6H7z"></path><line x1="10" y1="3" x2="10" y2="6"></line><line x1="14" y1="3" x2="14" y2="6"></line><line x1="10" y1="18" x2="10" y2="21"></line><line x1="14" y1="18" x2="14" y2="21"></line><line x1="7" y1="6" x2="7" y2="18"></line></svg>'
    if strumento == "Liquidità":
        return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{inline_style}"><rect x="2" y="6" width="20" height="12" rx="2"></rect><circle cx="12" cy="12" r="2.5"></circle><line x1="6" y1="12" x2="6.01" y2="12"></line><line x1="18" y1="12" x2="18.01" y2="12"></line></svg>'
    return ""


def render_convex_positions_html_table(df, show_details=False):
    right_align_cols = ["Quote", "Prezzo", "Peso Reale", "Target", "Controvalore", "TER"]
    cols = ["Strumento", "Quote", "Prezzo", "Peso Reale", "Target", "Controvalore"]
    if show_details:
        cols = ["Strumento", "Nome", "ISIN", "Quote", "Prezzo", "Peso Reale", "Target", "Controvalore", "TER", "Regime Fiscale"]
    
    th_cells = []
    for c in cols:
        align = "right" if c in right_align_cols else "left"
        th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:{align}; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">{c}</th>')
    
    rows_html = []
    for _, r in df.iterrows():
        td_cells = []
        for c in cols:
            val = r[c]
            align = "right" if c in right_align_cols else "left"
            if c == "Strumento":
                td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; font-weight:700; color:{BADGE_TEXT}; white-space:nowrap;">{val}</td>')
            elif c == "ISIN":
                td_cells.append(f'<td style="padding:10px 14px; font-family:{MONO}; font-size:11px; color:{BADGE_TEXT}; white-space:nowrap;"><span style="background:rgba(255,247,237,0.05); padding:2px 6px; border-radius:4px; border:1px solid {BORDER};">{val}</span></td>')
            elif c in right_align_cols:
                td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-family:{MONO}; font-weight:600; white-space:nowrap;">{val}</td>')
            elif c == "Regime Fiscale":
                is_div = "Diverso" in str(val)
                col = POS if is_div else MUTED
                bg = "rgba(61,220,151,0.1)" if is_div else "rgba(255,247,237,0.05)"
                td_cells.append(f'<td style="padding:10px 14px; font-size:11px;"><span style="background:{bg}; color:{col}; padding:3px 8px; border-radius:4px; font-weight:600;">{val}</span></td>')
            else:
                td_cells.append(f'<td style="padding:10px 14px; font-size:12px; color:{MUTED};">{val}</td>')
        rows_html.append(f'<tr style="border-bottom:1px solid {BORDER}; transition:background 0.15s ease;">{"".join(td_cells)}</tr>')
    return f'<div style="width:100%; overflow-x:auto; border:1px solid {BORDER}; border-radius:8px; background:rgba(255,247,237,0.02); margin-bottom:18px;"><table style="width:100%; border-collapse:collapse; text-align:left;"><thead><tr>{"".join(th_cells)}</tr></thead><tbody>{"".join(rows_html)}</tbody></table></div>'



# ==============================================================================
# PREZZI LIVE DEI 5 STRUMENTI (cache 15 minuti, fallback dichiarato se il
# recupero fallisce — mai spacciato per prezzo di mercato)
# ==============================================================================
_CONVEX_BASE_PRICES = {"NTSG": 100.0, "AVWS": 50.0, "DBMFE": 25.0, "PPFB": 50.0, "WBTC": 100.0}
# PPFB/WBTC/DBMFE corretti nel tempo — nessuno dei tre era il ticker giusto in origine:
# WBTC-ETFP.MI (~EUR 16/quota) e' l'ETP Bitcoin, non BTC-USD (prezzo grezzo di Bitcoin).
# DBMFE.PA e' la quotazione UCITS EUR reale (ISIN LU2951555403), non DBMF (ETF USD diverso).
# EGLN.L e' iShares Physical Gold ETC (ISIN IE00B4ND3602, ~EUR 74/quota) — "PPFB" e'
# letteralmente il suo ticker ufficiale; SGLD.MI (Invesco, ISIN diverso) era stato usato
# per errore in una correzione intermedia, poi sostituito con quello giusto.
_CONVEX_YF_TICKERS = {"NTSG": "NTSG.MI", "AVWS": "AVWS.DE", "DBMFE": "DBMFE.PA", "PPFB": "EGLN.L", "WBTC": "WBTC-ETFP.MI"}

# Cache di prezzi aggiornata da uno scheduler GitHub Actions (fetch_live_prices.py,
# .github/workflows/update_live_prices.yml) — il fetch live a runtime da Streamlit
# Community Cloud fallisce spesso perché Yahoo Finance limita il pool di IP
# condivisi degli host cloud (segnalato dall'utente: "Benchmark SPY non
# raggiungibile"). Si legge prima il file cache (scritto da un runner GitHub
# Actions con IP diverso, aggiornato 3 volte al giorno); il fetch live resta
# solo come fallback per uso locale/prima esecuzione senza cache ancora scritta.
_PRICE_CACHE_PATH = os.path.join(os.path.dirname(__file__), "live_prices_cache.json")
_PRICE_CACHE_MAX_AGE_H = 48  # oltre questa età si tenta comunque il fetch live


def _load_price_cache():
    if not os.path.exists(_PRICE_CACHE_PATH):
        return None
    try:
        with open(_PRICE_CACHE_PATH, "r") as f:
            cache = json.load(f)
        fetched_at = datetime.datetime.strptime(cache["fetched_at"], "%Y-%m-%dT%H:%M:%SZ")
        age_h = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - fetched_at).total_seconds() / 3600
        cache["_age_hours"] = age_h
        return cache
    except Exception:
        return None


@st.cache_data(ttl=900)
def fetch_convex_live_prices():
    cache = _load_price_cache()
    if cache and cache.get("convex_prices") and cache["_age_hours"] <= _PRICE_CACHE_MAX_AGE_H:
        prices, live_ok = {}, {}
        for key in _CONVEX_YF_TICKERS:
            if key in cache["convex_prices"]:
                prices[key], live_ok[key] = float(cache["convex_prices"][key]), True
            else:
                prices[key], live_ok[key] = _CONVEX_BASE_PRICES[key], False
        return prices, live_ok

    prices, live_ok = {}, {}
    for key, ticker in _CONVEX_YF_TICKERS.items():
        try:
            url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}?range=5d&interval=1d"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            data = json.loads(urllib.request.urlopen(req, timeout=3).read().decode())
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            last = next(c for c in reversed(closes) if c is not None)
            prices[key], live_ok[key] = float(last), True
        except Exception:
            prices[key], live_ok[key] = _CONVEX_BASE_PRICES[key], False
    return prices, live_ok


def get_price_cache_freshness():
    """Etichetta onesta sulla freschezza dei prezzi mostrati (cache o live)."""
    cache = _load_price_cache()
    if cache and cache.get("convex_prices"):
        fetched_at = datetime.datetime.strptime(cache["fetched_at"], "%Y-%m-%dT%H:%M:%SZ")
        return f"Prezzi aggiornati al {fetched_at.strftime('%d/%m/%Y %H:%M')} UTC"
    return "Prezzi da fetch live (nessuna cache disponibile)"


convex_prices, convex_prices_live = fetch_convex_live_prices()

# ==============================================================================
# INTESTAZIONE
# ==============================================================================

_cp_data = portfolio_manager.load_convex_portfolio()
_last_updated = _cp_data.get("last_updated")
_has_holdings = bool(_cp_data.get("holdings")) and any(v.get("shares", 0) > 0 for v in _cp_data.get("holdings", {}).values())

_is_fresh = False
if _last_updated and _has_holdings:
    try:
        _days = (datetime.date.today() - datetime.datetime.strptime(_last_updated, "%Y-%m-%d").date()).days
        _is_fresh = _days <= 35
    except Exception:
        pass
_status_color = POS if _is_fresh else MUTED_DOT
_status_label = f"Aggiornato al {_last_updated}" if _is_fresh else "Portafoglio Modello (100.000 €)"


col_title, col_stat = st.columns([3, 2])
with col_title:
    st_html(f"""
    <div style="padding: 2px 0 8px 0;">
        <div style="font-size: 13px; font-weight: 600; color: {MUTED}; text-transform: uppercase; letter-spacing: 0.5px;">
            Convex Stack · <span style="color: {ACCENT}; font-weight: 700;">Leva Sistematica</span>
        </div>
    </div>
    """)
with col_stat:
    st_html(f"""
    <div style="text-align: right; padding-top: 2px;">
        <div style="font-size: 11px; color: {MUTED};">
            <span style="width:6px; height:6px; border-radius:50%; background:{_status_color}; display:inline-block; margin-right:5px;"></span>{_status_label}
        </div>
        <div style="font-size: 11px; color: {MUTED_2}; margin-top: 2px;">
            Versamento PAC: 1° del mese
        </div>
    </div>
    """)

# ==============================================================================
# SCHEDE: PORTAFOGLIO, METRICHE, GUIDA — stessi 3 nomi e stesso ordine di
# Apex Engine, senza emoji (Apex reale non ne usa nei nomi di scheda).
# ==============================================================================
tab_pf, tab_metriche, tab_guida = st.tabs(["Portafoglio", "Metriche", "Guida"])

with tab_pf:
    active_instruments = convex_engine.CONVEX_INSTRUMENTS
    cfg = portfolio_manager.load_config()
    _saved_holdings = {k: float(v.get("shares", 0.0)) for k, v in _cp_data.get("holdings", {}).items()}
    _saved_cash = float(_cp_data.get("cash_eur", 0.0))
    _saved_pac = float(cfg.get("monthly_pac_eur", 500.0))

    convex_report = convex_engine.evaluate_convex_stack(
        current_holdings=_saved_holdings,
        market_prices=convex_prices,
        monthly_pac_eur=_saved_pac,
        cash_balance=_saved_cash,
        instruments=active_instruments
    )

    # Hero Banner
    _tot_live = convex_report.total_value
    _val_str = f"€ {_tot_live:,.0f}" if _tot_live > 0 else "n/d"
    _ntsg_w = active_instruments.get("NTSG", {}).get("target_weight", 0.0)
    _notional_pct = (1.0 + 0.5 * _ntsg_w) * 100.0
    st_html(f"""
    <div style="padding: 16px 2px 4px;">
        <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.8px; color: {MUTED}; margin-bottom: 8px;">Valore Portafoglio Convex</div>
        <div style="display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;">
            <span style="font-family:{MONO}; font-size:40px; font-weight:800; letter-spacing:-1px;">{_val_str}</span>
            <span style="font-size:13px; font-weight:700; color:{ACCENT}; background:rgba(201,164,76,0.12); padding:3px 8px; border-radius:6px; border:1px solid rgba(201,164,76,0.25); font-family:{MONO};">{_notional_pct:.1f}% Nozionale (Leva 1.5x NTSG)</span>
        </div>
        <div style="font-size:12px; color:{MUTED}; margin-top:8px;">{len(active_instruments)} strumenti attivi · prossimo ribilanciamento PAC: 1° del mese</div>
    </div>
    """)

    # 1. Azione del Mese PAC (Water-Filling)
    pac_act = convex_report.pac_action
    if pac_act and convex_report.total_value > 0:
        st_html(f"""
        <div class="glass-card-accent">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 8px;">
                <div style="color: {ACCENT}; font-weight: 700; font-size: 15px;">
                    AZIONE PAC CONSIGLIATA PER IL 1° DEL MESE
                </div>
                <div style="font-family:{MONO}; font-size: 18px; font-weight: 700; color:{BADGE_TEXT};">
                    € {pac_act.deposit_amount_eur:,.0f}
                </div>
            </div>
            <div style="font-size: 14px; color: {BADGE_TEXT}; font-weight: 600; margin-bottom: 6px;">
                Acquista: <span style="color:{POS}; font-weight: 800;">{pac_act.recommended_asset}</span> — {pac_act.asset_name}
            </div>
            <div style="font-size: 13px; color: {MUTED}; margin-bottom: 8px;">
                Stima Operativa: <strong>{pac_act.estimated_shares} quote</strong> al prezzo di circa {pac_act.estimated_price:.2f} € (Residuo cassa: {pac_act.remaining_cash:.2f} €).
            </div>
            <div style="font-size: 12px; color: {MUTED_2}; line-height: 1.4; border-top: 1px solid {BORDER}; padding-top: 6px;">
                Motivazione: {pac_act.reason}
            </div>
        </div>
        """)
    elif convex_report.total_value <= 0:
        st.info("Inserisci le tue quote per ricevere il consiglio operativo di questo mese.")

    # 2. Verifica Soglie di Trim
    if convex_report.trim_alerts:
        for al in convex_report.trim_alerts:
            st_html(f"""
            <div style="background: rgba(236,101,123,0.08); border: 1px solid rgba(236,101,123,0.3); border-radius: 8px; padding: 14px; margin-bottom: 10px;">
                <div style="color:{NEG}; font-weight:700; font-size:14px;">SFORAMENTO SOGLIA DI TRIM: {al['asset']} ({al['name']})</div>
                <div style="font-size:12.5px; color:{BADGE_TEXT}; margin-top:4px;">
                    Peso attuale: <strong>{al['current_weight']*100:.1f}%</strong> (Soglia Max: {al['threshold_max']*100:.1f}%). Eccesso da vendere: <strong>€ {al['excess_eur']:,.0f}</strong> (~{al['shares_to_sell']} quote).
                </div>
                <div style="font-size:11.5px; color:{MUTED}; margin-top:6px;">
                    {al['tax_note']}
                </div>
            </div>
            """)
    elif convex_report.total_value > 0:
        st_html(f"""
        <div style="background: rgba(61,220,151,0.06); border: 1px solid rgba(61,220,151,0.25); border-radius: 8px; padding: 14px; margin-bottom: 16px;">
            <div style="color:{POS}; font-weight:700; font-size:13.5px;">TUTTI GLI ASSET SONO DENTRO LE BANDE DI TOLLERANZA</div>
            <div style="font-size:12px; color:{MUTED}; margin-top:3px;">
                Nessuna vendita necessaria. Bitcoin e Oro sono entrambi sotto la soglia del 13.13% (target ×1.75, verifica trimestrale a +75%).
            </div>
        </div>
        """)

    # 3. Composizione del Portafoglio
    if convex_report.total_value > 0:
        st_html(section_title("Composizione del Portafoglio"))
        alloc_segments = [(k, convex_report.assets[k].current_weight * 100.0, _COLOR_MAP.get(k, ACCENT)) for k in active_instruments]
        cash_val = convex_report.total_value - sum(convex_report.assets[k].current_value for k in active_instruments)
        cash_pct = max(0.0, (cash_val / convex_report.total_value) * 100.0) if convex_report.total_value > 0 else 0.0
        if cash_pct > 0.01:
            alloc_segments.append(("Liquidità", cash_pct, _COLOR_MAP.get("Liquidità", "#8E877F")))
        bar_segs = "".join(f'<div style="height:100%; width:{pct:.2f}%; background:{color};"></div>' for _, pct, color in alloc_segments)
        legend_items = "".join(
            f'<div style="display:flex; align-items:center; gap:6px;">{get_convex_class_svg(k, size=14, color=color)} <span style="opacity:0.85;">{k}</span> <b style="font-family:{MONO}; font-weight:700;">{pct:.1f}%</b></div>'
            for k, pct, color in alloc_segments
        )

        st_html(f'<div style="display:flex; height:12px; border-radius:6px; overflow:hidden; border:1px solid {BORDER_STRONG}; margin-bottom:12px;">{bar_segs}</div>')
        st_html(f'<div style="display:flex; flex-wrap:wrap; gap:12px 20px; margin-bottom:20px; font-size:11.5px;">{legend_items}</div>')

    # 4. Posizioni Attive nel Portafoglio
    if convex_report.total_value > 0:
        c_title, c_tog = st.columns([3, 2])
        with c_title:
            st_html(section_title("Posizioni Attive nel Portafoglio"))
        with c_tog:
            st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
            show_cx_details = st.toggle("Mostra dettagli strumenti (ISIN, TER, Fiscalità)", value=False, key="cx_pos_details_toggle")
        
        cx_rows = []
        meta_map = portfolio_manager.CONVEX_INSTRUMENTS_METADATA
        for k, st_info in convex_report.assets.items():
            meta = meta_map.get(k, {})
            tgt = active_instruments.get(k, {}).get("target_weight", 0.0) * 100.0
            cx_rows.append({
                "Strumento": f'<span style="display:inline-flex; align-items:center; gap:6px;">{get_convex_class_svg(k, size=14, color=_COLOR_MAP.get(k, ACCENT))} {k}</span>',
                "Nome": st_info.name,
                "ISIN": meta.get("isin", "N/A"),
                "Quote": f"{st_info.current_shares:,.2f}",
                "Prezzo": f"€ {st_info.current_price:,.2f}",
                "Peso Reale": f"{st_info.current_weight*100:.2f}%",
                "Target": f"{tgt:.1f}%",
                "Controvalore": f"€ {st_info.current_value:,.0f}",
                "TER": f"{meta.get('ter', 0.0)*100:.2f}%",
                "Regime Fiscale": "Reddito Diverso (compensa minus)" if st_info.tax_type == "REDDITO_DIVERSO" else "Reddito di Capitale (non compensa)"
            })
        st_html(render_convex_positions_html_table(pd.DataFrame(cx_rows), show_details=show_cx_details))

    # 5. Modulo di Configurazione Quote e Parametri (in calce alla scheda)
    with st.expander("Modifica Quote Possedute e Rata PAC", expanded=False):
        st.caption("Inserisci le quote possedute di ciascuno strumento e la liquidità per il PAC mensile.")
        col_inp1, col_inp2 = st.columns(2)
        instr_list = list(active_instruments.items())
        half = (len(instr_list) + 1) // 2
        input_holdings = {}
        with col_inp1:
            for key, info in instr_list[:half]:
                input_holdings[key] = st.number_input(
                    f"{key} — {info['name']}",
                    min_value=0.0,
                    value=float(_saved_holdings.get(key, 0.0)),
                    step=1.0,
                    format="%.2f",
                    help=f"Prezzo: {convex_prices[key]:.2f} €" + ("" if convex_prices_live[key] else " (base)"),
                    key=f"cx_inp_{key}"
                )
        with col_inp2:
            for key, info in instr_list[half:]:
                input_holdings[key] = st.number_input(
                    f"{key} — {info['name']}",
                    min_value=0.0,
                    value=float(_saved_holdings.get(key, 0.0)),
                    step=1.0,
                    format="%.2f",
                    help=f"Prezzo: {convex_prices[key]:.2f} €" + ("" if convex_prices_live[key] else " (base)"),
                    key=f"cx_inp_{key}"
                )

        c_pac, c_cash = st.columns(2)
        with c_pac:
            pac_input = st.number_input(
                "Liquidità Pronta per il PAC di Questo Mese (€)", min_value=0.0,
                value=_saved_pac, step=50.0, format="%.0f", key="cx_pac_input"
            )
        with c_cash:
            cash_input = st.number_input(
                "Cassa Residua Non Investita (€)", min_value=0.0,
                value=_saved_cash, step=50.0, format="%.0f", key="cx_cash_input"
            )

        if st.button("Salva Quote e Parametri", use_container_width=True, key="convex_save_holdings"):
            _new_portfolio = {
                "cash_eur": cash_input,
                "holdings": {k: {"shares": v, "last_price": convex_prices.get(k, 0.0)} for k, v in input_holdings.items()},
                "last_updated": datetime.date.today().strftime("%Y-%m-%d"),
            }
            _ok_p = portfolio_manager.save_convex_portfolio(_new_portfolio)
            portfolio_manager.save_config({**cfg, "monthly_pac_eur": pac_input})
            if _ok_p:
                st.toast("Quote Convex salvate con successo.")
                st.rerun()
            else:
                st.error("Errore nel salvataggio.")


with tab_metriche:
    _cx_ret_path = os.path.join(os.path.dirname(__file__), "convex_monthly_returns.csv")
    if os.path.exists(_cx_ret_path):
        _cx_ret = pd.read_csv(_cx_ret_path, index_col=0, parse_dates=True).iloc[:, 0]
        _cx_nav = pd.DataFrame({"value": (1.0 + _cx_ret).cumprod() * 100.0})
        _cx_nav["roll_max"] = _cx_nav["value"].cummax()
        _cx_nav["drawdown"] = (_cx_nav["value"] - _cx_nav["roll_max"]) / _cx_nav["roll_max"] * 100.0

        # Metriche ufficiali: da portfolio_manager.get_convex_metrics(), SOLO
        # il periodo di validazione fuori campione (vedi nota nel modulo) — non
        # piu' ricalcolate qui da zero sull'intera serie 2000-2026, che mescolava
        # il periodo usato per scegliere i pesi 45/15/25/7.5/7.5 (TRAIN) con
        # quello mai visto durante quella scelta (TEST), senza distinzione.
        _m_cx = portfolio_manager.get_convex_metrics()
        cagr_gross, cagr_net = _m_cx["cagr_gross"], _m_cx["cagr_net"]
        vol, sharpe, sortino, mdd = _m_cx["volatility"], _m_cx["sharpe"], _m_cx["sortino"], _m_cx["max_drawdown"]
        mdd_storico = _m_cx.get("max_drawdown_storico", mdd)

        _cx_ter_annual = convex_report.ter_weighted if convex_report.total_value > 0 else \
            sum(i["ter"] * i["target_weight"] for i in active_instruments.values())
        _cx_ter_eur_year = convex_report.total_value * _cx_ter_annual if convex_report.total_value > 0 else 0.0

        st_html(f"""
        <div style="display:flex; gap:24px; flex-wrap:wrap; margin-bottom:16px;">
            {sub_hero_metric("Crescita Annua Lorda", f"{cagr_gross*100:.2f}%", f"Netto stimato (se liquidato): {cagr_net*100:.2f}% annuo", POS if cagr_gross >= 0 else NEG, primary=True)}
            {sub_hero_metric("Indice di Sharpe", f"{sharpe:.2f}", "Rendimento rispetto al rischio", POS if sharpe >= 1.0 else None, primary=True)}
            {sub_hero_metric("Calo Massimo Storico", f"{mdd_storico*100:.2f}%", "Massima discesa temporanea dal 1987", primary=True)}
        </div>
        <div style="display:flex; gap:20px; flex-wrap:wrap; margin-bottom:24px; padding-top:12px; border-top:1px solid {BORDER};">
            {sub_hero_metric("Volatilità Annua", f"{vol*100:.2f}%", "Oscillazione media annua del capitale")}
            {sub_hero_metric("Indice di Sortino", f"{sortino:.2f}", "Protezione ed efficienza sui soli ribassi")}
            {sub_hero_metric("Costo Annuo Strumenti", f"{_cx_ter_annual*100:.2f}%/anno", f"Costo totale: € {_cx_ter_eur_year:,.0f}/anno")}
        </div>
        """)
        st.caption(
            f"Metriche calcolate al lordo delle imposte · Periodo di verifica recente: {_m_cx.get('test_period', '')} · "
            f"Storico completo: {_m_cx.get('storico_period', '')}."
        )


        # ----------------------------------------------------------------------
        # Crescita Patrimoniale — selettore di periodo e benchmark
        # ----------------------------------------------------------------------
        st_html(section_title("Crescita del Portafoglio Convex vs S&P 500", top="8px", bottom="8px"))
        st.caption(
            f"Crescita di 100 € investiti nel portafoglio Convex a confronto con l'indice S&P 500 ({_cx_ret.index[0].year}–{_cx_ret.index[-1].year})."
        )

        selected_range = st.segmented_control(
            "Periodo", options=["6M", "1A", "3A", "Test (6A)", "Da Inizio"],
            default="Test (6A)", label_visibility="collapsed", key="cx_chart_range_ctrl"
        )
        if not selected_range:
            selected_range = "Test (6A)"

        last_dt = _cx_nav.index[-1]
        if selected_range == "6M":
            start_dt = last_dt - pd.DateOffset(months=6)
        elif selected_range == "1A":
            start_dt = last_dt - pd.DateOffset(years=1)
        elif selected_range == "3A":
            start_dt = last_dt - pd.DateOffset(years=3)
        elif selected_range in ("5A", "6A", "Test (6A)"):
            start_dt = pd.Timestamp("2020-09-30")
        else:
            start_dt = _cx_nav.index[0]

        _nav_plot = _cx_nav[_cx_nav.index >= start_dt].copy()
        _nav_plot["norm"] = (_nav_plot["value"] / _nav_plot["value"].iloc[0]) * 100.0

        # Carica benchmark SPY dal dataset mensile storico completo (1993–2026)
        s_spy_full = portfolio_manager.load_monthly_benchmark_spy(start_date=_nav_plot.index[0])
        common_dt = _nav_plot.index.intersection(s_spy_full.index)

        # Scala logaritmica
        _cx_use_log = False
        if selected_range in ("3A", "5A", "Test (6A)", "Da Inizio"):
            _cx_use_log = st.toggle("Scala logaritmica", value=False, key="convex_log_scale")

        fig_cx_eq = go.Figure()
        fig_cx_eq.add_trace(go.Scatter(
            x=_nav_plot.index, y=_nav_plot["norm"], mode="lines", name="Convex Stack",
            line=dict(color=ACCENT, width=2),
            fill=None if _cx_use_log else "tozeroy", fillcolor="rgba(201, 164, 76, 0.10)",
            hovertemplate="Base 100: %{y:.2f}<extra></extra>"
        ))
        if len(common_dt) > 0:
            _spy_aligned = s_spy_full.loc[common_dt]
            _spy_norm = (_spy_aligned / _spy_aligned.iloc[0]) * 100.0
            fig_cx_eq.add_trace(go.Scatter(
                x=_spy_norm.index, y=_spy_norm, mode="lines", name="S&P 500 Benchmark",
                line=dict(color='#7A7266', width=1.5, dash='dot'),
                hovertemplate="S&P 500: %{y:.2f}<extra></extra>"
            ))

        # Marcatori Test Recente e Live
        _oos_start = pd.Timestamp("2020-09-30")
        if _nav_plot.index[0] <= _oos_start <= _nav_plot.index[-1]:
            fig_cx_eq.add_vline(x=_oos_start, line=dict(color=MUTED, width=1, dash="dash"))
            fig_cx_eq.add_annotation(x=_oos_start, y=1.0, yref="paper", yanchor="bottom",
                                      xanchor="left",
                                      text="Fase di test recente (2020) →", showarrow=False,
                                      font=dict(size=10, color=ACCENT))

        _live_start = pd.Timestamp("2026-09-14")
        if _nav_plot.index[0] < _live_start <= _nav_plot.index[-1]:
            fig_cx_eq.add_vline(x=_live_start, line=dict(color="#3DDC97", width=1, dash="dash"))
            fig_cx_eq.add_annotation(x=_live_start, y=0.88, yref="paper", yanchor="bottom",
                                      xanchor="right",
                                      text="← Inizio operatività reale (Settembre 2026)", showarrow=False,
                                      font=dict(size=10, color="#3DDC97"))

        fig_cx_update_layout = dict(
            template="plotly_dark",
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color=MUTED, family="Inter"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=10)),
            margin=dict(t=30, b=10, l=10, r=10), height=280,
            xaxis=dict(range=[_nav_plot.index[0], _nav_plot.index[-1]], showgrid=False, tickfont=dict(size=10)),
            yaxis=dict(type="log") if _cx_use_log else dict(),
            yaxis_title="Base 100"
        )
        fig_cx_eq.update_layout(**fig_cx_update_layout)
        st.plotly_chart(fig_cx_eq, use_container_width=True)

        st_html(section_title("Perdite Temporanee dal Massimo (Calo dal Picco)", top="14px", bottom="6px"))
        fig_cx_dd = go.Figure()
        fig_cx_dd.add_trace(go.Scatter(
            x=_nav_plot.index, y=_nav_plot["drawdown"], fill="tozeroy", mode="lines",
            line=dict(color=NEG, width=1.2), fillcolor="rgba(236,101,123,0.15)",
            hovertemplate="%{x|%d %b %Y}<br>Calo: %{y:.2f}%<extra></extra>", name="Calo"
        ))
        if _nav_plot.index[0] <= _oos_start <= _nav_plot.index[-1]:
            fig_cx_dd.add_vline(x=_oos_start, line=dict(color=MUTED, width=1, dash="dash"))
        if _nav_plot.index[0] < _live_start <= _nav_plot.index[-1]:
            fig_cx_dd.add_vline(x=_live_start, line=dict(color="#3DDC97", width=1, dash="dash"))

        fig_cx_dd.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color=MUTED, family="Inter"),
            xaxis=dict(range=[_nav_plot.index[0], _nav_plot.index[-1]], showgrid=False, tickfont=dict(size=10)),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,247,237,0.05)', tickfont=dict(size=10), ticksuffix="%"),
            margin=dict(t=4, b=10, l=10, r=10), height=140, showlegend=False
        )
        st.plotly_chart(fig_cx_dd, use_container_width=True)

        st.caption("Percentuale di discesa temporanea dal valore massimo precedente, calcolata al lordo delle imposte.")

        st_html(section_title("Tabella dei Rendimenti Mese per Mese"))
        st_html(render_monthly_returns_html_table(_cx_nav))

        st_html(section_title("Affidabilità e Regolarità dei Risultati"))
        st.caption("Statistiche sui mesi positivi e capacità di tenuta del portafoglio nei momenti negativi di mercato.")
        _cx_pos_months = int((_cx_ret > 0).sum())
        _cx_tot_months = int(len(_cx_ret))
        _cx_best_m = float(_cx_ret.max() * 100.0) if not _cx_ret.empty else 0.0
        _cx_worst_m = float(_cx_ret.min() * 100.0) if not _cx_ret.empty else 0.0
        _cx_pos_pct = (_cx_pos_months / _cx_tot_months * 100.0) if _cx_tot_months > 0 else 0.0

        st_html(f"""
        <div style="display:flex; gap:20px; flex-wrap:wrap; margin-bottom:20px;">
            {sub_hero_metric("Mesi Positivi", f"{_cx_pos_pct:.1f}%", f"{_cx_pos_months} su {_cx_tot_months} mesi", POS if _cx_pos_pct >= 55 else None)}
            {sub_hero_metric("Miglior Mese", f"+{_cx_best_m:.2f}%", "Picco mensile positivo", POS)}
            {sub_hero_metric("Peggior Mese", f"{_cx_worst_m:.2f}%", "Massima contrazione mensile", NEG)}
        </div>
        """)
    else:
        st.warning("Dati storici non trovati (convex_monthly_returns.csv).")

with tab_guida:
    st_html(section_title("La Routine Operativa in 3 Semplici Passi", top="0"))
    r1, r2, r3 = st.columns(3)
    for col, num, title, body in [
        (r1, "1", "Risparmio Mensile (PAC)", "All'inizio di ogni mese, versa la rata di risparmio periodico."),
        (r2, "2", "Verifica del Portafoglio", "Controlla le quote possedute e la liquidità disponibile."),
        (r3, "3", "Riequilibrio & Trim", "Acquista lo strumento più indietro. Vendi una parte di Oro/BTC solo se saliti oltre il 75% del target."),
    ]:
        with col:
            st_html(f"""
            <div class="glass-card" style="text-align:center; height: 130px;">
                <div style="font-family:{FRAUNCES}; font-size:24px; color:{ACCENT}; font-weight:700;">{num}</div>
                <div style="font-size:13.5px; font-weight:700; color:{BADGE_TEXT}; margin:6px 0;">{title}</div>
                <div style="font-size:12px; color:{MUTED}; line-height:1.4;">{body}</div>
            </div>
            """)

    st_html(section_title(f"I {len(active_instruments)} Strumenti del Portafoglio"))
    st.caption("Dossier strategico, dettagli operativi e trattamento fiscale per ciascun componente del portafoglio.")
    
    meta_map = portfolio_manager.CONVEX_INSTRUMENTS_METADATA
    col_c1, col_c2 = st.columns(2)
    for idx, (key, info) in enumerate(active_instruments.items()):
        meta = meta_map.get(key, {})
        target_pct = info.get("target_weight", 0.0) * 100.0
        target_col = _COLOR_MAP.get(key, ACCENT)
        trim_str = f"Incasso profitti (trim) oltre {meta['trim_threshold']*100:.2f}% (+75% sopra target)" if meta.get("trim_threshold") else "Riequilibrio con nuovi versamenti PAC (nessuna vendita)"
        is_diverso = meta.get("tax_type") == "diverso"
        tax_badge_bg = "rgba(61,220,151,0.12)" if is_diverso else "rgba(255,247,237,0.05)"
        tax_badge_col = POS if is_diverso else MUTED

        card_html = f"""
        <div class="glass-card" style="margin-bottom: 16px; padding: 18px 20px;">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px;">
                <div style="display:flex; align-items:center; gap:10px;">
                    <div style="background:rgba(255,247,237,0.05); border:1px solid {BORDER}; padding:8px; border-radius:8px; display:flex; align-items:center; justify-content:center;">
                        {get_convex_class_svg(key, size=22, color=target_col)}
                    </div>
                    <div>
                        <div style="font-family:{MONO}; font-size:16px; font-weight:800; color:{target_col}; letter-spacing:0.3px;">{key}</div>
                        <div style="font-size:11px; color:{MUTED};">{meta.get('exchange', 'Borsa Europea')} · <span style="font-family:{MONO}; font-weight:600; color:{BADGE_TEXT};">{meta.get('isin', '')}</span></div>
                    </div>
                </div>
                <div style="text-align:right;">
                    <div style="font-family:{MONO}; font-size:15px; font-weight:800; color:{BADGE_TEXT};">Obiettivo {target_pct:.1f}%</div>
                    <div style="font-size:11px; color:{MUTED_2}; font-family:{MONO};">Costo: {info['ter']*100:.2f}%/anno</div>
                </div>
            </div>
            
            <div style="font-size:13px; font-weight:700; color:{BADGE_TEXT}; margin-bottom:8px; line-height:1.35;">
                {info['name']}
            </div>
            
            <div style="font-size:12px; color:{MUTED}; line-height:1.5; margin-bottom:10px;">
                <span style="font-weight:700; color:{BADGE_TEXT};">Ruolo nel Portafoglio:</span> {meta.get('role', info.get('asset_class', ''))}
            </div>

            <div style="font-size:11.5px; color:{MUTED_2}; line-height:1.45; padding:8px 12px; background:rgba(255,247,237,0.02); border:1px solid {BORDER_STRONG}; border-radius:6px; margin-bottom:12px;">
                <span style="font-weight:700; color:{MUTED};">Funzionamento:</span> {meta.get('driver', '')}
            </div>

            <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px; font-size:11px; border-top:1px solid {BORDER}; padding-top:10px;">
                <div style="color:{MUTED};">
                    <span style="font-weight:600;">Regola:</span> {trim_str}
                </div>
                <div>
                    <span style="background:{tax_badge_bg}; color:{tax_badge_col}; padding:3px 8px; border-radius:4px; font-weight:600;">
                        {meta.get('tax_regime', '')}
                    </span>
                </div>
            </div>
        </div>
        """
        with col_c1 if idx % 2 == 0 else col_c2:
            st_html(card_html)


    # Esposizione effettiva del portafoglio
    _ntsg_w = active_instruments.get("NTSG", {}).get("target_weight", 0.0)
    _notional_pct = (1.0 + 0.5 * _ntsg_w) * 100.0
    st_html(section_title("Come Funziona il Controllo del Rischio"))
    st_html(f"""
    <div class="glass-card">
        <div style="font-size: 13px; color: {MUTED}; line-height: 1.6;">
            Convex Stack lavora con un'efficienza superiore alla media: per ogni 100 € investiti, sui mercati lavorano circa {_notional_pct:.1f} €, grazie ai titoli di stato già integrati nel fondo principale NTSG (senza alcun debito a tuo carico).<br><br>
            La protezione del capitale si basa su una regola chiara: quando Bitcoin o Oro crescono tanto da superare la loro quota ideale di oltre il 75%, a fine trimestre si vende la quota in eccesso per <strong>mettere al sicuro i guadagni</strong> e destinarli agli strumenti più prudenti. La solidità complessiva è garantita dalla combinazione di <strong>cinque classi di attivo complementari</strong> (azioni mondiali, piccole aziende di valore, protezione per le crisi, oro fisico e Bitcoin), che non scendono mai tutte insieme nello stesso momento.
        </div>
    </div>
    """)

    st_html(f"""
    <div style="margin-top: 24px; padding: 14px; background: rgba(255,247,237,0.02); border: 1px solid {BORDER}; border-radius: 8px; font-size: 11.5px; color: {MUTED}; line-height: 1.5;">
        Questo strumento è di supporto informativo e non costituisce consulenza finanziaria personalizzata.
        Le performance passate non garantiscono risultati futuri. Investire in strumenti a leva comporta rischio di
        perdita del capitale.
    </div>
    """)
