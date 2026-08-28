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
# HTML RENDERING HELPERS
# ==============================================================================
def st_html(html_str):
    """Renders raw HTML safely without Markdown parser indentation issues."""
    cleaned = "\n".join(line.strip() for line in html_str.strip().splitlines())
    try:
        st.html(cleaned)
    except AttributeError:
        st.markdown(cleaned, unsafe_allow_html=True)


def fill_slot(slot, html_str):
    """Riempie a posteriori un st.empty() riservato prima nel flusso — usato
    per il valore hero, che deve apparire visivamente PRIMA del controllo
    capitale ma puo' essere calcolato solo DOPO aver letto il widget."""
    cleaned = "\n".join(line.strip() for line in html_str.strip().splitlines())
    slot.markdown(cleaned, unsafe_allow_html=True)


# ==============================================================================
# THEME & GLOBAL STYLING
# ==============================================================================
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
</style>
""")


# ==============================================================================
# DESIGN TOKENS ("Apex Restyle" — istituzionale + consumer, palette calda)
# ==============================================================================
POS = "#3DDC97"                       # verde caldo — riservato al P&L positivo
NEG = "#EC657B"                       # rosa-corallo — riservato al P&L negativo / attenzione reale.
                                       # Spostato da #F2726A: a 38 gradi di distanza sulla ruota
                                       # cromatica da ACCENT (oro) erano troppo vicini per una
                                       # distinzione istantanea; ora a 52 gradi.
MUTED_DOT = "#5B534B"                 # segnale "in pausa" — non e' una notizia negativa
ACCENT = "#C9A44C"                    # oro tenue — unico accento di marca/interattivo
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


def section_title(text, top="26px", bottom="10px"):
    return f'<div style="font-family:{FRAUNCES}; font-size:16px; font-weight:600; letter-spacing:-0.1px; margin:{top} 0 {bottom};">{text}</div>'


def monogram(text, size=26):
    return f'''<span style="display:inline-flex; align-items:center; justify-content:center; width:{size}px; height:{size}px; border-radius:6px; border:1px solid {ACCENT}; color:{ACCENT}; font-family:{MONO}; font-weight:700; font-size:10px; letter-spacing:-0.3px; flex-shrink:0;">{text}</span>'''


# Peso di base massimo per classe attiva in apex_v2_engine.py (base_weight=0.25,
# poi scalato dal fattore di vol-target che non supera mai 1.0 — 25% e' il
# vero tetto per singola classe). Vedi APEX_V2_SPEC.md §20.
V2_MAX_BASE_ALLOC_PCT = 25.0


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
logo_tag = f'<img src="data:image/png;base64,{logo_b64}" style="height: 60px; width: auto; object-fit: contain;" />' if logo_b64 else monogram("AE", size=42)

col_title, col_meta = st.columns([3, 2])
with col_title:
    st_html(f"""
    <div style="display: flex; align-items: center; gap: 14px; padding: 6px 0;">
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; padding: 5px 9px; border-radius: 10px; display: flex; align-items: center; justify-content: center;">
            {logo_tag}
        </div>
        <div>
            <div style="font-family: {FRAUNCES}; font-size: 22px; font-weight: 600; letter-spacing: -0.4px; line-height: 1.2;">Apex Engine</div>
            <div style="font-size: 11px; font-weight: 600; opacity: 0.65; letter-spacing: 0.4px; text-transform: uppercase; margin-top: 1px;">
                Sistema Quantitativo Multi-Asset <span style="color: {ACCENT}; font-weight: 700;">v2.0</span>
            </div>
        </div>
    </div>
    """)

with col_meta:
    st_html(f"""
    <div style="text-align: right; padding-top: 10px;">
        <div style="font-size: 11px; color: {MUTED};">
            <span style="width:6px; height:6px; border-radius:50%; background:{engine_status_color}; display:inline-block; margin-right:5px;"></span>{engine_status_text} · Aggiornato {last_update_display}
        </div>
        <a href="https://t.me/apex_multiasset" target="_blank" style="text-decoration: none; display: inline-flex; align-items: center; gap: 5px; font-size: 11px; font-weight: 600; color: #0088cc; background: rgba(0,136,204,0.1); border: 1px solid rgba(0,136,204,0.25); padding: 3px 10px; border-radius: 20px; margin-top: 6px;">
            ✈ @apex_multiasset
        </a>
    </div>
    """)

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
# LAST REBALANCE CALLOUT (sopra le tab, sempre visibile — e' l'informazione
# piu' urgente quando presente: cosa comprare/vendere oggi sul broker)
# ==============================================================================
last_actions = (pf or {}).get("last_action_log") or []
if last_actions:
    last_action_date = (pf or {}).get("last_action_date", "")
    st_html(f"""
    <div style="background: {ACCENT_SOFT}; border: 1px solid rgba(201,164,76,0.35); border-radius: 8px 8px 0 0; border-bottom: none; padding: 10px 16px 6px; font-size: 13px;">
        <span style="width:6px; height:6px; border-radius:50%; background:{ACCENT}; display:inline-block; margin-right:7px;"></span>
        <strong>Ultimo ribilanciamento ({last_action_date})</strong> — operazioni da replicare sul tuo broker
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
    # Slot riservato per l'hero: deve comparire per primo visivamente ma il
    # suo valore dipende dal capitale inserito piu' sotto — riempito a
    # posteriori con fill_slot() una volta noto il capitale.
    hero_slot = st.empty()

    c_val, c_cur = st.columns([2, 1])
    with c_val:
        _default_cap = 100000
        try:
            _default_cap = max(1000, int(st.query_params.get("cap", 100000)))
        except (TypeError, ValueError):
            pass
        capitale_input = st.number_input(
            "Capitale broker", min_value=1000, value=_default_cap, step=1000, format="%d",
            label_visibility="collapsed"
        )
    with c_cur:
        _default_cur = st.query_params.get("cur", "USD ($)")
        if _default_cur not in ("USD ($)", "EUR (€)"):
            _default_cur = "USD ($)"
        valuta_sel = st.segmented_control("Valuta", ["USD ($)", "EUR (€)"], default=_default_cur, label_visibility="collapsed")

    st.query_params["cap"] = str(int(capitale_input))
    st.query_params["cur"] = valuta_sel

    eur_usd_rate = float(data.get("eur_usd", 1.085))
    is_eur = (valuta_sel == "EUR (€)")
    curr_sym = "€" if is_eur else "$"
    fx_ratio = (1.0 / eur_usd_rate) if is_eur else 1.0
    capitale = capitale_input * eur_usd_rate if is_eur else float(capitale_input)

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
    num_pos = len(op_eq) + len(op_cr) + (1 if gold_detail else 0) + (1 if bond_detail else 0)

    # --- Riempimento dell'hero (valore portafoglio + variazione) ---
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

    # --- Segnali per classe (striscia unica, non 5 riquadri) ---
    st_html(section_title("Segnali per classe"))

    def signal_item(label, value_text, dot_color=None, title_attr=""):
        dot = f'<span style="width:7px; height:7px; border-radius:50%; background:{dot_color}; display:inline-block; margin-right:7px; flex-shrink:0;"></span>' if dot_color else ""
        title_html = f' title="{title_attr}"' if title_attr else ""
        return f'<div{title_html} style="display:flex; align-items:center; gap:7px; font-size:12.5px;">{dot}<span style="font-weight:600;">{label}</span><span style="font-family:{MONO}; color:{MUTED}; margin-left:auto;">{value_text}</span></div>'

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

    # Griglia (non flex-wrap): ogni voce occupa una colonna di larghezza
    # uguale, allineate sia in riga sia in colonna invece di accodarsi in
    # base alla lunghezza del proprio contenuto.
    signals_html = "".join([
        signal_item("Azioni", _eq_val, POS if _eq_active else MUTED_DOT, _eq_title),
        signal_item("Bitcoin", _cr_val, POS if _cr_active else MUTED_DOT, _cr_title),
        signal_item("Oro", _g_val, POS if _g_active else MUTED_DOT, _g_title),
        signal_item("Obbligazioni", _b_val, POS if _b_active else MUTED_DOT, _b_title),
        signal_item("Monetario", f"{alloc.get('Cash', 0):.0f}%"),
    ])
    st_html(f'<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:14px 22px; padding:14px 18px; background:{SURFACE}; border:1px solid {BORDER}; border-radius:10px; margin-bottom:8px;">{signals_html}</div>')

    # --- Allocazione (barra singola, composizione — la performance vive
    # nell'hero e nella tabella, non ripetuta qui) ---
    st_html(section_title("Allocazione"))

    alloc_segments = []
    if op_eq:
        alloc_segments.append(("Azionario", sum(r.get("Peso (%)", 0.0) for r in op_eq), CLASS_COLOR_EQ))
    if op_cr:
        alloc_segments.append(("Bitcoin", op_cr[0].get("Peso (%)", 0.0), CLASS_COLOR_BTC))
    if alloc.get('Gold', 0) > 0:
        alloc_segments.append(("Oro", alloc.get('Gold', 0), CLASS_COLOR_GOLD))
    if alloc.get('Bonds', 0) > 0:
        alloc_segments.append(("Obbligazioni", alloc.get('Bonds', 0), CLASS_COLOR_BOND))
    if alloc.get('Cash', 0) > 0:
        alloc_segments.append(("Monetario", alloc.get('Cash', 0), CLASS_COLOR_CASH))

    if alloc_segments:
        bar_segs = "".join(f'<div style="height:100%; width:{pct:.2f}%; background:{color};"></div>' for _, pct, color in alloc_segments)
        legend_items = "".join(
            f'<div style="display:flex; align-items:center; gap:6px;"><span style="width:9px; height:9px; border-radius:2px; background:{color}; display:inline-block;"></span><span style="color:{MUTED};">{label}</span> <b style="font-family:{MONO}; font-weight:700;">{pct:.1f}%</b></div>'
            for label, pct, color in alloc_segments
        )
        st_html(f'<div style="display:flex; height:12px; border-radius:6px; overflow:hidden; border:1px solid {BORDER_STRONG}; margin-bottom:12px;">{bar_segs}</div>')
        st_html(f'<div style="display:flex; flex-wrap:wrap; gap:12px 20px; margin-bottom:20px; font-size:11.5px;">{legend_items}</div>')

    # --- Tabella unica con tutte le posizioni di tutte le classi ---
    real_cash_usd = max(0.0, capitale - tot_invested_usd)
    cash_weight_pct = (real_cash_usd / capitale * 100) if capitale > 0 else 0.0

    def color_pnl(val):
        color = POS if val > 0 else NEG if val < 0 else MUTED
        return f'color: {color}; font-weight: 700;'

    def style_stato(val):
        if "●" in str(val):
            return f'color: {ACCENT}; font-size: 15px; text-align: center;'
        return 'text-align: center; opacity: 0.4;'

    col_val_label = f"Valore ({curr_sym})"
    col_rend_label = f"Rendimento ({curr_sym})"

    unified_rows = []
    # Azioni ordinate per rendimento decrescente: chi sta guadagnando di piu'
    # in cima, chi sta perdendo di piu' in fondo — leggibile a colpo
    # d'occhio senza dover scandire tutte le 15 righe (i pesi sono quasi
    # identici essendo un basket equal-weight, quindi ordinare per peso non
    # li distinguerebbe in modo utile).
    # Sigle invece dei nomi per classe (AZ/BTC/AU/FI/CASH/TOT) — coerenti col
    # vocabolario gia' usato nel cockpit, colonna molto piu' stretta di
    # "Obbligazioni"/"Monetario" per nessuna perdita di informazione.
    NEW_MARK = "●"
    for r in sorted(op_eq, key=lambda x: x["Rendimento %"], reverse=True):
        unified_rows.append({
            "Classe": "AZ", "Titolo": r["Titolo"], "Stato": NEW_MARK if r["Stato"] == "NUOVO" else "",
            "Data Ingresso": r["Data Ingresso"],
            "Ingresso ($)": r["Ingresso ($)"], "Attuale ($)": r["Attuale ($)"],
            "Peso (%)": r["Peso (%)"], "Rendimento %": r["Rendimento %"],
        })
    if op_cr:
        r = op_cr[0]
        unified_rows.append({
            "Classe": "BTC", "Titolo": r["Titolo"], "Stato": NEW_MARK if r["Stato"] == "NUOVO" else "",
            "Data Ingresso": r["Data Ingresso"],
            "Ingresso ($)": r["Ingresso ($)"], "Attuale ($)": r["Attuale ($)"],
            "Peso (%)": r["Peso (%)"], "Rendimento %": r["Rendimento %"],
        })

    def _detail_row(classe, ticker, detail):
        return {
            "Classe": classe, "Titolo": ticker, "Stato": NEW_MARK if detail["days"] <= 7 else "",
            "Data Ingresso": f"{detail['entry_date']} ({detail['days']}g)",
            "Ingresso ($)": detail["entry_price"], "Attuale ($)": detail["current_price"],
            "Peso (%)": detail["weight_pct"], "Rendimento %": detail["pnl_pct"],
        }

    if gold_detail:
        unified_rows.append(_detail_row("AU", "GLD", gold_detail))
    if bond_detail:
        unified_rows.append(_detail_row("FI", "IEF", bond_detail))

    unified_rows.append({
        "Classe": "CASH", "Titolo": "Liquidità", "Stato": "",
        "Data Ingresso": "—",
        "Ingresso ($)": float("nan"), "Attuale ($)": float("nan"),
        "Peso (%)": cash_weight_pct, "Rendimento %": float("nan"),
    })

    # Riga totale — stessa informazione dell'hero (P&L aggregato), calcolata
    # dagli stessi dati della tabella invece che in un riquadro separato.
    unified_rows.append({
        "Classe": "TOT", "Titolo": "", "Stato": "",
        "Data Ingresso": "—",
        "Ingresso ($)": float("nan"), "Attuale ($)": float("nan"),
        "Peso (%)": 100.0, "Rendimento %": tot_pnl_pct,
    })

    def style_total_row(row):
        if row.get("Classe") == "TOT":
            return [f'font-weight: 800; border-top: 2px solid {BORDER_STRONG};'] * len(row)
        return [''] * len(row)

    show_details = st.toggle("Mostra dettagli esecuzione (quote, data ingresso, prezzi)", value=False)
    compact_cols = ["Classe", "Titolo", "Stato", "Peso (%)", col_val_label, "Rendimento %"]
    full_cols = ["Classe", "Titolo", "Stato", "Data Ingresso", "Quote", "Ingresso ($)", "Attuale ($)", "Peso (%)", col_val_label, "Rendimento %", col_rend_label]
    active_cols = full_cols if show_details else compact_cols

    st_html(section_title("Posizioni"))

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

    # Altezza fissa invece di mostrare tutte le righe senza limite: ~8 righe
    # visibili, il resto scorre dentro la tabella stessa (nessuna riga
    # nascosta, solo non tutte in vista contemporaneamente).
    st.dataframe(df_pos_styled, use_container_width=True, hide_index=True, height=360)


# ==============================================================================
# TAB 2: METRICHE (EQUITY CURVE, DRAWDOWN, KPI, STORICO)
# ==============================================================================
with tab_perf:
    eq_curve = load_equity()

    # Intervallo calcolato dai dati reali, non un valore fisso in testo che
    # sarebbe rimasto scorretto ogni mese che passa.
    #
    # "Backtest out-of-sample" e' vero solo per la parte generata da
    # generate_v2_track_record.py (replay storico offline). Da quando
    # backend.py gira in produzione ogni notte, ogni voce che scrive porta
    # "live": True (vedi update_equity_curve, APEX_V2_SPEC.md §24) — quindi
    # si puo' distinguere onestamente le due fasi invece di chiamare tutto
    # "backtest" anche mesi dopo che il forward-tracking reale e' iniziato.
    track_record_range_str = ""
    live_since_str = None
    if eq_curve and "history" in eq_curve and len(eq_curve["history"]) > 0:
        _hist_dates = pd.to_datetime([h["date"] for h in eq_curve["history"]])
        _d0, _d1 = _hist_dates.min(), _hist_dates.max()
        track_record_range_str = f" ({MESI_IT[_d0.month-1]} {_d0.year} – {MESI_IT[_d1.month-1]} {_d1.year})"

        _live_dates = sorted(h["date"] for h in eq_curve["history"] if h.get("live"))
        if _live_dates:
            live_since_str = format_date_italian(_live_dates[0])

    if live_since_str:
        _banner_title = f"SIMULAZIONE STORICA + FORWARD-TRACKING DAL VIVO{track_record_range_str}"
        _banner_sub = f"Simulazione a regole fisse fino al {live_since_str}, poi decisioni reali eseguite ogni notte in produzione · Reinvestimento composto"
        _banner_badge = f"BASE 100 · LIVE DAL {live_since_str.upper()}"
    else:
        _banner_title = f"SIMULAZIONE QUANTITATIVA & TRACK RECORD{track_record_range_str}"
        _banner_sub = "Serie storica a regole fisse deterministiche su dati storici di mercato · Reinvestimento composto"
        _banner_badge = "BASE 100 · BACKTEST OUT-OF-SAMPLE"

    st_html(f"""
    <div style="background: {ACCENT_SOFT}; border: 1px solid rgba(201,164,76,0.25); border-radius: 8px; padding: 10px 14px; margin-bottom: 18px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
        <div>
            <span style="font-size: 13px; font-weight: 700; color: {ACCENT};">{_banner_title}</span>
            <div style="font-size: 11px; opacity: 0.65; margin-top: 2px;">{_banner_sub}</div>
        </div>
        <span style="background: rgba(201,164,76,0.16); color: {ACCENT}; font-size: 11px; font-weight: 700; padding: 3px 8px; border-radius: 6px; font-family: {MONO};">{_banner_badge}</span>
    </div>
    """)

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

    # Stima netto teorica: 26% (aliquota flat italiana) solo sulla quota di
    # guadagno, come se l'intera posizione venisse realizzata oggi. Le
    # perdite non generano beneficio fiscale in questa stima semplificata
    # (non modella riporto perdite 4 anni art. 68 TUIR, vedi APEX_V2_SPEC.md §8.9/§10).
    net_ret_pct_est = total_ret_pct * (1.0 - 0.26) if total_ret_pct > 0 else total_ret_pct

    # --- Sub-hero: le 3 metriche piu' importanti, in grande, non sepolte in
    # una striscia di 9 — le altre restano nella striscia sotto.
    def sub_hero_metric(label, value, subtext="", val_color=None):
        return f"""
        <div style="flex: 1 1 160px;">
            <div style="font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.6px; color: {MUTED}; margin-bottom: 5px;">{label}</div>
            <div style="font-family: {MONO}; font-size: 28px; font-weight: 800; color: {val_color or 'inherit'};">{value}</div>
            <div style="font-size: 11px; color: {MUTED}; margin-top: 2px;">{subtext}</div>
        </div>
        """

    st_html(f"""
    <div style="display:flex; gap:32px; flex-wrap:wrap; margin-bottom:24px;">
        {sub_hero_metric("Rendimento", f"{total_ret_pct:+.2f}%", f"Netto stimato: {net_ret_pct_est:+.2f}%", POS if total_ret_pct >= 0 else NEG)}
        {sub_hero_metric("CAGR Annualizzato", f"{cagr_pct:+.2f}%", "Composto annuo", POS if cagr_pct >= 0 else NEG)}
        {sub_hero_metric("Max Drawdown", f"{max_dd:.2f}%", "Massima perdita storica")}
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

    if eq_curve and "history" in eq_curve and len(eq_curve["history"]) > 0:
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

        # Range Y esplicito calcolato dai dati effettivamente disegnati (non
        # l'autorange di Plotly): "fill='tozeroy'" sulla curva strategia
        # tirava l'asse fino a 0 anche quando i valori reali stavano tutti
        # tra 90 e 140, schiacciando le linee in alto nel grafico invece di
        # centrarle. Padding 8% sopra/sotto il range dei dati.
        _y_values = list(df_plot['norm_close'])

        # 1. Curva equity Apex — area/linea (piu' convenzionale di una candela per
        # un NAV multi-asset ribilanciato, che non ha un vero OHLC intra-periodo).
        fig.add_trace(go.Scatter(
            x=df_plot.index,
            y=df_plot['norm_close'],
            mode='lines',
            name='Strategia Apex',
            line=dict(color=ACCENT, width=2),
            fill='tozeroy',
            fillcolor='rgba(201, 164, 76, 0.10)',
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
                _y_values.extend(df_spy_norm.tolist())

                spy_it_dates = [f"{d.day:02d} {IT_MONTHS[d.month]} {d.year}" for d in df_spy_plot.index]
                fig.add_trace(go.Scatter(
                    x=df_spy_plot.index,
                    y=df_spy_norm,
                    text=spy_it_dates,
                    hovertemplate="<b>%{text}</b><br>S&P 500: %{y:.2f}<extra></extra>",
                    mode='lines',
                    name="S&P 500 Benchmark",
                    line=dict(color='#7A7266', width=1.5, dash='dot'),
                ))

        _y_min, _y_max = min(_y_values), max(_y_values)
        _y_pad = max((_y_max - _y_min) * 0.08, 1.0)

        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(family="Inter, sans-serif"),
            xaxis=dict(
                showgrid=False,
                tickfont=dict(size=11),
                tickmode='array' if len(ticks) > 0 else 'auto',
                tickvals=ticks if len(ticks) > 0 else None,
                ticktext=tick_labels if len(tick_labels) > 0 else None
            ),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,247,237,0.07)', tickfont=dict(size=11),
                       range=[_y_min - _y_pad, _y_max + _y_pad]),
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
            fillcolor='rgba(236, 101, 123, 0.15)',
            hovertemplate="%{x|%d %b %Y}<br>Drawdown: %{y:.2f}%<extra></extra>",
            name="Drawdown"
        ))
        fig_dd.update_layout(
            template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(family="Inter, sans-serif"),
            xaxis=dict(showgrid=False, tickfont=dict(size=10)),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,247,237,0.05)', tickfont=dict(size=10), ticksuffix="%"),
            margin=dict(l=0, r=0, t=4, b=0), height=110, showlegend=False
        )
        st.plotly_chart(fig_dd, use_container_width=True)
    else:
        st.info("In attesa del file di tracciamento storico.")

    st.write("")

    # Striscia secondaria (le statistiche restanti) — stesso principio del
    # cockpit e della tabella posizioni: un solo contenitore con divisori.
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

        def kpi_item(title, value, subtext="", badge_text=None, badge_color=None, val_color=None, first=False):
            badge_html = ""
            if badge_text:
                bcol = badge_color or BADGE_NEUTRAL_BG
                badge_html = f'<span style="background:{bcol}; color:{BADGE_TEXT}; font-size:9px; font-weight:700; padding:1px 6px; border-radius:4px; font-family:{MONO}; margin-left:6px;">{badge_text}</span>'
            return f"""
            <div style="padding: 6px 4px;">
                <div style="font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.4px; color: {MUTED}; white-space: nowrap;">{title}{badge_html}</div>
                <div style="font-size: 18px; font-weight: 800; color: {val_color or 'inherit'}; font-family: {MONO}; margin: 2px 0;">{value}</div>
                <div style="opacity: 0.6; font-size: 10px;">{subtext}</div>
            </div>
            """

        strip_items = [
            kpi_item("Win Rate", f"{win_rate:.1f}%", f"{len(wins)} vincenti su {len(hist)}",
                     badge_text=f"{len(wins)}/{len(hist)}", first=True),
            kpi_item("Profit Factor", f"{profit_factor:.2f}", "Profitti lordi / perdite",
                     badge_text=("ECCELLENTE" if profit_factor >= 1.5 else "STABILE"),
                     badge_color=(BADGE_POS_BG if profit_factor >= 1.5 else BADGE_NEUTRAL_BG)),
            kpi_item("Payoff Ratio", f"{payoff_ratio:.2f}x", "Vincita media / perdita media",
                     badge_text=("ASIMMETRIA" if payoff_ratio >= 2.0 else "EQUILIBRATO")),
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

        st_html(f'<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 4px 8px; background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 14px; margin-bottom: 20px;">{"".join(strip_items)}</div>')

        if hist:
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

            def _short_reason(raw):
                # backend.py scrive motivazioni pensate per i messaggi Telegram
                # (emoji + dettaglio tra parentesi) — solo 3 possibili oggi
                # (verificato in backend.py), qui basta la categoria: la
                # tabella di Streamlit non supporta tooltip nelle celle, quindi
                # la versione corta deve restare leggibile da sola.
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
                hide_index=True,
                height=360
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

    st_html(section_title("Cadenza Operativa", top="0"))
    st_html(f"""
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 20px;">
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px;">
            <div style="font-family: {FRAUNCES}; font-weight: 600; font-size: 14px; margin-bottom: 6px;">Ogni giorno (Lun-Ven)</div>
            <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5;">Prezzi e NAV vengono aggiornati. Nessuna decisione di trading in questa fase — solo osservazione.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px;">
            <div style="font-family: {FRAUNCES}; font-weight: 600; font-size: 14px; margin-bottom: 6px;">Ultimo venerdì del mese</div>
            <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5;">Il segnale macro di ogni classe viene ricontrollato (attiva/in pausa) e il peso complessivo viene riscalato per centrare il target di volatilità. Non esiste un controllo settimanale intermedio: le decisioni sono solo qui.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px;">
            <div style="font-family: {FRAUNCES}; font-weight: 600; font-size: 14px; margin-bottom: 6px;">Ultimo venerdì del trimestre</div>
            <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5;">In aggiunta al ribilanciamento mensile, il basket azionario viene rinnovato: i titoli con volatilità realizzata più alta escono, i nuovi primi in classifica entrano. Nessuno stop-loss per singola posizione: l'uscita avviene solo per rotazione o disattivazione della classe.</div>
        </div>
    </div>
    """)

    st.divider()

    st_html(section_title("Documentazione Strategica", top="0"))
    st_html(f'''
    <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px; margin-bottom: 14px;">
        <div style="font-family: {FRAUNCES}; font-weight: 600; font-size: 14px; margin-bottom: 4px;">Obiettivo Primario</div>
        <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5;">Generare alpha reale (indipendente dal semplice beta di mercato) con bassa frequenza di intervento (rotazione mensile/trimestrale, mai giornaliera) e alta efficienza fiscale, eliminando ogni componente emotiva attraverso l'allocazione dinamica quantitativa.</div>
    </div>

    <div style="font-size: 12.5px; font-weight: 700; color: {MUTED}; text-transform: uppercase; letter-spacing: 0.5px; margin: 16px 0 8px 0;">Il Sistema — Segnale di Timing per Classe</div>
    <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5; margin-bottom: 10px;">Ogni classe di attivo (Azioni, Obbligazioni, Oro, Bitcoin) viene attivata o disattivata in base al proprio trend di lungo periodo — non esiste più un tetto percentuale fisso per classe:</div>

    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; margin-bottom: 14px;">
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-weight: 700; font-size: 13px;">Azioni</span>
                <span style="background: {BADGE_NEUTRAL_BG}; color: {MUTED}; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: {MONO};">BASKET BASSA VOL</span>
            </div>
            <div style="font-size: 12px; opacity: 0.8; line-height: 1.4;">Attiva se SPY è sopra le medie mobili a 40 E 20 settimane insieme (conferma multi-timeframe, isteresi adattiva sulla banda).</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-weight: 700; font-size: 13px;">Bitcoin</span>
                <span style="background: {BADGE_NEUTRAL_BG}; color: {MUTED}; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: {MONO};">SOLO BTC-USD</span>
            </div>
            <div style="font-size: 12px; opacity: 0.8; line-height: 1.4;">Nessuna rotazione altcoin (testata e respinta: nessun edge aggiuntivo). Stesso segnale di timing dell'azionario.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-weight: 700; font-size: 13px;">Oro</span>
                <span style="background: {BADGE_NEUTRAL_BG}; color: {MUTED}; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: {MONO};">SEGNALE DI TREND</span>
            </div>
            <div style="font-size: 12px; opacity: 0.8; line-height: 1.4;">Protezione contro inflazione e incertezza, attivata dallo stesso meccanismo di timing.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-weight: 700; font-size: 13px;">Obbligazioni</span>
                <span style="background: {BADGE_NEUTRAL_BG}; color: {MUTED}; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: {MONO};">SEGNALE DI TREND</span>
            </div>
            <div style="font-size: 12px; opacity: 0.8; line-height: 1.4;">Titoli di stato, allocati quando il proprio trend è favorevole.</div>
        </div>
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-weight: 700; font-size: 13px;">Monetario</span>
                <span style="background: {BADGE_NEUTRAL_BG}; color: {MUTED}; font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: {MONO};">RESIDUO</span>
            </div>
            <div style="font-size: 12px; opacity: 0.8; line-height: 1.4;">Rifugio sicuro e liquidità per le classi in pausa o per il target di volatilità.</div>
        </div>
    </div>

    <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px; margin-bottom: 10px;">
        <div style="font-family: {FRAUNCES}; font-weight: 600; font-size: 14px; margin-bottom: 4px;">Selezione del Basket Azionario</div>
        <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5;">Ogni trimestre, tra i titoli dell'universo tracciato il sistema seleziona i 15 con la volatilità realizzata più bassa (26 settimane), non i più momentum-forti: l'obiettivo è mantenere il carattere fiscale di "redditi diversi" (azioni singole, compensabili) con un profilo di rischio stabile. Massimo 2 titoli per settore, per non concentrare il basket su un solo comparto.</div>
    </div>

    <div style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px; margin-bottom: 18px;">
        <div style="font-family: {FRAUNCES}; font-weight: 600; font-size: 14px; margin-bottom: 4px;">Vol-Targeting di Portafoglio</div>
        <div style="font-size: 12.5px; opacity: 0.8; line-height: 1.5;">Ogni classe attiva parte da un peso di base uguale (25%), poi tutte le classi attive vengono scalate mensilmente dallo stesso fattore per centrare una volatilità target del 13% annualizzato (finestra 12 settimane) — non è un tetto per classe: se due classi attive mostrano lo stesso peso è perché partono dallo stesso 25% base e vengono scalate allo stesso modo, non per un limite massimo. Non esiste uno stop-loss per singola posizione: testato esplicitamente e respinto perché riduce l'edge senza migliorare il rischio aggiustato per rendimento (dettagli in APEX_V2_SPEC.md §3).</div>
    </div>
    ''')

    st.divider()

    st_html(f'''
    <div style="background: rgba(236, 101, 123, 0.04); border: 1px solid rgba(236, 101, 123, 0.18); border-radius: 8px; padding: 12px 14px; font-size: 11.5px; opacity: 0.8; line-height: 1.5;">
        <strong>Note Legali ed Esclusione di Responsabilità:</strong><br>
        Questa piattaforma ha scopo puramente informativo e di analisi statistica. Non fornisce consulenza finanziaria né raccomandazioni personalizzate ai sensi delle normative vigenti.<br>
        I rendimenti passati non garantiscono risultati futuri. Ogni investimento comporta il rischio di perdita del capitale ed è effettuato sotto la totale ed esclusiva responsabilità dell'utente. L'autore declina qualsiasi responsabilità per eventuali perdite derivanti dall'uso di questi dati.
    </div>
    ''')
