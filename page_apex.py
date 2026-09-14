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
invece che sempre da GitHub. Solo la versione Completa (basket 15 titoli):
la variante Semplice (1 ETF, USMV) è stata rimossa, perdeva su ogni
metrica testata senza alcun vantaggio a compensare la minore complessità.
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
except Exception as _reload_err:
    print(f"[WARN] importlib.reload fallito: {_reload_err}")

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


def _spy_benchmark_freshness_label():
    """Etichetta onesta sulla freschezza del benchmark SPY mostrato — mai
    lasciare che una cache vecchia passi per dato corrente senza dichiararlo."""
    cache = _load_price_cache()
    if cache and cache.get("spy_history"):
        age_h = cache.get("_age_hours", 0.0)
        if age_h > _PRICE_CACHE_MAX_AGE_H:
            return f"Benchmark SPY non aggiornato da {age_h/24:.0f} giorni (ultimo aggiornamento: {cache['fetched_at'][:10]})"
        return None
    return "Benchmark SPY da serie storica locale (nessuna cache prezzi disponibile)"


# ==============================================================================
# HTML RENDERING HELPERS & STYLING (DA UI_COMPONENTS CONDIVISO)
# ==============================================================================
from ui_components import (
    st_html, fill_slot, inject_page_styles, section_title, sub_hero_metric,
    render_monthly_returns_html_table, get_logo_b64,
    POS, NEG, MUTED_DOT, ACCENT, ACCENT_SOFT, SURFACE, BORDER, BORDER_STRONG,
    BORDER_GOLD, MUTED, MUTED_2, BADGE_TEXT, FRAUNCES, MONO, MESI_IT
)

inject_page_styles()

BADGE_POS_BG = "#1D5F42"
BADGE_NEG_BG = "#7B2836"
BADGE_NEUTRAL_BG = "rgba(255,247,237,0.1)"

CLASS_COLOR_EQ = portfolio_manager.get_class_color("Azioni")
CLASS_COLOR_BTC = portfolio_manager.get_class_color("Cryptovalute")
CLASS_COLOR_GOLD = portfolio_manager.get_class_color("Oro")
CLASS_COLOR_BOND = portfolio_manager.get_class_color("Obbligazioni")
CLASS_COLOR_CASH = portfolio_manager.get_class_color("Liquidità")


# ==============================================================================
# ICONE SVG (identiche ad Apex Engine)
# ==============================================================================
def get_class_svg(classe, size=16, color="currentColor", style=""):
    """Restituisce l'icona SVG vettoriale ufficiale per ciascuna classe di attivo."""
    use_col = None if color == "currentColor" else color
    return portfolio_manager.get_macro_class_svg(classe, size=size, color=use_col, style=style)


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
    if "freeride" in s or "de-risk" in s:
        svg = f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{POS}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><polyline points="20 6 9 17 4 12"/></svg>'
        return f'<span title="Freeride De-risk (Recupero 100% capitale)" style="display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; vertical-align:middle; cursor:help;">{svg}</span>'
    if "rotazione" in s or "uscito" in s:
        svg = f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><path d="M16 3l4 4-4 4"/><path d="M20 7H4"/><path d="M8 21l-4-4 4-4"/><path d="M4 17h16"/></svg>'
        return f'<span title="Rotazione trimestrale paniere" style="display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; vertical-align:middle; cursor:help;">{svg}</span>'
    if "trail" in s:
        svg = f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="#A5B4FC" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg>'
        return f'<span title="Trailing Stop" style="display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; vertical-align:middle; cursor:help;">{svg}</span>'
    if "ribilanciamento" in s or "rebalance" in s or "trim" in s:
        svg = f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/><path d="M7 21h10"/><path d="M12 3v18"/><path d="M3 7h2c2 0 5-1 7-2 2 1 5 2 7 2h2"/></svg>'
        return f'<span title="Ribilanciamento pesi (Vol-targeting)" style="display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; vertical-align:middle; cursor:help;">{svg}</span>'
    if "time-stop" in s or "stagnazione" in s:
        svg = f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="#D8B4FE" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{style}"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>'
        return f'<span title="Time-Stop Stagnazione" style="display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px; vertical-align:middle; cursor:help;">{svg}</span>'
    if "disattivata" in s or "regime" in s or "stop" in s or "circuit" in s:
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
            align = "right" if c in ["Quote", "Ingresso ($)", "Attuale ($)", "Stop Loss ($)", "Uscita ($)", "Peso (%)", col_val_label, "Rendimento %", col_rend_label] else "left"
            th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:{align}; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">{c}</th>')

    rows_html = []
    for _, r in df.iterrows():
        td_cells = []
        classe = str(r.get("Classe", ""))
        for c in active_cols:
            val = r.get(c, "")
            align = "right" if c in ["Quote", "Ingresso ($)", "Attuale ($)", "Stop Loss ($)", "Uscita ($)", "Peso (%)", col_val_label, "Rendimento %", col_rend_label] else "left"
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
            elif c == "Stop Loss ($)":
                if pd.notna(val) and isinstance(val, (int, float)) and val > 0:
                    v_str = f"${val:,.2f}"
                    td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:{align}; font-family:{MONO}; font-weight:600; color:{NEG}; white-space:nowrap;">{v_str}</td>')
                elif isinstance(val, str) and val and val != "—":
                    td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:{align}; font-family:{MONO}; font-weight:600; color:{NEG}; white-space:nowrap;">{val}</td>')
                else:
                    td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:{align}; font-family:{MONO}; color:{MUTED}; opacity:0.5;">—</td>')
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
        align = "left" if c in ["Operazione", "Strumento", "Dettaglio Operativo"] else "right"
        th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:{align}; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">{c}</th>')

    rows_html = []
    for _, r in df.iterrows():
        td_cells = []
        op = str(r.get("Operazione", ""))
        for c in th_cols:
            val = r.get(c, "")
            align = "left" if c in ["Operazione", "Strumento", "Dettaglio Operativo"] else "right"
            if c == "Operazione":
                op_u = op.upper()
                if any(k in op_u for k in ("VENDITA", "CHIUSURA", "SELL")):
                    badge_bg = "rgba(236,101,123,0.12)"
                    badge_col = NEG
                    border_col = "rgba(236,101,123,0.3)"
                    op_name = "CHIUSURA" if "CHIUSURA" in op_u else "VENDITA"
                elif any(k in op_u for k in ("RIDUZIONE", "TRIM")):
                    badge_bg = "rgba(201,164,76,0.15)"
                    badge_col = ACCENT
                    border_col = "rgba(201,164,76,0.35)"
                    op_name = "RIDUZIONE"
                elif any(k in op_u for k in ("INCREMENTO", "AUMENTO")):
                    badge_bg = "rgba(61,220,151,0.12)"
                    badge_col = POS
                    border_col = "rgba(61,220,151,0.3)"
                    op_name = "INCREMENTO"
                else:
                    badge_bg = "rgba(61,220,151,0.12)"
                    badge_col = POS
                    border_col = "rgba(61,220,151,0.3)"
                    op_name = "ACQUISTO"
                action_svg = get_action_svg(op_name, size=13)
                td_cells.append(f'<td style="padding:10px 14px; text-align:left; white-space:nowrap;"><span style="background:{badge_bg}; color:{badge_col}; border:1px solid {border_col}; padding:3px 8px; border-radius:4px; font-size:11px; font-weight:700; font-family:{MONO}; display:inline-flex; align-items:center; gap:6px;">{action_svg} {op_name}</span></td>')
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
    th_joined = "".join(th_cells)
    tr_joined = "".join(rows_html)
    return f'<div style="width:100%; overflow-x:auto; border:1px solid {BORDER}; border-radius:8px; background:rgba(255,247,237,0.02); margin-bottom:14px;"><table style="width:100%; border-collapse:collapse; text-align:left;"><thead><tr>{th_joined}</tr></thead><tbody>{tr_joined}</tbody></table></div>'


def render_action_log_html_table(actions):
    th_cols = ["Operazione", "Strumento", "Dettaglio Operativo", "Prezzo ($)"]
    th_cells = []
    for c in th_cols:
        align = "right" if c == "Prezzo ($)" else "left"
        th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:{align}; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">{c}</th>')

    rows_html = []
    for act_str in actions:
        clean = act_str.strip().replace("[", "").replace("]", "").replace("TRIM:", "RIDUZIONE:")
        parts = [p.strip() for p in clean.split("|")]
        first = parts[0]
        op_label = "OPERAZIONE"
        tkr = ""
        if ":" in first:
            a_p, t_p = first.split(":", 1)
            op_label = a_p.strip().upper()
            tkr = t_p.strip()
        else:
            tkr = first

        tkr = portfolio_manager.clean_crypto_ticker(tkr)

        op_u = op_label.upper()
        if any(k in op_u for k in ("VENDITA", "CHIUSURA", "SELL")):
            badge_bg = "rgba(236,101,123,0.12)"
            badge_col = NEG
            border_col = "rgba(236,101,123,0.3)"
            op_name = "CHIUSURA" if "CHIUSURA" in op_u else "VENDITA"
        elif any(k in op_u for k in ("RIDUZIONE", "TRIM")):
            badge_bg = "rgba(201,164,76,0.15)"
            badge_col = ACCENT
            border_col = "rgba(201,164,76,0.35)"
            op_name = "RIDUZIONE"
        elif any(k in op_u for k in ("INCREMENTO", "AUMENTO")):
            badge_bg = "rgba(61,220,151,0.12)"
            badge_col = POS
            border_col = "rgba(61,220,151,0.3)"
            op_name = "INCREMENTO"
        else:
            badge_bg = "rgba(61,220,151,0.12)"
            badge_col = POS
            border_col = "rgba(61,220,151,0.3)"
            op_name = "APERTURA"

        action_svg = get_action_svg(op_name, size=13)
        badge_html = f'<span style="background:{badge_bg}; color:{badge_col}; border:1px solid {border_col}; padding:3px 8px; border-radius:4px; font-size:11px; font-weight:700; font-family:{MONO}; display:inline-flex; align-items:center; gap:6px;">{action_svg} {op_name}</span>'

        detail_str = parts[1] if len(parts) > 1 else "—"
        detail_str = detail_str.replace("Bitcoin Core Ballast", "BTC").replace("Bitcoin Core", "BTC").replace("Bitcoin", "BTC")
        price_str = ""
        for p in parts[2:]:
            if "Prezzo" in p:
                price_str = p.replace("Prezzo:", "").strip()
            elif not price_str:
                price_str = p

        if not price_str and len(parts) > 2:
            price_str = parts[2].replace("Prezzo:", "").strip()

        px_display = price_str if price_str else "—"

        td_cells = [
            f'<td style="padding:10px 14px; text-align:left; white-space:nowrap;">{badge_html}</td>',
            f'<td style="padding:10px 14px; font-size:12.5px; font-weight:700; color:{BADGE_TEXT}; white-space:nowrap;">{tkr}</td>',
            f'<td style="padding:10px 14px; font-size:12px; color:{MUTED};">{detail_str}</td>',
            f'<td style="padding:10px 14px; font-size:12px; text-align:right; font-family:{MONO}; white-space:nowrap;">{px_display}</td>',
        ]
        rows_html.append(f'<tr style="border-bottom:1px solid {BORDER}; transition:background 0.15s ease;">{"".join(td_cells)}</tr>')

    th_joined = "".join(th_cells)
    tr_joined = "".join(rows_html)
    return f'<div style="width:100%; overflow-x:auto; border:1px solid {BORDER}; border-radius:8px; background:rgba(255,247,237,0.02); margin-bottom:14px;"><table style="width:100%; border-collapse:collapse; text-align:left;"><thead><tr>{th_joined}</tr></thead><tbody>{tr_joined}</tbody></table></div>'


def render_recent_trades_html_table(df, active_cols):
    th_cells = []
    for c in active_cols:
        if c == "Operazione":
            th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:left; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">Azione</th>')
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
                op_u = op.upper()
                if any(k in op_u for k in ("CHIUSURA", "VENDITA", "SELL")):
                    badge_bg = "rgba(236,101,123,0.12)"
                    badge_col = NEG
                    border_col = "rgba(236,101,123,0.3)"
                    op_name = "CHIUSURA"
                elif any(k in op_u for k in ("RIDUZIONE", "TRIM")):
                    badge_bg = "rgba(201,164,76,0.15)"
                    badge_col = ACCENT
                    border_col = "rgba(201,164,76,0.35)"
                    op_name = "RIDUZIONE"
                else:
                    badge_bg = "rgba(61,220,151,0.12)"
                    badge_col = POS
                    border_col = "rgba(61,220,151,0.3)"
                    op_name = "ACQUISTO"
                action_svg = get_action_svg(op_name, size=13)
                td_cells.append(f'<td style="padding:10px 14px; text-align:left; white-space:nowrap;"><span style="background:{badge_bg}; color:{badge_col}; border:1px solid {border_col}; padding:3px 8px; border-radius:4px; font-size:11px; font-weight:700; font-family:{MONO}; display:inline-flex; align-items:center; gap:6px;">{action_svg} {op_name}</span></td>')
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
    th_joined = "".join(th_cells)
    tr_joined = "".join(rows_html)
    return f'<div style="width:100%; overflow-x:auto; border:1px solid {BORDER}; border-radius:8px; background:rgba(255,247,237,0.02); margin-bottom:14px;"><table style="width:100%; border-collapse:collapse; text-align:left;"><thead><tr>{th_joined}</tr></thead><tbody>{tr_joined}</tbody></table></div>'


def get_reason_badge(reason_text, size=13):
    s = str(reason_text).strip()
    svg = get_reason_svg(s, size=size)
    s_lower = s.lower()
    bg = "rgba(255,255,255,0.05)"
    fg = BADGE_TEXT
    border = "rgba(255,255,255,0.1)"
    if "freeride" in s_lower or "de-risk" in s_lower:
        bg = "rgba(61, 220, 151, 0.12)"
        fg = POS
        border = "rgba(61, 220, 151, 0.28)"
    elif "rotazione" in s_lower:
        bg = "rgba(59, 130, 246, 0.10)"
        fg = "#93C5FD"
        border = "rgba(59, 130, 246, 0.25)"
    elif "trail" in s_lower:
        bg = "rgba(99, 102, 241, 0.12)"
        fg = "#A5B4FC"
        border = "rgba(99, 102, 241, 0.25)"
    elif "ribilanciamento" in s_lower or "trim" in s_lower:
        bg = "rgba(201, 164, 76, 0.12)"
        fg = "#E5C478"
        border = "rgba(201, 164, 76, 0.30)"
    elif "time-stop" in s_lower or "stagnazione" in s_lower:
        bg = "rgba(168, 85, 247, 0.12)"
        fg = "#D8B4FE"
        border = "rgba(168, 85, 247, 0.25)"
    elif "regime" in s_lower or "stop" in s_lower or "disattivata" in s_lower or "circuit" in s_lower or "bear" in s_lower:
        bg = "rgba(242, 114, 106, 0.10)"
        fg = NEG
        border = "rgba(242, 114, 106, 0.25)"
    elif "migrazione" in s_lower:
        bg = "rgba(156, 163, 175, 0.10)"
        fg = MUTED
        border = "rgba(156, 163, 175, 0.20)"
    return f'<div style="display:inline-flex; align-items:center; gap:6px; background:{bg}; color:{fg}; border:1px solid {border}; padding:3px 8px; border-radius:4px; font-size:11px; font-weight:600; font-family:{MONO}; white-space:nowrap;">{svg}<span>{s}</span></div>'


def render_hist_trades_html_table(df, active_cols):
    th_cells = []
    for c in active_cols:
        if c == "Motivazione":
            th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:left; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">Tipo Operazione</th>')
        elif c in ["Classe", "Era", "Data Ingresso", "Data Uscita", "Durata"]:
            th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:center; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">{c}</th>')
        else:
            align = "right" if c in ["Prezzo Ingresso", "Prezzo Uscita", "Peso (%)", "Rendimento %"] else "left"
            th_cells.append(f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:{align}; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">{c}</th>')

    rows_html = []
    for _, r in df.iterrows():
        td_cells = []
        reason = str(r.get("Motivazione", ""))
        for c in active_cols:
            val = r.get(c, "")
            align = "right" if c in ["Prezzo Ingresso", "Prezzo Uscita", "Peso (%)", "Rendimento %"] else "left"
            if c == "Motivazione":
                td_cells.append(f'<td style="padding:8px 14px; text-align:left; white-space:nowrap;">{get_reason_badge(reason)}</td>')
            elif c == "Titolo":
                td_cells.append(f'<td style="padding:10px 14px; font-size:12.5px; text-align:{align}; font-weight:700; color:{BADGE_TEXT}; white-space:nowrap;">{val}</td>')
            elif c == "Classe":
                cls_str = str(val)
                svg = get_class_svg(cls_str, size=14)
                td_cells.append(f'<td style="padding:10px 14px; font-size:11.5px; text-align:center; white-space:nowrap;"><span title="{cls_str}" style="display:inline-flex; align-items:center; gap:5px; color:{MUTED};">{svg}<span>{cls_str}</span></span></td>')
            elif c == "Era":
                era_str = str(val)
                short_era = era_str.split()[0] if "(" in era_str else era_str
                td_cells.append(f'<td style="padding:10px 14px; font-size:11px; text-align:center; font-family:{MONO}; color:{MUTED}; white-space:nowrap;"><span style="background:rgba(255,255,255,0.04); border:1px solid {BORDER}; padding:2px 6px; border-radius:3px;">{short_era}</span></td>')
            elif c in ["Data Ingresso", "Data Uscita"]:
                td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:center; color:{MUTED}; white-space:nowrap;">{val}</td>')
            elif c == "Durata":
                td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:center; font-family:{MONO}; white-space:nowrap;">{val}</td>')
            elif c == "Peso (%)":
                w_str = f"{val:.2f}%" if (pd.notna(val) and isinstance(val, (int, float))) else "—"
                td_cells.append(f'<td style="padding:10px 14px; font-size:12px; text-align:{align}; font-family:{MONO}; white-space:nowrap;">{w_str}</td>')
            elif c in ["Prezzo Ingresso", "Prezzo Uscita"]:
                if pd.notna(val) and isinstance(val, (int, float)):
                    if val >= 100:
                        v_str = f"${val:,.2f}"
                    elif val >= 1:
                        v_str = f"${val:,.3f}"
                    else:
                        v_str = f"${val:,.4f}"
                else:
                    v_str = "—"
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
    return f'''<div style="width:100%; max-height:450px; overflow-y:auto; overflow-x:auto; border:1px solid {BORDER}; border-radius:8px; background:rgba(255,247,237,0.02); margin-bottom:18px;"><table style="width:100%; border-collapse:collapse; text-align:left;"><thead><tr>{"".join(th_cells)}</tr></thead><tbody>{"".join(rows_html)}</tbody></table></div>'''


def render_open_trades_html_table(df):
    th_cells = [
        f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:left; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">Titolo</th>',
        f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:center; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">Data Ingresso</th>',
        f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:center; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">Permanenza</th>',
        f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:right; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">Prezzo Ingresso</th>',
        f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:right; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">Prezzo Attuale</th>',
        f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:right; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">Peso (%)</th>',
        f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:right; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">Rendimento %</th>',
        f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; text-align:center; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">Stato</th>',
    ]
    rows_html = []
    for _, r in df.iterrows():
        tkr = r["Titolo"]
        d_in = r["Data Ingresso"]
        giorni = r["Giorni"]
        p_in = f"${r['Prezzo Ingresso']:,.2f}" if pd.notna(r['Prezzo Ingresso']) else "—"
        p_cur = f"${r['Prezzo Attuale']:,.2f}" if pd.notna(r['Prezzo Attuale']) else "—"
        peso = f"{r['Peso (%)']:.2f}%"
        rend = r['Rendimento %']
        color = POS if rend > 0 else NEG if rend < 0 else MUTED
        rend_str = f"{rend:+.2f}%"
        badge_stato = f'<span style="background:rgba(61,220,151,0.12); color:{POS}; border:1px solid rgba(61,220,151,0.25); padding:3px 7px; border-radius:4px; font-size:10.5px; font-weight:700; font-family:{MONO};">IN POSIZIONE</span>'
        tds = [
            f'<td style="padding:10px 14px; font-size:12.5px; text-align:left; font-weight:700; color:{BADGE_TEXT}; white-space:nowrap;">{tkr}</td>',
            f'<td style="padding:10px 14px; font-size:12px; text-align:center; color:{MUTED}; white-space:nowrap;">{d_in}</td>',
            f'<td style="padding:10px 14px; font-size:12px; text-align:center; font-family:{MONO}; white-space:nowrap;">{giorni}</td>',
            f'<td style="padding:10px 14px; font-size:12px; text-align:right; font-family:{MONO}; white-space:nowrap;">{p_in}</td>',
            f'<td style="padding:10px 14px; font-size:12px; text-align:right; font-family:{MONO}; white-space:nowrap;">{p_cur}</td>',
            f'<td style="padding:10px 14px; font-size:12px; text-align:right; font-family:{MONO}; white-space:nowrap;">{peso}</td>',
            f'<td style="padding:10px 14px; font-size:12.5px; text-align:right; font-family:{MONO}; font-weight:700; color:{color}; white-space:nowrap;">{rend_str}</td>',
            f'<td style="padding:10px 14px; text-align:center; white-space:nowrap;">{badge_stato}</td>',
        ]
        rows_html.append(f'<tr style="border-bottom:1px solid {BORDER}; transition:background 0.15s ease;">{"".join(tds)}</tr>')
    return f'''<div style="width:100%; max-height:450px; overflow-y:auto; overflow-x:auto; border:1px solid {BORDER}; border-radius:8px; background:rgba(255,247,237,0.02); margin-bottom:18px;"><table style="width:100%; border-collapse:collapse; text-align:left;"><thead><tr>{"".join(th_cells)}</tr></thead><tbody>{"".join(rows_html)}</tbody></table></div>'''


def monogram(text, size=26):
    return f'''<span style="display:inline-flex; align-items:center; justify-content:center; width:{size}px; height:{size}px; border-radius:6px; border:1px solid {ACCENT}; color:{ACCENT}; font-family:{MONO}; font-weight:700; font-size:10px; letter-spacing:-0.3px; flex-shrink:0;">{text}</span>'''


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

col_title, col_stat = st.columns([3, 2])
with col_title:
    st_html(f"""
    <div style="padding: 2px 0 8px 0;">
        <div style="font-size: 13px; font-weight: 600; color: {MUTED}; text-transform: uppercase; letter-spacing: 0.5px;">
            Apex Engine · <span style="color: {ACCENT}; font-weight: 700;">Tattico</span>
        </div>
    </div>
    """)

with col_stat:
    st_html(f"""
    <div style="text-align: right; padding-top: 2px;">
        <div style="font-size: 11px; color: {MUTED};">
            <span style="width:6px; height:6px; border-radius:50%; background:{engine_status_color}; display:inline-block; margin-right:5px;"></span>{engine_status_text} · Aggiornato {last_update_display}
        </div>
        <div style="font-size: 11px; color: {MUTED_2}; margin-top: 2px;">
            Cadenza: decisione venerdì, esecuzione lunedì
        </div>
    </div>
    """)

# ==========================================================================
# VERSIONE — solo Completa (basket 15 titoli). La variante Semplice (1 ETF,
# USMV) è stata rimossa: su ogni finestra testata risultava peggiore su
# CAGR, Sharpe e MaxDD rispetto alla Completa, senza alcun vantaggio a
# compensare la minore complessità operativa.
# ==========================================================================
m_apex = portfolio_manager.get_apex_metrics()
_m_apex_active = m_apex

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
        elif ticker in ("GLD", "IEF"):
            continue  # GLD (Oro) e IEF (Obbligazioni) gestiti separatamente come classi macro
        else:
            num_eq += 1
            pos_num = num_eq

        row = {
            "Pos": pos_num,
            "Titolo": portfolio_manager.clean_crypto_ticker(ticker) if is_crypto else ticker,
            "Stato": "NUOVO" if is_new_this_week else "",
            "Data Ingresso": entry_formatted,
            "Ingresso ($)": info.get("entry_price", 0.0),
            "Attuale ($)": curr_p,
            "Stop Loss ($)": info.get("stop_loss", float("nan")),
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

    with st.expander("Parametri Capitale Apex", expanded=False):
        c_cap, c_save = st.columns([3, 1])
        with c_cap:
            cap_apex_input = st.number_input(
                "Capitale di Riferimento Apex (€)",
                min_value=1000.0,
                value=float(cfg.get("apex_capital_eur", 100000.0)),
                step=5000.0,
                format="%.0f",
                help="Capitale di riferimento per il calcolo delle quote e dei controvalori operativi di Apex Engine."
            )
        with c_save:
            st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
            if st.button("Salva Capitale", use_container_width=True, key="apex_save_cap"):
                new_cfg = {**cfg, "apex_capital_eur": cap_apex_input,
                           "last_updated": datetime.date.today().strftime("%Y-%m-%d")}
                if portfolio_manager.save_config(new_cfg):
                    st.toast("Capitale Apex salvato per questa sessione.")
                    cfg = new_cfg
                else:
                    st.error("Errore nel salvataggio della configurazione.")

        if _apex_live_eur:
            st.caption(f"Capitale configurabile · default 100.000 € (NAV storico del modello: €{_apex_live_eur:,.0f} / ${_nav_usd:,.0f})")
        else:
            st.caption("Valore standard da config.json")



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

    gold_detail = position_detail("GLD", capitale) if ("GLD" in open_pos_raw or alloc.get('Gold', 0) > 0) else None
    if gold_detail:
        tot_pnl_usd += gold_detail["pnl_usd"]
        tot_invested_usd += gold_detail.get("value_usd", gold_cap)
    elif alloc.get('Gold', 0) > 0:
        tot_invested_usd += gold_cap

    bond_detail = position_detail("IEF", capitale) if ("IEF" in open_pos_raw or alloc.get('Bonds', 0) > 0) else None
    if bond_detail:
        tot_pnl_usd += bond_detail["pnl_usd"]
        tot_invested_usd += bond_detail.get("value_usd", bond_cap)
    elif alloc.get('Bonds', 0) > 0:
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

    PROXIES_DISPLAY = {"GLD": "Oro", "IEF": "Obbligazioni", "BTC": "Cryptovalute", "Cash": "Liquidità"}

    hist_trades = (pf or {}).get("trade_history") or []
    latest_hist_exit_date = ""
    latest_hist_trades = []
    if hist_trades:
        exit_dates = [t.get("exit_date") for t in hist_trades if t.get("exit_date")]
        if exit_dates:
            latest_hist_exit_date = max(exit_dates)
            latest_hist_trades = [t for t in hist_trades if t.get("exit_date") == latest_hist_exit_date]

    # --- 1. Ordini Operativi & Stato Allineamento ---
    st_html(section_title("Ordini Operativi & Stato Allineamento"))
    if pending_orders:
        orders_rows = []
        tot_buy_val = 0.0
        tot_sell_val = 0.0
        num_buys = 0
        num_sells = 0

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

            is_buy_act = o.get("action_type") == "BUY" or "ACQUISTO" in str(act_label).upper() or "APERTURA" in str(act_label).upper() or "INCREMENTO" in str(act_label).upper()
            if is_buy_act:
                tot_buy_val += val_user
                num_buys += 1
            else:
                tot_sell_val += val_user
                num_sells += 1

            orders_rows.append({
                "Operazione": act_label,
                "Strumento": disp_name,
                "Variazione Peso": f"{o.get('delta_w_pct', 0.0):+.2f}%",
                f"Controvalore ({curr_sym})": val_user,
                "Quote": shares_str,
                "Prezzo ($)": px,
                "Dettaglio Operativo": o.get("desc", "").replace("TRIM:", "RIDUZIONE:"),
            })

        fmt_action_date = format_date_italian(last_action_date) if last_action_date else "Lunedì"
        summary_parts = []
        if num_buys > 0:
            summary_parts.append(f"{num_buys} acquisti ({curr_sym}{tot_buy_val:,.0f})")
        if num_sells > 0:
            summary_parts.append(f"{num_sells} vendite/riduzioni ({curr_sym}{tot_sell_val:,.0f})")
        summary_text = " · ".join(summary_parts)

        st_html(f"""
        <div style="background: {ACCENT_SOFT}; border: 1px solid rgba(201,164,76,0.35); border-radius: 8px; padding: 14px 18px; margin: 8px 0 12px;">
            <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px; margin-bottom:6px;">
                <div style="display:flex; align-items:center; gap:8px;">
                    <span style="width:8px; height:8px; border-radius:50%; background:{ACCENT}; display:inline-block; flex-shrink:0;"></span>
                    <strong style="font-size:14px; color:{BADGE_TEXT};">Ordini Operativi per Lunedì ({fmt_action_date})</strong>
                    <span style="background:{BADGE_NEUTRAL_BG}; color:{ACCENT}; font-size:10.5px; font-weight:700; padding:3px 7px; border-radius:4px; font-family:{MONO};">DA ESEGUIRE ORE 15:30 CET</span>
                </div>
                <div style="font-size:11.5px; color:{MUTED};">Capitale operativo: <b style="color:{BADGE_TEXT};">{curr_sym}{capitale * fx_ratio:,.0f}</b></div>
            </div>
            <div style="font-size:12px; color:{BADGE_TEXT};">
                {summary_text} — Esecuzione all'apertura mercati USA a prezzo di mercato o limite sul riferimento.
            </div>
        </div>
        """)
        df_orders = pd.DataFrame(orders_rows)
        st_html(render_orders_html_table(df_orders, curr_sym))
    else:
        st_html(f"""
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 14px 18px; margin: 8px 0 16px;">
            <div style="display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <div style="width: 28px; height: 28px; border-radius: 6px; background: rgba(61,220,151,0.12); border: 1px solid rgba(61,220,151,0.25); display: flex; align-items: center; justify-content: center; flex-shrink: 0;">
                        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="{POS}" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                    </div>
                    <div>
                        <strong style="font-size: 13.5px; color: {BADGE_TEXT};">Portafoglio allineato ai target quantitativi</strong>
                        <div style="color: {MUTED}; font-size: 11.5px; margin-top: 1px;">Nessun ordine operativo da eseguire per lunedì. Tutti gli strumenti attivi rientrano nei pesi ottimali.</div>
                    </div>
                </div>
                <div style="font-size: 11.5px; color: {MUTED}; background: rgba(255,247,237,0.02); border: 1px solid {BORDER_STRONG}; padding: 5px 10px; border-radius: 6px; font-family: {MONO};">
                    Prossima verifica: Venerdì sera alle 22:00 CET
                </div>
            </div>
        </div>
        """)

    # --- 2. Regimi e Segnali Macro ---
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
        signal_item("Cryptovalute", _cr_val, _cr_title),
        signal_item("Oro", _g_val, _g_title),
        signal_item("Obbligazioni", _b_val, _b_title),
        signal_item("Liquidità", f"{alloc.get('Cash', 0):.0f}%"),
    ])
    st_html(f'<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:14px 22px; padding:14px 18px; background:{SURFACE}; border:1px solid {BORDER}; border-radius:10px; margin-bottom:8px;">{signals_html}</div>')
    if not data:
        st.caption("Dati live non raggiungibili in questo momento — mostrati gli ultimi valori disponibili localmente, se presenti.")

    # --- 3. Composizione del Portafoglio ---
    st_html(section_title("Composizione del Portafoglio"))

    alloc_segments = []
    if op_eq:
        alloc_segments.append(("Azioni", sum(r.get("Peso (%)", 0.0) for r in op_eq), CLASS_COLOR_EQ))
    if op_cr:
        alloc_segments.append(("Cryptovalute", sum(r.get("Peso (%)", 0.0) for r in op_cr), CLASS_COLOR_BTC))
    if gold_detail:
        alloc_segments.append(("Oro", gold_detail.get("weight_pct", alloc.get('Gold', 0)), CLASS_COLOR_GOLD))
    elif alloc.get('Gold', 0) > 0:
        alloc_segments.append(("Oro", alloc.get('Gold', 0), CLASS_COLOR_GOLD))
    if bond_detail:
        alloc_segments.append(("Obbligazioni", bond_detail.get("weight_pct", alloc.get('Bonds', 0)), CLASS_COLOR_BOND))
    elif alloc.get('Bonds', 0) > 0:
        alloc_segments.append(("Obbligazioni", alloc.get('Bonds', 0), CLASS_COLOR_BOND))

    tot_invested_pct = sum(pct for _, pct, _ in alloc_segments)
    cash_pct = max(0.0, 100.0 - tot_invested_pct)
    if cash_pct > 0.001:
        alloc_segments.append(("Liquidità", cash_pct, CLASS_COLOR_CASH))

    if alloc_segments:
        bar_segs = "".join(f'<div style="height:100%; width:{pct:.2f}%; background:{color};"></div>' for _, pct, color in alloc_segments)
        legend_items = "".join(
            f'<div style="display:flex; align-items:center; gap:6px;">{get_class_svg(label, size=14, color=color)} <span style="opacity:0.85;">{label}</span> <b style="font-family:{MONO}; font-weight:700;">{pct:.1f}%</b></div>'
            for label, pct, color in alloc_segments
        )

        st_html(f'<div style="display:flex; height:12px; border-radius:6px; overflow:hidden; border:1px solid {BORDER_STRONG}; margin-bottom:12px;">{bar_segs}</div>')
        st_html(f'<div style="display:flex; flex-wrap:wrap; gap:12px 20px; margin-bottom:20px; font-size:11.5px;">{legend_items}</div>')

    # --- 4. Posizioni Attive nel Portafoglio ---
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
            "Stop Loss ($)": r.get("Stop Loss ($)", float("nan")),
            "Peso (%)": r["Peso (%)"], "Rendimento %": r["Rendimento %"],
        })
    for r in sorted(op_cr, key=lambda x: x["Rendimento %"], reverse=True):
        disp_name = portfolio_manager.clean_crypto_ticker(r["Titolo"])
        unified_rows.append({
            "Classe": "Cryptovalute", "Strumento": disp_name,
            "Data Ingresso": r["Data Ingresso"],
            "Ingresso ($)": r["Ingresso ($)"], "Attuale ($)": r["Attuale ($)"],
            "Stop Loss ($)": r.get("Stop Loss ($)", float("nan")),
            "Peso (%)": r["Peso (%)"], "Rendimento %": r["Rendimento %"],
        })

    def _detail_row(classe, disp_name, detail):
        fmt_d = format_date_italian(detail['entry_date']) if detail.get('entry_date') and detail['entry_date'] != "N/A" else "—"
        return {
            "Classe": classe, "Strumento": disp_name,
            "Data Ingresso": f"{fmt_d} ({detail['days']}g)" if fmt_d != "—" else "—",
            "Ingresso ($)": detail["entry_price"], "Attuale ($)": detail["current_price"],
            "Stop Loss ($)": float("nan"),
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
        "Stop Loss ($)": float("nan"),
        "Peso (%)": cash_weight_pct, "Rendimento %": float("nan"),
    })

    if unified_rows:
        show_details = st.toggle("Mostra dettagli esecuzione", value=False, key="pos_details_toggle")
        compact_cols = ["Strumento", "Peso (%)", "Stop Loss ($)", col_val_label, "Rendimento %"]
        full_cols = ["Classe", "Strumento", "Data Ingresso", "Quote", "Ingresso ($)", "Attuale ($)", "Stop Loss ($)", "Peso (%)", col_val_label, "Rendimento %", col_rend_label]
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
            is_crypto_class = row["Classe"] in ["Cryptovalute", "Bitcoin"]
            return f"{q:.6f}" if is_crypto_class and q < 1 else (f"{q:.4f}" if is_crypto_class else f"{int(round(q)):,}")

        df_pos["Quote_raw"] = df_pos.apply(_quote_raw, axis=1)
        df_pos["Quote"] = df_pos.apply(_quote_display, axis=1)
        df_pos[col_val_label] = capitale * (df_pos["Peso (%)"] / 100.0) * fx_ratio
        df_pos[col_rend_label] = (df_pos["Rendimento %"] / 100.0) * df_pos[col_val_label]

        st_html(render_positions_html_table(df_pos, active_cols, curr_sym, col_val_label, col_rend_label))
    else:
        st.caption("Nessuna posizione attiva al momento.")

    # --- 5. Storico Recente Operazioni ---
    st_html(section_title("Storico Recente Operazioni"))

    has_recent_content = False
    if last_actions:
        has_recent_content = True
        fmt_last_date = format_date_italian(last_action_date) if last_action_date else ""
        rebalance_date_label = f" ({fmt_last_date})" if fmt_last_date else ""
        st_html(f"""
        <div style="font-size:12px; font-weight:600; color:{MUTED}; margin:4px 0 8px;">
            Operazioni eseguite nell'ultimo ribilanciamento{rebalance_date_label}:
        </div>
        """)
        st_html(render_action_log_html_table(last_actions))

    if latest_hist_trades or hist_trades:
        has_recent_content = True
        rec_source = latest_hist_trades if latest_hist_trades else hist_trades[-8:]
        rec_exit_date = latest_hist_exit_date or (rec_source[-1].get("exit_date") if rec_source else "")
        fmt_rec_exit = format_date_italian(rec_exit_date) if rec_exit_date else ""
        rec_date_label = f" ({fmt_rec_exit})" if fmt_rec_exit else ""

        c_rec_t, c_rec_tog = st.columns([3, 2])
        with c_rec_t:
            st_html(f"""
            <div style="font-size:12px; font-weight:600; color:{MUTED}; margin:10px 0 6px;">
                Ultime posizioni liquidate o ridotte{rec_date_label}:
            </div>
            """)
        with c_rec_tog:
            st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
            show_rec_details = st.toggle("Mostra dettagli esecuzione", value=False, key="rec_details_toggle")

        recent_rows = []
        for t in rec_source:
            reason = str(t.get("reason", ""))
            op_type = "RIDUZIONE" if "trim" in reason.lower() else "CHIUSURA"
            recent_rows.append({
                "Operazione": op_type,
                "Strumento": portfolio_manager.clean_crypto_ticker(t.get("ticker", "")),
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

    if not has_recent_content:
        st.caption("Nessuna operazione recente registrata.")


# ==============================================================================
# TAB 2: METRICHE (EQUITY CURVE, DRAWDOWN, KPI, STORICO)
# ==============================================================================
with tab_perf:
    # Gerarchia visiva a due livelli: le 3 metriche che rispondono a "quanto ho
    # guadagnato / quanto rischio ho corso" sono grandi e in cima (quelle che
    # contano per chi non è un esperto); le 3 di supporto tecnico (Volatilità,
    # Sortino, Calmar — variazioni/dettagli delle prime) sono più piccole,
    # sotto un separatore. Prima erano 6 numeri tutti uguali, senza gerarchia.
    st_html(f"""
    <div style="display:flex; gap:24px; flex-wrap:wrap; margin-bottom:16px;">
        {sub_hero_metric("Crescita Annua Lorda", f"{_m_apex_active['cagr_gross']*100:+.2f}%", f"Netto stimato: {_m_apex_active['cagr_net']*100:+.2f}% annuo", POS if _m_apex_active['cagr_gross'] >= 0 else NEG, primary=True)}
        {sub_hero_metric("Indice di Sharpe", f"{_m_apex_active['sharpe']:.2f}", "Rendimento rispetto al rischio", POS if _m_apex_active['sharpe'] >= 1.0 else None, primary=True)}
        {sub_hero_metric("Calo Massimo Storico", f"{_m_apex_active.get('max_drawdown_storico', _m_apex_active['max_drawdown'])*100:.2f}%", "Massima discesa temporanea dal 1987", primary=True)}
    </div>
    <div style="display:flex; gap:20px; flex-wrap:wrap; margin-bottom:24px; padding-top:12px; border-top:1px solid {BORDER};">
        {sub_hero_metric("Volatilità Annua", f"{_m_apex_active['volatility']*100:.1f}%", "Oscillazione media annua del capitale")}
        {sub_hero_metric("Indice di Sortino", f"{_m_apex_active['sortino']:.2f}", "Protezione ed efficienza sui soli ribassi")}
        {sub_hero_metric("Rapporto Calmar", f"{_m_apex_active['calmar']:.2f}", "Rapporto tra guadagno annuo e calo massimo")}
    </div>
    """)
    st.caption(
        f"Metriche calcolate al lordo delle imposte · Periodo di verifica recente: {_m_apex_active.get('test_period', '')} · "
        f"Storico completo: {_m_apex_active.get('storico_period', '')}."
    )

    st_html(section_title("Curva Equity vs Benchmark", top="8px", bottom="8px"))

    selected_range = st.segmented_control(
        "Periodo",
        options=["6M", "1A", "3A", "Test (6A)", "Da Inizio"],
        default="Test (6A)",
        label_visibility="collapsed",
        key="chart_range_ctrl"
    ) or "Test (6A)"

    _ap_nav = portfolio_manager.load_apex_contiguous_history()
    if not _ap_nav.empty:
        last_dt = _ap_nav.index[-1]
        if selected_range == "6M":
            start_dt = last_dt - pd.DateOffset(months=6)
        elif selected_range == "1A":
            start_dt = last_dt - pd.DateOffset(years=1)
        elif selected_range == "3A":
            start_dt = last_dt - pd.DateOffset(years=3)
        elif selected_range in ("5A", "6A", "Test (6A)"):
            start_dt = pd.Timestamp("2020-09-30")
        else:
            start_dt = _ap_nav.index[0]

        _plot_df = _ap_nav[_ap_nav.index >= start_dt].copy()
        _plot_df["norm"] = (_plot_df["value"] / _plot_df["value"].iloc[0]) * 100.0

        s_spy_full = portfolio_manager.load_monthly_benchmark_spy(start_date=_plot_df.index[0])
        common_dt = _plot_df.index.intersection(s_spy_full.index)

        _use_log = False
        if selected_range in ("3A", "5A", "Test (6A)", "Da Inizio"):
            _use_log = st.toggle("Scala logaritmica", value=False, key="apex_hist_log_scale")

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=_plot_df.index, y=_plot_df["norm"], mode="lines", name="Apex Engine",
            line=dict(color=ACCENT, width=2),
            fill=None if _use_log else "tozeroy", fillcolor="rgba(201, 164, 76, 0.10)",
            hovertemplate="Base 100: %{y:.2f}<extra></extra>"
        ))
        if len(common_dt) > 0:
            _spy_aligned = s_spy_full.loc[common_dt]
            _spy_norm = (_spy_aligned / _spy_aligned.iloc[0]) * 100.0
            fig.add_trace(go.Scatter(
                x=_spy_norm.index, y=_spy_norm, mode="lines", name="S&P 500 Benchmark",
                line=dict(color='#7A7266', width=1.5, dash='dot'),
                hovertemplate="S&P 500: %{y:.2f}<extra></extra>"
            ))

        # Linea verticale demarcazione Test Recente a Settembre 2020
        _oos_start = pd.Timestamp("2020-09-30")
        if _plot_df.index[0] <= _oos_start <= _plot_df.index[-1]:
            fig.add_vline(x=_oos_start, line=dict(color=MUTED, width=1, dash="dash"))
            fig.add_annotation(x=_oos_start, y=1.0, yref="paper", yanchor="bottom",
                                xanchor="left",
                                text="Fase di test recente (2020) →", showarrow=False,
                                font=dict(size=10, color=ACCENT))

        # Linea verticale inizio Operatività Reale a Settembre 2026
        _live_start = pd.Timestamp("2026-09-14")
        if _plot_df.index[0] < _live_start <= _plot_df.index[-1]:
            fig.add_vline(x=_live_start, line=dict(color="#3DDC97", width=1, dash="dash"))
            fig.add_annotation(x=_live_start, y=0.88, yref="paper", yanchor="bottom",
                                xanchor="right",
                                text="← Inizio operatività reale (Settembre 2026)", showarrow=False,
                                font=dict(size=10, color="#3DDC97"))

        fig.update_layout(
            template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(family="Inter, sans-serif"),
            xaxis=dict(range=[_plot_df.index[0], _plot_df.index[-1]], showgrid=False, tickfont=dict(size=11)),
            yaxis=dict(type="log", showgrid=True, gridcolor='rgba(255,247,237,0.07)', tickfont=dict(size=11)) if _use_log else dict(showgrid=True, gridcolor='rgba(255,247,237,0.07)', tickfont=dict(size=11)),
            margin=dict(l=0, r=0, t=10, b=0), height=380,
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor='rgba(0,0,0,0)')
        )
        st.plotly_chart(fig, use_container_width=True)

        st_html(section_title("Perdite Temporanee dal Massimo (Calo dal Picco)", top="14px", bottom="6px"))
        fig_dd = go.Figure()
        fig_dd.add_trace(go.Scatter(
            x=_plot_df.index, y=_plot_df['drawdown'], fill='tozeroy', mode='lines',
            line=dict(color=NEG, width=1.2), fillcolor='rgba(236, 101, 123, 0.15)',
            hovertemplate="Calo: %{y:.2f}%<extra></extra>", name="Calo"
        ))
        if _plot_df.index[0] <= _oos_start <= _plot_df.index[-1]:
            fig_dd.add_vline(x=_oos_start, line=dict(color=MUTED, width=1, dash="dash"))
        if _plot_df.index[0] < _live_start <= _plot_df.index[-1]:
            fig_dd.add_vline(x=_live_start, line=dict(color="#3DDC97", width=1, dash="dash"))

        fig_dd.update_layout(
            template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(family="Inter, sans-serif"),
            xaxis=dict(range=[_plot_df.index[0], _plot_df.index[-1]], showgrid=False, tickfont=dict(size=10)),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,247,237,0.05)', tickfont=dict(size=10), ticksuffix="%"),
            margin=dict(l=0, r=0, t=4, b=0), height=110, showlegend=False
        )
        st.plotly_chart(fig_dd, use_container_width=True)

        st.caption(
            f"Crescita di 100 € investiti nella strategia Apex a confronto con l'indice S&P 500 ({_ap_nav.index[0].year}–{_ap_nav.index[-1].year})."
        )

        st_html(section_title("Tabella dei Rendimenti Mese per Mese"))
        st_html(render_monthly_returns_html_table(_ap_nav))
    else:
        st.info("File storico di Apex non trovato.")


    # --- Statistiche Operative (storico delle operazioni chiuse) ---
    hist_master = fetch_json_local_or_github("apex_full_historical_trades.json") or []
    if not hist_master and pf:
        hist_master = pf.get("trade_history", [])

    num_open = len(pf.get("open_positions", {})) if pf else 0

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

    if hist_master:
        st_html(section_title("Registro Operazioni e Statistiche di Esecuzione"))

        st_html(f"""
        <div style="background: rgba(255,247,237,0.03); border: 1px solid {BORDER}; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; font-size: 12px; color: {MUTED}; line-height: 1.5;">
            <div style="display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:8px; margin-bottom:4px;">
                <strong style="color: {BADGE_TEXT}; font-size: 13px;">Registro Operativo Completo (1987 – Oggi)</strong>
                <span style="background: {BADGE_NEUTRAL_BG}; color: {ACCENT}; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 4px; font-family: {MONO};">{len(hist_master):,} OPERAZIONI REGISTRATE · {num_open} APERTE</span>
            </div>
            Questo registro include la totalità delle operazioni storiche e recenti generate dalla strategia Apex:<br/>
            dall'<strong>Allocazione Macro Sistematica (1987–2011)</strong>, alla selezione point-in-time del <strong>Paniere Low-Beta 15 Titoli e Macro (2012–2024)</strong>, alle operazioni del modulo <strong>Crypto Frontier Venture (2018–2024)</strong>, fino al <strong>Portafoglio Tracciato Live (marzo 2024–oggi)</strong>.<br/>
            Le <strong>{num_open} posizioni aperte</strong> attualmente in essere sono consultabili sia selezionando la vista sottostante sia nel Tab <em>Portafoglio Attuale</em>.
        </div>
        """)

        tab_sel = st.radio(
            "Visualizzazione Registro",
            [f"Operazioni Chiuse ({len(hist_master):,})", f"Posizioni Attualmente Aperte ({num_open})"],
            horizontal=True,
            label_visibility="collapsed",
            key="apex_register_view_mode"
        )

        if tab_sel.startswith("Operazioni Chiuse"):
            df_master = pd.DataFrame(hist_master)
            if "exit_date" in df_master.columns:
                df_master["exit_date_raw"] = df_master["exit_date"].astype(str)
            else:
                df_master["exit_date_raw"] = ""

            c_scp, c_cls, c_yr, c_srch = st.columns([1.6, 1.3, 1.1, 1.4])
            with c_scp:
                n_tot = len(df_master)
                n_pit = len(df_master[df_master["era"] != "1987-2011 (Macro Allocazione)"]) if "era" in df_master.columns else n_tot
                n_cry = len(df_master[df_master["era"] == "2018-2024 (Crypto Frontier Venture)"]) if "era" in df_master.columns else 0
                n_live = len(df_master[df_master["era"] == "2024-Oggi (Tracking Live)"]) if "era" in df_master.columns else 0
                scope_opts = [
                    f"Tutto lo Storico ({n_tot})",
                    f"Titoli & Macro PIT ({n_pit})",
                    f"Crypto Frontier Venture ({n_cry})",
                    f"Tracking Live 2024-Oggi ({n_live})",
                ]
                flt_scope = st.selectbox("Ambito Storico", scope_opts, label_visibility="collapsed")

            with c_cls:
                classes = sorted([str(c) for c in df_master["asset_class"].dropna().unique()]) if "asset_class" in df_master.columns else []
                cls_opts = ["Tutte le Classi"] + classes
                flt_cls = st.selectbox("Classe di Attivo", cls_opts, label_visibility="collapsed")

            with c_yr:
                y_counts = {}
                for t in hist_master:
                    y = str(t.get("exit_date", ""))[:4]
                    if y and len(y) == 4 and y.isdigit():
                        y_counts[y] = y_counts.get(y, 0) + 1
                y_opts = ["Tutti gli Anni"] + [f"{y} ({y_counts[y]})" for y in sorted(y_counts.keys(), reverse=True)]
                flt_yr = st.selectbox("Filtro Anno", y_opts, label_visibility="collapsed")

            with c_srch:
                search_t = st.text_input("Cerca Ticker", placeholder="Cerca ticker (es. BTC, AAPL, IEF...)", label_visibility="collapsed")

            df_display = df_master.copy()
            if "ticker" in df_display.columns:
                df_display["ticker"] = df_display["ticker"].apply(portfolio_manager.clean_crypto_ticker)
            if "Titoli & Macro PIT" in flt_scope and "era" in df_display.columns:
                df_display = df_display[df_display["era"] != "1987-2011 (Macro Allocazione)"]
            elif "Crypto Frontier Venture" in flt_scope and "era" in df_display.columns:
                df_display = df_display[df_display["era"] == "2018-2024 (Crypto Frontier Venture)"]
            elif "Tracking Live" in flt_scope and "era" in df_display.columns:
                df_display = df_display[df_display["era"] == "2024-Oggi (Tracking Live)"]

            if flt_cls != "Tutte le Classi" and "asset_class" in df_display.columns:
                df_display = df_display[df_display["asset_class"] == flt_cls]

            if flt_yr != "Tutti gli Anni":
                chosen_year = flt_yr.split()[0]
                df_display = df_display[df_display["exit_date_raw"].str.startswith(chosen_year)]

            if search_t and "ticker" in df_display.columns:
                df_display = df_display[df_display["ticker"].astype(str).str.contains(search_t.strip().upper(), na=False)]

            disp_trades = df_display.to_dict("records")
            wins = [t for t in disp_trades if t.get("profit_pct", 0) > 0]
            losses = [t for t in disp_trades if t.get("profit_pct", 0) <= 0]
            win_rate = (len(wins) / len(disp_trades) * 100) if disp_trades else 0.0
            gross_profit = sum(t.get("profit_pct", 0.0) for t in wins)
            gross_loss = abs(sum(t.get("profit_pct", 0.0) for t in losses))
            profit_factor = gross_profit / gross_loss if gross_loss != 0 else (999.0 if gross_profit > 0 else 0.0)
            expectancy_pct = sum(t.get("profit_pct", 0.0) for t in disp_trades) / len(disp_trades) if disp_trades else 0.0

            durations = []
            for t in disp_trades:
                try:
                    d_in = datetime.datetime.strptime(str(t.get("entry_date", "")), "%Y-%m-%d")
                    d_out = datetime.datetime.strptime(str(t.get("exit_date", "")), "%Y-%m-%d")
                    durations.append(max(1, (d_out - d_in).days))
                except Exception:
                    pass
            avg_days_val = int(round(sum(durations) / len(durations))) if durations else 0

            p_list = [t.get("profit_pct", 0.0) for t in disp_trades]
            best_trade_val, worst_trade_val = "—", "—"
            if p_list:
                max_idx, min_idx = p_list.index(max(p_list)), p_list.index(min(p_list))
                best_t = disp_trades[max_idx]
                worst_t = disp_trades[min_idx]
                best_trade_val = f"{best_t.get('ticker', '-')}: {best_t.get('profit_pct', 0.0):+.2f}%"
                worst_trade_val = f"{worst_t.get('ticker', '-')}: {worst_t.get('profit_pct', 0.0):+.2f}%"

            st_html(section_title(f"Statistiche Operative ({len(disp_trades):,} Operazioni)"))
            strip_items = [
                kpi_item("Tasso di Successo", f"{win_rate:.1f}%", f"{len(wins)} vincenti su {len(disp_trades)}", badge_text=f"{len(wins)}/{len(disp_trades)}"),
                kpi_item("Aspettativa per Trade", f"{expectancy_pct:+.2f}%", "Rendimento medio per operazione",
                         badge_text="EDGE STATISTICO", badge_color=BADGE_POS_BG, val_color=POS if expectancy_pct > 0 else NEG),
                kpi_item("Fattore di Profitto", f"{profit_factor:.2f}", "Profitti lordi / perdite",
                         badge_text=("ECCELLENTE" if profit_factor >= 1.5 else "STABILE"),
                         badge_color=(BADGE_POS_BG if profit_factor >= 1.5 else BADGE_NEUTRAL_BG)),
                kpi_item("Miglior Operazione", best_trade_val, "Massimo profitto registrato", val_color=POS),
                kpi_item("Peggior Operazione", worst_trade_val, "Massima perdita registrata", val_color=NEG),
                kpi_item("Durata Media", f"{avg_days_val}g", "giorni medi in posizione"),
            ]
            st_html(f'<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 4px 8px; background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 14px; margin-bottom: 20px;">{"".join(strip_items)}</div>')

            def calc_duration(r):
                try:
                    d_in = datetime.datetime.strptime(str(r.get("entry_date", "")), "%Y-%m-%d")
                    d_out = datetime.datetime.strptime(str(r.get("exit_date", "")), "%Y-%m-%d")
                    return f"{max(1, (d_out - d_in).days)}g"
                except Exception:
                    return "-"

            df_display["Durata"] = df_display.apply(calc_duration, axis=1)
            df_display["Peso (%)"] = df_display["weight"].apply(lambda w: round(w * 100, 2) if pd.notna(w) else 0.0)
            df_display = df_display.rename(columns={
                "ticker": "Titolo", "entry_date": "Data Ingresso", "exit_date": "Data Uscita",
                "entry_price": "Prezzo Ingresso", "exit_price": "Prezzo Uscita",
                "profit_pct": "Rendimento %", "reason": "Motivazione",
                "asset_class": "Classe", "era": "Era"
            })

            cols_hist = ["Titolo", "Classe", "Era", "Data Ingresso", "Data Uscita", "Durata", "Prezzo Ingresso", "Prezzo Uscita", "Peso (%)", "Rendimento %", "Motivazione"]

            df_table = df_display.copy()
            df_table["Data Uscita"] = df_table["Data Uscita"].apply(lambda d: format_date_italian(d) if d else "—")
            if "Data Ingresso" in df_table.columns:
                df_table["Data Ingresso"] = df_table["Data Ingresso"].apply(lambda d: format_date_italian(d) if d else "—")

            st_html(render_hist_trades_html_table(df_table, cols_hist))

            c_csv1, c_csv2 = st.columns([1, 1])
            with c_csv1:
                csv_filt_df = df_display[["Titolo", "Classe", "Era", "Data Ingresso", "Data Uscita", "Durata", "Prezzo Ingresso", "Prezzo Uscita", "Peso (%)", "Rendimento %", "Motivazione"]].copy()
                csv_filtered = csv_filt_df.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"Esporta Selezione ({len(df_display)} trade) in CSV",
                    data=csv_filtered,
                    file_name="apex_operazioni_selezionate.csv",
                    mime="text/csv",
                    key="dl_trades_filtered_csv"
                )
            with c_csv2:
                csv_master_path = os.path.join(os.path.dirname(__file__), "apex_full_historical_trades.csv")
                if os.path.exists(csv_master_path):
                    with open(csv_master_path, "rb") as f_csv:
                        csv_all = f_csv.read()
                    st.download_button(
                        label=f"Esporta Registro Completo 1987–Oggi ({len(hist_master)} trade)",
                        data=csv_all,
                        file_name="apex_full_historical_trades_1987_2026.csv",
                        mime="text/csv",
                        key="dl_trades_master_csv"
                    )
            st.caption(f"Visualizzate {len(df_display):,} su {len(hist_master):,} operazioni totali registrate · Nessuna discrepanza temporale.")
        else:
            # Posizioni Attualmente Aperte
            open_pos = pf.get("open_positions", {})
            today = datetime.date.today()
            open_rows = []
            for tkr, pos in open_pos.items():
                entry_d_str = pos.get("entry_date", "")
                try:
                    entry_d = datetime.datetime.strptime(entry_d_str, "%Y-%m-%d").date()
                    days = max(0, (today - entry_d).days)
                except Exception:
                    days = 0
                entry_p = pos.get("entry_price", 0.0)
                curr_p = pos.get("current_price", entry_p)
                rend = ((curr_p / entry_p) - 1.0) * 100 if entry_p > 0 else 0.0
                w = pos.get("weight", 0.0) * 100
                open_rows.append({
                    "Titolo": portfolio_manager.clean_crypto_ticker(tkr) if pos.get("is_crypto") else tkr,
                    "Data Ingresso": format_date_italian(entry_d_str) if entry_d_str else "—",
                    "Giorni": f"{days}g",
                    "Prezzo Ingresso": entry_p,
                    "Prezzo Attuale": curr_p,
                    "Peso (%)": round(w, 2),
                    "Rendimento %": round(rend, 2),
                    "Stato": "In Posizione",
                })
            df_open = pd.DataFrame(open_rows).sort_values("Peso (%)", ascending=False)
            st_html(render_open_trades_html_table(df_open))
            st.caption(f"{len(df_open)} posizioni aperte attive nel portafoglio. Verranno archiviate nel registro operazioni chiuse alla loro liquidazione o rotazione.")
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
            <div style="font-size: 12.5px; opacity: 0.85; line-height: 1.5;">Il motore analizza le chiusure settimanali. In caso di ribilanciamento, genera gli ordini operativi (vendite e acquisti) con quote dimensionate al capitale.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px 16px;">
            <div style="font-family: {FRAUNCES}; font-weight: 600; font-size: 14px; margin-bottom: 6px;">2. Lunedì Pomeriggio</div>
            <div style="font-size: 12.5px; opacity: 0.85; line-height: 1.5;">All'apertura dei mercati USA, esecuzione degli ordini a mercato o limite. Se non vi sono ordini generati, il portafoglio resta invariato.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px 16px;">
            <div style="font-family: {FRAUNCES}; font-weight: 600; font-size: 14px; margin-bottom: 6px;">3. Infrasettimanale</div>
            <div style="font-size: 12.5px; opacity: 0.85; line-height: 1.5;">Nessun intervento richiesto. Il modello opera su chiusure settimanali (weekly close), neutralizzando il rumore intraday ed eliminando l'over-trading.</div>
        </div>
    </div>
    """)

    st.divider()

    st_html(section_title("Allocazione Dinamica del Portafoglio", top="0"))
    st_html(f'''
    <div style="font-size: 12.5px; opacity: 0.85; line-height: 1.5; margin-bottom: 14px;">
        Ciascun mercato viene attivato solo quando la tendenza di fondo è chiaramente positiva, proteggendo il capitale nelle fasi di ribasso e partecipando alla crescita nelle fasi favorevoli:
    </div>

    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; margin-bottom: 24px;">
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 12px 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="font-weight: 700; font-size: 13.5px; display: inline-flex; align-items: center; gap: 7px;">{get_class_svg("Azioni", 16)} Azioni</span>
                <span style="background: {BADGE_NEUTRAL_BG}; color: {POS}; font-size: 9.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: {MONO};">15 AZIONI PIÙ STABILI</span>
            </div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.45;">Selezione trimestrale delle 15 aziende dell'S&P 500 meno sensibili alle oscillazioni di mercato (massimo 2 per settore). In caso di perdite, permette di recuperare le imposte future.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 12px 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="font-weight: 700; font-size: 13.5px; display: inline-flex; align-items: center; gap: 7px;">{get_class_svg("Cryptovalute", 16)} Cryptovalute</span>
                <span style="background: {BADGE_NEUTRAL_BG}; color: #2E9E70; font-size: 9.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: {MONO};">RISERVA DIGITALE & VENTURE</span>
            </div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.45;">Partecipa alla crescita del mondo crypto puntando su Bitcoin e su una selezione di monete emergenti, con protezioni automatiche per limitare le perdite e incassare i profitti. Disattivato durante le crisi prolungate.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 12px 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="font-weight: 700; font-size: 13.5px; display: inline-flex; align-items: center; gap: 7px;">{get_class_svg("Oro", 16)} Oro</span>
                <span style="background: {BADGE_NEUTRAL_BG}; color: {ACCENT}; font-size: 9.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: {MONO};">BENE RIFUGIO</span>
            </div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.45;">Protezione del potere d'acquisto contro inflazione, svalutazione monetaria e tensioni internazionali. Attivo durante le fasi di crescita dei metalli preziosi.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 12px 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="font-weight: 700; font-size: 13.5px; display: inline-flex; align-items: center; gap: 7px;">{get_class_svg("Obbligazioni", 16)} Obbligazioni</span>
                <span style="background: {BADGE_NEUTRAL_BG}; color: #8B7FC7; font-size: 9.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: {MONO};">TITOLI DI STATO USA</span>
            </div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.45;">Obbligazioni governative americane a 7-10 anni, allocate quando i tassi di interesse e l'andamento del credito offrono rendimenti sicuri.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 12px 14px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                <span style="font-weight: 700; font-size: 13.5px; display: inline-flex; align-items: center; gap: 7px;">{get_class_svg("Liquidità", 16)} Liquidità</span>
                <span style="background: {BADGE_NEUTRAL_BG}; color: {MUTED}; font-size: 9.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: {MONO};">RISERVA PROTETTA</span>
            </div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.45;">Rifugio sicuro per il capitale nei momenti in cui i mercati scendono. Genera rendimenti di mercato a zero rischio di perdita.</div>
        </div>
    </div>
    ''')

    st.divider()

    st_html(section_title("I 3 Livelli di Protezione del Capitale", top="0"))
    st_html(f"""
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 24px;">
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px 16px;">
            <div style="font-family: {FRAUNCES}; font-weight: 600; font-size: 14px; margin-bottom: 4px;">1. Riduzione Automatica nei Momenti Difficili</div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.5;">Quando i mercati diventano troppo agitati e imprevedibili, la strategia riduce in automatico l'esposizione al rischio, salvaguardando il capitale e comprimendo le perdite.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px 16px;">
            <div style="font-family: {FRAUNCES}; font-weight: 600; font-size: 14px; margin-bottom: 4px;">2. Zero Debiti e Zero Rischio Margin Call</div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.5;">Il portafoglio non prende mai denaro a prestito e investe solo il capitale disponibile. Non esiste alcun rischio di richieste di liquidità forzata da parte del broker.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px 16px;">
            <div style="font-family: {FRAUNCES}; font-weight: 600; font-size: 14px; margin-bottom: 4px;">3. Filtro Anti-Falsi Segnali</div>
            <div style="font-family: Inter, sans-serif; font-size: 12px; opacity: 0.85; line-height: 1.5;">Per entrare o uscire da una classe di attivo, la strategia richiede che la tendenza a medio termine (5 mesi) e quella a lungo termine (10 mesi) siano concordi, evitando mosse affrettate sui rimbalzi temporanei.</div>
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
