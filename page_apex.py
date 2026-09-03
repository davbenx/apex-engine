"""
page_apex.py — Pagina Apex Engine (navigazione multipagina, vedi main.py)
==================================================================================
Solo Apex Engine: motore tattico automatico, nessun input Convex qui (vedi
page_convex.py per quello). Principi guida: lean, senza attrito, robusto,
semplice da mantenere. Ricostruito fedelmente dal vero app.py di Apex Engine
(davbenx/apex-engine, backup pre-deploy) — stesse 3 schede (Portafoglio/
Metriche/Guida), stesse icone SVG, stesso grafico con selettore periodo,
stessa card macro. Adattamenti legittimi per il contesto multipagina: nessun
st.set_page_config() (lo imposta main.py una sola volta), capitale nella
sidebar invece che in tab (coerente con page_convex.py, che è EUR-only),
dati apex_data.json/portfolio.json/equity.json letti da GitHub o locale
invece che sempre da GitHub, selettore Completa/Semplice (USMV) aggiunto
questa sessione.
==================================================================================
"""

import base64
import datetime
import json
import os
import urllib.request

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import importlib
import portfolio_manager

try:
    importlib.reload(portfolio_manager)
except Exception:
    pass

# st.set_page_config() rimosso: la pagina gira dentro main.py (st.navigation), che lo imposta una sola volta.

# ==============================================================================
# CACHE PREZZI (scritta da fetch_live_prices.py via GitHub Actions) — il fetch
# SPY a runtime da Streamlit Community Cloud fallisce spesso perché Yahoo
# Finance limita il pool di IP condivisi degli host cloud (segnalato
# dall'utente: "Benchmark SPY non raggiungibile"). Si legge prima questo file
# (aggiornato 3 volte al giorno da un runner con IP diverso); il fetch live
# resta come fallback solo per uso locale/prima esecuzione senza cache.
# ==============================================================================
_PRICE_CACHE_PATH = os.path.join(os.path.dirname(__file__), "live_prices_cache.json")
_PRICE_CACHE_MAX_AGE_H = 48


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


# ==============================================================================
# HTML RENDERING HELPERS & STYLING
# ==============================================================================
def st_html(html_str):
    cleaned = "\n".join(line.strip() for line in html_str.strip().splitlines())
    st.markdown(cleaned, unsafe_allow_html=True)


def fill_slot(slot, html_str):
    """Riempie a posteriori un st.empty() riservato prima nel flusso — usato
    per il valore hero, che deve apparire visivamente PRIMA del controllo
    capitale ma puo' essere calcolato solo DOPO aver letto il widget."""
    cleaned = "\n".join(line.strip() for line in html_str.strip().splitlines())
    slot.markdown(cleaned, unsafe_allow_html=True)


st_html("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=JetBrains+Mono:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"], .stApp {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        letter-spacing: -0.01em;
    }

    /* Tabular numbers for financial metrics and dataframes */
    [data-testid="stMetricValue"], [data-testid="stMetricLabel"], .stDataFrame, div[data-testid="stTable"], table {
        font-family: 'JetBrains Mono', monospace !important;
        font-variant-numeric: tabular-nums !important;
    }

    /* Tab navigation polish */
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

    div[style*="border-radius"] {
        transition: border-color 0.15s ease-in-out;
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
        border: 1px solid rgba(201, 164, 76, 0.22);
        border-radius: 8px;
        padding: 14px 16px;
        margin-bottom: 16px;
    }

    /* Rimuove completamente la sidebar e controlli collegati */
    [data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"],
    section[data-testid="stSidebar"] {
        display: none !important;
    }
</style>
""")


# ==============================================================================
# DESIGN TOKENS (identici al vero Apex Engine)
# ==============================================================================
POS = "#3DDC97"
NEG = "#EC657B"
MUTED_DOT = "#5B534B"
ACCENT = "#C9A44C"
ACCENT_SOFT = "rgba(201,164,76,0.10)"
SURFACE = "rgba(255,247,237,0.045)"
BORDER = "rgba(255,247,237,0.09)"
BORDER_STRONG = "rgba(255,247,237,0.16)"
MUTED = "#9C9187"
MUTED_2 = "#6E655C"
BADGE_TEXT = "#F5F1EA"
BADGE_POS_BG = "#1D5F42"
BADGE_NEG_BG = "#7B2836"
BADGE_NEUTRAL_BG = "rgba(255,247,237,0.1)"

CLASS_COLOR_EQ = POS
CLASS_COLOR_BTC = "#2E9E70"
CLASS_COLOR_GOLD = ACCENT
CLASS_COLOR_BOND = "#8B7FC7"
CLASS_COLOR_CASH = "#4A443D"

FRAUNCES = "'Fraunces', Georgia, serif"
MONO = "'JetBrains Mono', monospace"

MESI_IT = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]


# ==============================================================================
# ICONE SVG (identiche al vero Apex Engine)
# ==============================================================================
def get_class_svg(classe, size=16, color="currentColor", style=""):
    """Restituisce l'icona SVG vettoriale ufficiale per ciascuna classe di attivo."""
    inline_style = f"display:inline-block; vertical-align:middle; flex-shrink:0; {style}"
    if classe in ("Azionario", "Azioni"):
        return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{inline_style}"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"></polyline><polyline points="16 7 22 7 22 13"></polyline></svg>'
    if classe == "Bitcoin":
        return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{inline_style}"><path d="M7 6h6a3 3 0 0 1 0 6H7zm0 6h7a3 3 0 0 1 0 6H7z"></path><line x1="10" y1="3" x2="10" y2="6"></line><line x1="14" y1="3" x2="14" y2="6"></line><line x1="10" y1="18" x2="10" y2="21"></line><line x1="14" y1="18" x2="14" y2="21"></line><line x1="7" y1="6" x2="7" y2="18"></line></svg>'
    if classe == "Oro":
        return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="{inline_style}"><polygon points="8.5 6 15.5 6 17 12 7 12" /><polygon points="2.5 13 9.5 13 11 19 1 19" /><polygon points="14.5 13 21.5 13 23 19 13 19" /></svg>'
    if classe == "Obbligazioni":
        return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{inline_style}"><line x1="3" y1="21" x2="21" y2="21"></line><line x1="3" y1="10" x2="21" y2="10"></line><polyline points="5 6 12 3 19 6"></polyline><line x1="6" y1="10" x2="6" y2="21"></line><line x1="10" y1="10" x2="10" y2="21"></line><line x1="14" y1="10" x2="14" y2="21"></line><line x1="18" y1="10" x2="18" y2="21"></line></svg>'
    return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{inline_style}"><rect x="2" y="6" width="20" height="12" rx="2"></rect><circle cx="12" cy="12" r="2.5"></circle><line x1="6" y1="12" x2="6.01" y2="12"></line><line x1="18" y1="12" x2="18.01" y2="12"></line></svg>'


def get_action_svg(action_type, size=16):
    s = str(action_type).upper()
    style = "display:inline-block; vertical-align:middle; flex-shrink:0;"
    if "CHIUSURA" in s or "EXIT" in s or "VENDITA" in s:
        svg = f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{NEG}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="{style}"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>'
        return f'<span title="Chiusura (Vendita 100%)" style="display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; vertical-align:middle; cursor:help;">{svg}</span>'
    if "RIDUZIONE" in s or "TRIM" in s:
        svg = f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{NEG}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="{style}"><line x1="7" y1="7" x2="17" y2="17"></line><polyline points="17 10 17 17 10 17"></polyline></svg>'
        return f'<span title="Riduzione (Vendita parziale)" style="display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; vertical-align:middle; cursor:help;">{svg}</span>'
    if "INCREMENTO" in s:
        svg = f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{POS}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="{style}"><line x1="7" y1="17" x2="17" y2="7"></line><polyline points="7 7 17 7 17 17"></polyline></svg>'
        return f'<span title="Incremento quota" style="display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; vertical-align:middle; cursor:help;">{svg}</span>'
    svg = f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{POS}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="{style}"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>'
    return f'<span title="Apertura (Nuovo acquisto)" style="display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; vertical-align:middle; cursor:help;">{svg}</span>'


def get_reason_svg(reason_text, size=16):
    s = str(reason_text).lower()
    style = "display:inline-block; vertical-align:middle; flex-shrink:0; opacity:0.9;"
    if "rotazione" in s or "uscito" in s:
        svg = f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><path d="M16 3l4 4-4 4"/><path d="M20 7H4"/><path d="M8 21l-4-4 4-4"/><path d="M4 17h16"/></svg>'
        return f'<span title="Rotazione trimestrale paniere" style="display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; vertical-align:middle; cursor:help;">{svg}</span>'
    if "ribilanciamento" in s or "rebalance" in s or "trim" in s:
        svg = f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/></svg>'
        return f'<span title="Ribilanciamento pesi (Vol-targeting)" style="display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; vertical-align:middle; cursor:help;">{svg}</span>'
    if "disattivata" in s or "regime" in s or "stop" in s:
        svg = f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{NEG}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg>'
        return f'<span title="Uscita / Regime disattivato" style="display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; vertical-align:middle; cursor:help;">{svg}</span>'
    svg = f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{MUTED}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>'
    return f'<span title="Allineamento / Setup" style="display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; vertical-align:middle; cursor:help;">{svg}</span>'


# ==============================================================================
# TABELLE HTML (identiche al vero Apex Engine)
# ==============================================================================
def render_positions_html_table(df, active_cols, curr_sym, col_val_label, col_rend_label):
    th_cells = []
    for c in active_cols:
        if c == "Classe":
            th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:center; width:44px; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">Classe</th>')
        elif c == "Data Ingresso":
            th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:center; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">{c}</th>')
        else:
            align = "right" if c in ["Quote", "Ingresso ($)", "Attuale ($)", "Uscita ($)", "Peso (%)", col_val_label, "Rendimento %", col_rend_label] else "left"
            th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:{align}; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">{c}</th>')

    rows_html = []
    for _, r in df.iterrows():
        td_cells = []
        classe = str(r.get("Classe", ""))
        for c in active_cols:
            val = r.get(c, "")
            align = "right" if c in ["Quote", "Ingresso ($)", "Attuale ($)", "Uscita ($)", "Peso (%)", col_val_label, "Rendimento %", col_rend_label] else "left"
            if c == "Classe":
                svg = get_class_svg(classe, size=16)
                td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:center; width:44px;"><span title="{classe}" style="display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; vertical-align:middle; cursor:help;">{svg}</span></td>')
            elif c == "Strumento":
                td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-weight:700; color:{BADGE_TEXT}; white-space:nowrap;">{val}</td>')
            elif c == "Data Ingresso":
                td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:center; color:{MUTED}; white-space:nowrap;">{val}</td>')
            elif c == "Quote":
                td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:{align}; font-family:{MONO}; white-space:nowrap;">{val}</td>')
            elif c in ["Ingresso ($)", "Attuale ($)"]:
                v_str = f"${val:,.2f}" if (pd.notna(val) and isinstance(val, (int, float))) else "—"
                td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:{align}; font-family:{MONO}; white-space:nowrap;">{v_str}</td>')
            elif c == "Peso (%)":
                v_str = f"{val:.2f}%" if pd.notna(val) else "—"
                td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-family:{MONO}; font-weight:600; white-space:nowrap;">{v_str}</td>')
            elif c == col_val_label:
                v_str = f"{curr_sym}{val:,.0f}" if (pd.notna(val) and isinstance(val, (int, float))) else "—"
                td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-family:{MONO}; font-weight:600; white-space:nowrap;">{v_str}</td>')
            elif c == "Rendimento %":
                if pd.notna(val) and isinstance(val, (int, float)):
                    color = POS if val > 0 else NEG if val < 0 else MUTED
                    v_str = f"{val:+.2f}%"
                    td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-family:{MONO}; font-weight:700; color:{color}; white-space:nowrap;">{v_str}</td>')
                else:
                    td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-family:{MONO}; color:{MUTED};">—</td>')
            elif c == col_rend_label:
                if pd.notna(val) and isinstance(val, (int, float)):
                    color = POS if val > 0 else NEG if val < 0 else MUTED
                    v_str = f"{curr_sym}{val:+,.0f}"
                    td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-family:{MONO}; font-weight:700; color:{color}; white-space:nowrap;">{v_str}</td>')
                else:
                    td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-family:{MONO}; color:{MUTED};">—</td>')
            else:
                td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align};">{val}</td>')
        rows_html.append(f'<tr style="border-bottom:1px solid {BORDER}; transition:background 0.15s ease;">{"".join(td_cells)}</tr>')
    return f'''<div style="width:100%; max-height:420px; overflow-y:auto; overflow-x:auto; border:1px solid {BORDER}; border-radius:8px; background:rgba(255,247,237,0.02); margin-bottom:18px;"><table style="width:100%; border-collapse:collapse; text-align:left;"><thead><tr>{"".join(th_cells)}</tr></thead><tbody>{"".join(rows_html)}</tbody></table></div>'''


def render_orders_html_table(df, curr_sym):
    th_cols = ["Operazione", "Strumento", "Variazione Peso", f"Controvalore ({curr_sym})", "Quote", "Prezzo ($)", "Dettaglio Operativo"]
    th_cells = []
    for c in th_cols:
        align = "center" if c == "Operazione" else ("right" if c in [f"Controvalore ({curr_sym})", "Quote", "Prezzo ($)", "Variazione Peso"] else "left")
        th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:{align}; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">{c}</th>')

    rows_html = []
    for _, r in df.iterrows():
        td_cells = []
        op = str(r.get("Operazione", ""))
        for c in th_cols:
            val = r.get(c, "")
            align = "right" if c in [f"Controvalore ({curr_sym})", "Quote", "Prezzo ($)", "Variazione Peso"] else "left"
            if c == "Operazione":
                td_cells.append(f'<td style="padding:10px 14px; text-align:center; width:44px;">{get_action_svg(op, size=16)}</td>')
            elif c == "Strumento":
                td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-weight:700; color:{BADGE_TEXT}; white-space:nowrap;">{val}</td>')
            elif c == "Variazione Peso":
                td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:{align}; font-family:{MONO}; white-space:nowrap;">{val}</td>')
            elif c == f"Controvalore ({curr_sym})":
                v_str = f"{curr_sym}{val:,.0f}" if (pd.notna(val) and isinstance(val, (int, float))) else "—"
                td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-family:{MONO}; font-weight:600; white-space:nowrap;">{v_str}</td>')
            elif c == "Quote":
                td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:{align}; font-family:{MONO}; white-space:nowrap;">{val}</td>')
            elif c == "Prezzo ($)":
                v_str = f"${val:,.2f}" if (pd.notna(val) and isinstance(val, (int, float))) else "—"
                td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:{align}; font-family:{MONO}; white-space:nowrap;">{v_str}</td>')
            elif c == "Dettaglio Operativo":
                td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:{align}; color:{MUTED};">{val}</td>')
            else:
                td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align};">{val}</td>')
        rows_html.append(f'<tr style="border-bottom:1px solid {BORDER}; transition:background 0.15s ease;">{"".join(td_cells)}</tr>')
    return f'''<div style="width:100%; overflow-x:auto; border:1px solid {BORDER}; border-radius:8px; background:rgba(255,247,237,0.02); margin-bottom:14px;"><table style="width:100%; border-collapse:collapse; text-align:left;"><thead><tr>{"".join(th_cells)}</tr></thead><tbody>{"".join(rows_html)}</tbody></table></div>'''


def render_recent_trades_html_table(df, active_cols):
    th_cells = []
    for c in active_cols:
        if c == "Operazione":
            th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:center; width:44px; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">Azione</th>')
        elif c in ["Data Ingresso", "Data Uscita"]:
            th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:center; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">{c}</th>')
        else:
            align = "right" if c in ["Ingresso ($)", "Uscita ($)", "Rendimento %", "Peso (%)"] else "left"
            th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:{align}; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">{c}</th>')

    rows_html = []
    for _, r in df.iterrows():
        td_cells = []
        op = str(r.get("Operazione", ""))
        for c in active_cols:
            val = r.get(c, "")
            align = "right" if c in ["Ingresso ($)", "Uscita ($)", "Rendimento %", "Peso (%)"] else "left"
            if c == "Operazione":
                td_cells.append(f'<td style="padding:10px 14px; text-align:center; width:44px;">{get_action_svg(op, size=16)}</td>')
            elif c == "Strumento":
                td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-weight:700; color:{BADGE_TEXT}; white-space:nowrap;">{val}</td>')
            elif c in ["Data Ingresso", "Data Uscita"]:
                td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:center; color:{MUTED}; white-space:nowrap;">{val}</td>')
            elif c in ["Ingresso ($)", "Uscita ($)"]:
                v_str = f"${val:,.2f}" if (pd.notna(val) and isinstance(val, (int, float))) else "—"
                td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:{align}; font-family:{MONO}; white-space:nowrap;">{v_str}</td>')
            elif c == "Peso (%)":
                v_str = f"{val:.2f}%" if pd.notna(val) else "—"
                td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-family:{MONO}; font-weight:600; white-space:nowrap;">{v_str}</td>')
            elif c == "Rendimento %":
                if pd.notna(val) and isinstance(val, (int, float)):
                    color = POS if val > 0 else NEG if val < 0 else MUTED
                    v_str = f"{val:+.2f}%"
                    td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-family:{MONO}; font-weight:700; color:{color}; white-space:nowrap;">{v_str}</td>')
                else:
                    td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-family:{MONO}; color:{MUTED};">—</td>')
            else:
                td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align};">{val}</td>')
        rows_html.append(f'<tr style="border-bottom:1px solid {BORDER}; transition:background 0.15s ease;">{"".join(td_cells)}</tr>')
    return f'''<div style="width:100%; overflow-x:auto; border:1px solid {BORDER}; border-radius:8px; background:rgba(255,247,237,0.02); margin-bottom:14px;"><table style="width:100%; border-collapse:collapse; text-align:left;"><thead><tr>{"".join(th_cells)}</tr></thead><tbody>{"".join(rows_html)}</tbody></table></div>'''


def render_hist_trades_html_table(df, active_cols):
    th_cells = []
    for c in active_cols:
        if c == "Motivazione":
            th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:center; width:44px; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">Tipo</th>')
        elif c in ["Data Ingresso", "Data Uscita", "Durata"]:
            th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:center; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">{c}</th>')
        else:
            align = "right" if c in ["Prezzo Ingresso", "Prezzo Uscita", "Rendimento %"] else "left"
            th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:{align}; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">{c}</th>')

    rows_html = []
    for _, r in df.iterrows():
        td_cells = []
        reason = str(r.get("Motivazione", ""))
        for c in active_cols:
            val = r.get(c, "")
            align = "right" if c in ["Prezzo Ingresso", "Prezzo Uscita", "Rendimento %"] else "left"
            if c == "Motivazione":
                td_cells.append(f'<td style="padding:10px 14px; text-align:center; width:44px;">{get_reason_svg(reason, size=16)}</td>')
            elif c == "Titolo":
                td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-weight:700; color:{BADGE_TEXT}; white-space:nowrap;">{val}</td>')
            elif c in ["Data Ingresso", "Data Uscita"]:
                td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:center; color:{MUTED}; white-space:nowrap;">{val}</td>')
            elif c == "Durata":
                td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:center; font-family:{MONO}; white-space:nowrap;">{val}</td>')
            elif c in ["Prezzo Ingresso", "Prezzo Uscita"]:
                v_str = f"${val:,.2f}" if (pd.notna(val) and isinstance(val, (int, float))) else "—"
                td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:{align}; font-family:{MONO}; white-space:nowrap;">{v_str}</td>')
            elif c == "Rendimento %":
                if pd.notna(val) and isinstance(val, (int, float)):
                    color = POS if val > 0 else NEG if val < 0 else MUTED
                    v_str = f"{val:+.2f}%"
                    td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-family:{MONO}; font-weight:700; color:{color}; white-space:nowrap;">{v_str}</td>')
                else:
                    td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-family:{MONO}; color:{MUTED};">—</td>')
            else:
                td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align};">{val}</td>')
        rows_html.append(f'<tr style="border-bottom:1px solid {BORDER}; transition:background 0.15s ease;">{"".join(td_cells)}</tr>')
    return f'''<div style="width:100%; max-height:420px; overflow-y:auto; overflow-x:auto; border:1px solid {BORDER}; border-radius:8px; background:rgba(255,247,237,0.02); margin-bottom:18px;"><table style="width:100%; border-collapse:collapse; text-align:left;"><thead><tr>{"".join(th_cells)}</tr></thead><tbody>{"".join(rows_html)}</tbody></table></div>'''


def render_monthly_returns_html_table(df_eq):
    """Genera la matrice HTML istituzionale dei rendimenti mensili e annuali."""
    if df_eq is None or df_eq.empty:
        return ''
    df = df_eq.copy()
    years = sorted(df.index.year.unique(), reverse=True)
    months = list(range(1, 13))

    th_cells = [f'<th style="padding:8px 10px; font-weight:600; color:{MUTED}; font-size:11px; text-align:left; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">Anno</th>']
    for m_name in MESI_IT:
        th_cells.append(f'<th style="padding:8px 8px; font-weight:600; color:{MUTED}; font-size:11px; text-align:right; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">{m_name}</th>')
    th_cells.append(f'<th style="padding:8px 12px; font-weight:700; color:{ACCENT}; font-size:11px; text-align:right; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; border-left:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">Tot Anno</th>')

    rows_html = []
    for y in years:
        td_cells = [f'<td style="padding:8px 10px; font-size:12px; font-weight:700; color:{BADGE_TEXT}; font-family:{MONO};">{y}</td>']
        df_y = df[df.index.year == y]
        df_prev = df[df.index.year < y]
        y_start_val = df_prev['value'].iloc[-1] if not df_prev.empty else df_y['value'].iloc[0]
        y_end_val = df_y['value'].iloc[-1]
        y_ret = ((y_end_val / y_start_val) - 1.0) * 100.0 if y_start_val > 0 else 0.0

        for m in months:
            df_ym = df[(df.index.year == y) & (df.index.month == m)]
            if df_ym.empty:
                td_cells.append(f'<td style="padding:8px 8px; font-size:11.5px; text-align:center; color:{MUTED}; font-family:{MONO}; opacity:0.4;">—</td>')
            else:
                df_before = df[df.index < df_ym.index[0]]
                m_start_val = df_before['value'].iloc[-1] if not df_before.empty else df_ym['value'].iloc[0]
                m_end_val = df_ym['value'].iloc[-1]
                m_ret = ((m_end_val / m_start_val) - 1.0) * 100.0 if m_start_val > 0 else 0.0

                col = POS if m_ret > 0 else NEG if m_ret < 0 else MUTED
                bg = 'rgba(61,220,151,0.07)' if m_ret > 0 else 'rgba(236,101,123,0.08)' if m_ret < 0 else 'transparent'
                td_cells.append(f'<td style="padding:8px 8px; font-size:11.5px; text-align:right; font-family:{MONO}; font-weight:600; color:{col}; background:{bg}; white-space:nowrap;">{m_ret:+.1f}%</td>')

        y_col = POS if y_ret > 0 else NEG if y_ret < 0 else MUTED
        y_bg = 'rgba(61,220,151,0.12)' if y_ret > 0 else 'rgba(236,101,123,0.12)' if y_ret < 0 else 'transparent'
        td_cells.append(f'<td style="padding:8px 12px; font-size:12px; text-align:right; font-family:{MONO}; font-weight:700; color:{y_col}; background:{y_bg}; border-left:1px solid {BORDER_STRONG}; white-space:nowrap;">{y_ret:+.1f}%</td>')
        rows_html.append(f'<tr style="border-bottom:1px solid {BORDER}; transition:background 0.15s ease;">{"".join(td_cells)}</tr>')

    return f'''<div style="width:100%; overflow-x:auto; border:1px solid {BORDER}; border-radius:8px; background:rgba(255,247,237,0.02); margin-bottom:22px;"><table style="width:100%; border-collapse:collapse; text-align:left;"><thead><tr>{"".join(th_cells)}</tr></thead><tbody>{"".join(rows_html)}</tbody></table></div>'''


def section_title(text, top="26px", bottom="10px"):
    return f'<div style="font-family:{FRAUNCES}; font-size:16px; font-weight:600; letter-spacing:-0.1px; margin:{top} 0 {bottom};">{text}</div>'


def monogram(text, size=26):
    return f'''<span style="display:inline-flex; align-items:center; justify-content:center; width:{size}px; height:{size}px; border-radius:6px; border:1px solid {ACCENT}; color:{ACCENT}; font-family:{MONO}; font-weight:700; font-size:10px; letter-spacing:-0.3px; flex-shrink:0;">{text}</span>'''


def get_logo_b64():
    for p in ["logo_icon.png", "logo.png"]:
        if os.path.exists(p):
            try:
                with open(p, "rb") as f:
                    return base64.b64encode(f.read()).decode()
            except Exception:
                pass
    return ""


def calculate_days(entry_date_str):
    try:
        entry_d = datetime.datetime.strptime(entry_date_str, "%Y-%m-%d").date()
        today = datetime.datetime.now().date()
        return max(0, (today - entry_d).days)
    except Exception:
        return 0


def format_date_italian(d_str):
    try:
        dt = datetime.datetime.strptime(d_str, "%Y-%m-%d")
        return f"{dt.day} {MESI_IT[dt.month-1]} {dt.year}"
    except Exception:
        return d_str


def parse_sync_timestamp(ts_str):
    try:
        return datetime.datetime.strptime(ts_str, "%d %b %Y, %H:%M (UTC)")
    except Exception:
        return None


def format_sync_timestamp_italian(ts_str):
    dt = parse_sync_timestamp(ts_str)
    if not dt:
        return ts_str
    return f"{dt.day} {MESI_IT[dt.month-1]} {dt.year}, {dt.strftime('%H:%M')} UTC"


# ==============================================================================
# CARICAMENTO CONFIGURAZIONE UTENTE E DATI LIVE (GitHub o locale)
# ==============================================================================
cfg = portfolio_manager.load_config()


@st.cache_data(ttl=60)
def fetch_json_local_or_github(filename):
    url = f"https://raw.githubusercontent.com/davbenx/apex-engine/main/{filename}"
    try:
        req = urllib.request.Request(f"{url}?t={int(datetime.datetime.now().timestamp() // 60)}", headers={'User-Agent': 'Mozilla/5.0'})
        return json.loads(urllib.request.urlopen(req, timeout=4).read().decode())
    except Exception:
        local_path = os.path.join(os.path.dirname(__file__), filename)
        if os.path.exists(local_path):
            try:
                with open(local_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
    return None


data = fetch_json_local_or_github("apex_data.json") or {}
apex_portfolio = fetch_json_local_or_github("portfolio.json") or {}

_apex_live_eur = None
try:
    _nav_usd = float(apex_portfolio.get("nav_usd", 0.0))
    _eur_usd_rate_live = float(data.get("eur_usd", 0.0))
    if _nav_usd > 0 and _eur_usd_rate_live > 0:
        _apex_live_eur = _nav_usd / _eur_usd_rate_live
except Exception:
    _apex_live_eur = None




# ==============================================================================
# HEADER & BRANDING (identico al vero Apex Engine)
# ==============================================================================
last_update = data.get("timestamp", "Sincronizzazione in corso...")
last_update_display = format_sync_timestamp_italian(last_update)

_sync_dt = parse_sync_timestamp(last_update)
_days_stale = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - _sync_dt).days if _sync_dt else None
engine_is_fresh = _days_stale is None or _days_stale <= 4
engine_status_text = "Motore Attivo" if engine_is_fresh else f"Ricalcolo in ritardo ({_days_stale}g)"
engine_status_color = POS if engine_is_fresh else NEG

logo_b64 = get_logo_b64()
logo_tag = f'<img src="data:image/png;base64,{logo_b64}" style="height: 48px; width: auto; object-fit: contain;" />' if logo_b64 else monogram("AE", size=42)

col_logo, col_stat = st.columns([3, 2])
with col_logo:
    st_html(f"""
    <div style="display: flex; align-items: center; gap: 14px; padding: 6px 0;">
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; padding: 5px 9px; border-radius: 10px; display: flex; align-items: center; justify-content: center;">
            {logo_tag}
        </div>
        <div>
            <div style="font-family: {FRAUNCES}; font-size: 22px; font-weight: 600; letter-spacing: -0.4px; line-height: 1.2;">Apex Engine</div>
            <div style="font-size: 11px; font-weight: 600; opacity: 0.65; letter-spacing: 0.4px; text-transform: uppercase; margin-top: 1px;">
                Sistema Quantitativo Multi-Asset <span style="color: {ACCENT}; font-weight: 700;">Tattico</span>
            </div>
        </div>
    </div>
    """)

with col_stat:
    st_html(f"""
    <div style="text-align: right; padding-top: 10px;">
        <div style="font-size: 11px; color: {MUTED};">
            <span style="width:6px; height:6px; border-radius:50%; background:{engine_status_color}; display:inline-block; margin-right:5px;"></span>{engine_status_text} · Aggiornato {last_update_display}
        </div>
        <div style="font-size: 11px; color: {MUTED_2}; margin-top: 4px;">
            Cadenza: decisione venerdì, esecuzione lunedì
        </div>
    </div>
    """)

# ==========================================================================
# VERSIONE — Completa (basket 15 titoli) o Semplice (1 ETF, USMV). Un
# precedente candidato (VLUE) è stato scartato: il suo apparente vantaggio
# derivava per ~25% da un solo titolo (Micron) durante un rally isolato
# 2025-2026, non da un vero effetto fattoriale (VLUE ha perso in 3 dei 5
# anni testati — research/test_weekly_apex_vlue_deep_dive.py). USMV è
# scelto per bassa concentrazione (titolo più pesante ~1.6%), non perché
# batte la versione Completa: su questa finestra è leggermente peggiore su
# CAGR, Sharpe e MaxDD — vedi research/apex_simple_etf_README.md.
# ==========================================================================
apex_versione = st.segmented_control(
    "Versione", options=["Completa", "Semplice"], default="Completa",
    label_visibility="collapsed", key="apex_versione"
) or "Completa"

_apex_simple_path = os.path.join(os.path.dirname(__file__), "apex_simple_etf_returns.csv")
m_apex = portfolio_manager.get_apex_metrics()
_m_apex_active = m_apex
_se_df = None
if apex_versione == "Semplice" and os.path.exists(_apex_simple_path):
    st.caption(
        "1 ETF (USMV, basso rischio di concentrazione) invece del basket di 15 titoli. "
        "Un po' meno performante della versione Completa (CAGR, Sharpe e MaxDD leggermente "
        "peggiori) ma molto più semplice — scelto per bassa concentrazione su singolo "
        "titolo (~1,6%), non perché batte la versione standard."
    )
    _se_df = pd.read_csv(_apex_simple_path, parse_dates=["date"]).set_index("date")
    _se_n_years = (_se_df.index[-1] - _se_df.index[0]).days / 365.25
    _se_cagr_net = (_se_df["nav_net"].iloc[-1] / _se_df["nav_net"].iloc[0]) ** (1 / _se_n_years) - 1
    _se_cagr_gross = (_se_df["nav_gross"].iloc[-1] / _se_df["nav_gross"].iloc[0]) ** (1 / _se_n_years) - 1
    _se_ret = _se_df["nav_net"].pct_change().dropna()
    _se_vol = _se_ret.std() * (252 ** 0.5)
    _se_sharpe = (_se_cagr_net - 0.03) / _se_vol if _se_vol > 0 else 0.0
    _se_dd_series = _se_df["nav_net"] / _se_df["nav_net"].cummax() - 1.0
    _se_mdd = _se_dd_series.min()
    _se_downside = _se_ret[_se_ret < 0]
    _se_sortino = (_se_cagr_net - 0.03) / (_se_downside.std() * (252 ** 0.5)) if len(_se_downside) > 0 and _se_downside.std() > 0 else 0.0
    _se_calmar = _se_cagr_net / abs(_se_mdd) if _se_mdd != 0 else 0.0
    _m_apex_active = {
        **m_apex, "cagr_net": _se_cagr_net, "cagr_gross": _se_cagr_gross,
        "volatility": _se_vol, "sharpe": _se_sharpe, "sortino": _se_sortino,
        "max_drawdown": _se_mdd, "calmar": _se_calmar,
    }

# ==============================================================================
# PORTFOLIO DATA EXTRACTION (serve sia al callout sopra le tab sia alla tab)
# ==============================================================================
alloc = data.get('allocations', {"Equities": 0, "Crypto": 0, "Gold": 0, "Bonds": 0, "Cash": 100})
raw_ts = data.get('timestamp', '')
ts_date = raw_ts.split(',')[0].strip() if ',' in raw_ts else (raw_ts.split(' ')[0] if raw_ts else datetime.datetime.now().strftime('%Y-%m-%d'))
macro_dates = data.get("macro_dates", {})

d_eq = macro_dates.get("Equities", ts_date)
d_cr = macro_dates.get("Crypto", ts_date)
d_g = macro_dates.get("Gold", ts_date)
d_b = macro_dates.get("Bonds", ts_date)

pf = apex_portfolio if apex_portfolio else None
open_pos_raw = pf.get("open_positions", {}) if pf else {}
op_eq = []
op_cr = []
num_eq = 0
num_cr = 0

if pf:
    for ticker, info in open_pos_raw.items():
        entry_d = info.get("entry_date", "N/A")
        days_open = calculate_days(entry_d) if entry_d != "N/A" else 0
        fmt_entry_d = format_date_italian(entry_d) if entry_d != "N/A" else "—"
        entry_formatted = f"{fmt_entry_d} ({days_open}g)" if entry_d != "N/A" else "—"

        curr_p = info.get("current_price", info.get("entry_price", 0.0))
        pnl_pct = ((curr_p / info["entry_price"]) - 1.0) * 100 if info.get("entry_price", 0) > 0 else 0.0

        is_crypto = info.get("is_crypto", False)
        is_new_this_week = days_open <= 7

        if is_crypto:
            num_cr += 1
            pos_num = num_cr
        else:
            num_eq += 1
            pos_num = num_eq

        row = {
            "Pos": pos_num,
            "Titolo": ticker,
            "Stato": "NUOVO" if is_new_this_week else "",
            "Data Ingresso": entry_formatted,
            "Ingresso ($)": info.get("entry_price", 0.0),
            "Attuale ($)": curr_p,
            "Peso (%)": info.get("weight", 0.0) * 100.0,
            "Rendimento %": pnl_pct
        }
        if is_crypto:
            op_cr.append(row)
        else:
            op_eq.append(row)


def find_crypto_position(open_positions):
    for tkr, info in open_positions.items():
        if info.get("is_crypto"):
            return tkr, info
    return None, None


def position_detail(ticker, capitale_usd):
    info = open_pos_raw.get(ticker)
    if not info:
        return None
    entry_p = info.get("entry_price", 0.0)
    curr_p = info.get("current_price", entry_p)
    weight = info.get("weight", 0.0)
    entry_d = info.get("entry_date", "N/A")
    days = calculate_days(entry_d) if entry_d != "N/A" else 0
    pnl_pct = ((curr_p / entry_p) - 1.0) * 100 if entry_p > 0 else 0.0
    value_usd = capitale_usd * weight
    pnl_usd = (pnl_pct / 100.0) * value_usd
    return {
        "entry_price": entry_p, "current_price": curr_p, "weight_pct": weight * 100.0,
        "entry_date": entry_d, "days": days, "pnl_pct": pnl_pct, "pnl_usd": pnl_usd, "value_usd": value_usd,
    }


# ==============================================================================
# SCHEDE PRINCIPALI (PORTAFOGLIO, METRICHE, GUIDA) — identiche al vero Apex Engine
# ==============================================================================
tab_pf, tab_perf, tab_guide = st.tabs([
    "Portafoglio",
    "Metriche",
    "Guida"
])


# ==============================================================================
# TAB 1: PORTAFOGLIO & ALLOCAZIONE
# ==============================================================================
with tab_pf:
    hero_slot = st.empty()

    with st.expander("⚙️ Parametri Capitale Broker Apex", expanded=False):
        c_cap, c_save = st.columns([3, 1])
        with c_cap:
            cap_apex_input = st.number_input(
                "Capitale Apex broker reale (€)",
                min_value=1000.0,
                value=float(cfg.get("apex_capital_eur", 100000.0)),
                step=5000.0,
                format="%.0f",
                help="Capitale effettivo allocato su Apex Engine. Calcola quote e controvalori operativi esatti."
            )
        with c_save:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            if st.button("Salva Capitale", use_container_width=True, key="apex_save_cap"):
                new_cfg = {**cfg, "apex_capital_eur": cap_apex_input,
                           "last_updated": datetime.date.today().strftime("%Y-%m-%d")}
                if portfolio_manager.save_config(new_cfg):
                    st.toast("Capitale Apex salvato per questa sessione.", icon="✅")
                    cfg = new_cfg
                else:
                    st.error("Errore nel salvataggio della configurazione.")
        if _apex_live_eur:
            st.caption(f"↳ Capitale configurabile · default 100.000 € (NAV storico del modello: €{_apex_live_eur:,.0f} / ${_nav_usd:,.0f})")
        else:
            st.caption("↳ Valore standard da config.json")



    eur_usd_rate = float(data.get("eur_usd", 1.085))
    curr_sym = "€"
    fx_ratio = 1.0 / eur_usd_rate
    capitale = float(cap_apex_input) * eur_usd_rate  # capitale in USD, per confronto con i prezzi di posizione

    gold_cap = capitale * (alloc.get('Gold', 0) / 100)
    bond_cap = capitale * (alloc.get('Bonds', 0) / 100)

    tot_pnl_usd = 0.0
    tot_invested_usd = 0.0

    for r in op_eq + op_cr:
        size = capitale * (r.get("Peso (%)", 0.0) / 100.0)
        tot_pnl_usd += (r["Rendimento %"] / 100) * size
        tot_invested_usd += size

    gold_detail = position_detail("GLD", capitale) if alloc.get('Gold', 0) > 0 else None
    if gold_detail:
        tot_pnl_usd += gold_detail["pnl_usd"]
        tot_invested_usd += gold_cap

    bond_detail = position_detail("IEF", capitale) if alloc.get('Bonds', 0) > 0 else None
    if bond_detail:
        tot_pnl_usd += bond_detail["pnl_usd"]
        tot_invested_usd += bond_cap

    btc_ticker, _ = find_crypto_position(open_pos_raw)
    btc_detail = position_detail(btc_ticker, capitale) if btc_ticker else None

    tot_pnl_pct = (tot_pnl_usd / capitale * 100) if capitale > 0 else 0.0
    tot_pnl_user = tot_pnl_usd * fx_ratio
    num_pos = len(op_eq) + len(op_cr) + (1 if gold_detail else 0) + (1 if bond_detail else 0)

    pnl_col = POS if tot_pnl_user >= 0 else NEG
    pnl_sign = "+" if tot_pnl_user >= 0 else "-"
    pnl_pct_str = f"{'+' if tot_pnl_pct >= 0 else ''}{tot_pnl_pct:.2f}%"
    fill_slot(hero_slot, f"""
    <div style="padding: 16px 2px 4px;">
        <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.8px; color: {MUTED}; margin-bottom: 8px;">Valore Portafoglio</div>
        <div style="display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;">
            <span style="font-family:{MONO}; font-size:40px; font-weight:800; letter-spacing:-1px;">{curr_sym}{capitale * fx_ratio:,.0f}</span>
            <span style="font-size:16px; font-weight:700; color:{pnl_col};">{pnl_sign}{curr_sym}{abs(tot_pnl_user):,.0f} <span style="opacity:0.75; font-weight:600;">({pnl_pct_str})</span></span>
        </div>
        <div style="font-size:12px; color:{MUTED}; margin-top:8px;">{num_pos} posizioni attive · prossimo ribilanciamento: ultimo venerdì del mese</div>
    </div>
    """)

    pending_orders = (pf or {}).get("pending_orders") or []
    last_actions = (pf or {}).get("last_action_log") or []
    last_action_date = (pf or {}).get("pending_orders_date") or (pf or {}).get("last_action_date") or ""

    PROXIES_DISPLAY = {"GLD": "Oro", "IEF": "Obbligazioni", "BTC": "Bitcoin", "Cash": "Liquidità"}

    hist_trades = (pf or {}).get("trade_history") or []
    latest_hist_exit_date = ""
    latest_hist_trades = []
    if hist_trades:
        exit_dates = [t.get("exit_date") for t in hist_trades if t.get("exit_date")]
        if exit_dates:
            latest_hist_exit_date = max(exit_dates)
            latest_hist_trades = [t for t in hist_trades if t.get("exit_date") == latest_hist_exit_date]

    # --- 1. Regimi e Segnali Macro ---
    st_html(section_title("Regimi e Segnali Macro"))

    def signal_item(label, value_text, title_attr=""):
        svg = get_class_svg(label, size=15)
        title_html = f' title="{title_attr}"' if title_attr else ""
        return f'<div{title_html} style="display:flex; align-items:center; gap:8px; font-size:12.5px;">{svg}<span style="font-weight:600;">{label}</span><span style="font-family:{MONO}; color:{MUTED}; margin-left:auto;">{value_text}</span></div>'

    def class_state(alloc_pct, since_date):
        is_active = alloc_pct > 0
        fmt_d = format_date_italian(since_date) if since_date and since_date != "-" else ""
        title = f"{'Attiva' if is_active else 'In pausa'}{(' dal ' + fmt_d) if fmt_d else ''}"
        value = f"{alloc_pct:.0f}%" if is_active else "in pausa"
        return is_active, value, title

    _eq_active, _eq_val, _eq_title = class_state(alloc.get('Equities', 0), d_eq)
    _cr_active, _cr_val, _cr_title = class_state(alloc.get('Crypto', 0), d_cr)
    _g_active, _g_val, _g_title = class_state(alloc.get('Gold', 0), d_g)
    _b_active, _b_val, _b_title = class_state(alloc.get('Bonds', 0), d_b)

    signals_html = "".join([
        signal_item("Azioni", _eq_val, _eq_title),
        signal_item("Bitcoin", _cr_val, _cr_title),
        signal_item("Oro", _g_val, _g_title),
        signal_item("Obbligazioni", _b_val, _b_title),
        signal_item("Liquidità", f"{alloc.get('Cash', 0):.0f}%"),
    ])
    st_html(f'<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:14px 22px; padding:14px 18px; background:{SURFACE}; border:1px solid {BORDER}; border-radius:10px; margin-bottom:8px;">{signals_html}</div>')
    if not data:
        st.caption("Dati live non raggiungibili in questo momento — mostrati gli ultimi valori disponibili localmente, se presenti.")

    # --- 2. Composizione del Portafoglio ---
    st_html(section_title("Composizione del Portafoglio"))

    alloc_segments = []
    if op_eq:
        alloc_segments.append(("Azioni", sum(r.get("Peso (%)", 0.0) for r in op_eq), CLASS_COLOR_EQ))
    if op_cr:
        alloc_segments.append(("Bitcoin", op_cr[0].get("Peso (%)", 0.0), CLASS_COLOR_BTC))
    if alloc.get('Gold', 0) > 0:
        alloc_segments.append(("Oro", alloc.get('Gold', 0), CLASS_COLOR_GOLD))
    if alloc.get('Bonds', 0) > 0:
        alloc_segments.append(("Obbligazioni", alloc.get('Bonds', 0), CLASS_COLOR_BOND))
    if alloc.get('Cash', 0) > 0:
        alloc_segments.append(("Liquidità", alloc.get('Cash', 0), CLASS_COLOR_CASH))

    if alloc_segments:
        bar_segs = "".join(f'<div style="height:100%; width:{pct:.2f}%; background:{color};"></div>' for _, pct, color in alloc_segments)
        legend_items = "".join(
            f'<div style="display:flex; align-items:center; gap:6px;">{get_class_svg(label, size=14, color=color)} <span style="opacity:0.85;">{label}</span> <b style="font-family:{MONO}; font-weight:700;">{pct:.1f}%</b></div>'
            for label, pct, color in alloc_segments
        )

        st_html(f'<div style="display:flex; height:12px; border-radius:6px; overflow:hidden; border:1px solid {BORDER_STRONG}; margin-bottom:12px;">{bar_segs}</div>')
        st_html(f'<div style="display:flex; flex-wrap:wrap; gap:12px 20px; margin-bottom:20px; font-size:11.5px;">{legend_items}</div>')

    # --- 3. Ordini Operativi / Stato Allineamento ---
    if pending_orders:
        st_html(f"""
        <div style="background: {ACCENT_SOFT}; border: 1px solid rgba(201,164,76,0.35); border-radius: 8px; padding: 12px 16px; margin: 14px 0 10px;">
            <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px;">
                <div>
                    <span style="width:7px; height:7px; border-radius:50%; background:{ACCENT}; display:inline-block; margin-right:7px; flex-shrink:0;"></span>
                    <strong style="font-size:13.5px;">Ordini Operativi per Lunedì ({last_action_date})</strong>
                    <span style="background:{BADGE_NEUTRAL_BG}; color:{ACCENT}; font-size:10px; font-weight:700; padding:2px 6px; border-radius:4px; font-family:{MONO}; margin-left:8px;">DA ESEGUIRE ORE 15:30 CET</span>
                </div>
                <div style="font-size:11.5px; color:{MUTED};">Quote e importi calcolati sul tuo capitale ({curr_sym}{capitale * fx_ratio:,.0f})</div>
            </div>
        </div>
        """)
        orders_rows = []
        for o in pending_orders:
            act_label = o.get("action", "ORDINE")
            if act_label == "TRIM":
                act_label = "RIDUZIONE"
            tkr = o.get("ticker", "")
            disp_name = o.get("display_name") or PROXIES_DISPLAY.get(tkr, tkr)
            px = o.get("price", 0.0)
            delta_w = abs(o.get("delta_w_pct", 0.0))
            val_usd = (delta_w / 100.0) * capitale
            val_user = val_usd * fx_ratio
            is_cr = o.get("is_crypto", False) or tkr == "BTC"
            shares = (val_usd / px) if px > 0 else 0.0
            shares_str = f"{shares:.4f}" if is_cr else f"{int(round(shares)):,}"

            orders_rows.append({
                "Operazione": act_label,
                "Strumento": disp_name,
                "Variazione Peso": f"{o.get('delta_w_pct', 0.0):+.2f}%",
                f"Controvalore ({curr_sym})": val_user,
                "Quote": shares_str,
                "Prezzo ($)": px,
                "Dettaglio Operativo": o.get("desc", "").replace("TRIM:", "RIDUZIONE:"),
            })
        df_orders = pd.DataFrame(orders_rows)
        st_html(render_orders_html_table(df_orders, curr_sym))
    else:
        st_html(f"""
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 11px 16px; margin: 14px 0 16px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
            <div style="display: flex; align-items: center; gap: 9px; font-size: 13px;">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="{POS}" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink: 0;"><polyline points="20 6 9 17 4 12"></polyline></svg>
                <strong>Portafoglio allineato ai target quantitativi</strong>
                <span style="color: {MUTED}; font-size: 12px;">— Nessun ordine da eseguire per lunedì</span>
            </div>
        </div>
        """)

    # --- 4. Posizioni Attive nel Portafoglio ---
    if apex_versione == "Semplice":
        st_html(section_title("Sleeve Azionaria — USMV (ETF Unico)"))
        st.caption("Nessun paniere: quando la classe Azionario è attiva, il 100% dell'esposizione azionaria è su un unico ETF (USMV, iShares MSCI USA Min Vol Factor).")
    else:
        st_html(section_title("Posizioni Attive nel Portafoglio"))
        real_cash_usd = max(0.0, capitale - tot_invested_usd)
        cash_weight_pct = (real_cash_usd / capitale * 100) if capitale > 0 else 0.0

        col_val_label = f"Valore ({curr_sym})"
        col_rend_label = f"Rendimento ({curr_sym})"

        unified_rows = []
        for r in sorted(op_eq, key=lambda x: x["Rendimento %"], reverse=True):
            unified_rows.append({
                "Classe": "Azioni", "Strumento": r["Titolo"],
                "Data Ingresso": r["Data Ingresso"],
                "Ingresso ($)": r["Ingresso ($)"], "Attuale ($)": r["Attuale ($)"],
                "Peso (%)": r["Peso (%)"], "Rendimento %": r["Rendimento %"],
            })
        if op_cr:
            r = op_cr[0]
            unified_rows.append({
                "Classe": "Bitcoin", "Strumento": "Bitcoin",
                "Data Ingresso": r["Data Ingresso"],
                "Ingresso ($)": r["Ingresso ($)"], "Attuale ($)": r["Attuale ($)"],
                "Peso (%)": r["Peso (%)"], "Rendimento %": r["Rendimento %"],
            })

        def _detail_row(classe, disp_name, detail):
            fmt_d = format_date_italian(detail['entry_date']) if detail.get('entry_date') and detail['entry_date'] != "N/A" else "—"
            return {
                "Classe": classe, "Strumento": disp_name,
                "Data Ingresso": f"{fmt_d} ({detail['days']}g)" if fmt_d != "—" else "—",
                "Ingresso ($)": detail["entry_price"], "Attuale ($)": detail["current_price"],
                "Peso (%)": detail["weight_pct"], "Rendimento %": detail["pnl_pct"],
            }

        if gold_detail:
            unified_rows.append(_detail_row("Oro", "Oro", gold_detail))
        if bond_detail:
            unified_rows.append(_detail_row("Obbligazioni", "Obbligazioni", bond_detail))

        unified_rows.append({
            "Classe": "Liquidità", "Strumento": "Liquidità",
            "Data Ingresso": "—",
            "Ingresso ($)": float("nan"), "Attuale ($)": float("nan"),
            "Peso (%)": cash_weight_pct, "Rendimento %": float("nan"),
        })

        if unified_rows:
            show_details = st.toggle("Mostra dettagli esecuzione", value=False, key="pos_details_toggle")
            compact_cols = ["Strumento", "Peso (%)", col_val_label, "Rendimento %"]
            full_cols = ["Classe", "Strumento", "Data Ingresso", "Quote", "Ingresso ($)", "Attuale ($)", "Peso (%)", col_val_label, "Rendimento %", col_rend_label]
            active_cols = full_cols if show_details else compact_cols

            df_pos = pd.DataFrame(unified_rows)

            def _quote_raw(row):
                if pd.notna(row["Ingresso ($)"]) and row["Ingresso ($)"] > 0:
                    return (capitale * row["Peso (%)"] / 100.0) / row["Ingresso ($)"]
                return float("nan")

            def _quote_display(row):
                q = row["Quote_raw"]
                if pd.isna(q):
                    return "—"
                return f"{q:.6f}" if row["Classe"] == "Bitcoin" and q < 1 else (f"{q:.4f}" if row["Classe"] == "Bitcoin" else f"{int(round(q)):,}")

            df_pos["Quote_raw"] = df_pos.apply(_quote_raw, axis=1)
            df_pos["Quote"] = df_pos.apply(_quote_display, axis=1)
            df_pos[col_val_label] = capitale * (df_pos["Peso (%)"] / 100.0) * fx_ratio
            df_pos[col_rend_label] = (df_pos["Rendimento %"] / 100.0) * df_pos[col_val_label]

            st_html(render_positions_html_table(df_pos, active_cols, curr_sym, col_val_label, col_rend_label))
        else:
            st.caption("Nessuna posizione attiva al momento.")

    # --- 5. Ultime Operazioni Eseguite ---
    if apex_versione == "Completa":
        if last_actions:
            rebalance_date_label = f" ({last_action_date})" if last_action_date else ""
            with st.expander(f"Ultime Operazioni Eseguite{rebalance_date_label}"):
                st.caption("Operazioni eseguite durante l'ultimo ciclo di ribilanciamento:")
                st.code("\n".join(last_actions).replace("TRIM:", "RIDUZIONE:"), language=None)
        elif latest_hist_trades:
            rebalance_date_label = f" ({format_date_italian(latest_hist_exit_date)})" if latest_hist_exit_date else ""
            with st.expander(f"Ultime Operazioni Eseguite{rebalance_date_label}"):
                st.caption("Operazioni eseguite durante l'ultimo ciclo di ribilanciamento:")
                show_rec_details = st.toggle("Mostra dettagli esecuzione", value=False, key="rec_details_toggle")
                recent_rows = []
                for t in latest_hist_trades:
                    reason = t.get("reason", "")
                    op_type = "RIDUZIONE" if "trim" in reason.lower() else "CHIUSURA"
                    recent_rows.append({
                        "Operazione": op_type,
                        "Strumento": t.get("ticker", ""),
                        "Data Ingresso": format_date_italian(t.get("entry_date", "")),
                        "Data Uscita": format_date_italian(t.get("exit_date", "")),
                        "Ingresso ($)": t.get("entry_price", 0.0),
                        "Uscita ($)": t.get("exit_price", 0.0),
                        "Rendimento %": t.get("profit_pct", 0.0),
                        "Peso (%)": t.get("weight", 0.0) * 100.0 if t.get("weight", 0.0) < 1.0 else t.get("weight", 0.0),
                    })
                df_rec = pd.DataFrame(recent_rows)
                rec_compact = ["Operazione", "Strumento", "Data Uscita", "Rendimento %"]
                rec_full = ["Operazione", "Strumento", "Data Ingresso", "Data Uscita", "Ingresso ($)", "Uscita ($)", "Rendimento %", "Peso (%)"]
                rec_cols = rec_full if show_rec_details else rec_compact
                df_rec_display = df_rec[[c for c in rec_cols if c in df_rec.columns]]
                st_html(render_recent_trades_html_table(df_rec_display, rec_cols))
    else:
        st.caption("Ultime Operazioni Eseguite non disponibile per la versione Semplice: è un backtest, non ha uno storico di operazioni reali proprio.")


# ==============================================================================
# TAB 2: METRICHE (EQUITY CURVE, DRAWDOWN, KPI, STORICO)
# ==============================================================================
with tab_perf:
    # Gerarchia visiva a due livelli: le 3 metriche che rispondono a "quanto ho
    # guadagnato / quanto rischio ho corso" sono grandi e in cima (quelle che
    # contano per chi non è un esperto); le 3 di supporto tecnico (Volatilità,
    # Sortino, Calmar — variazioni/dettagli delle prime) sono più piccole,
    # sotto un separatore. Prima erano 6 numeri tutti uguali, senza gerarchia.
    def sub_hero_metric(label, value, subtext="", val_color=None, primary=False):
        val_size = "32px" if primary else "20px"
        return f"""
        <div style="flex: 1 1 {'160px' if primary else '130px'};">
            <div style="font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.6px; color: {MUTED}; margin-bottom: 5px;">{label}</div>
            <div style="font-family: {MONO}; font-size: {val_size}; font-weight: 800; color: {val_color or 'inherit'};">{value}</div>
            <div style="font-size: 11px; color: {MUTED}; margin-top: 2px;">{subtext}</div>
        </div>
        """

    st_html(f"""
    <div style="display:flex; gap:24px; flex-wrap:wrap; margin-bottom:16px;">
        {sub_hero_metric("Crescita Annua Netta", f"{_m_apex_active['cagr_net']*100:+.2f}%", f"Lordo: {_m_apex_active['cagr_gross']*100:+.2f}%", POS if _m_apex_active['cagr_net'] >= 0 else NEG, primary=True)}
        {sub_hero_metric("Indice di Sharpe", f"{_m_apex_active['sharpe']:.2f}", "Efficienza rendimento/rischio", POS if _m_apex_active['sharpe'] >= 1.0 else None, primary=True)}
        {sub_hero_metric("Calo Massimo Storico", f"{_m_apex_active['max_drawdown']*100:.2f}%", "Il calo peggiore mai vissuto", primary=True)}
    </div>
    <div style="display:flex; gap:20px; flex-wrap:wrap; margin-bottom:24px; padding-top:12px; border-top:1px solid {BORDER};">
        {sub_hero_metric("Volatilità Annua", f"{_m_apex_active['volatility']*100:.1f}%", "Oscillazione realizzata")}
        {sub_hero_metric("Indice di Sortino", f"{_m_apex_active['sortino']:.2f}", "Come Sharpe, guarda solo ai cali")}
        {sub_hero_metric("Calmar", f"{_m_apex_active['calmar']:.2f}", "Crescita / peggior perdita")}
    </div>
    """)

    st_html(section_title("Curva Equity vs Benchmark (SPY)", top="8px", bottom="8px"))
    if apex_versione == "Semplice":
        st.caption("Backtest su USMV (2017+) — Apex non ha mai tradato realmente questa versione: solo i 15 titoli (Completa) sono il conto vero.")

    selected_range = st.segmented_control(
        "Periodo",
        options=["6M", "1A", "3A", "5A", "Tutto"],
        default="Tutto" if apex_versione == "Semplice" else "1A",
        label_visibility="collapsed",
        key="chart_range_ctrl"
    )
    if not selected_range:
        selected_range = "Tutto" if apex_versione == "Semplice" else "1A"


    @st.cache_data(ttl=3600)
    def load_benchmark():
        cache = _load_price_cache()
        if cache and cache.get("spy_history") and cache["_age_hours"] <= _PRICE_CACHE_MAX_AGE_H:
            hist = cache["spy_history"]
            idx = pd.to_datetime([h["date"] for h in hist])
            df_b = pd.DataFrame({
                "open": [h["open"] for h in hist],
                "high": [h["high"] for h in hist],
                "low": [h["low"] for h in hist],
                "close": [h["close"] for h in hist],
            }, index=idx).ffill().dropna()
            return df_b
        try:
            # range=10y (non 2y): la versione Semplice mostra fino a 9 anni di
            # storico ("Tutto") — con solo 2 anni di SPY il benchmark veniva
            # normalizzato a un punto di partenza a metà grafico invece che
            # dall'inizio reale, producendo una curva incoerente (segnalato
            # dall'utente). 10y copre anche il caso Completa (storico più
            # corto) senza alcun costo aggiuntivo.
            url = "https://query2.finance.yahoo.com/v8/finance/chart/SPY?range=10y&interval=1d"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            res = json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
            data_spy = res['chart']['result'][0]
            timestamps = pd.to_datetime(data_spy['timestamp'], unit='s')
            quote = data_spy['indicators']['quote'][0]
            df_b = pd.DataFrame({
                'open': quote['open'], 'high': quote['high'], 'low': quote['low'], 'close': quote['close']
            }, index=timestamps).ffill().dropna()
            return df_b
        except Exception:
            return pd.DataFrame()

    # Carica lo storico: Completa usa equity.json reale, Semplice usa il
    # backtest USMV già caricato sopra (_se_df) — nessun dato inventato.
    if apex_versione == "Semplice" and _se_df is not None:
        df_eq = _se_df.rename(columns={"nav_net": "close"}).copy()
        df_eq["open"] = df_eq["close"].shift(1).fillna(df_eq["close"].iloc[0])
        df_eq["high"] = df_eq[["open", "close"]].max(axis=1)
        df_eq["low"] = df_eq[["open", "close"]].min(axis=1)
        eq_curve = {"history": True}
    else:
        _eq_path_local = os.path.join(os.path.dirname(__file__), "equity.json")
        eq_curve = fetch_json_local_or_github("equity.json") or (json.load(open(_eq_path_local)) if os.path.exists(_eq_path_local) else None)
        df_eq = None
        if eq_curve and "history" in eq_curve and len(eq_curve["history"]) > 0:
            df_eq = pd.DataFrame(eq_curve["history"])
            df_eq['date'] = pd.to_datetime(df_eq['date'])
            df_eq = df_eq.sort_values('date').drop_duplicates('date', keep='last').set_index('date')
            if 'open' not in df_eq.columns or df_eq['open'].isna().all():
                df_eq['open'] = df_eq['value'].shift(1).fillna(df_eq['value'].iloc[0])
                df_eq['high'] = df_eq[['open', 'value']].max(axis=1)
                df_eq['low'] = df_eq[['open', 'value']].min(axis=1)
            df_eq['close'] = df_eq['value'] if 'value' in df_eq.columns else df_eq['close']

    if df_eq is not None and len(df_eq) > 0:
        df_eq['roll_max'] = df_eq['close'].cummax()
        df_eq['drawdown'] = (df_eq['close'] - df_eq['roll_max']) / df_eq['roll_max'] * 100

        initial_val = df_eq['open'].iloc[0]
        final_val = df_eq['close'].iloc[-1]
        base_val = initial_val if initial_val > 0 else 100000.0
        df_eq['norm_open'] = (df_eq['open'] / base_val) * 100
        df_eq['norm_high'] = (df_eq['high'] / base_val) * 100
        df_eq['norm_low'] = (df_eq['low'] / base_val) * 100
        df_eq['norm_close'] = (df_eq['close'] / base_val) * 100

        if len(df_eq) >= 5:
            df_agg = df_eq.resample('W-FRI').agg({
                'norm_open': 'first', 'norm_high': 'max', 'norm_low': 'min', 'norm_close': 'last', 'close': 'last'
            }).dropna()
            df_agg['norm_high'] = df_agg[['norm_open', 'norm_close', 'norm_high']].max(axis=1)
            df_agg['norm_low'] = df_agg[['norm_open', 'norm_close', 'norm_low']].min(axis=1)
        else:
            df_agg = df_eq

        last_dt = df_agg.index[-1]
        if selected_range == "1M":
            start_dt = last_dt - pd.DateOffset(months=1)
        elif selected_range == "3M":
            start_dt = last_dt - pd.DateOffset(months=3)
        elif selected_range == "6M":
            start_dt = last_dt - pd.DateOffset(months=6)
        elif selected_range == "1A":
            start_dt = last_dt - pd.DateOffset(years=1)
        else:
            start_dt = df_agg.index[0]

        df_plot = df_agg[df_agg.index >= start_dt].copy()

        ticks, tick_labels = [], []
        if not df_plot.empty:
            start_d, end_d = df_plot.index[0], df_plot.index[-1]
            total_days = (end_d - start_d).days
            all_days = pd.date_range(start_d, end_d, freq='D')
            if total_days <= 45:
                ticks = [all_days[i] for i in range(0, len(all_days), 7)]
                tick_labels = [f"{d.day} {MESI_IT[d.month-1]}" for d in ticks]
            elif total_days <= 120:
                ticks = [d for d in all_days if d.day in [1, 15]]
                tick_labels = [f"{d.day:02d} {MESI_IT[d.month-1]}" for d in ticks]
            elif total_days <= 450:
                ticks = [d for d in all_days if d.day == 1]
                tick_labels = [f"{MESI_IT[d.month-1]} '{d.strftime('%y')}" if (d.month in [1, 7] or (len(ticks) > 0 and d == ticks[0])) else MESI_IT[d.month-1] for d in ticks]
            else:
                ticks = [d for d in all_days if d.day == 1 and d.month in [1, 4, 7, 10]]
                tick_labels = [f"{MESI_IT[d.month-1]} '{d.strftime('%y')}" for d in ticks]

        it_dates_str = [f"{d.day:02d} {MESI_IT[d.month-1]} {d.year}" for d in df_plot.index]

        df_spy = load_benchmark()

        fig = go.Figure()
        _y_values = list(df_plot['norm_close'])

        strategy_name = "USMV (Semplice)" if apex_versione == "Semplice" else "Apex Engine"
        fig.add_trace(go.Scatter(
            x=df_plot.index, y=df_plot['norm_close'], mode='lines', name=strategy_name,
            line=dict(color=ACCENT, width=2), fill='tozeroy', fillcolor='rgba(201, 164, 76, 0.10)',
            text=it_dates_str, hovertemplate="<b>%{text}</b><br>Base 100: %{y:.2f}<extra></extra>"
        ))

        if not df_spy.empty:
            start_date = df_plot.index[0]
            df_spy_aligned = df_spy[df_spy.index >= start_date].copy()
            if not df_spy_aligned.empty:
                first_spy = df_spy_aligned['close'].iloc[0]
                df_spy_plot = df_spy_aligned['close'].resample('W-FRI').last().dropna() if len(df_spy_aligned) >= 5 else df_spy_aligned['close']
                df_spy_norm = (df_spy_plot / first_spy) * 100
                _y_values.extend(df_spy_norm.tolist())
                spy_it_dates = [f"{d.day:02d} {MESI_IT[d.month-1]} {d.year}" for d in df_spy_plot.index]
                fig.add_trace(go.Scatter(
                    x=df_spy_plot.index, y=df_spy_norm, text=spy_it_dates,
                    hovertemplate="<b>%{text}</b><br>S&P 500: %{y:.2f}<extra></extra>",
                    mode='lines', name="S&P 500 Benchmark", line=dict(color='#7A7266', width=1.5, dash='dot'),
                ))
        else:
            st.caption("Benchmark SPY non raggiungibile in questo momento — mostrata solo la curva della strategia.")

        _y_min, _y_max = min(_y_values), max(_y_values)
        _y_pad = max((_y_max - _y_min) * 0.08, 1.0)

        fig.update_layout(
            template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(family="Inter, sans-serif"),
            xaxis=dict(showgrid=False, tickfont=dict(size=11),
                       tickmode='array' if len(ticks) > 0 else 'auto',
                       tickvals=ticks if len(ticks) > 0 else None,
                       ticktext=tick_labels if len(tick_labels) > 0 else None),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,247,237,0.07)', tickfont=dict(size=11),
                       range=[_y_min - _y_pad, _y_max + _y_pad]),
            margin=dict(l=0, r=0, t=10, b=0), height=380,
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor='rgba(0,0,0,0)')
        )
        st.plotly_chart(fig, use_container_width=True)

        st_html(section_title("Calo dal Massimo Storico", top="14px", bottom="6px"))
        df_underwater = df_eq[(df_eq.index >= df_plot.index[0]) & (df_eq.index <= df_plot.index[-1])]
        dd_it_dates_str = [f"{d.day:02d} {MESI_IT[d.month-1]} {d.year}" for d in df_underwater.index]
        fig_dd = go.Figure()
        fig_dd.add_trace(go.Scatter(
            x=df_underwater.index, y=df_underwater['drawdown'], fill='tozeroy', mode='lines',
            line=dict(color=NEG, width=1.2), fillcolor='rgba(236, 101, 123, 0.15)',
            text=dd_it_dates_str, hovertemplate="<b>%{text}</b><br>Calo: %{y:.2f}%<extra></extra>", name="Calo"
        ))
        fig_dd.update_layout(
            template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(family="Inter, sans-serif"),
            xaxis=dict(showgrid=False, tickfont=dict(size=10),
                       tickmode='array' if len(ticks) > 0 else 'auto',
                       tickvals=ticks if len(ticks) > 0 else None,
                       ticktext=tick_labels if len(tick_labels) > 0 else None),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,247,237,0.05)', tickfont=dict(size=10), ticksuffix="%"),
            margin=dict(l=0, r=0, t=4, b=0), height=110, showlegend=False
        )
        st.plotly_chart(fig_dd, use_container_width=True)

        if apex_versione == "Completa":
            st.caption(
                f"Grafico dai {len(df_eq)} punti di storico reale disponibili "
                f"({df_eq.index[0].date()} → {df_eq.index[-1].date()})."
            )

        st_html(section_title("Matrice dei Rendimenti"))
        st_html(render_monthly_returns_html_table(df_eq.rename(columns={"close": "value"}) if "value" not in df_eq.columns else df_eq))
    else:
        st.info("In attesa del file di tracciamento storico.")

    # --- Statistiche Operative (solo versione Completa: storico reale di trade) ---
    if apex_versione == "Semplice":
        st.caption("Statistiche Operative e Registro Operazioni non disponibili per la versione Semplice: è un backtest su USMV, non ha uno storico di operazioni reali proprio (quello in Completa è dei 15 titoli).")
    elif pf:
        hist = pf.get("trade_history", [])
        wins = [t for t in hist if t.get("profit_pct", 0) > 0]
        losses = [t for t in hist if t.get("profit_pct", 0) <= 0]

        win_rate = (len(wins) / len(hist) * 100) if hist else 0.0
        gross_profit = sum(t["profit_pct"] for t in wins)
        gross_loss = abs(sum(t["profit_pct"] for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss != 0 else 0.0
        expectancy_pct = sum(t["profit_pct"] for t in hist) / len(hist) if hist else 0.0

        def kpi_item(title, value, subtext="", badge_text=None, badge_color=None, val_color=None):
            badge_html = ""
            if badge_text:
                bcol = badge_color or BADGE_NEUTRAL_BG
                badge_html = f'<div style="margin-top:4px;"><span style="background:{bcol}; color:{BADGE_TEXT}; font-size:8.5px; font-weight:700; padding:2px 5px; border-radius:3px; font-family:{MONO}; letter-spacing:0.3px; display:inline-block;">{badge_text}</span></div>'
            return f"""
            <div style="padding: 6px 8px; min-width: 0;">
                <div style="font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; color: {MUTED}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">{title}</div>
                <div style="font-size: 18px; font-weight: 800; color: {val_color or 'inherit'}; font-family: {MONO}; margin: 2px 0;">{value}</div>
                <div style="font-size: 10.5px; color: {MUTED}; line-height: 1.2;">{subtext}</div>
                {badge_html}
            </div>
            """

        if hist:
            st_html(section_title("Statistiche Operative"))
            strip_items = [
                kpi_item("Tasso di Successo", f"{win_rate:.1f}%", f"{len(wins)} vincenti su {len(hist)}", badge_text=f"{len(wins)}/{len(hist)}"),
                kpi_item("Aspettativa per Trade", f"{expectancy_pct:+.2f}%", "Rendimento atteso medio",
                         badge_text="EDGE STATISTICO", badge_color=BADGE_POS_BG, val_color=POS if expectancy_pct > 0 else NEG),
                kpi_item("Fattore di Profitto", f"{profit_factor:.2f}", "Profitti lordi / perdite",
                         badge_text=("ECCELLENTE" if profit_factor >= 1.5 else "STABILE"),
                         badge_color=(BADGE_POS_BG if profit_factor >= 1.5 else BADGE_NEUTRAL_BG)),
            ]
            p_list = [t.get("profit_pct", 0.0) for t in hist]
            max_idx, min_idx = p_list.index(max(p_list)), p_list.index(min(p_list))
            durations = []
            for t in hist:
                try:
                    d_in = datetime.datetime.strptime(str(t.get("entry_date", "")), "%Y-%m-%d")
                    d_out = datetime.datetime.strptime(str(t.get("exit_date", "")), "%Y-%m-%d")
                    durations.append(max(1, (d_out - d_in).days))
                except Exception:
                    pass
            avg_days_val = int(round(sum(durations) / len(durations))) if durations else 0
            strip_items += [
                kpi_item("Miglior Operazione", hist[max_idx].get("ticker", "-"), f"{hist[max_idx].get('profit_pct', 0.0):+.2f}%", val_color=POS),
                kpi_item("Peggior Operazione", hist[min_idx].get("ticker", "-"), f"{hist[min_idx].get('profit_pct', 0.0):+.2f}%", val_color=NEG),
                kpi_item("Durata Media", f"{avg_days_val}g", "giorni in posizione"),
            ]
            st_html(f'<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 4px 8px; background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 14px; margin-bottom: 20px;">{"".join(strip_items)}</div>')

            st_html(section_title("Registro Operazioni Chiuse"))
            df_hist = pd.DataFrame(hist).sort_values("exit_date", ascending=False)

            def calc_duration(r):
                try:
                    d_in = datetime.datetime.strptime(str(r.get("entry_date", "")), "%Y-%m-%d")
                    d_out = datetime.datetime.strptime(str(r.get("exit_date", "")), "%Y-%m-%d")
                    return f"{max(1, (d_out - d_in).days)}g"
                except Exception:
                    return "-"

            df_hist["Durata"] = df_hist.apply(calc_duration, axis=1)
            df_hist = df_hist.rename(columns={
                "ticker": "Titolo", "entry_date": "Data Ingresso", "exit_date": "Data Uscita",
                "entry_price": "Prezzo Ingresso", "exit_price": "Prezzo Uscita",
                "profit_pct": "Rendimento %", "reason": "Motivazione"
            })

            def _short_reason(raw):
                s = str(raw)
                if "Migrazione" in s:
                    return "Migrazione"
                if "Ribilanciamento" in s:
                    return "Ribilanciamento"
                if "Uscito" in s or "disattivata" in s:
                    return "Rotazione"
                return (s[:20] + "…") if len(s) > 20 else s

            if "Motivazione" in df_hist.columns:
                df_hist["Motivazione"] = df_hist["Motivazione"].apply(_short_reason)

            show_trade_details = st.toggle("Mostra dettagli esecuzione", value=False, key="trade_details_toggle")
            compact_cols_hist = ["Titolo", "Data Uscita", "Durata", "Rendimento %", "Motivazione"]
            full_cols_hist = ["Titolo", "Data Ingresso", "Data Uscita", "Durata", "Prezzo Ingresso", "Prezzo Uscita", "Rendimento %", "Motivazione"]
            cols_hist = full_cols_hist if show_trade_details else compact_cols_hist

            df_hist["Data Uscita"] = df_hist["Data Uscita"].apply(lambda d: format_date_italian(d) if d else "—")
            if "Data Ingresso" in df_hist.columns:
                df_hist["Data Ingresso"] = df_hist["Data Ingresso"].apply(lambda d: format_date_italian(d) if d else "—")

            df_hist_display = df_hist[[c for c in cols_hist if c in df_hist.columns]]

            c_srch, c_flt = st.columns([2, 1])
            with c_srch:
                search_t = st.text_input("Cerca Ticker", placeholder="Cerca per simbolo o nome (es. NVDA, AAPL, BTC...)", label_visibility="collapsed")
            with c_flt:
                reason_options = ["Tutte le Operazioni"] + sorted(df_hist_display["Motivazione"].dropna().unique().tolist()) if "Motivazione" in df_hist_display.columns else ["Tutte le Operazioni"]
                flt_reason = st.selectbox("Filtro Uscita", reason_options, label_visibility="collapsed")

            if search_t:
                df_hist_display = df_hist_display[df_hist_display["Titolo"].str.contains(search_t.strip().upper(), na=False)]
            if flt_reason != "Tutte le Operazioni":
                df_hist_display = df_hist_display[df_hist_display["Motivazione"] == flt_reason]

            st_html(render_hist_trades_html_table(df_hist_display, cols_hist))
            st.caption("**Trasparenza Metodologica:** I dati mostrano la simulazione oggettiva su dati storici reali di mercato. Le posizioni correnti e i segnali settimanali sono elaborati dal vivo dall'algoritmo Apex.")
        else:
            st.info("Nessuna operazione chiusa registrata.")


# ==============================================================================
# TAB 3: GUIDA & STRATEGIA
# ==============================================================================
with tab_guide:
    st_html(f'''
    <div style="background: rgba(0, 136, 204, 0.06); border: 1px solid rgba(0, 136, 204, 0.25); border-radius: 8px; padding: 14px 18px; margin-bottom: 22px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
        <div>
            <div style="font-weight: 700; font-size: 14.5px; color: #0088cc; margin-bottom: 3px;">Canale Ufficiale Notifiche Telegram</div>
            <div style="font-size: 12.5px; opacity: 0.85; line-height: 1.4;">Ricevi in tempo reale i cambi di regime macro e gli ordini operativi del venerdì sera.</div>
        </div>
        <a href="https://t.me/apex_multiasset" target="_blank" style="background: #0088cc; color: #ffffff; text-decoration: none; padding: 7px 16px; border-radius: 6px; font-size: 12.5px; font-weight: 700;">
            Unisciti al Canale →
        </a>
    </div>
    ''')

    st_html(section_title("La Routine Operativa", top="0"))
    st_html(f"""
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 24px;">
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px 16px;">
            <div style="font-family: {FRAUNCES}; font-weight: 600; font-size: 14px; margin-bottom: 6px;">1. Venerdì Sera</div>
            <div style="font-size: 12.5px; opacity: 0.85; line-height: 1.5;">Il motore analizza le chiusure settimanali. Se c'è un ribilanciamento, ricevi la notifica Telegram con gli ordini esatti (vendite e acquisti) e le quote calcolate sul tuo capitale.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px 16px;">
            <div style="font-family: {FRAUNCES}; font-weight: 600; font-size: 14px; margin-bottom: 6px;">2. Lunedì Pomeriggio</div>
            <div style="font-size: 12.5px; opacity: 0.85; line-height: 1.5;">All'apertura dei mercati USA, esegui gli ordini sul tuo broker (es. Fineco, IBKR, Trade Republic). Se il venerdì non c'erano ordini, <strong>non fai nulla</strong>.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px 16px;">
            <div style="font-family: {FRAUNCES}; font-weight: 600; font-size: 14px; margin-bottom: 6px;">3. Durante la Settimana</div>
            <div style="font-size: 12.5px; opacity: 0.85; line-height: 1.5;">Nessun intervento necessario. L'algoritmo non fa micro-trading intraday: zero stress, zero decisioni emotive e piena serenità.</div>
        </div>
    </div>
    """)

    st.divider()

    st_html(section_title("Allocazione Dinamica", top="0"))
    st_html(f'''
    <div style="font-size: 12.5px; opacity: 0.85; line-height: 1.5; margin-bottom: 14px;">
        Ogni classe di attivo viene attivata solo quando il proprio trend di fondo è confermato al rialzo, proteggendo il capitale durante le fasi orso e sfruttando la crescita nei mercati favorevoli:
    </div>

    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; margin-bottom: 24px;">
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 12px 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="font-weight: 700; font-size: 13.5px; display: inline-flex; align-items: center; gap: 7px;">{get_class_svg("Azioni", 16)} Azioni</span>
                <span style="background: {BADGE_NEUTRAL_BG}; color: {POS}; font-size: 9.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: {MONO};">15 AZIONI A BASSA VOLATILITÀ</span>
            </div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.45;">Selezione trimestrale delle 15 azioni a minore oscillazione dell'S&P 500 (max 2 per settore). Massima efficienza fiscale (minusvalenze compensabili).</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 12px 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="font-weight: 700; font-size: 13.5px; display: inline-flex; align-items: center; gap: 7px;">{get_class_svg("Bitcoin", 16)} Bitcoin</span>
                <span style="background: {BADGE_NEUTRAL_BG}; color: #2E9E70; font-size: 9.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: {MONO};">ATTIVO DIGITALE</span>
            </div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.45;">Cattura la forte espansione dei cicli di liquidità globale. Disattivato tempestivamente durante i mercati ribassisti prolungati.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 12px 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="font-weight: 700; font-size: 13.5px; display: inline-flex; align-items: center; gap: 7px;">{get_class_svg("Oro", 16)} Oro</span>
                <span style="background: {BADGE_NEUTRAL_BG}; color: {ACCENT}; font-size: 9.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: {MONO};">BENE RIFUGIO</span>
            </div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.45;">Protezione contro svalutazione monetaria, inflazione e shock geopolitici. Attivo nei trend rialzisti dei metalli preziosi.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 12px 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="font-weight: 700; font-size: 13.5px; display: inline-flex; align-items: center; gap: 7px;">{get_class_svg("Obbligazioni", 16)} Obbligazioni</span>
                <span style="background: {BADGE_NEUTRAL_BG}; color: #8B7FC7; font-size: 9.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: {MONO};">TITOLI DI STATO USA</span>
            </div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.45;">Obbligazioni governative USA a 7-10 anni, allocate quando il trend dei tassi e del credito è favorevole.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 12px 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="font-weight: 700; font-size: 13.5px; display: inline-flex; align-items: center; gap: 7px;">{get_class_svg("Liquidità", 16)} Liquidità</span>
                <span style="background: {BADGE_NEUTRAL_BG}; color: {MUTED}; font-size: 9.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: {MONO};">RISERVA MONETARIA</span>
            </div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.45;">Custodia sicura per la liquidità non investita. Genera rendimenti monetari di mercato a zero rischio di capitale.</div>
        </div>
    </div>
    ''')

    st.divider()

    st_html(section_title("Sicurezza Quantitativa", top="0"))
    st_html(f"""
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 24px;">
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px 16px;">
            <div style="font-family: {FRAUNCES}; font-weight: 600; font-size: 14px; margin-bottom: 4px;">1. Controllo della Volatilità Adattivo</div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.5;">Il peso di ciascun asset viene scalato periodicamente in base alla volatilità del mercato: nei periodi turbolenti l'esposizione si riduce in automatico, comprimendo i drawdown storici.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px 16px;">
            <div style="font-family: {FRAUNCES}; font-weight: 600; font-size: 14px; margin-bottom: 4px;">2. Garanzia Strutturale Senza Leva Finanziaria</div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.5;">La somma dei pesi di portafoglio è vincolata matematicamente a non superare mai il 100% (&Sigma; w &le; 1.0). Zero rischio di margin call o liquidazione forzata.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px 16px;">
            <div style="font-family: {FRAUNCES}; font-weight: 600; font-size: 14px; margin-bottom: 4px;">3. Tendenza a Doppio Orizzonte con Isteresi</div>
            <div style="font-family: Inter, sans-serif; font-size: 12px; opacity: 0.85; line-height: 1.5;">Richiede l'accordo contemporaneo delle medie mobili a 40 e 20 settimane con una banda di tolleranza anti-rumore, evitando ingressi e uscite repentine sui falsi segnali.</div>
        </div>
    </div>
    """)

    st.divider()

    st_html(f'''
    <div style="background: rgba(236, 101, 123, 0.04); border: 1px solid rgba(236, 101, 123, 0.18); border-radius: 8px; padding: 12px 16px; font-size: 11.5px; opacity: 0.85; line-height: 1.5;">
        <strong>Note Legali ed Esclusione di Responsabilità:</strong><br>
        Questa piattaforma ha scopo puramente informativo e di analisi statistica quantitativa. Non costituisce consulenza finanziaria personalizzata, sollecitazione al pubblico risparmio né raccomandazione d'investimento ai sensi delle normative vigenti.<br>
        I rendimenti passati e le simulazioni storiche non costituiscono garanzia di risultati futuri. Ogni decisione di investimento comporta il rischio di perdita del capitale ed è effettuata sotto la totale ed esclusiva responsabilità dell'utente.
    </div>
    ''')
