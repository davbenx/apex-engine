import base64
import datetime
import json
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


def monogram(text, active=True, size=26):
    color = POS if active else NEUTRAL_DOT
    return f'''<span style="display:inline-flex; align-items:center; justify-content:center; width:{size}px; height:{size}px; border-radius:6px; border:1px solid {color}; color:{color}; font-family:'JetBrains Mono',monospace; font-weight:700; font-size:10px; letter-spacing:-0.3px; flex-shrink:0;">{text}</span>'''


# Peso di base massimo per classe attiva in apex_v2_engine.py
# (base_weight = 0.25, poi scalato dal fattore di vol-target che non supera
# mai 1.0 — quindi 25% e' davvero il tetto per singola classe, non solo una
# soglia arbitraria). Vedi APEX_V2_SPEC.md §20.
V2_MAX_BASE_ALLOC_PCT = 25.0


def ring_badge(mono_text, fill_frac, size=30):
    """Disco CSS a settore circolare (conic-gradient, un solo elemento,
    nessuna sovrapposizione/posizionamento assoluto): il riempimento verde è
    la quota del 25% di peso massimo per classe attualmente in uso. A
    riempimento zero la classe è in pausa; pieno = al tetto consentito dal
    vol-target (fattore di scala = 1.0, nessuna riduzione per rischio)."""
    frac = max(0.0, min(1.0, fill_frac))
    deg = frac * 360.0
    gradient = f"conic-gradient({POS} {deg:.1f}deg, #374151 {deg:.1f}deg 360deg)"
    return f'''<div style="width:{size}px; height:{size}px; min-width:{size}px; border-radius:50%; background:{gradient}; box-sizing:border-box; display:flex; align-items:center; justify-content:center; flex-shrink:0;">
        <span style="font-family:'JetBrains Mono',monospace; font-size:8.5px; font-weight:800; color:#F9FAFB; line-height:1;">{mono_text}</span>
    </div>'''


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


MESI_IT = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]


def format_date_italian(d_str):
    try:
        dt = datetime.datetime.strptime(d_str, "%Y-%m-%d")
        return f"{dt.day} {MESI_IT[dt.month-1]} {dt.year}"
    except Exception:
        return d_str


def parse_sync_timestamp(ts_str):
    """Il backend genera il timestamp in inglese (strftime %b, locale server)."""
    try:
        return datetime.datetime.strptime(ts_str, "%d %b %Y, %H:%M (UTC)")
    except Exception:
        return None


def format_sync_timestamp_italian(ts_str):
    dt = parse_sync_timestamp(ts_str)
    if not dt:
        return ts_str
    return f"{dt.day} {MESI_IT[dt.month-1]} {dt.year}, {dt.strftime('%H:%M')} UTC"


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
last_update_display = format_sync_timestamp_italian(last_update)

# "Motore Attivo" e' un segnale reale, non decorativo: confronta l'eta' del
# timestamp di sync con la cadenza attesa (Lun-Ven). Oltre 4 giorni (copre un
# weekend + un giorno di margine) senza aggiornamento -> stato di ritardo.
_sync_dt = parse_sync_timestamp(last_update)
_days_stale = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - _sync_dt).days if _sync_dt else None
engine_is_fresh = _days_stale is None or _days_stale <= 4
engine_status_text = "Motore Attivo" if engine_is_fresh else f"Ricalcolo in ritardo ({_days_stale}g)"
engine_status_color = POS if engine_is_fresh else NEG

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
                <span style="width:6px; height:6px; border-radius:50%; background:{engine_status_color}; display:inline-block;"></span> {engine_status_text}
            </span>
        </div>
        <div style="opacity: 0.65; font-size: 11.5px; line-height: 1.4;">
            <strong>Aggiornato:</strong> {last_update_display}<br>
            <strong>Prezzi e NAV:</strong> aggiornati Lun-Ven · <strong>Decisioni:</strong> ultimo venerdì del mese
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
    """Il disco si riempie in proporzione a alloc_pct/25% (il vero tetto per
    classe, vedi ring_badge) — niente percentuale scritta: il numero esatto
    resta nella tabella posizioni sotto, qui e' un indicatore visivo, non
    l'unica fonte del dato (vedi APEX_V2_SPEC.md §20)."""
    if is_cash:
        state_text = "Riserva di liquidità"
    else:
        fmt_d = format_date_italian(since_date) if since_date and since_date != "-" else ""
        state_text = f"{'Attiva' if is_active else 'In pausa'}{(' dal ' + fmt_d) if fmt_d else ''}"

    fill_frac = 0.0 if is_cash else (alloc_pct / V2_MAX_BASE_ALLOC_PCT)
    ring = ring_badge(mono_text, fill_frac)
    return f"""
    <div style="display:flex; align-items:center; gap:9px; background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 7px 12px 7px 8px; min-width: 150px;">
        {ring}
        <div style="line-height:1.3;">
            <div style="font-size:11.5px; font-weight:700; letter-spacing:0.1px;">{label}</div>
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
    # cosi' resta la prima cosa visibile aprendo la tab. Azionario e' un
    # riquadro con 15 figli (i singoli titoli): "maxdepth=1" mostra solo il
    # livello classi all'apertura (nessuna sotto-cella minuscola), un clic su
    # "AZIONARIO" zooma nativamente sui 15 titoli a piena area — niente
    # secondo grafico separato, e' lo stesso treemap che si apre.
    tm_ids, tm_labels, tm_parents, tm_values, tm_colors, tm_text, tm_hover = [], [], [], [], [], [], []

    if op_eq:
        eq_weight_total = sum(r.get("Peso (%)", 0.0) for r in op_eq)
        eq_pnl_weighted = (sum(r["Rendimento %"] * r.get("Peso (%)", 0.0) for r in op_eq) / eq_weight_total) if eq_weight_total > 0 else 0.0
        tm_ids.append("AZIONARIO"); tm_labels.append("AZIONARIO"); tm_parents.append("")
        tm_values.append(eq_weight_total); tm_colors.append(eq_pnl_weighted)
        tm_text.append(f"{eq_weight_total:.1f}% · {eq_pnl_weighted:+.2f}%")
        tm_hover.append(f"Azionario ({len(op_eq)} titoli) — clic per il dettaglio per titolo<br>{eq_weight_total:.1f}% del portafoglio · Rendimento medio ponderato: {eq_pnl_weighted:+.2f}%")
        for r in op_eq:
            tm_ids.append(f"AZ::{r['Titolo']}"); tm_labels.append(r["Titolo"]); tm_parents.append("AZIONARIO")
            tm_values.append(r.get("Peso (%)", 0.0)); tm_colors.append(r["Rendimento %"])
            tm_text.append(f"{r.get('Peso (%)', 0.0):.1f}% · {r['Rendimento %']:+.2f}%")
            tm_hover.append(f"{r['Titolo']} — {r.get('Peso (%)', 0.0):.1f}% del portafoglio<br>Rendimento: {r['Rendimento %']:+.2f}%")

    if op_cr:
        r = op_cr[0]
        tm_ids.append("BITCOIN"); tm_labels.append("BITCOIN"); tm_parents.append("")
        tm_values.append(r.get("Peso (%)", 0.0)); tm_colors.append(r["Rendimento %"])
        tm_text.append(f"{r.get('Peso (%)', 0.0):.1f}% · {r['Rendimento %']:+.2f}%")
        tm_hover.append(f"Bitcoin — {r.get('Peso (%)', 0.0):.1f}% del portafoglio<br>Rendimento: {r['Rendimento %']:+.2f}%")

    if alloc.get('Gold', 0) > 0:
        _gd = open_pos_raw.get("GLD")
        _g_pct = (((_gd.get("current_price", _gd.get("entry_price", 0.0)) / _gd["entry_price"]) - 1.0) * 100) if _gd and _gd.get("entry_price", 0) > 0 else 0.0
        tm_ids.append("ORO"); tm_labels.append("ORO"); tm_parents.append("")
        tm_values.append(alloc.get('Gold', 0)); tm_colors.append(_g_pct)
        tm_text.append(f"{alloc.get('Gold', 0):.1f}% · {_g_pct:+.2f}%")
        tm_hover.append(f"Oro — {alloc.get('Gold', 0):.1f}% del portafoglio<br>Rendimento: {_g_pct:+.2f}%")

    if alloc.get('Bonds', 0) > 0:
        _bd = open_pos_raw.get("IEF")
        _b_pct = (((_bd.get("current_price", _bd.get("entry_price", 0.0)) / _bd["entry_price"]) - 1.0) * 100) if _bd and _bd.get("entry_price", 0) > 0 else 0.0
        tm_ids.append("OBBLIGAZIONI"); tm_labels.append("OBBLIGAZIONI"); tm_parents.append("")
        tm_values.append(alloc.get('Bonds', 0)); tm_colors.append(_b_pct)
        tm_text.append(f"{alloc.get('Bonds', 0):.1f}% · {_b_pct:+.2f}%")
        tm_hover.append(f"Obbligazioni — {alloc.get('Bonds', 0):.1f}% del portafoglio<br>Rendimento: {_b_pct:+.2f}%")

    if alloc.get('Cash', 0) > 0:
        tm_ids.append("MONETARIO"); tm_labels.append("MONETARIO"); tm_parents.append("")
        tm_values.append(alloc.get('Cash', 0)); tm_colors.append(0.0)
        tm_text.append(f"{alloc.get('Cash', 0):.1f}%")
        tm_hover.append(f"Monetario — {alloc.get('Cash', 0):.1f}% del portafoglio (liquidità, nessun rendimento)")

    if tm_ids:
        fig_tm = go.Figure(go.Treemap(
            ids=tm_ids, labels=tm_labels, parents=tm_parents, values=tm_values,
            branchvalues="total",
            maxdepth=1,
            marker=dict(
                colors=tm_colors,
                colorscale=[[0, "#7F1D1D"], [0.5, "#374151"], [1, "#065F46"]],
                cmid=0,
                line=dict(width=1, color="rgba(128,128,128,0.35)")
            ),
            text=tm_text,
            hovertext=tm_hover,
            hoverinfo="text",
            textinfo="label+text",
            textfont=dict(color="#F3F4F6", family="'JetBrains Mono', monospace", size=13),
            pathbar=dict(visible=True, textfont=dict(size=11, family="Inter, sans-serif", color=MUTED)),
        ))
        fig_tm.update_layout(margin=dict(l=2, r=2, t=4, b=2), height=280, paper_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig_tm, use_container_width=True)
        if op_eq:
            st.caption('Clicca "AZIONARIO" per il dettaglio dei 15 titoli, clicca in alto per tornare alla vista d\'insieme.')

    st.write("")

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

    st.write("")

    # --- Tabella unica con tutte le posizioni di tutte le classi (azioni,
    # Bitcoin, Oro, Obbligazioni, Monetario) — il treemap sopra da' la vista
    # d'insieme con i numeri, questa e' l'elenco completo, sempre presente,
    # senza dover sommare card sparse per le classi non-azionarie.
    real_cash_usd = max(0.0, capitale - tot_invested_usd)
    cash_weight_pct = (real_cash_usd / capitale * 100) if capitale > 0 else 0.0

    def color_pnl(val):
        color = POS if val > 0 else NEG if val < 0 else MUTED
        return f'color: {color}; font-weight: 700;'

    def style_stato(val):
        if "NUOVO" in str(val):
            return f'color: {ACCENT}; font-weight: 700; text-align: center;'
        return 'text-align: center; opacity: 0.4;'

    col_val_label = f"Valore ({curr_sym})"
    col_rend_label = f"Rendimento ({curr_sym})"

    unified_rows = []
    for r in op_eq:
        unified_rows.append({
            "Classe": "Azionario", "Titolo": r["Titolo"], "Stato": r["Stato"],
            "Data Ingresso": r["Data Ingresso"],
            "Ingresso ($)": r["Ingresso ($)"], "Attuale ($)": r["Attuale ($)"],
            "Peso (%)": r["Peso (%)"], "Rendimento %": r["Rendimento %"],
        })
    if op_cr:
        r = op_cr[0]
        unified_rows.append({
            "Classe": "Bitcoin", "Titolo": r["Titolo"], "Stato": r["Stato"],
            "Data Ingresso": r["Data Ingresso"],
            "Ingresso ($)": r["Ingresso ($)"], "Attuale ($)": r["Attuale ($)"],
            "Peso (%)": r["Peso (%)"], "Rendimento %": r["Rendimento %"],
        })

    def _detail_row(classe, ticker, detail):
        return {
            "Classe": classe, "Titolo": ticker, "Stato": "NUOVO" if detail["days"] <= 7 else "",
            "Data Ingresso": f"{detail['entry_date']} ({detail['days']}g)",
            "Ingresso ($)": detail["entry_price"], "Attuale ($)": detail["current_price"],
            "Peso (%)": detail["weight_pct"], "Rendimento %": detail["pnl_pct"],
        }

    if gold_detail:
        unified_rows.append(_detail_row("Oro", "GLD", gold_detail))
    if bond_detail:
        unified_rows.append(_detail_row("Obbligazioni", "IEF", bond_detail))

    unified_rows.append({
        "Classe": "Monetario", "Titolo": "Liquidità", "Stato": "",
        "Data Ingresso": "—",
        "Ingresso ($)": float("nan"), "Attuale ($)": float("nan"),
        "Peso (%)": cash_weight_pct, "Rendimento %": float("nan"),
    })

    # Riga totale al posto della card "Rendimento Galleggiante" — stessa
    # informazione (P&L aggregato), calcolata dagli stessi dati della
    # tabella invece che in un riquadro separato sopra.
    unified_rows.append({
        "Classe": "TOTALE", "Titolo": "", "Stato": "",
        "Data Ingresso": "—",
        "Ingresso ($)": float("nan"), "Attuale ($)": float("nan"),
        "Peso (%)": 100.0, "Rendimento %": tot_pnl_pct,
    })

    def style_total_row(row):
        if row.get("Classe") == "TOTALE":
            return ['font-weight: 800; border-top: 2px solid rgba(128,128,128,0.3);'] * len(row)
        return [''] * len(row)

    show_details = st.toggle("Mostra dettagli esecuzione (quote, data ingresso, prezzi)", value=False)
    compact_cols = ["Classe", "Titolo", "Stato", "Peso (%)", col_val_label, "Rendimento %"]
    full_cols = ["Classe", "Titolo", "Stato", "Data Ingresso", "Quote", "Ingresso ($)", "Attuale ($)", "Peso (%)", col_val_label, "Rendimento %", col_rend_label]
    active_cols = full_cols if show_details else compact_cols

    st_html('<div style="font-size: 15px; font-weight: 700; letter-spacing: -0.2px; margin-bottom: 8px;">Tutte le posizioni</div>')

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

    df_pos_display = df_pos[[c for c in active_cols if c in df_pos.columns]]

    df_pos_styled = df_pos_display.style.format({
        "Ingresso ($)": "{:.2f}",
        "Attuale ($)": "{:.2f}",
        "Peso (%)": "{:.2f}%",
        col_val_label: "{:,.0f}",
        "Rendimento %": "{:+.2f}%",
        col_rend_label: "{:+,.0f}",
    }, na_rep="—").map(color_pnl, subset=[c for c in ['Rendimento %', col_rend_label] if c in df_pos_display.columns]).map(style_stato, subset=[c for c in ['Stato'] if c in df_pos_display.columns]).apply(style_total_row, axis=1)

    st.dataframe(df_pos_styled, use_container_width=True, hide_index=True)


# ==============================================================================
# TAB 2: METRICHE (EQUITY CURVE, DRAWDOWN, KPI, STORICO)
# ==============================================================================
with tab_perf:
    eq_curve = load_equity()

    # Intervallo calcolato dai dati reali, non un valore fisso in testo che
    # sarebbe rimasto scorretto ogni mese che passa.
    track_record_range_str = ""
    if eq_curve and "history" in eq_curve and len(eq_curve["history"]) > 0:
        _hist_dates = pd.to_datetime([h["date"] for h in eq_curve["history"]])
        _d0, _d1 = _hist_dates.min(), _hist_dates.max()
        track_record_range_str = f" ({MESI_IT[_d0.month-1]} {_d0.year} – {MESI_IT[_d1.month-1]} {_d1.year})"

    st_html(f"""
    <div style="background: rgba(59, 130, 246, 0.06); border: 1px solid rgba(59, 130, 246, 0.22); border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
        <div>
            <span style="font-size: 13px; font-weight: 700; color: {ACCENT};">SIMULAZIONE QUANTITATIVA & TRACK RECORD{track_record_range_str}</span>
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

        # Striscia unica invece di 9 card separate (6 KPI + 3 statistiche trade):
        # stesso principio gia' applicato al cockpit e alla tabella posizioni —
        # un solo contenitore con divisori interni, non tanti riquadri ripetuti.
        def kpi_item(title, value, subtext="", badge_text=None, badge_color=None, val_color=None, first=False):
            badge_html = ""
            if badge_text:
                bcol = badge_color or "rgba(128,128,128,0.18)"
                badge_html = f'<span style="background:{bcol}; color:#F3F4F6; font-size:9px; font-weight:700; padding:1px 6px; border-radius:4px; font-family:\'JetBrains Mono\',monospace; margin-left:6px;">{badge_text}</span>'
            border = "none" if first else f"1px solid {BORDER}"
            return f"""
            <div style="flex: 1 1 145px; padding: 6px 16px; border-left: {border};">
                <div style="font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; color: {MUTED}; white-space: nowrap;">{title}{badge_html}</div>
                <div style="font-size: 18px; font-weight: 800; color: {val_color or 'inherit'}; font-family: 'JetBrains Mono', monospace; margin: 2px 0;">{value}</div>
                <div style="opacity: 0.6; font-size: 10px;">{subtext}</div>
            </div>
            """

        # Stima netto teorica: 26% (aliquota flat italiana) solo sulla quota di
        # guadagno, come se l'intera posizione venisse realizzata oggi. Le
        # perdite non generano beneficio fiscale in questa stima semplificata
        # (non modella riporto perdite 4 anni art. 68 TUIR, vedi APEX_V2_SPEC.md §8.9/§10).
        net_ret_pct_est = total_ret_pct * (1.0 - 0.26) if total_ret_pct > 0 else total_ret_pct

        strip_items = [
            kpi_item("Rendimento Lordo", f"{total_ret_pct:+.2f}%",
                     f"Netto stimato: {net_ret_pct_est:+.2f}%",
                     val_color=(POS if total_ret_pct >= 0 else NEG), first=True),
            kpi_item("CAGR Annualizzato", f"{cagr_pct:+.2f}%", "Rendimento lordo composto annuo",
                     val_color=(POS if cagr_pct >= 0 else NEG)),
            kpi_item("Win Rate", f"{win_rate:.1f}%", f"{len(wins)} vincenti su {len(hist)}",
                     badge_text=f"{len(wins)}/{len(hist)}"),
            kpi_item("Profit Factor", f"{profit_factor:.2f}", "Profitti lordi / perdite",
                     badge_text=("ECCELLENTE" if profit_factor >= 1.5 else "STABILE"),
                     badge_color=("#065F46" if profit_factor >= 1.5 else "#374151")),
            kpi_item("Payoff Ratio", f"{payoff_ratio:.2f}x", "Vincita media / perdita media",
                     badge_text=("ASIMMETRIA" if payoff_ratio >= 2.0 else "EQUILIBRATO")),
            kpi_item("Max Drawdown", f"{max_dd:.2f}%", "Massima perdita storica",
                     badge_text=("PROTETTO" if max_dd > -15 else "ATTENZIONE"),
                     badge_color=("#374151" if max_dd > -15 else "#7F1D1D")),
        ]

        if hist:
            p_list = [t.get("profit_pct", 0.0) for t in hist]
            max_idx = p_list.index(max(p_list))
            min_idx = p_list.index(min(p_list))
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

            strip_items += [
                kpi_item("Miglior Trade", best_trade_t, f"{best_trade_p:+.2f}%", val_color=POS),
                kpi_item("Peggior Trade", worst_trade_t, f"{worst_trade_p:+.2f}%", val_color=NEG),
                kpi_item("Durata Media Trade", f"{avg_days_val}g", "giorni in posizione"),
            ]

        st_html(f'<div style="display: flex; flex-wrap: wrap; background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 4px 0; margin-bottom: 20px;">{"".join(strip_items)}</div>')

        if hist:
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
            <div style="font-size: 12.5px; opacity: 0.8;">Ricevi in tempo reale i cambi di allocazione e gli ordini di rotazione.</div>
        </div>
        <a href="https://t.me/apex_multiasset" target="_blank" style="background: #0088cc; color: #ffffff; text-decoration: none; padding: 6px 14px; border-radius: 6px; font-size: 12.5px; font-weight: 700;">
            Unisciti al canale →
        </a>
    </div>
    ''')

    st_html('<div style="font-size: 15px; font-weight: 700; letter-spacing: -0.2px; margin-bottom: 10px;">Cadenza Operativa</div>')
    st_html(f"""
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 20px;">
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px;">
            <div style="font-weight: 700; font-size: 13.5px; margin-bottom: 6px;">Ogni giorno (Lun-Ven)</div>
            <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5;">Prezzi e NAV vengono aggiornati. Nessuna decisione di trading in questa fase — solo osservazione.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px;">
            <div style="font-weight: 700; font-size: 13.5px; margin-bottom: 6px;">Ultimo venerdì del mese</div>
            <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5;">Il segnale macro di ogni classe viene ricontrollato (attiva/in pausa) e il peso complessivo viene riscalato per centrare il target di volatilità. Non esiste un controllo settimanale intermedio: le decisioni sono solo qui.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px;">
            <div style="font-weight: 700; font-size: 13.5px; margin-bottom: 6px;">Ultimo venerdì del trimestre</div>
            <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5;">In aggiunta al ribilanciamento mensile, il basket azionario viene rinnovato: i titoli con volatilità realizzata più alta escono, i nuovi primi in classifica entrano. Nessuno stop-loss per singola posizione: l'uscita avviene solo per rotazione o disattivazione della classe.</div>
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
            <div style="font-size: 12px; opacity: 0.8; line-height: 1.4;">Attiva se SPY è sopra le medie mobili a 40 E 20 settimane insieme (conferma multi-timeframe, isteresi adattiva sulla banda).</div>
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
        <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5;">Ogni trimestre, tra i titoli dell'universo tracciato il sistema seleziona i 15 con la volatilità realizzata più bassa (26 settimane), non i più momentum-forti: l'obiettivo è mantenere il carattere fiscale di "redditi diversi" (azioni singole, compensabili) con un profilo di rischio stabile. Massimo 2 titoli per settore, per non concentrare il basket su un solo comparto.</div>
    </div>

    <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px; margin-bottom: 18px;">
        <div style="font-weight: 700; font-size: 13.5px; margin-bottom: 4px;">Vol-Targeting di Portafoglio</div>
        <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5;">Ogni classe attiva parte da un peso di base uguale (25%), poi tutte le classi attive vengono scalate mensilmente dallo stesso fattore per centrare una volatilità target del 13% annualizzato (finestra 12 settimane) — non è un tetto per classe: se due classi attive mostrano lo stesso peso è perché partono dallo stesso 25% base e vengono scalate allo stesso modo, non per un limite massimo. Non esiste uno stop-loss per singola posizione: testato esplicitamente e respinto perché riduce l'edge senza migliorare il rischio aggiustato per rendimento (dettagli in APEX_V2_SPEC.md §3).</div>
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
