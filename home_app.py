"""
home_app.py — Vista d'Insieme APEX CONVEX
==================================================================================
Pagina iniziale della dashboard unificata (navigazione multipagina, vedi main.py).
Principi guida: lean, senza attrito, robusto, semplice da mantenere.
Impianto grafico e visivo al 100% coerente con il canone Apex Engine:
stessi font (Fraunces, Inter, JetBrains Mono), palette dark glassmorphism calda,
stessa struttura a 3 schede (Portafoglio, Metriche, Guida), barra di allocazione
segmentata con icone SVG, scorecard metriche a due livelli e tabelle HTML custom.
==================================================================================
"""

import datetime
import json
import os
import urllib.request

import importlib
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import convex_engine
import portfolio_manager

try:
    importlib.reload(portfolio_manager)
    importlib.reload(convex_engine)
except Exception as _reload_err:
    print(f"[WARN] importlib.reload fallito: {_reload_err}")

# st.set_page_config() rimosso: la pagina gira dentro main.py (st.navigation), che lo imposta una sola volta.

# ==============================================================================
# HTML RENDERING HELPERS & STYLING (DARK GLASSMORPHISM — identici ad Apex Engine)
# ==============================================================================
def st_html(html_str):
    cleaned = "\n".join(line.strip() for line in html_str.strip().splitlines())
    st.markdown(cleaned, unsafe_allow_html=True)


def fill_slot(slot, html_str):
    cleaned = "\n".join(line.strip() for line in html_str.strip().splitlines())
    slot.markdown(cleaned, unsafe_allow_html=True)


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

    /* Rimuove completamente la sidebar e i relativi controlli */
    [data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"],
    section[data-testid="stSidebar"] {
        display: none !important;
    }
</style>
""")

# Design Tokens (identici ad Apex Engine)
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

FRAUNCES = "'Fraunces', Georgia, serif"
MONO = "'JetBrains Mono', monospace"
MESI_IT = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]


def section_title(text, top="26px", bottom="10px"):
    return f'<div style="font-family:{FRAUNCES}; font-size:16px; font-weight:600; letter-spacing:-0.1px; margin:{top} 0 {bottom};">{text}</div>'


def sub_hero_metric(label, value, subtext="", val_color=None, primary=False):
    val_size = "32px" if primary else "20px"
    return f"""
    <div style="flex: 1 1 {'160px' if primary else '130px'};">
        <div style="font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.6px; color: {MUTED}; margin-bottom: 5px;">{label}</div>
        <div style="font-family: {MONO}; font-size: {val_size}; font-weight: 800; color: {val_color or 'inherit'};">{value}</div>
        <div style="font-size: 11px; color: {MUTED}; margin-top: 2px;">{subtext}</div>
    </div>
    """


def get_logo_b64():
    import base64
    for p in ["logo_icon.png", "logo.png"]:
        if os.path.exists(p):
            try:
                with open(p, "rb") as f:
                    return base64.b64encode(f.read()).decode()
            except Exception:
                pass
    return ""


def get_macro_class_svg(classe, size=15, color="currentColor"):
    inline_style = f"display:inline-block; vertical-align:middle; flex-shrink:0;"
    c = str(classe).lower()
    if "azionar" in c or "azioni" in c:
        return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{inline_style}"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"></polyline><polyline points="16 7 22 7 22 13"></polyline></svg>'
    if "obbligazion" in c:
        return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{inline_style}"><line x1="3" y1="21" x2="21" y2="21"></line><line x1="3" y1="10" x2="21" y2="10"></line><polyline points="5 6 12 3 19 6"></polyline><line x1="6" y1="10" x2="6" y2="21"></line><line x1="10" y1="10" x2="10" y2="21"></line><line x1="14" y1="10" x2="14" y2="21"></line><line x1="18" y1="10" x2="18" y2="21"></line></svg>'
    if "managed" in c or "cta" in c:
        return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{inline_style}"><circle cx="12" cy="12" r="10"></circle><polygon points="16.24 7.76 14.12 14.12 7.76 16.24 9.88 9.88 16.24 7.76"></polygon></svg>'

    if "oro" in c:
        return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" style="{inline_style}"><polygon points="8.5 6 15.5 6 17 12 7 12" /><polygon points="2.5 13 9.5 13 11 19 1 19" /><polygon points="14.5 13 21.5 13 23 19 13 19" /></svg>'
    if "bitcoin" in c or "crypto" in c:
        return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{inline_style}"><path d="M7 6h6a3 3 0 0 1 0 6H7zm0 6h7a3 3 0 0 1 0 6H7z"></path><line x1="10" y1="3" x2="10" y2="6"></line><line x1="14" y1="3" x2="14" y2="6"></line><line x1="10" y1="18" x2="10" y2="21"></line><line x1="14" y1="18" x2="14" y2="21"></line><line x1="7" y1="6" x2="7" y2="18"></line></svg>'
    return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="{inline_style}"><rect x="2" y="6" width="20" height="12" rx="2"></rect><circle cx="12" cy="12" r="2.5"></circle><line x1="6" y1="12" x2="6.01" y2="12"></line><line x1="18" y1="12" x2="18.01" y2="12"></line></svg>'


def render_monthly_returns_html_table(df_eq):
    if df_eq is None or df_eq.empty:
        return ''
    df = df_eq.copy()
    years = sorted(df.index.year.unique(), reverse=True)
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
        for m in range(1, 13):
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
        rows_html.append(f'<tr style="border-bottom:1px solid {BORDER};">{"".join(td_cells)}</tr>')

    return f'<div style="width:100%; overflow-x:auto; border:1px solid {BORDER}; border-radius:8px; background:rgba(255,247,237,0.02); margin-bottom:22px;"><table style="width:100%; border-collapse:collapse; text-align:left;"><thead><tr>{"".join(th_cells)}</tr></thead><tbody>{"".join(rows_html)}</tbody></table></div>'


# ==============================================================================
# BENCHMARK SPY CACHED
# ==============================================================================
_PRICE_CACHE_PATH = os.path.join(os.path.dirname(__file__), "live_prices_cache.json")

@st.cache_data(ttl=3600)
def load_benchmark_spy():
    if os.path.exists(_PRICE_CACHE_PATH):
        try:
            with open(_PRICE_CACHE_PATH, "r") as f:
                cache = json.load(f)
            if cache.get("spy_history"):
                hist = cache["spy_history"]
                idx = pd.to_datetime([h["date"] for h in hist])
                close = [h["close"] for h in hist]
                return pd.Series(close, index=idx).ffill().dropna()
        except Exception:
            pass
    try:
        url = "https://query2.finance.yahoo.com/v8/finance/chart/SPY?range=10y&interval=1d"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        res = json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
        data_spy = res['chart']['result'][0]
        timestamps = pd.to_datetime(data_spy['timestamp'], unit='s')
        close = data_spy['indicators']['quote'][0]['close']
        return pd.Series(close, index=timestamps).ffill().dropna()
    except Exception:
        return pd.Series(dtype=float)


# ==============================================================================
# CARICAMENTO DATI REALI
# ==============================================================================
_BASE_DIR = os.path.dirname(__file__)

def _load_json(filename):
    p = os.path.join(_BASE_DIR, filename)
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

apex_portfolio = _load_json("portfolio.json")
apex_data = _load_json("apex_data.json")
convex_portfolio = _load_json("convex_portfolio.json")
cfg = portfolio_manager.load_config()

# Dati di tracking del modello
_nav_usd = float(apex_portfolio.get("nav_usd", 0.0))
_eur_usd_rate = float(apex_data.get("eur_usd", 0.0))
# Capitale di riferimento Apex: valore standard configurabile (default 100.000 €)
apex_val_eur = float(cfg.get("apex_capital_eur", 100000.0))



# Prezzi e strumenti Convex
_active_instruments = convex_engine.CONVEX_INSTRUMENTS
_base_prices = {"NTSG": 28.69, "AVWS": 25.64, "DBMFE": 123.50, "PPFB": 75.15, "WBTC": 16.60}
if os.path.exists(_PRICE_CACHE_PATH):
    try:
        with open(_PRICE_CACHE_PATH, "r") as f:
            _cache_pr = json.load(f).get("convex_prices", {})
            for k in _base_prices:
                if k in _cache_pr:
                    _base_prices[k] = float(_cache_pr[k])
    except Exception:
        pass

convex_holdings_saved = convex_portfolio.get("holdings", {})
convex_has_real_data = bool(convex_holdings_saved) and any(v.get("shares", 0) > 0 for v in convex_holdings_saved.values())
if convex_has_real_data:
    convex_val_eur = sum(v.get("shares", 0.0) * (v.get("last_price") or _base_prices.get(k, 0.0)) for k, v in convex_holdings_saved.items()) \
        + float(convex_portfolio.get("cash_eur", 0.0))
else:
    convex_val_eur = float(cfg.get("convex_capital_eur", 100000.0))

_tot = apex_val_eur + convex_val_eur
_real_apex_ratio = (apex_val_eur / _tot) if _tot > 0 else 0.50
_real_convex_ratio = (convex_val_eur / _tot) if _tot > 0 else 0.50
_target_apex = float(cfg.get("target_apex_ratio", 0.50))

cx_holdings_dict = {k: v.get("shares", 0.0) for k, v in convex_holdings_saved.items()} if convex_has_real_data else \
    {k: (_target_apex * _tot * info["target_weight"] / _base_prices[k]) for k, info in _active_instruments.items()}

_cx_rep = convex_engine.evaluate_convex_stack(
    current_holdings=cx_holdings_dict,
    market_prices=_base_prices,
    monthly_pac_eur=float(cfg.get("monthly_pac_eur", 600.0)),
    cash_balance=float(convex_portfolio.get("cash_eur", 0.0)) if convex_has_real_data else 0.0,
    instruments=_active_instruments
)

_apex_allocs = apex_data.get("allocations")
unified_data = portfolio_manager.compute_unified_portfolio(
    apex_val=apex_val_eur,
    convex_report=_cx_rep,
    monthly_pac=float(cfg.get("monthly_pac_eur", 600.0)),
    target_apex_ratio=_target_apex,
    apex_allocations=_apex_allocs
)

# ==============================================================================
# INTESTAZIONE BRANDING (Identica ad Apex Engine)
# ==============================================================================
_logo_b64 = get_logo_b64()
_logo_tag = (f'<img src="data:image/png;base64,{_logo_b64}" style="height: 48px; width: auto; object-fit: contain;" />'
             if _logo_b64 else '')

_last_sync_str = apex_data.get("timestamp", datetime.date.today().strftime("%Y-%m-%d"))
_both_ok = not (apex_portfolio.get("pending_orders")) and not (_cx_rep.trim_alerts)
_status_dot_color = POS if _both_ok else ACCENT
_status_label_text = "Tutti i sistemi allineati" if _both_ok else "Intervento suggerito"

col_logo, col_stat = st.columns([3, 2])
with col_logo:
    st_html(f"""
    <div style="display: flex; align-items: center; gap: 14px; padding: 6px 0;">
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; padding: 5px 9px; border-radius: 10px; display: flex; align-items: center; justify-content: center;">
            {_logo_tag}
        </div>
        <div>
            <div style="font-family: {FRAUNCES}; font-size: 22px; font-weight: 600; letter-spacing: -0.4px; line-height: 1.2; color: {BADGE_TEXT};">Apex Convex</div>
            <div style="font-size: 11px; font-weight: 600; opacity: 0.65; letter-spacing: 0.4px; text-transform: uppercase; margin-top: 1px;">
                Vista d'Insieme delle Due Strategie
            </div>
        </div>
    </div>
    """)
with col_stat:
    st_html(f"""
    <div style="text-align: right; padding-top: 10px;">
        <div style="font-size: 11px; color: {MUTED};">
            <span style="width:6px; height:6px; border-radius:50%; background:{_status_dot_color}; display:inline-block; margin-right:5px;"></span>{_status_label_text}
        </div>
        <div style="font-size: 11px; color: {MUTED_2}; margin-top: 2px;">
            Sincronizzazione: {_last_sync_str}
        </div>
    </div>
    """)

# ==============================================================================
# SCHEDE PRINCIPALI: PORTAFOGLIO, METRICHE, GUIDA (CANONICO APEX ENGINE)
# ==============================================================================
tab_pf, tab_perf, tab_guide = st.tabs([
    "Portafoglio",
    "Metriche",
    "Guida"
])

# ==============================================================================
# TAB 1: PORTAFOGLIO COMBINATO
# ==============================================================================
with tab_pf:
    # 1. Hero Value Banner
    _in_range = 0.30 <= _real_apex_ratio <= 0.55
    _ratio_badge_col = POS if _in_range else ACCENT
    st_html(f"""
    <div style="padding: 16px 2px 4px;">
        <div style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.8px; color: {MUTED}; margin-bottom: 8px;">Patrimonio Consolidato Globale</div>
        <div style="display:flex; align-items:baseline; gap:14px; flex-wrap:wrap;">
            <span style="font-family:{MONO}; font-size:40px; font-weight:800; letter-spacing:-1px;">€ {_tot:,.0f}</span>
            <span style="font-size:12.5px; font-weight:700; color:{_ratio_badge_col}; background:rgba(255,247,237,0.06); padding:4px 10px; border-radius:6px; border:1px solid {BORDER}; font-family:{MONO};">
                Dual-Engine {"in Equilibrio" if _in_range else "da Riequilibrare"} · Target {_target_apex*100:.0f}/{(1-_target_apex)*100:.0f}
            </span>
        </div>
        <div style="font-size:12px; color:{MUTED}; margin-top:8px;">Target: {_target_apex*100:.0f}% Apex / {(1-_target_apex)*100:.0f}% Convex · Fascia di tolleranza operativa: 30–55%</div>
    </div>
    """)

    # 2. Centro di Controllo dei Due Motori (Sintesi e Stato Operativo)
    st_html(section_title("Centro di Controllo dei Due Motori"))
    _pending_orders = apex_portfolio.get("pending_orders") or []
    
    col_mot1, col_mot2 = st.columns(2)
    with col_mot1:
        if _pending_orders:
            _apex_badge_html = f'<span style="background:rgba(236,101,123,0.12); color:{NEG}; border:1px solid rgba(236,101,123,0.3); padding:4px 9px; border-radius:6px; font-size:11.5px; font-weight:700; display:inline-flex; align-items:center; gap:5px;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="{NEG}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg> {len(_pending_orders)} ordine/i pendenti per lunedì</span>'
        else:
            _apex_badge_html = f'<span style="background:rgba(61,220,151,0.10); color:{POS}; border:1px solid rgba(61,220,151,0.25); padding:4px 9px; border-radius:6px; font-size:11.5px; font-weight:700; display:inline-flex; align-items:center; gap:5px;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="{POS}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg> Allineato · Nessun ordine da eseguire</span>'

        st_html(f"""
        <div style="background:{SURFACE}; border:1px solid {BORDER}; border-radius:10px; padding:16px 18px; height:100%;">
            <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;">
                <div style="font-family:{FRAUNCES}; font-size:16px; font-weight:700; color:#3DDC97; display:flex; align-items:center; gap:8px;">
                    Apex Engine
                </div>
                <div style="font-size:11px; color:{MUTED};">Venerdì ore 21:00 CET</div>
            </div>
            <div style="font-size:12px; color:{MUTED}; margin-bottom:12px;">
                Tattico Alpha · Rotazione 15 S&P 500 Low-Vol + Trend multi-asset
            </div>
            <div style="display:flex; justify-content:space-between; align-items:baseline; padding:10px 12px; background:rgba(255,247,237,0.02); border:1px solid {BORDER_STRONG}; border-radius:6px; margin-bottom:12px;">
                <span style="font-size:12px; color:{MUTED};">Quota Reale:</span>
                <span style="font-family:{MONO}; font-weight:700; font-size:13px; color:{BADGE_TEXT};">€ {apex_val_eur:,.0f} ({_real_apex_ratio*100:.1f}%)</span>
                <span style="font-size:11px; color:{MUTED}; margin-left:6px;">Target {_target_apex*100:.0f}%</span>
            </div>
            <div>{_apex_badge_html}</div>
        </div>
        """)

    with col_mot2:
        if _cx_rep.trim_alerts:
            _cx_badge_html = f'<span style="background:rgba(236,101,123,0.12); color:{NEG}; border:1px solid rgba(236,101,123,0.3); padding:4px 9px; border-radius:6px; font-size:11.5px; font-weight:700; display:inline-flex; align-items:center; gap:5px;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="{NEG}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg> Trim consigliato ({len(_cx_rep.trim_alerts)} asset sopra soglia)</span>'
        else:
            _cx_badge_html = f'<span style="background:rgba(61,220,151,0.10); color:{POS}; border:1px solid rgba(61,220,151,0.25); padding:4px 9px; border-radius:6px; font-size:11.5px; font-weight:700; display:inline-flex; align-items:center; gap:5px;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="{POS}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg> In banda · Tutti i 5 asset entro soglie</span>'

        st_html(f"""
        <div style="background:{SURFACE}; border:1px solid {BORDER}; border-radius:10px; padding:16px 18px; height:100%;">
            <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;">
                <div style="font-family:{FRAUNCES}; font-size:16px; font-weight:700; color:#C9A44C; display:flex; align-items:center; gap:8px;">
                    Convex Stack
                </div>
                <div style="font-size:11px; color:{MUTED};">1° del mese con versamento PAC</div>
            </div>
            <div style="font-size:12px; color:{MUTED}; margin-bottom:12px;">
                Strategico PAC · Leva 1.5x NTSG + SCV + CTA + Oro + BTC (122.5% Nozionale)
            </div>
            <div style="display:flex; justify-content:space-between; align-items:baseline; padding:10px 12px; background:rgba(255,247,237,0.02); border:1px solid {BORDER_STRONG}; border-radius:6px; margin-bottom:12px;">
                <span style="font-size:12px; color:{MUTED};">Quota Reale:</span>
                <span style="font-family:{MONO}; font-weight:700; font-size:13px; color:{BADGE_TEXT};">€ {convex_val_eur:,.0f} ({_real_convex_ratio*100:.1f}%)</span>
                <span style="font-size:11px; color:{MUTED}; margin-left:6px;">Target {(1-_target_apex)*100:.0f}%</span>
            </div>
            <div>{_cx_badge_html}</div>
        </div>
        """)

    # 3. Composizione Macro Consolidata
    st_html(section_title("Composizione Macro Consolidata"))
    _macro = unified_data["macro_breakdown"]
    _c_map = {
        "Azionario Globale & USA": POS,
        "Obbligazionario Governativo": "#8B7FC7",
        "Managed Futures (CTA)": "#E0A96D",
        "Oro Fisico": ACCENT,
        "Bitcoin": "#F7931A",
    }
    macro_segs = [(k, _macro.get(k, 0.0) * 100.0, _c_map.get(k, MUTED)) for k in _c_map]
    if unified_data["idle_cash_pct"] > 0.01:
        macro_segs.append(("Liquidità", unified_data["idle_cash_pct"] * 100.0, "#4A443D"))

    _tot_pct = sum(p for _, p, _ in macro_segs)
    if _tot_pct > 0:
        bar_segs = "".join(f'<div style="height:100%; width:{(pct/_tot_pct)*100:.2f}%; background:{col};" title="{label}: {pct:.1f}%"></div>' for label, pct, col in macro_segs)
        legend_items = "".join(
            f'<div style="display:flex; align-items:center; gap:6px;">{get_macro_class_svg(label, size=14, color=col)} <span style="opacity:0.85;">{label}</span> <b style="font-family:{MONO}; font-weight:700;">{pct:.1f}%</b></div>'
            for label, pct, col in macro_segs
        )
        st_html(f'<div style="display:flex; height:12px; border-radius:6px; overflow:hidden; border:1px solid {BORDER_STRONG}; margin-bottom:12px;">{bar_segs}</div>')
        st_html(f'<div style="display:flex; flex-wrap:wrap; gap:12px 20px; margin-bottom:20px; font-size:11.5px;">{legend_items}</div>')

    # 4. Consiglio Smart-Flow PAC
    st_html(section_title("Consiglio Smart-Flow (Ribilanciamento a Costo Fiscale Zero)"))
    st_html(f"""
    <div class="glass-card-accent">
        <div style="font-size:14px; font-weight:700; color:{ACCENT}; margin-bottom:4px;">
            DIREZIONE CONSIGLIATA PER IL PROSSIMO VERSAMENTO PAC: {unified_data['smart_flow_destination'].upper()}
        </div>
        <div style="font-size:12.5px; color:{BADGE_TEXT}; line-height:1.5;">
            {unified_data['smart_flow_note']}
        </div>
    </div>
    """)


    # 7. Parametri di Simulazione e Rata PAC
    with st.expander("Parametri Globali e Rata PAC (Simulazione)", expanded=False):
        st.caption("Configura i capitali di riferimento standard, il target di allocazione e la rata PAC per la simulazione globale.")
        p_c1, p_c2 = st.columns(2)
        with p_c1:
            cfg_apex_cap = st.number_input("Capitale di Riferimento Apex (€)", min_value=1000.0, value=float(cfg.get("apex_capital_eur", 100000.0)), step=5000.0, format="%.0f")
            cfg_target_apex = st.slider("Target Allocazione Apex (%)", min_value=10, max_value=90, value=int(cfg.get("target_apex_ratio", 0.50)*100), step=5) / 100.0
        with p_c2:
            cfg_convex_cap = st.number_input("Capitale di Riferimento Convex (€)", min_value=1000.0, value=float(cfg.get("convex_capital_eur", 100000.0)), step=5000.0, format="%.0f")
            cfg_pac = st.number_input("Rata PAC Mensile (€)", min_value=50.0, value=float(cfg.get("monthly_pac_eur", 500.0)), step=50.0, format="%.0f")
        
        if st.button("Salva Parametri Globali", use_container_width=True, key="home_save_cfg"):
            new_cfg = {
                **cfg,
                "apex_capital_eur": cfg_apex_cap,
                "convex_capital_eur": cfg_convex_cap,
                "target_apex_ratio": cfg_target_apex,
                "target_convex_ratio": 1.0 - cfg_target_apex,
                "monthly_pac_eur": cfg_pac,
                "last_updated": datetime.date.today().strftime("%Y-%m-%d")
            }
            if portfolio_manager.save_config(new_cfg):
                st.toast("Parametri globali aggiornati per questa sessione.")
                st.rerun()
            else:
                st.error("Errore nel salvataggio.")




# ==============================================================================
# TAB 2: METRICHE COMBINATE & BACKTEST
# ==============================================================================
with tab_perf:
    _dual = portfolio_manager.get_combined_dual_engine_metrics()

    st_html(f"""
    <div style="display:flex; gap:24px; flex-wrap:wrap; margin-bottom:16px;">
        {sub_hero_metric("Crescita Annua Netta", f"{_dual['cagr_net']*100:.2f}%", f"Lordo {_dual['cagr_gross']*100:.2f}%", POS if _dual['cagr_net'] >= 0 else NEG, primary=True)}
        {sub_hero_metric("Indice di Sharpe", f"{_dual['sharpe']:.2f}", "Efficienza rendimento/rischio", POS if _dual['sharpe'] >= 1.0 else None, primary=True)}
        {sub_hero_metric("Calo Massimo Storico", f"{_dual['max_drawdown']*100:.2f}%", "Abbattuto sotto il 10%", primary=True)}
    </div>
    <div style="display:flex; gap:20px; flex-wrap:wrap; margin-bottom:24px; padding-top:12px; border-top:1px solid {BORDER};">
        {sub_hero_metric("Volatilità Annua", f"{_dual['volatility']*100:.1f}%", "Oscillazione realizzata del mix")}
        {sub_hero_metric("Indice di Sortino", f"{_dual['sortino']:.2f}", "Rendimento sui ribassi negativi")}
        {sub_hero_metric("Correlazione Reale", f"{_dual['correlation']:.2f}", "Bassa correlazione cross-strategia")}
    </div>
    """)

    # Carica serie combinata 142 mesi (2014-11 al 2026-08)
    if hasattr(portfolio_manager, "load_combined_monthly_history"):
        df_comb = portfolio_manager.load_combined_monthly_history(target_apex=_target_apex, target_convex=(1.0 - _target_apex))
    else:
        base_dir = os.path.dirname(__file__)
        apex_file = os.path.join(base_dir, "apex_monthly_returns_extended.csv")
        conv_file = os.path.join(base_dir, "convex_monthly_returns.csv")
        if os.path.exists(apex_file) and os.path.exists(conv_file):
            a_ret = pd.read_csv(apex_file, index_col=0, parse_dates=True).iloc[:, 0]
            c_ret = pd.read_csv(conv_file, index_col=0, parse_dates=True).iloc[:, 0]
            common = a_ret.index.intersection(c_ret.index)
            if len(common) > 0:
                comb_ret = _target_apex * a_ret.loc[common] + (1.0 - _target_apex) * c_ret.loc[common]
                df_comb = pd.DataFrame({"return": comb_ret})
                df_comb["value"] = (1.0 + comb_ret).cumprod() * 100.0
                df_comb["roll_max"] = df_comb["value"].cummax()
                df_comb["drawdown"] = (df_comb["value"] - df_comb["roll_max"]) / df_comb["roll_max"] * 100.0
            else:
                df_comb = pd.DataFrame()
        else:
            df_comb = pd.DataFrame()


    if not df_comb.empty:
        st_html(section_title("Curva Equity Combinata vs Benchmark (SPY)", top="8px", bottom="8px"))
        st.caption(f"Serie mensile dal backtest comune (2014–2026, 142 mesi reali). Combinazione pesata {_target_apex*100:.0f}% Apex Engine / {(1-_target_apex)*100:.0f}% Convex Stack.")


        selected_range = st.segmented_control(
            "Periodo", options=["1A", "3A", "5A", "10A", "Tutto"],
            default="5A", label_visibility="collapsed", key="comb_chart_range_ctrl"
        ) or "5A"

        last_dt = df_comb.index[-1]
        if selected_range == "1A":
            start_dt = last_dt - pd.DateOffset(years=1)
        elif selected_range == "3A":
            start_dt = last_dt - pd.DateOffset(years=3)
        elif selected_range == "5A":
            start_dt = last_dt - pd.DateOffset(years=5)
        elif selected_range == "10A":
            start_dt = last_dt - pd.DateOffset(years=10)
        else:
            start_dt = df_comb.index[0]

        _comb_plot = df_comb[df_comb.index >= start_dt].copy()
        _comb_plot["norm"] = (_comb_plot["value"] / _comb_plot["value"].iloc[0]) * 100.0

        s_spy_full = portfolio_manager.load_monthly_benchmark_spy(start_date=_comb_plot.index[0])
        common_dt = _comb_plot.index.intersection(s_spy_full.index)

        fig_comb = go.Figure()
        fig_comb.add_trace(go.Scatter(
            x=_comb_plot.index, y=_comb_plot["norm"], mode="lines",
            name=f"Apex Convex (Mix {_target_apex*100:.0f}/{(1-_target_apex)*100:.0f})",
            line=dict(color=ACCENT, width=2), fill="tozeroy", fillcolor="rgba(201, 164, 76, 0.10)",
            hovertemplate="Base 100: %{y:.2f}<extra></extra>"
        ))
        if len(common_dt) > 0:
            _spy_aligned = s_spy_full.loc[common_dt]
            _spy_norm = (_spy_aligned / _spy_aligned.iloc[0]) * 100.0
            fig_comb.add_trace(go.Scatter(
                x=_spy_norm.index, y=_spy_norm, mode="lines", name="S&P 500 Benchmark",
                line=dict(color='#7A7266', width=1.5, dash='dot'),
                hovertemplate="S&P 500: %{y:.2f}<extra></extra>"
            ))


        fig_comb.update_layout(
            template="plotly_dark",
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color=MUTED, family="Inter"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=10)),
            margin=dict(t=30, b=10, l=10, r=10), height=280,
            yaxis_title="Base 100"
        )
        st.plotly_chart(fig_comb, use_container_width=True)

        st_html(section_title("Calo dal Massimo Storico (Drawdown Combinato)", top="14px", bottom="6px"))
        fig_comb_dd = go.Figure()
        fig_comb_dd.add_trace(go.Scatter(
            x=df_comb.index, y=df_comb["drawdown"], fill="tozeroy", mode="lines",
            line=dict(color=NEG, width=1.2), fillcolor="rgba(236,101,123,0.15)",
            hovertemplate="%{x|%d %b %Y}<br>Calo: %{y:.2f}%<extra></extra>", name="Calo Combinato"
        ))
        fig_comb_dd.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color=MUTED, family="Inter"),
            xaxis=dict(showgrid=False, tickfont=dict(size=10)),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,247,237,0.05)', tickfont=dict(size=10), ticksuffix="%"),
            margin=dict(t=4, b=10, l=10, r=10), height=140, showlegend=False
        )
        st.plotly_chart(fig_comb_dd, use_container_width=True)

        st_html(section_title("Matrice dei Rendimenti Mensili Combinati"))
        st_html(render_monthly_returns_html_table(df_comb))

    st_html(section_title("Sinergia Quantitativa & Costi"))
    st_html(f"""
    <div class="glass-card">
        <div style="font-size: 13px; color: {MUTED}; line-height: 1.6;">
            {_dual["synergy_summary"]}
        </div>
    </div>
    """)


# ==============================================================================
# TAB 3: GUIDA OPERATIVA & FISCALITÀ
# ==============================================================================
with tab_guide:
    st_html(section_title("La Routine Operativa Combinata", top="0"))
    r1, r2, r3 = st.columns(3)
    with r1:
        st_html(f"""
        <div class="glass-card" style="text-align:center; height: 140px;">
            <div style="font-family:{FRAUNCES}; font-size:24px; color:{POS}; font-weight:700;">1</div>
            <div style="font-size:13.5px; font-weight:700; color:{BADGE_TEXT}; margin:6px 0;">Venerdì ore 21:00 CET</div>
            <div style="font-size:12px; color:{MUTED}; line-height:1.4;">Controlla Apex Engine: il motore valuta le chiusure settimanali e notifica su Telegram eventuali ordini operativi per lunedì.</div>
        </div>
        """)
    with r2:
        st_html(f"""
        <div class="glass-card" style="text-align:center; height: 140px;">
            <div style="font-family:{FRAUNCES}; font-size:24px; color:{ACCENT}; font-weight:700;">2</div>
            <div style="font-size:13.5px; font-weight:700; color:{BADGE_TEXT}; margin:6px 0;">1° del Mese</div>
            <div style="font-size:12px; color:{MUTED}; line-height:1.4;">Controlla Convex Stack: inserisci la rata PAC del mese e versa sull'asset più sottopesato. Esegui il trim se Oro o BTC superano l'11.25%.</div>
        </div>
        """)
    with r3:
        st_html(f"""
        <div class="glass-card" style="text-align:center; height: 140px;">
            <div style="font-family:{FRAUNCES}; font-size:24px; color:#8B7FC7; font-weight:700;">3</div>
            <div style="font-size:13.5px; font-weight:700; color:{BADGE_TEXT}; margin:6px 0;">Ribilanciamento Smart-Flow</div>
            <div style="font-size:12px; color:{MUTED}; line-height:1.4;">Se Apex scende sotto il {(_target_apex-0.05)*100:.0f}% del totale, indirizza il nuovo risparmio mensile verso Apex; altrimenti va su Convex, sull'asset più sottopesato tra i 5 — sempre a costo fiscale zero.</div>
        </div>
        """)

    st_html(section_title("I Due Motori a Confronto"))
    m_col1, m_col2 = st.columns(2)
    with m_col1:
        st_html(f"""
        <div class="glass-card" style="height: 195px;">
            <div style="font-family:{MONO}; font-size:14px; font-weight:700; color:{POS}; display:flex; align-items:center; gap:6px;">Apex Engine (Tattico Alpha)</div>
            <div style="font-size:12px; color:{MUTED}; line-height:1.5; margin-top:8px;">
                Motore quantitativo a selezione attiva (15 titoli S&P 500 a minima volatilità con buffer rank 20) e trend following macro a doppio filtro temporale (40w/20w con isteresi).
                Durante i mercati ribassisti disattiva l'azionario e protegge il 100% del capitale in liquidità remunerata o Treasury.
            </div>
        </div>
        """)
    with m_col2:
        st_html(f"""
        <div class="glass-card" style="height: 195px;">
            <div style="font-family:{MONO}; font-size:14px; font-weight:700; color:{ACCENT}; display:flex; align-items:center; gap:6px;">Convex Stack (Strategico PAC)</div>
            <div style="font-size:12px; color:{MUTED}; line-height:1.5; margin-top:8px;">
                Portafoglio multi-asset a leva implicita istituzionale (NTSG 1.5x, futures Treasury senza debito a margine personale).
                Combina azionario globale, fattore small cap value, trend following anti-crisi (DBMFE) e riserve reali (Oro fisico ed ETP Bitcoin con compensazione fiscale delle minusvalenze).
            </div>
        </div>
        """)


    st_html(section_title("Ottimizzazione Fiscale Italiana (Redditi Diversi vs Capitale)"))
    st_html(f"""
    <div class="glass-card">
        <div style="font-size: 13px; color: {MUTED}; line-height: 1.6;">
            Nel regime fiscale italiano, gli <strong>ETF armonizzati (NTSG, AVWS, DBMFE)</strong> generano <em>Redditi di Capitale</em> su cui l'imposta del 26% si applica per intero senza possibilità di compensare le perdite pregresse nello zainetto fiscale.
            Al contrario, gli strumenti su materie prime e crypto (<strong>PPFB — iShares Physical Gold ETC</strong> e <strong>WBTC — WisdomTree Physical Bitcoin ETP</strong>) generano per legge <strong>Redditi Diversi</strong>.
            Le plusvalenze realizzate durante le operazioni di trim di Oro e Bitcoin compensano direttamente le minusvalenze accumulate, azzerando l'imposta fino a concorrenza del credito d'imposta disponibile.
        </div>
    </div>
    """)

    st_html(f"""
    <div style="margin-top: 24px; padding: 14px; background: rgba(255,247,237,0.02); border: 1px solid {BORDER}; border-radius: 8px; font-size: 11.5px; color: {MUTED}; line-height: 1.5;">
        Questo strumento è di supporto informativo e decisionale e non costituisce consulenza finanziaria personalizzata.
        Le performance passate e le simulazioni storiche non garantiscono risultati futuri.
    </div>
    """)
