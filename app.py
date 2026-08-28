import base64
import datetime
import json
import math
import os
import urllib.request

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="Apex Multi-Asset",
    page_icon="logo_icon.png" if os.path.exists("logo_icon.png") else "🦅",
    layout="wide"
)

# ==============================================================================
# HTML RENDERING HELPER (PREVENTS UNRENDERED CODE BLOCKS)
# ==============================================================================
def st_html(html_str):
    """Renders raw HTML safely without Markdown parser indentation issues."""
    cleaned = "\n".join(line.strip() for line in html_str.strip().splitlines())
    try:
        st.html(cleaned)
    except AttributeError:
        st.markdown(cleaned, unsafe_allow_html=True)


# ==============================================================================
# THEME & GLOBAL STYLING
# ==============================================================================
st_html("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"], .stApp {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        letter-spacing: -0.01em;
    }

    /* Tabular numbers for financial metrics and dataframes */
    [data-testid="stMetricValue"], [data-testid="stMetricLabel"], .stDataFrame, div[data-testid="stTable"], table {
        font-family: 'JetBrains Mono', monospace !important;
        font-variant-numeric: tabular-nums !important;
    }

    /* Standardized typography for section headers */
    h4, .section-title {
        font-family: 'Inter', sans-serif !important;
        font-size: 16px !important;
        font-weight: 700 !important;
        letter-spacing: -0.2px !important;
        margin-top: 14px !important;
        margin-bottom: 8px !important;
    }

    h5, .subsection-title {
        font-family: 'Inter', sans-serif !important;
        font-size: 14px !important;
        font-weight: 700 !important;
        margin-top: 12px !important;
        margin-bottom: 6px !important;
    }

    /* Tab navigation polish */
    .stTabs [data-baseweb="tab-list"] {
        gap: 6px;
        border-bottom: 1px solid rgba(128,128,128,0.2);
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 18px;
        border-radius: 8px 8px 0px 0px;
        font-weight: 600;
        font-size: 13.5px;
    }

    /* Flat instrument-panel surfaces: hairline border, subtle hover lift, no heavy chrome */
    div[style*="border-radius"] {
        transition: transform 0.15s ease-in-out, border-color 0.15s ease-in-out;
    }
</style>
""")


# ==============================================================================
# DESIGN TOKENS ("Instrument Panel" — palette neutra, colore riservato al segno)
# ==============================================================================
POS = "#10B981"       # verde — riservato al P&L positivo
NEG = "#EF4444"        # rosso — riservato al P&L negativo / attenzione reale
NEUTRAL_DOT = "rgba(128,128,128,0.45)"   # segnale "in pausa" — non è una notizia negativa
ACCENT = "#3B82F6"     # unico accento di marca, solo per elementi interattivi
SURFACE = "rgba(128,128,128,0.045)"
BORDER = "rgba(128,128,128,0.14)"
MUTED = "#9CA3AF"


def flat_card(inner_html, padding="14px 16px", opacity="1"):
    return f'<div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: {padding}; opacity: {opacity};">{inner_html}</div>'


def monogram(text, active=True, size=26):
    color = POS if active else NEUTRAL_DOT
    return f'''<span style="display:inline-flex; align-items:center; justify-content:center; width:{size}px; height:{size}px; border-radius:6px; border:1px solid {color}; color:{color}; font-family:'JetBrains Mono',monospace; font-weight:700; font-size:10px; letter-spacing:-0.3px; flex-shrink:0;">{text}</span>'''


def ring_svg(pct, active, size=30, stroke=3):
    r = (size - stroke) / 2.0
    circumference = 2 * math.pi * r
    frac = max(0.0, min(1.0, pct / 100.0))
    offset = circumference * (1 - frac)
    color = POS if active else NEUTRAL_DOT
    c = size / 2.0
    return f'''<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" style="flex-shrink:0;">
        <circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="rgba(128,128,128,0.15)" stroke-width="{stroke}"/>
        <circle cx="{c}" cy="{c}" r="{r}" fill="none" stroke="{color}" stroke-width="{stroke}"
            stroke-dasharray="{circumference:.2f}" stroke-dashoffset="{offset:.2f}"
            stroke-linecap="round" transform="rotate(-90 {c} {c})"/>
    </svg>'''


# ==============================================================================
# DATA LOADING & SYNC
# ==============================================================================
@st.cache_data(ttl=60)
def fetch_json_from_github(filename):
    url = f"https://raw.githubusercontent.com/davbenx/apex-engine/main/{filename}"
    try:
        buster = int(datetime.datetime.now().timestamp() // 60)
        req = urllib.request.Request(f"{url}?t={buster}", headers={'User-Agent': 'Mozilla/5.0'})
        return json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
    except Exception:
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
    return None


def load_data():
    return fetch_json_from_github('apex_data.json')


def load_portfolio():
    return fetch_json_from_github('portfolio.json')


def load_equity():
    return fetch_json_from_github('equity.json')


data = load_data()
if not data:
    st.error("Dati non disponibili. In attesa del ricalcolo notturno su GitHub.")
    st.stop()


# ==============================================================================
# FORMATTING & HELPERS
# ==============================================================================
def format_price(val):
    if val is None or pd.isna(val):
        return "$0.00"
    try:
        num = float(val)
        return f"${num:,.2f}" if abs(num) >= 1.0 else f"${num:,.6f}"
    except Exception:
        return f"${val}"


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
        mesi = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]
        return f"{dt.day} {mesi[dt.month-1]} {dt.year}"
    except Exception:
        return d_str


def get_logo_b64():
    for p in ["logo_icon.png", "logo.png"]:
        if os.path.exists(p):
            try:
                with open(p, "rb") as f:
                    return base64.b64encode(f.read()).decode()
            except Exception:
                pass
    return ""


# ==============================================================================
# HEADER & BRANDING
# ==============================================================================
last_update = data.get("timestamp", "Sincronizzazione in corso...")
logo_b64 = get_logo_b64()
logo_tag = f'<img src="data:image/png;base64,{logo_b64}" style="height: 75px; width: auto; object-fit: contain;" />' if logo_b64 else monogram("AE", active=True, size=52)

col_title, col_meta = st.columns([3, 2])
with col_title:
    st_html(f"""
    <div style="display: flex; align-items: center; gap: 16px; padding: 6px 0;">
        <div style="background: rgba(128, 128, 128, 0.06); border: 1px solid {BORDER}; padding: 6px 10px; border-radius: 12px; display: flex; align-items: center; justify-content: center;">
            {logo_tag}
        </div>
        <div>
            <div style="font-size: 28px; font-weight: 800; letter-spacing: -0.8px; line-height: 1.15;">APEX ENGINE</div>
            <div style="font-size: 12px; font-weight: 600; opacity: 0.75; letter-spacing: 0.6px; text-transform: uppercase; margin-top: 3px; line-height: 1.35;">
                Sistema Quantitativo<br>
                Multi-Asset<br>
                <span style='color: {ACCENT}; font-weight: 700;'>v2.0</span>
            </div>
        </div>
    </div>
    """)

with col_meta:
    st_html(f"""
    <div style="text-align: right; padding-top: 8px;">
        <div style="display: flex; justify-content: flex-end; align-items: center; gap: 8px; margin-bottom: 5px;">
            <a href="https://t.me/apex_multiasset" target="_blank" style="text-decoration: none; display: inline-flex; align-items: center; gap: 4px; background: rgba(0, 136, 204, 0.1); color: #0088cc; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; border: 1px solid rgba(0, 136, 204, 0.25);">
                Notifiche Telegram →
            </a>
            <span style="display:inline-flex; align-items:center; gap:5px; background: rgba(128,128,128,0.08); color: {MUTED}; padding: 4px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; border: 1px solid {BORDER};">
                <span style="width:6px; height:6px; border-radius:50%; background:{POS}; display:inline-block;"></span> Motore Attivo
            </span>
        </div>
        <div style="opacity: 0.65; font-size: 11.5px; line-height: 1.4;">
            <strong>Aggiornato:</strong> {last_update}<br>
            <strong>Ricalcolo:</strong> Lun-Ven 23:00 UTC
        </div>
    </div>
    """)

# ==============================================================================
# COCKPIT — STATO SEGNALI MACRO PER CLASSE
# ==============================================================================
alloc = data.get('allocations', {"Equities": 0, "Crypto": 0, "Gold": 0, "Bonds": 0, "Cash": 100})
raw_ts = data.get('timestamp', '')
ts_date = raw_ts.split(',')[0].strip() if ',' in raw_ts else (raw_ts.split(' ')[0] if raw_ts else datetime.datetime.now().strftime('%Y-%m-%d'))
macro_dates = data.get("macro_dates", {})

d_eq = macro_dates.get("Equities", ts_date)
d_cr = macro_dates.get("Crypto", ts_date)
d_g = macro_dates.get("Gold", ts_date)
d_b = macro_dates.get("Bonds", ts_date)


def cockpit_pill(mono_text, label, alloc_pct, is_active, since_date, is_cash=False):
    """Anello = peso %, colore = stato (verde=attiva, grigio=in pausa/riserva).
    La data del segnale è sempre testo visibile — mai solo in tooltip (vedi §12.1)."""
    if is_cash:
        state_text = "Riserva di liquidità"
    else:
        fmt_d = format_date_italian(since_date) if since_date and since_date != "-" else ""
        state_text = f"{'Attiva' if is_active else 'In pausa'}{(' dal ' + fmt_d) if fmt_d else ''}"

    ring = ring_svg(alloc_pct, is_active and not is_cash)
    return f"""
    <div style="display:flex; align-items:center; gap:9px; background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 12px 7px 8px; min-width: 172px;">
        <div style="position:relative; width:30px; height:30px;">
            {ring}
            <span style="position:absolute; inset:0; display:flex; align-items:center; justify-content:center; font-family:'JetBrains Mono',monospace; font-size:8.5px; font-weight:700; opacity:0.9;">{mono_text}</span>
        </div>
        <div style="line-height:1.3;">
            <div style="font-size:11.5px; font-weight:700; letter-spacing:0.1px;">{label} <span style="font-family:'JetBrains Mono',monospace; font-weight:700; opacity:0.85;">{alloc_pct:.0f}%</span></div>
            <div style="font-size:10px; opacity:0.6;">{state_text}</div>
        </div>
    </div>
    """

pill_eq = cockpit_pill("EQ", "Azioni", alloc.get('Equities', 0), alloc.get('Equities', 0) > 0, d_eq)
pill_cr = cockpit_pill("₿", "Bitcoin", alloc.get('Crypto', 0), alloc.get('Crypto', 0) > 0, d_cr)
pill_g = cockpit_pill("AU", "Oro", alloc.get('Gold', 0), alloc.get('Gold', 0) > 0, d_g)
pill_b = cockpit_pill("FI", "Obbligazioni", alloc.get('Bonds', 0), alloc.get('Bonds', 0) > 0, d_b)
pill_c = cockpit_pill("$", "Monetario", alloc.get('Cash', 0), False, "", is_cash=True)

st_html(f'<div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 12px 0 18px 0;">{pill_eq}{pill_cr}{pill_g}{pill_b}{pill_c}</div>')


# ==============================================================================
# PORTFOLIO DATA EXTRACTION
# ==============================================================================
pf = load_portfolio()
open_pos_raw = pf.get("open_positions", {}) if pf else {}
op_eq = []
op_cr = []
num_eq = 0
num_cr = 0

if pf:
    for ticker, info in open_pos_raw.items():
        entry_d = info.get("entry_date", "N/A")
        days_open = calculate_days(entry_d) if entry_d != "N/A" else 0
        entry_formatted = f"{entry_d} ({days_open}g)" if entry_d != "N/A" else "N/A"

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


def instrument_card(mono_text, label, is_active, detail, curr_sym, fx_ratio):
    if not is_active or detail is None:
        return f"""
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 12px 14px; opacity: 0.55;">
            <div style="display:flex; align-items:center; gap:8px; margin-bottom:8px;">
                {monogram(mono_text, active=False)}
                <span style="font-weight:600; font-size:11.5px; letter-spacing:0.3px; text-transform:uppercase; color:{MUTED};">{label}</span>
            </div>
            <div style="font-size:11.5px; opacity:0.75;">Non allocato — segnale in pausa</div>
        </div>
        """
    val_user = detail["value_usd"] * fx_ratio
    pnl_user = detail["pnl_usd"] * fx_ratio
    pnl_color = POS if detail["pnl_pct"] >= 0 else NEG
    pnl_sign = "+" if pnl_user >= 0 else "-"
    fmt_d = format_date_italian(detail["entry_date"]) if detail["entry_date"] != "N/A" else "-"
    return f"""
    <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 12px 14px;">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;">
            <div style="display:flex; align-items:center; gap:8px;">
                {monogram(mono_text, active=True)}
                <span style="font-weight:600; font-size:11.5px; letter-spacing:0.3px; text-transform:uppercase; color:{MUTED};">{label}</span>
            </div>
            <span style="font-family:'JetBrains Mono',monospace; font-weight:700; font-size:12px;">{detail['weight_pct']:.1f}%</span>
        </div>
        <div style="font-size:19px; font-weight:800; font-family:'JetBrains Mono',monospace; margin-bottom:2px;">{curr_sym}{val_user:,.0f}</div>
        <div style="font-size:12px; font-weight:700; color:{pnl_color}; font-family:'JetBrains Mono',monospace; margin-bottom:7px;">{pnl_sign}{curr_sym}{abs(pnl_user):,.0f} ({detail['pnl_pct']:+.2f}%)</div>
        <div style="font-size:10.5px; opacity:0.6; display:flex; justify-content:space-between; gap:8px; flex-wrap:wrap;">
            <span>{format_price(detail['entry_price'])} → {format_price(detail['current_price'])}</span>
            <span>dal {fmt_d} · {detail['days']}g</span>
        </div>
    </div>
    """


def cash_card(value_usd, weight_pct, curr_sym, fx_ratio):
    val_user = value_usd * fx_ratio
    return f"""
    <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 12px 14px;">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;">
            <div style="display:flex; align-items:center; gap:8px;">
                {monogram("$", active=True)}
                <span style="font-weight:600; font-size:11.5px; letter-spacing:0.3px; text-transform:uppercase; color:{MUTED};">Monetario</span>
            </div>
            <span style="font-family:'JetBrains Mono',monospace; font-weight:700; font-size:12px;">{weight_pct:.1f}%</span>
        </div>
        <div style="font-size:19px; font-weight:800; font-family:'JetBrains Mono',monospace; margin-bottom:2px;">{curr_sym}{val_user:,.0f}</div>
        <div style="font-size:10.5px; opacity:0.6;">Parcheggio strategico e riserve per il target di volatilità</div>
    </div>
    """


# ==============================================================================
# LAST REBALANCE CALLOUT (sopra le tab, sempre visibile)
# ==============================================================================
last_actions = (pf or {}).get("last_action_log") or []
if last_actions:
    last_action_date = (pf or {}).get("last_action_date", "")
    st_html(f"""
    <div style="background: rgba(59, 130, 246, 0.06); border: 1px solid rgba(59, 130, 246, 0.25); border-bottom: none; border-radius: 8px 8px 0 0; padding: 10px 14px 6px 14px; font-size: 13px;">
        <div style="font-weight: 700;">Ultimo ribilanciamento ({last_action_date}) — operazioni da replicare sul tuo broker</div>
    </div>
    """)
    st.code("\n".join(last_actions), language=None)
    st.write("")

# ==============================================================================
# MAIN TABS DECLARATION (PORTAFOGLIO, METRICHE, GUIDA)
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
    # --- Treemap: allocazione + performance in un solo colpo d'occhio.
    # Basato sui pesi di strategia (indipendente dal capitale inserito sotto),
    # cosi' resta la prima cosa visibile aprendo la tab.
    tm_ids, tm_labels, tm_parents, tm_values, tm_colors, tm_text, tm_hover = [], [], [], [], [], [], []

    if op_eq:
        eq_weight_total = sum(r.get("Peso (%)", 0.0) for r in op_eq)
        eq_pnl_weighted = (sum(r["Rendimento %"] * r.get("Peso (%)", 0.0) for r in op_eq) / eq_weight_total) if eq_weight_total > 0 else 0.0
        tm_ids.append("AZIONARIO"); tm_labels.append("AZIONARIO"); tm_parents.append("")
        tm_values.append(eq_weight_total); tm_colors.append(eq_pnl_weighted)
        tm_text.append(f"{eq_pnl_weighted:+.2f}%")
        tm_hover.append(f"Azionario — {eq_weight_total:.1f}% del portafoglio<br>Rendimento medio ponderato: {eq_pnl_weighted:+.2f}%")
        for r in op_eq:
            tm_ids.append(f"AZ::{r['Titolo']}"); tm_labels.append(r["Titolo"]); tm_parents.append("AZIONARIO")
            tm_values.append(r.get("Peso (%)", 0.0)); tm_colors.append(r["Rendimento %"])
            tm_text.append(f"{r['Rendimento %']:+.2f}%")
            tm_hover.append(f"{r['Titolo']} — {r.get('Peso (%)', 0.0):.1f}% del portafoglio<br>Rendimento: {r['Rendimento %']:+.2f}%")

    if op_cr:
        r = op_cr[0]
        tm_ids.append("BITCOIN"); tm_labels.append("BITCOIN"); tm_parents.append("")
        tm_values.append(r.get("Peso (%)", 0.0)); tm_colors.append(r["Rendimento %"])
        tm_text.append(f"{r['Rendimento %']:+.2f}%")
        tm_hover.append(f"Bitcoin — {r.get('Peso (%)', 0.0):.1f}% del portafoglio<br>Rendimento: {r['Rendimento %']:+.2f}%")

    if alloc.get('Gold', 0) > 0:
        _gd = open_pos_raw.get("GLD")
        _g_pct = (((_gd.get("current_price", _gd.get("entry_price", 0.0)) / _gd["entry_price"]) - 1.0) * 100) if _gd and _gd.get("entry_price", 0) > 0 else 0.0
        tm_ids.append("ORO"); tm_labels.append("ORO"); tm_parents.append("")
        tm_values.append(alloc.get('Gold', 0)); tm_colors.append(_g_pct)
        tm_text.append(f"{_g_pct:+.2f}%")
        tm_hover.append(f"Oro — {alloc.get('Gold', 0):.1f}% del portafoglio<br>Rendimento: {_g_pct:+.2f}%")

    if alloc.get('Bonds', 0) > 0:
        _bd = open_pos_raw.get("IEF")
        _b_pct = (((_bd.get("current_price", _bd.get("entry_price", 0.0)) / _bd["entry_price"]) - 1.0) * 100) if _bd and _bd.get("entry_price", 0) > 0 else 0.0
        tm_ids.append("OBBLIGAZIONI"); tm_labels.append("OBBLIGAZIONI"); tm_parents.append("")
        tm_values.append(alloc.get('Bonds', 0)); tm_colors.append(_b_pct)
        tm_text.append(f"{_b_pct:+.2f}%")
        tm_hover.append(f"Obbligazioni — {alloc.get('Bonds', 0):.1f}% del portafoglio<br>Rendimento: {_b_pct:+.2f}%")

    if alloc.get('Cash', 0) > 0:
        tm_ids.append("MONETARIO"); tm_labels.append("MONETARIO"); tm_parents.append("")
        tm_values.append(alloc.get('Cash', 0)); tm_colors.append(0.0)
        tm_text.append("—")
        tm_hover.append(f"Monetario — {alloc.get('Cash', 0):.1f}% del portafoglio")

    if tm_ids:
        fig_tm = go.Figure(go.Treemap(
            ids=tm_ids, labels=tm_labels, parents=tm_parents, values=tm_values,
            branchvalues="total",
            marker=dict(
                colors=tm_colors,
                colorscale=[[0, "#7F1D1D"], [0.5, "#374151"], [1, "#065F46"]],
                cmid=0,
                line=dict(width=1, color="rgba(0,0,0,0.35)")
            ),
            text=tm_text,
            hovertext=tm_hover,
            hoverinfo="text",
            textinfo="label+text",
            textfont=dict(color="#F3F4F6", family="Inter, sans-serif", size=12),
            pathbar=dict(visible=True, textfont=dict(size=11)),
        ))
        fig_tm.update_layout(margin=dict(l=2, r=2, t=4, b=2), height=270, paper_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig_tm, use_container_width=True)

    st.write("")

    c_inp, c_pnl = st.columns([3, 2])
    with c_inp:
        c_val, c_cur = st.columns([3, 2])
        with c_val:
            _default_cap = 100000
            try:
                _default_cap = max(1000, int(st.query_params.get("cap", 100000)))
            except (TypeError, ValueError):
                pass
            capitale_input = st.number_input(
                "Capitale Broker Reale", min_value=1000, value=_default_cap, step=1000, format="%d"
            )
        with c_cur:
            _default_cur = st.query_params.get("cur", "USD ($)")
            if _default_cur not in ("USD ($)", "EUR (€)"):
                _default_cur = "USD ($)"
            valuta_sel = st.segmented_control("Valuta Conto", ["USD ($)", "EUR (€)"], default=_default_cur)

        st.query_params["cap"] = str(int(capitale_input))
        st.query_params["cur"] = valuta_sel

        eur_usd_rate = float(data.get("eur_usd", 1.085))
        is_eur = (valuta_sel == "EUR (€)")
        curr_sym = "€" if is_eur else "$"
        fx_ratio = (1.0 / eur_usd_rate) if is_eur else 1.0

        if is_eur:
            capitale = capitale_input * eur_usd_rate
            st.caption(f"Conto: **€{capitale_input:,.0f}** · Potere d'acquisto: **${capitale:,.0f} USD** (Tasso EUR/USD: `{eur_usd_rate:.4f}`)")
        else:
            capitale = float(capitale_input)
            st.caption(f"Conto operativo: **${capitale:,.0f} USD** (Prezzi e quote calcolati in dollari)")

    # v2: ogni posizione (azioni, IEF, GLD, BTC) porta il proprio peso reale in
    # portfolio.json ("weight", frazione del capitale) — nessuna quota fissa per
    # istanza (v1 assumeva 20 azioni al 5% e crypto al 10%/2.5%, non piu' valido).
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

    with c_pnl:
        num_pos = len(op_eq) + len(op_cr) + (1 if gold_detail else 0) + (1 if bond_detail else 0)
        breakdown_items = []
        if len(op_eq) > 0:
            breakdown_items.append(f"{len(op_eq)} Azioni")
        if len(op_cr) > 0:
            breakdown_items.append("Bitcoin")
        if gold_detail:
            breakdown_items.append("Oro")
        if bond_detail:
            breakdown_items.append("Obbligazioni")
        breakdown_str = f"({', '.join(breakdown_items)})" if breakdown_items else ""

        if num_pos > 0:
            pnl_sign = "+" if tot_pnl_user >= 0 else "-"
            pnl_col = POS if tot_pnl_user >= 0 else NEG
            pnl_val_str = f"{pnl_sign}{curr_sym}{abs(tot_pnl_user):,.0f}"
            pnl_pct_str = f"{'+' if tot_pnl_pct>=0 else ''}{tot_pnl_pct:.2f}%"
            if is_eur:
                sub_text = f"Su {num_pos} posizioni {breakdown_str} · (${tot_pnl_usd:+,.0f} USD)"
            else:
                sub_text = f"Su {num_pos} posizioni {breakdown_str}"
        else:
            pnl_col = MUTED
            pnl_val_str = f"{curr_sym}0"
            pnl_pct_str = "0.00%"
            sub_text = "Nessuna posizione aperta (attesa venerdì)"

        st_html(f"""
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 16px; margin-top: 2px;">
            <div style="opacity: 0.7; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Rendimento Galleggiante ({curr_sym})</div>
            <div style="font-size: 20px; font-weight: 700; color: {pnl_col}; font-family: 'JetBrains Mono', monospace; margin: 2px 0;">
                {pnl_val_str} <span style="font-size: 13px; font-weight: 600;">({pnl_pct_str})</span>
            </div>
            <div style="opacity: 0.6; font-size: 10.5px;">{sub_text}</div>
        </div>
        """)

    st.write("")

    # --- Card asset singoli: Monetario, Obbligazioni, Oro, Bitcoin — parità
    # informativa con la tabella Azioni (peso%, data ingresso, prezzo ingr.->attuale).
    real_cash_usd = max(0.0, capitale - tot_invested_usd)
    cash_weight_pct = (real_cash_usd / capitale * 100) if capitale > 0 else 0.0

    card_cash = cash_card(real_cash_usd, cash_weight_pct, curr_sym, fx_ratio)
    card_bond = instrument_card("FI", "Obbligazioni", bond_detail is not None, bond_detail, curr_sym, fx_ratio)
    card_gold = instrument_card("AU", "Oro", gold_detail is not None, gold_detail, curr_sym, fx_ratio)
    card_btc = instrument_card("₿", "Bitcoin", btc_detail is not None, btc_detail, curr_sym, fx_ratio)

    st_html(f'<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 10px; margin-bottom: 18px;">{card_cash}{card_bond}{card_gold}{card_btc}</div>')

    def color_pnl(val):
        color = POS if val > 0 else NEG if val < 0 else MUTED
        return f'color: {color}; font-weight: 700;'

    def style_stato(val):
        if "NUOVO" in str(val):
            return f'color: {ACCENT}; font-weight: 700; text-align: center;'
        return 'text-align: center; opacity: 0.4;'

    col_val_label = f"Valore ({curr_sym})"
    col_rend_label = f"Rendimento ({curr_sym})"

    show_details = st.toggle("Mostra dettagli esecuzione (quote, data ingresso, prezzi)", value=False)
    compact_cols = ["Pos", "Titolo", "Stato", "Peso (%)", col_val_label, "Rendimento %"]
    full_cols = ["Pos", "Titolo", "Stato", "Data Ingresso", "Quote", "Ingresso ($)", "Attuale ($)", "Peso (%)", col_val_label, "Rendimento %", col_rend_label]
    active_cols = full_cols if show_details else compact_cols

    st_html(f"""
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
        <span style="font-size: 15px; font-weight: 700; letter-spacing: -0.2px;">Basket Azionario (bassa volatilità)</span>
        <span style="color: {MUTED}; font-size: 11.5px; font-weight: 600; font-family: 'JetBrains Mono', monospace;">{num_eq} / {max(len(data.get('top20', [])), num_eq)} posizioni</span>
    </div>
    """)

    if op_eq:
        df_op_eq = pd.DataFrame(op_eq)
        df_op_eq["Quote"] = [max(1, int(round((capitale * r.get("Peso (%)", 0.0) / 100.0) / r["Ingresso ($)"]))) if r["Ingresso ($)"] > 0 else 0 for _, r in df_op_eq.iterrows()]
        df_op_eq[col_val_label] = [r["Quote"] * r["Attuale ($)"] * fx_ratio for _, r in df_op_eq.iterrows()]
        df_op_eq[col_rend_label] = df_op_eq[col_val_label] - (df_op_eq["Quote"] * df_op_eq["Ingresso ($)"] * fx_ratio)

        df_op_eq = df_op_eq[[c for c in active_cols if c in df_op_eq.columns]]

        df_eq_styled = df_op_eq.style.format({
            "Quote": "{:d}",
            "Ingresso ($)": "{:.2f}",
            "Attuale ($)": "{:.2f}",
            "Peso (%)": "{:.2f}%",
            col_val_label: "{:,.0f}",
            "Rendimento %": "{:+.2f}%",
            col_rend_label: "{:+,.0f}"
        }).map(color_pnl, subset=[c for c in ['Rendimento %', col_rend_label] if c in df_op_eq.columns]).map(style_stato, subset=[c for c in ['Stato'] if c in df_op_eq.columns])

        st.dataframe(df_eq_styled, use_container_width=True, hide_index=True)
    else:
        st.info("Nessuna azione in portafoglio. In attesa del ricalcolo di fine mese.")

    st.write("")
    with st.expander("Radar Rotazione — basket azionario in arrivo (bassa volatilità, trimestrale)"):
        st_html(f"""
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 14px; margin-bottom: 15px; font-size: 13px; line-height: 1.5;">
            I titoli già in portafoglio sono contrassegnati come <strong>IN PORTAFOGLIO</strong>, i nuovi candidati come <strong style="color:{ACCENT};">NUOVO</strong> — subentrano alla prossima rotazione trimestrale se il segnale macro di classe è attivo. Bitcoin non compare qui: è un asset singolo (nessuna rotazione), il suo stato è nel cockpit sopra e nella sua card in portafoglio.
        </div>
        """)

        held_tickers = set(open_pos_raw.keys())

        def style_radar_stato(val):
            if "NUOVO" in str(val):
                return f'color: {ACCENT}; font-weight: 700; text-align: center;'
            return 'text-align: center; opacity: 0.4;'

        if alloc.get("Equities", 0) > 0:
            top20 = data.get("top20", [])
            if top20:
                df_radar_eq = pd.DataFrame(top20)
                df_radar_eq = df_radar_eq.rename(columns={"Ticker": "Titolo", "Prezzo": "Prezzo ($)"})
                df_radar_eq["Pos"] = list(range(1, len(df_radar_eq) + 1))
                df_radar_eq["Stato"] = ["IN PORTAFOGLIO" if tkr in held_tickers else "NUOVO" for tkr in df_radar_eq["Titolo"]]
                cols = ["Pos", "Titolo", "Stato", "Prezzo ($)", "Volatilita' Ann. (%)"]
                df_radar_eq = df_radar_eq[[c for c in cols if c in df_radar_eq.columns]]

                fmt = {"Prezzo ($)": "{:.2f}"}
                if "Volatilita' Ann. (%)" in df_radar_eq.columns:
                    fmt["Volatilita' Ann. (%)"] = "{:.1f}%"
                st.dataframe(
                    df_radar_eq.style.format(fmt).map(
                        style_radar_stato, subset=['Stato'] if 'Stato' in df_radar_eq.columns else None
                    ),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("Nessun dato basket disponibile.")
        else:
            st.warning("Classe Azionario in pausa (segnale sotto la media a 40 settimane).")


# ==============================================================================
# TAB 2: METRICHE (EQUITY CURVE, DRAWDOWN, KPI, STORICO)
# ==============================================================================
with tab_perf:
    st_html(f"""
    <div style="background: rgba(59, 130, 246, 0.06); border: 1px solid rgba(59, 130, 246, 0.22); border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
        <div>
            <span style="font-size: 13px; font-weight: 700; color: {ACCENT};">SIMULAZIONE QUANTITATIVA & TRACK RECORD (Feb 2024 – Ago 2026)</span>
            <div style="font-size: 11px; opacity: 0.65; margin-top: 2px;">Serie storica a regole fisse deterministiche su dati storici di mercato · Reinvestimento composto</div>
        </div>
        <span style="background: rgba(59, 130, 246, 0.12); color: {ACCENT}; font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 6px; font-family: 'JetBrains Mono', monospace;">BASE 100 · BACKTEST OUT-OF-SAMPLE</span>
    </div>
    """)

    selected_range = st.segmented_control(
        "Periodo",
        options=["1M", "3M", "6M", "1A", "Tutto"],
        default="6M",
        label_visibility="collapsed",
        key="chart_range_ctrl"
    )
    if not selected_range:
        selected_range = "6M"

    @st.cache_data(ttl=3600)
    def load_benchmark():
        try:
            url = "https://query2.finance.yahoo.com/v8/finance/chart/SPY?range=2y&interval=1d"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            res = json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
            data_spy = res['chart']['result'][0]
            timestamps = pd.to_datetime(data_spy['timestamp'], unit='s')
            quote = data_spy['indicators']['quote'][0]
            df_b = pd.DataFrame({
                'open': quote['open'],
                'high': quote['high'],
                'low': quote['low'],
                'close': quote['close']
            }, index=timestamps).ffill().dropna()
            return df_b
        except Exception:
            return pd.DataFrame()

    df_spy = load_benchmark()
    eq_curve = load_equity()

    total_ret_pct = 0.0
    cagr_pct = 0.0
    max_dd = 0.0

    if eq_curve and "history" in eq_curve and len(eq_curve["history"]) > 0:
        df_eq = pd.DataFrame(eq_curve["history"])
        df_eq['date'] = pd.to_datetime(df_eq['date'])
        df_eq = df_eq.set_index('date')

        if 'open' not in df_eq.columns or df_eq['open'].isna().all():
            df_eq['open'] = df_eq['value'].shift(1).fillna(df_eq['value'].iloc[0])
            df_eq['high'] = df_eq[['open', 'value']].max(axis=1)
            df_eq['low'] = df_eq[['open', 'value']].min(axis=1)
            df_eq['close'] = df_eq['value']

        df_eq['roll_max'] = df_eq['close'].cummax()
        df_eq['drawdown'] = (df_eq['close'] - df_eq['roll_max']) / df_eq['roll_max'] * 100
        max_dd = df_eq['drawdown'].min()

        initial_val = df_eq['open'].iloc[0]
        final_val = df_eq['close'].iloc[-1]
        total_ret_pct = ((final_val / initial_val) - 1.0) * 100

        years_elapsed = (df_eq.index[-1] - df_eq.index[0]).days / 365.25
        if years_elapsed > 0 and initial_val > 0 and final_val > 0:
            cagr_pct = ((final_val / initial_val) ** (1.0 / years_elapsed) - 1.0) * 100

        # Normalizzazione Base 100
        base_val = initial_val if initial_val > 0 else 100000.0
        df_eq['norm_open'] = (df_eq['open'] / base_val) * 100
        df_eq['norm_high'] = (df_eq['high'] / base_val) * 100
        df_eq['norm_low'] = (df_eq['low'] / base_val) * 100
        df_eq['norm_close'] = (df_eq['close'] / base_val) * 100

        # Aggregazione settimanale (W-FRI) per la curva equity
        if len(df_eq) >= 5:
            df_agg = df_eq.resample('W-FRI').agg({
                'norm_open': 'first',
                'norm_high': 'max',
                'norm_low': 'min',
                'norm_close': 'last',
                'close': 'last'
            }).dropna()
            df_agg['norm_high'] = df_agg[['norm_open', 'norm_close', 'norm_high']].max(axis=1)
            df_agg['norm_low'] = df_agg[['norm_open', 'norm_close', 'norm_low']].min(axis=1)
        else:
            df_agg = df_eq

        # Range filter
        last_dt = df_agg.index[-1]
        if selected_range == "1M":
            start_dt = last_dt - pd.DateOffset(months=1)
        elif selected_range == "3M":
            start_dt = last_dt - pd.DateOffset(months=3)
        elif selected_range == "6M":
            start_dt = last_dt - pd.DateOffset(months=6)
        elif selected_range == "1A":
            start_dt = last_dt - pd.DateOffset(years=1)
        else:  # "Tutto"
            start_dt = df_agg.index[0]

        df_plot = df_agg[df_agg.index >= start_dt].copy()

        IT_MONTHS = {1: 'Gen', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'Mag', 6: 'Giu', 7: 'Lug', 8: 'Ago', 9: 'Set', 10: 'Ott', 11: 'Nov', 12: 'Dic'}

        ticks = []
        tick_labels = []
        if not df_plot.empty:
            start_d = df_plot.index[0]
            end_d = df_plot.index[-1]
            total_days = (end_d - start_d).days
            all_days = pd.date_range(start_d, end_d, freq='D')

            if total_days <= 45:
                ticks = [all_days[i] for i in range(0, len(all_days), 7)]
                tick_labels = [f"{d.day} {IT_MONTHS[d.month]}" for d in ticks]
            elif total_days <= 120:
                ticks = [d for d in all_days if d.day in [1, 15]]
                tick_labels = [f"{d.day:02d} {IT_MONTHS[d.month]}" for d in ticks]
            elif total_days <= 450:
                ticks = [d for d in all_days if d.day == 1]
                tick_labels = [f"{IT_MONTHS[d.month]} '{d.strftime('%y')}" if (d.month in [1, 7] or (len(ticks) > 0 and d == ticks[0])) else IT_MONTHS[d.month] for d in ticks]
            else:
                ticks = [d for d in all_days if d.day == 1 and d.month in [1, 4, 7, 10]]
                tick_labels = [f"{IT_MONTHS[d.month]} '{d.strftime('%y')}" for d in ticks]

        it_dates_str = [f"{d.day:02d} {IT_MONTHS[d.month]} {d.year}" for d in df_plot.index]

        fig = go.Figure()

        # 1. Curva equity Apex — area/linea (piu' convenzionale di una candela per
        # un NAV multi-asset ribilanciato, che non ha un vero OHLC intra-periodo).
        fig.add_trace(go.Scatter(
            x=df_plot.index,
            y=df_plot['norm_close'],
            mode='lines',
            name='Strategia Apex',
            line=dict(color=ACCENT, width=2),
            fill='tozeroy',
            fillcolor='rgba(59, 130, 246, 0.10)',
            text=it_dates_str,
            hovertemplate="<b>%{text}</b><br>Base 100: %{y:.2f}<extra></extra>"
        ))

        # 2. Benchmark S&P 500 (linea di riferimento settimanale, quieta)
        if not df_spy.empty:
            start_date = df_plot.index[0]
            df_spy_aligned = df_spy[df_spy.index >= start_date].copy()
            if not df_spy_aligned.empty:
                first_spy = df_spy_aligned['close'].iloc[0]
                df_spy_plot = df_spy_aligned['close'].resample('W-FRI').last().dropna() if len(df_spy_aligned) >= 5 else df_spy_aligned['close']
                df_spy_norm = (df_spy_plot / first_spy) * 100

                spy_it_dates = [f"{d.day:02d} {IT_MONTHS[d.month]} {d.year}" for d in df_spy_plot.index]
                fig.add_trace(go.Scatter(
                    x=df_spy_plot.index,
                    y=df_spy_norm,
                    text=spy_it_dates,
                    hovertemplate="<b>%{text}</b><br>S&P 500: %{y:.2f}<extra></extra>",
                    mode='lines',
                    name="S&P 500 Benchmark",
                    line=dict(color='#6B7280', width=1.5, dash='dot'),
                ))

        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(
                showgrid=False,
                tickfont=dict(size=11),
                tickmode='array' if len(ticks) > 0 else 'auto',
                tickvals=ticks if len(ticks) > 0 else None,
                ticktext=tick_labels if len(tick_labels) > 0 else None
            ),
            yaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.08)', tickfont=dict(size=11), title="Base 100"),
            margin=dict(l=0, r=0, t=10, b=0),
            height=380,
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor='rgba(0,0,0,0)')
        )
        st.plotly_chart(fig, use_container_width=True)

        # 3. Underwater chart — drawdown dal massimo storico nel tempo (risoluzione
        # giornaliera per non attenuare la vera profondità intra-settimanale).
        st.caption("Drawdown dal massimo storico")
        df_underwater = df_eq[(df_eq.index >= df_plot.index[0]) & (df_eq.index <= df_plot.index[-1])]
        fig_dd = go.Figure()
        fig_dd.add_trace(go.Scatter(
            x=df_underwater.index, y=df_underwater['drawdown'],
            fill='tozeroy', mode='lines',
            line=dict(color=NEG, width=1.2),
            fillcolor='rgba(239, 68, 68, 0.16)',
            hovertemplate="%{x|%d %b %Y}<br>Drawdown: %{y:.2f}%<extra></extra>",
            name="Drawdown"
        ))
        fig_dd.update_layout(
            template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(showgrid=False, tickfont=dict(size=10)),
            yaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.06)', tickfont=dict(size=10), ticksuffix="%"),
            margin=dict(l=0, r=0, t=4, b=0), height=110, showlegend=False
        )
        st.plotly_chart(fig_dd, use_container_width=True)
    else:
        st.info("In attesa del file di tracciamento storico.")

    st.write("")

    # KPI cards — superficie neutra uniforme, colore solo dove il segno conta.
    if pf:
        hist = pf.get("trade_history", [])
        wins = [t for t in hist if t.get("profit_pct", 0) > 0]
        losses = [t for t in hist if t.get("profit_pct", 0) <= 0]

        win_rate = (len(wins) / len(hist) * 100) if hist else 0.0
        avg_win = sum(t["profit_pct"] for t in wins) / len(wins) if wins else 0.0
        avg_loss = sum(t["profit_pct"] for t in losses) / len(losses) if losses else 0.0
        gross_profit = sum(t["profit_pct"] for t in wins)
        gross_loss = abs(sum(t["profit_pct"] for t in losses))

        payoff_ratio = avg_win / abs(avg_loss) if avg_loss != 0 else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss != 0 else 0.0

        def make_kpi_card(title, value, subtext, badge_text=None, badge_color=None, val_color=None):
            badge_html = ""
            if badge_text:
                bcol = badge_color or "rgba(128,128,128,0.18)"
                badge_html = f'<span style="background:{bcol}; color:#F3F4F6; font-size:10px; font-weight:700; padding:2px 7px; border-radius:4px; font-family:\'JetBrains Mono\',monospace;">{badge_text}</span>'
            return f"""
            <div style="flex: 1 1 175px; min-width: 155px; background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 11px 14px; display: flex; flex-direction: column; justify-content: space-between;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                    <span style="font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.4px; color: {MUTED};">{title}</span>
                    {badge_html}
                </div>
                <div style="font-size: 21px; font-weight: 800; color: {val_color or 'inherit'}; font-family: 'JetBrains Mono', monospace; margin: 2px 0;">
                    {value}
                </div>
                <div style="opacity: 0.6; font-size: 10.5px; margin-top: 2px;">{subtext}</div>
            </div>
            """

        # Stima netto teorica: 26% (aliquota flat italiana) solo sulla quota di
        # guadagno, come se l'intera posizione venisse realizzata oggi. Le
        # perdite non generano beneficio fiscale in questa stima semplificata
        # (non modella riporto perdite 4 anni art. 68 TUIR, vedi APEX_V2_SPEC.md §8.9/§10).
        net_ret_pct_est = total_ret_pct * (1.0 - 0.26) if total_ret_pct > 0 else total_ret_pct

        kpi_ret = make_kpi_card(
            "Rendimento Lordo", f"{total_ret_pct:+.2f}%",
            f"Netto stimato (26%, se realizzato oggi): {net_ret_pct_est:+.2f}%",
            val_color=(POS if total_ret_pct >= 0 else NEG)
        )
        kpi_cagr = make_kpi_card(
            "CAGR Annualizzato", f"{cagr_pct:+.2f}%", "Rendimento lordo composto annuo",
            val_color=(POS if cagr_pct >= 0 else NEG)
        )
        kpi_win = make_kpi_card(
            "Win Rate", f"{win_rate:.1f}%", f"{len(wins)} vincenti su {len(hist)}",
            badge_text=f"{len(wins)}/{len(hist)}"
        )
        kpi_pf = make_kpi_card(
            "Profit Factor", f"{profit_factor:.2f}", "Profitti lordi / perdite",
            badge_text=("ECCELLENTE" if profit_factor >= 1.5 else "STABILE"),
            badge_color=("#065F46" if profit_factor >= 1.5 else "#374151")
        )
        kpi_po = make_kpi_card(
            "Payoff Ratio", f"{payoff_ratio:.2f}x", "Vincita media / perdita media",
            badge_text=("ASIMMETRIA" if payoff_ratio >= 2.0 else "EQUILIBRATO")
        )
        kpi_dd = make_kpi_card(
            "Max Drawdown", f"{max_dd:.2f}%", "Massima perdita storica",
            badge_text=("PROTETTO" if max_dd > -15 else "ATTENZIONE"),
            badge_color=("#374151" if max_dd > -15 else "#7F1D1D")
        )

        st_html(f'<div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px;">{kpi_ret}{kpi_cagr}{kpi_win}{kpi_pf}{kpi_po}{kpi_dd}</div>')

        if hist:
            p_list = [t.get("profit_pct", 0.0) for t in hist]
            max_val = max(p_list)
            min_val = min(p_list)
            max_idx = p_list.index(max_val)
            min_idx = p_list.index(min_val)
            best_trade_t = hist[max_idx].get("ticker", "-")
            best_trade_p = hist[max_idx].get("profit_pct", 0.0)
            worst_trade_t = hist[min_idx].get("ticker", "-")
            worst_trade_p = hist[min_idx].get("profit_pct", 0.0)

            durations = []
            for t in hist:
                try:
                    d_in = datetime.datetime.strptime(str(t.get("entry_date", "")), "%Y-%m-%d")
                    d_out = datetime.datetime.strptime(str(t.get("exit_date", "")), "%Y-%m-%d")
                    durations.append(max(1, (d_out - d_in).days))
                except Exception:
                    pass
            avg_days_val = int(round(sum(durations) / len(durations))) if durations else 0

            st_html(f"""
            <div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 24px; font-size: 12.5px;">
                <div style="flex: 1 1 200px; background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 9px 14px; display: flex; justify-content: space-between; align-items: center;">
                    <span style="opacity: 0.75; color: {MUTED};">Miglior Trade</span>
                    <span style="font-weight: 700; color: {POS}; font-family: 'JetBrains Mono', monospace;">{best_trade_t} ({best_trade_p:+.2f}%)</span>
                </div>
                <div style="flex: 1 1 200px; background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 9px 14px; display: flex; justify-content: space-between; align-items: center;">
                    <span style="opacity: 0.75; color: {MUTED};">Peggior Trade</span>
                    <span style="font-weight: 700; color: {NEG}; font-family: 'JetBrains Mono', monospace;">{worst_trade_t} ({worst_trade_p:+.2f}%)</span>
                </div>
                <div style="flex: 1 1 200px; background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 9px 14px; display: flex; justify-content: space-between; align-items: center;">
                    <span style="opacity: 0.75; color: {MUTED};">Durata Media Trade</span>
                    <span style="font-weight: 700; font-family: 'JetBrains Mono', monospace;">{avg_days_val} giorni</span>
                </div>
            </div>
            """)

            st_html('<div style="font-size: 15px; font-weight: 700; letter-spacing: -0.2px; margin-bottom: 8px;">Registro Operazioni Chiuse</div>')

            df_hist = pd.DataFrame(hist).sort_values("exit_date", ascending=False)

            def calc_duration(r):
                try:
                    d_in = datetime.datetime.strptime(str(r.get("entry_date", "")), "%Y-%m-%d")
                    d_out = datetime.datetime.strptime(str(r.get("exit_date", "")), "%Y-%m-%d")
                    return f"{max(1, (d_out - d_in).days)}g"
                except Exception:
                    return "-"

            df_hist["Durata"] = df_hist.apply(calc_duration, axis=1)

            def color_trade_pnl(val):
                if isinstance(val, (int, float)):
                    color = POS if val > 0 else NEG if val < 0 else MUTED
                    return f'color: {color}; font-weight: 700;'
                return ''

            df_hist = df_hist.rename(columns={
                "ticker": "Titolo",
                "entry_date": "Data Ingresso",
                "exit_date": "Data Uscita",
                "entry_price": "Prezzo Ingresso",
                "exit_price": "Prezzo Uscita",
                "profit_pct": "Rendimento %",
                "reason": "Motivazione"
            })

            cols_hist = ["Titolo", "Data Ingresso", "Data Uscita", "Durata", "Prezzo Ingresso", "Prezzo Uscita", "Rendimento %", "Motivazione"]
            df_hist = df_hist[[c for c in cols_hist if c in df_hist.columns]]

            # Search & Filter Controls
            c_srch, c_flt = st.columns([2, 1])
            with c_srch:
                search_t = st.text_input("Cerca Ticker", placeholder="Cerca per ticker (es. NVDA, AAPL, BTC...)", label_visibility="collapsed")
            with c_flt:
                reason_options = ["Tutte le Motivazioni"] + sorted(df_hist["Motivazione"].dropna().unique().tolist()) if "Motivazione" in df_hist.columns else ["Tutte le Motivazioni"]
                flt_reason = st.selectbox("Filtro Uscita", reason_options, label_visibility="collapsed")

            if search_t:
                df_hist = df_hist[df_hist["Titolo"].str.contains(search_t.strip().upper(), na=False)]
            if flt_reason != "Tutte le Motivazioni":
                df_hist = df_hist[df_hist["Motivazione"] == flt_reason]

            st.dataframe(
                df_hist.style.format({
                    "Prezzo Ingresso": format_price,
                    "Prezzo Uscita": format_price,
                    "Rendimento %": "{:+.2f}%"
                }).map(color_trade_pnl, subset=['Rendimento %'] if 'Rendimento %' in df_hist.columns else None),
                use_container_width=True,
                hide_index=True
            )
            st.caption("**Trasparenza Metodologica:** Lo storico delle operazioni chiuse e la curva equity Base 100 documentano la simulazione quantitativa deterministica su dati storici di mercato (out-of-sample) a regole fisse. Le posizioni aperte e i segnali operativi decorrono dal forward-tracking dell'Apex Engine.")
        else:
            st.info("Nessuna operazione chiusa registrata.")


# ==============================================================================
# TAB 3: GUIDA & STRATEGIA
# ==============================================================================
with tab_guide:
    st_html(f'''
    <div style="background: rgba(0, 136, 204, 0.06); border: 1px solid rgba(0, 136, 204, 0.25); border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
        <div>
            <div style="font-weight: 700; font-size: 14px; color: #0088cc; margin-bottom: 2px;">Canale Ufficiale Notifiche Telegram</div>
            <div style="font-size: 12.5px; opacity: 0.8;">Ricevi in tempo reale i cambi di mercato, gli ordini di rotazione e i livelli di protezione aggiornati.</div>
        </div>
        <a href="https://t.me/apex_multiasset" target="_blank" style="background: #0088cc; color: #ffffff; text-decoration: none; padding: 6px 14px; border-radius: 6px; font-size: 12.5px; font-weight: 700;">
            Unisciti al canale →
        </a>
    </div>
    ''')

    st_html('<div style="font-size: 15px; font-weight: 700; letter-spacing: -0.2px; margin-bottom: 10px;">Regole Operative</div>')
    st_html(f"""
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 20px;">
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px;">
            <div style="font-weight: 700; font-size: 13.5px; margin-bottom: 6px;">1. Controllo mensile</div>
            <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5;">L'ultimo venerdì del mese l'app vende i titoli deboli e li sostituisce con i nuovi primi in classifica per mantenere il portafoglio forte.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px;">
            <div style="font-weight: 700; font-size: 13.5px; margin-bottom: 6px;">2. Controllo settimanale</div>
            <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5;">Ogni venerdì aggiorna i livelli di protezione. Se in settimana sono state chiuse delle posizioni, queste vengono sostituite con nuovi ingressi.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px;">
            <div style="font-weight: 700; font-size: 13.5px; margin-bottom: 6px;">3. Cambi di Mercato</div>
            <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5;">Se l'app spegne un settore, viene liquidato interamente il venerdì. Se il prezzo crolla sotto il livello di protezione, l'app chiude l'investimento.</div>
        </div>
    </div>
    """)

    st.divider()

    st_html('<div style="font-size: 15px; font-weight: 700; letter-spacing: -0.2px; margin-bottom: 12px;">Documentazione Strategica</div>')
    st_html(f'''
    <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px; margin-bottom: 14px;">
        <div style="font-weight: 700; font-size: 13.5px; margin-bottom: 4px;">Obiettivo Primario</div>
        <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5;">Generare alpha reale (indipendente dal semplice beta di mercato) con bassa frequenza di intervento (rotazione mensile/trimestrale, mai giornaliera) e alta efficienza fiscale, eliminando ogni componente emotiva attraverso l'allocazione dinamica quantitativa.</div>
    </div>

    <div style="font-size: 12.5px; font-weight: 700; color: {MUTED}; text-transform: uppercase; letter-spacing: 0.5px; margin: 16px 0 8px 0;">Il Sistema — Segnale di Timing per Classe</div>
    <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5; margin-bottom: 10px;">Ogni classe di attivo (Azioni, Obbligazioni, Oro, Bitcoin) viene attivata o disattivata in base al proprio trend di lungo periodo — non esiste più un tetto percentuale fisso per classe:</div>

    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; margin-bottom: 14px;">
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-weight: 700; font-size: 13px;">Azioni</span>
                <span style="background: rgba(128,128,128,0.15); color: {MUTED}; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: 'JetBrains Mono', monospace;">BASKET BASSA VOL</span>
            </div>
            <div style="font-size: 12px; opacity: 0.8; line-height: 1.4;">Attiva se SPY è sopra la media mobile a 40 settimane (con isteresi adattiva).</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-weight: 700; font-size: 13px;">Bitcoin</span>
                <span style="background: rgba(128,128,128,0.15); color: {MUTED}; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: 'JetBrains Mono', monospace;">SOLO BTC-USD</span>
            </div>
            <div style="font-size: 12px; opacity: 0.8; line-height: 1.4;">Nessuna rotazione altcoin (testata e respinta: nessun edge aggiuntivo). Stesso segnale di timing dell'azionario.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-weight: 700; font-size: 13px;">Oro</span>
                <span style="background: rgba(128,128,128,0.15); color: {MUTED}; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: 'JetBrains Mono', monospace;">SEGNALE DI TREND</span>
            </div>
            <div style="font-size: 12px; opacity: 0.8; line-height: 1.4;">Protezione contro inflazione e incertezza, attivata dallo stesso meccanismo di timing.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-weight: 700; font-size: 13px;">Obbligazioni</span>
                <span style="background: rgba(128,128,128,0.15); color: {MUTED}; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: 'JetBrains Mono', monospace;">SEGNALE DI TREND</span>
            </div>
            <div style="font-size: 12px; opacity: 0.8; line-height: 1.4;">Titoli di stato, allocati quando il proprio trend è favorevole.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-weight: 700; font-size: 13px;">Monetario</span>
                <span style="background: rgba(128,128,128,0.15); color: {MUTED}; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: 'JetBrains Mono', monospace;">RESIDUO</span>
            </div>
            <div style="font-size: 12px; opacity: 0.8; line-height: 1.4;">Rifugio sicuro e liquidità per le classi in pausa o per il target di volatilità.</div>
        </div>
    </div>

    <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px; margin-bottom: 10px;">
        <div style="font-weight: 700; font-size: 13.5px; margin-bottom: 4px;">Selezione del Basket Azionario</div>
        <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5;">Ogni trimestre, tra i titoli dell'universo tracciato il sistema seleziona i 15 con la volatilità realizzata più bassa (26 settimane), non i più momentum-forti: l'obiettivo è mantenere il carattere fiscale di "redditi diversi" (azioni singole, compensabili) con un profilo di rischio stabile.</div>
    </div>

    <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px; margin-bottom: 18px;">
        <div style="font-weight: 700; font-size: 13.5px; margin-bottom: 4px;">Vol-Targeting di Portafoglio</div>
        <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5;">L'esposizione aggregata alle classi rischiose viene scalata mensilmente per centrare una volatilità target del 13% annualizzato (finestra 12 settimane) — non esiste uno stop-loss per singola posizione: testato esplicitamente e respinto perché riduce l'edge senza migliorare il rischio aggiustato per rendimento (dettagli in APEX_V2_SPEC.md §4).</div>
    </div>
    ''')

    st.divider()

    st_html(f'''
    <div style="background: rgba(239, 68, 68, 0.04); border: 1px solid rgba(239, 68, 68, 0.18); border-radius: 8px; padding: 12px 14px; font-size: 11.5px; opacity: 0.8; line-height: 1.5;">
        <strong>Note Legali ed Esclusione di Responsabilità:</strong><br>
        Questa piattaforma ha scopo puramente informativo e di analisi statistica. Non fornisce consulenza finanziaria né raccomandazioni personalizzate ai sensi delle normative vigenti.<br>
        I rendimenti passati non garantiscono risultati futuri. Ogni investimento comporta il rischio di perdita del capitale ed è effettuato sotto la totale ed esclusiva responsabilità dell'utente. L'autore declina qualsiasi responsabilità per eventuali perdite derivanti dall'uso di questi dati.
    </div>
    ''')
