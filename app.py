"""
app.py — Dashboard APEX CONVEX
==================================================================================
Due motori quantitativi: uno tattico (Apex), uno di accumulo a lungo termine
(Convex). Principi guida: lean, senza attrito, robusto, semplice da mantenere.
Unione tra rigore istituzionale e semplicità operativa retail.
==================================================================================
"""

import base64
import datetime
import json
import os
import urllib.request

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import convex_engine
import portfolio_manager

st.set_page_config(
    page_title="APEX CONVEX",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

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

    /* Card style — identico alla convenzione di Apex Engine: border-radius 8px,
       stesso padding usato nei riquadri di app.py di Apex (14px 16px). */
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
</style>
""")

def get_logo_b64():
    """Identica alla funzione di Apex Engine: stesso logo, stesso meccanismo."""
    for p in ["logo_icon.png", "logo.png"]:
        if os.path.exists(p):
            try:
                with open(p, "rb") as f:
                    return base64.b64encode(f.read()).decode()
            except Exception:
                pass
    return ""

def render_html_table(df, right_align_cols=None):
    """Tabella HTML nello stesso stile di Apex Engine — non lo stile Streamlit
    di default (st.dataframe), che ha un aspetto visibile diverso."""
    right_align_cols = right_align_cols or []
    th_cells = "".join(
        f'<th style="padding:10px 14px; font-weight:600; color:{MUTED}; font-size:11px; '
        f'text-align:{"right" if c in right_align_cols else "left"}; text-transform:uppercase; '
        f'border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">{c}</th>'
        for c in df.columns
    )
    rows_html = []
    for _, r in df.iterrows():
        td_cells = "".join(
            f'<td style="padding:10px 14px; font-size:12.5px; '
            f'text-align:{"right" if c in right_align_cols else "left"}; '
            f'font-family:{MONO if c in right_align_cols else "inherit"};">{r[c]}</td>'
            for c in df.columns
        )
        rows_html.append(f'<tr style="border-bottom:1px solid {BORDER};">{td_cells}</tr>')
    return (
        f'<div style="width:100%; overflow-x:auto; border:1px solid {BORDER}; border-radius:8px; '
        f'background:rgba(255,247,237,0.02); margin-bottom:14px;">'
        f'<table style="width:100%; border-collapse:collapse; text-align:left;">'
        f'<thead><tr>{th_cells}</tr></thead><tbody>{"".join(rows_html)}</tbody></table></div>'
    )

MESI_IT = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

def render_monthly_returns_html_table(df_eq):
    """Matrice HTML dei rendimenti mensili e annuali — stessa logica di Apex Engine.
    df_eq: DataFrame indicizzato per data con colonna 'value' (patrimonio)."""
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

# Design Tokens (identici a quelli di Apex Engine — stesso sistema visivo)
POS = "#3DDC97"           # Verde caldo P&L positivo
NEG = "#EC657B"           # Corallo P&L negativo / attenzione reale
MUTED_DOT = "#5B534B"     # Segnale "in pausa" — non è una notizia negativa
ACCENT = "#C9A44C"        # Oro accento istituzionale
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

# ==============================================================================
# CARICAMENTO CONFIGURAZIONE UTENTE (CAMPI STANDARD COMPILABILI)
# ==============================================================================
cfg = portfolio_manager.load_config()

# ==============================================================================
# DATO LIVE APEX (spostato qui, prima della sidebar, per poterne pre-riempire
# il campo capitale con il valore reale invece che con lo statico config.json)
# ==============================================================================
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

apex_data = fetch_json_local_or_github("apex_data.json") or {}
apex_portfolio = fetch_json_local_or_github("portfolio.json") or {}

# Capitale Apex live: nav_usd convertito in EUR col cambio del giorno. Se il
# dato live non è disponibile, resta il valore statico salvato in config.json
# — non un errore, solo un fallback dichiarato (vedi caption sotto al campo).
_apex_live_eur = None
try:
    _nav_usd = float(apex_portfolio.get("nav_usd", 0.0))
    _eur_usd_rate = float(apex_data.get("eur_usd", 0.0))
    if _nav_usd > 0 and _eur_usd_rate > 0:
        _apex_live_eur = _nav_usd / _eur_usd_rate
except Exception:
    _apex_live_eur = None

with st.sidebar:
    st_html(f"""
    <div style="padding: 10px 0 16px 0; border-bottom: 1px solid {BORDER}; margin-bottom: 16px;">
        <div style="font-family: {FRAUNCES}; font-size: 20px; font-weight: 600; color: {BADGE_TEXT};">Impostazioni Patrimonio</div>
        <div style="font-size: 11px; color: {MUTED}; text-transform: uppercase; letter-spacing: 0.5px; margin-top: 2px;">Campi Standard Compilabili</div>
    </div>
    """)

    cap_apex_input = st.number_input(
        "Capitale Apex Engine (€)",
        min_value=1000.0,
        value=float(_apex_live_eur) if _apex_live_eur else float(cfg.get("apex_capital_eur", 79000.0)),
        step=1000.0,
        format="%.0f"
    )
    if _apex_live_eur:
        st.caption(f"↳ precompilato dal NAV live (€{_apex_live_eur:,.0f}) · modificabile")
    else:
        st.caption("↳ NAV live non disponibile, valore da config.json")

    cap_convex_input = st.number_input(
        "Capitale Convex Stack (€)",
        min_value=1000.0,
        value=float(cfg.get("convex_capital_eur", 130000.0)),
        step=1000.0,
        format="%.0f"
    )

    pac_input = st.number_input(
        "Versamento Mensile PAC (€)",
        min_value=0.0,
        value=float(cfg.get("monthly_pac_eur", 600.0)),
        step=50.0,
        format="%.0f"
    )

    pac_growth_input = st.number_input(
        "Indicizzazione Annua PAC (%)",
        min_value=0.0,
        max_value=20.0,
        value=float(cfg.get("pac_annual_growth", 0.04) * 100.0),
        step=0.5,
        format="%.1f"
    ) / 100.0

    target_apex_ratio_input = st.slider(
        "Target Allocazione Apex (%)",
        min_value=20,
        max_value=80,
        value=int(cfg.get("target_apex_ratio", 0.45) * 100),
        step=5
    ) / 100.0

    if st.button("💾 Salva Configurazione", use_container_width=True):
        new_cfg = {
            "apex_capital_eur": cap_apex_input,
            "convex_capital_eur": cap_convex_input,
            "monthly_pac_eur": pac_input,
            "pac_annual_growth": pac_growth_input,
            "target_apex_ratio": target_apex_ratio_input,
            "target_convex_ratio": 1.0 - target_apex_ratio_input,
            "wbtc_trim_threshold": float(cfg.get("wbtc_trim_threshold", 0.1125)),
            "ppfb_trim_threshold": float(cfg.get("ppfb_trim_threshold", 0.1125)),
            "last_updated": datetime.date.today().strftime("%Y-%m-%d")
        }
        if portfolio_manager.save_config(new_cfg):
            st.toast("Salvato per questa sessione dell'app.", icon="✅")
            cfg = new_cfg
        else:
            st.error("Errore nel salvataggio della configurazione.")

    st_html(f"""
    <div style="margin-top: 24px; padding: 14px; background: rgba(255,247,237,0.02); border: 1px solid {BORDER}; border-radius: 8px; font-size: 11.5px; color: {MUTED}; line-height: 1.5;">
        <strong style="color:{BADGE_TEXT};">Regola d'Oro Fiscale:</strong><br>
        Le plusvalenze su <strong>PPFB (Oro)</strong> e <strong>WBTC (Bitcoin)</strong> sono "redditi diversi": compensano le minusvalenze pregresse.
    </div>
    """)

# ==============================================================================
# CARICAMENTO DATI CONVEX (Apex già caricato sopra, prima della sidebar)
# ==============================================================================
convex_portfolio = portfolio_manager.load_convex_portfolio()

# Prezzi live dei 5 strumenti Convex (cache 15 minuti). Se il recupero fallisce
# per un singolo titolo, si usa un prezzo di base dichiarato (100/50/25/50/100)
# — mai spacciato per prezzo di mercato: la tabella lo segnala.
_CONVEX_BASE_PRICES = {"NTSG": 100.0, "AVWS": 50.0, "DBMFE": 25.0, "PPFB": 50.0, "WBTC": 100.0}
# PPFB/WBTC corretti: i vecchi ticker (PPFB.MI, BTC-USD) non erano validi per il prezzo
# reale per quota — PPFB.MI non e' fetchable, BTC-USD dava il prezzo grezzo di Bitcoin
# invece di quello dell'ETP. Verificato via Yahoo chart API: SGLD.MI (~EUR 367, oro) e
# WBTC-ETFP.MI (~EUR 16, Bitcoin ETP) sono i ticker reali e fetchable per questi ISIN.
_CONVEX_YF_TICKERS = {"NTSG": "NTSG.MI", "AVWS": "AVWS.DE", "DBMFE": "DBMFE.PA", "PPFB": "EGLN.L", "WBTC": "WBTC-ETFP.MI"}

# Cache prezzi scritta da fetch_live_prices.py via GitHub Actions — il fetch
# a runtime da Streamlit Community Cloud fallisce spesso perché Yahoo Finance
# limita il pool di IP condivisi degli host cloud. Si legge prima la cache
# (aggiornata 3 volte al giorno da un runner con IP diverso); il fetch live
# resta come fallback solo per uso locale/prima esecuzione senza cache.
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

convex_prices, convex_prices_live = fetch_convex_live_prices()
convex_holdings = {k: v.get("shares", 0.0) for k, v in convex_portfolio.get("holdings", {}).items()}
if not convex_holdings:
    # Nessuna posizione salvata in convex_portfolio.json: simula un portafoglio
    # già allineato ai pesi target, solo per non mostrare una tabella vuota.
    # Aggiorna convex_portfolio.json con le tue quote reali per un dato vero.
    convex_holdings = {
        "NTSG": (cap_convex_input * 0.45) / convex_prices["NTSG"],
        "AVWS": (cap_convex_input * 0.15) / convex_prices["AVWS"],
        "DBMFE": (cap_convex_input * 0.25) / convex_prices["DBMFE"],
        "PPFB": (cap_convex_input * 0.075) / convex_prices["PPFB"],
        "WBTC": (cap_convex_input * 0.075) / convex_prices["WBTC"],
    }
    convex_holdings_are_simulated = True
else:
    convex_holdings_are_simulated = False

convex_report = convex_engine.evaluate_convex_stack(
    current_holdings=convex_holdings,
    market_prices=convex_prices,
    monthly_pac_eur=pac_input,
    cash_balance=convex_portfolio.get("cash_eur", 0.0)
)

# Unificazione del patrimonio — usa la ripartizione macro REALE e corrente di
# Apex (apex_data.json["allocations"]), non una stima fissa
unified = portfolio_manager.compute_unified_portfolio(
    apex_val=cap_apex_input,
    convex_report=convex_report,
    monthly_pac=pac_input,
    target_apex_ratio=target_apex_ratio_input,
    apex_allocations=apex_data.get("allocations")
)

# Metriche dei due motori e congiunte
m_apex = portfolio_manager.get_apex_metrics()
m_convex = portfolio_manager.get_convex_metrics()
m_dual = portfolio_manager.get_combined_dual_engine_metrics()

# ==============================================================================
# HEADER & TOP KPI RIBBON (SINTESI IMMEDIATA)
# ==============================================================================
_logo_b64 = get_logo_b64()
_logo_tag = (f'<img src="data:image/png;base64,{_logo_b64}" style="height: 48px; width: auto; object-fit: contain;" />'
             if _logo_b64 else '🏛️')

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
                Due motori quantitativi <span style="color: {ACCENT}; font-weight: 700;">tattico + accumulo</span>
            </div>
        </div>
    </div>
    """)

with col_stat:
    st_html(f"""
    <div style="text-align: right; padding-top: 10px;">
        <div style="font-size: 11px; color: {MUTED};">
            <span style="width:6px; height:6px; border-radius:50%; background:{POS}; display:inline-block; margin-right:5px;"></span>Sistema Operativo
        </div>
        <div style="font-size: 11px; color: {MUTED_2}; margin-top: 2px;">
            Ribilanciamento PAC: 1° del mese
        </div>
    </div>
    """)

# Top Ribbon KPI Cards
c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.metric("Patrimonio Consolidato", f"€ {unified['total_wealth_eur']:,.0f}", f"+ PAC €{pac_input:.0f}/m")
with c2:
    st.metric("Allocazione Attuale", f"{unified['apex_weight']*100:.1f}% / {unified['convex_weight']*100:.1f}%", f"Target {target_apex_ratio_input*100:.0f}/{(1-target_apex_ratio_input)*100:.0f}")
with c3:
    st.metric("Crescita Annua Netta", f"{m_dual['cagr_net']*100:.2f}%", f"Lordo {m_dual['cagr_gross']*100:.2f}%",
               help="CAGR netto (tasse comprese) e, sotto, lordo (prima delle tasse).")
with c4:
    st.metric("Perdita Massima Storica", f"{m_dual['max_drawdown']*100:.2f}%", "vs -50% Azionario",
               help="Il calo peggiore mai registrato dal punto più alto al più basso.")
with c5:
    st.metric("Rendimento per Rischio", f"{m_dual['sharpe']:.2f}", f"Sortino {m_dual['sortino']:.2f}",
               help="Sharpe: quanto rendimento si ottiene per ogni unità di rischio. Più alto è meglio.")

st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

# ==============================================================================
# AZIONE DEL MESE — SMART FLOW (sempre visibile, nessun click richiesto)
# ==============================================================================
# Spostato qui dalla scheda "Sintesi Globale": è la singola informazione più
# utile e più cercata ogni mese (dove va la rata PAC) — deve essere visibile
# subito, non in fondo a una terza scheda.
st_html(f"""
<div style="background: rgba(255,247,237,0.03); border: 1px solid {BORDER_STRONG}; border-radius: 8px; padding: 16px 20px; margin-bottom: 18px;">
    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 6px;">
        <div style="font-size: 14px; font-weight: 700; color:{ACCENT};">
            💡 AZIONE DEL MESE (RIBILANCIAMENTO SENZA VENDITE, ZERO TASSE)
        </div>
        <div style="font-size: 12px; font-weight: 600; color:{BADGE_TEXT};">
            Destinazione Flusso: <span style="color:{POS};">{unified['smart_flow_destination']}</span>
        </div>
    </div>
    <div style="font-size: 13px; color: {MUTED}; line-height: 1.5;">
        {unified['smart_flow_note']}
    </div>
</div>
""")

# ==============================================================================
# MAIN TABS — ordine per frequenza d'uso: prima ciò che richiede un'azione
# mensile dell'utente (Convex, dove va indirizzata la rata PAC), poi la vista
# d'insieme del patrimonio, infine Apex (motore automatico, solo monitoraggio,
# nessuna azione manuale richiesta da chi legge la dashboard).
# ==============================================================================
tab_convex, tab_dual, tab_apex = st.tabs([
    "🛡️ Convex Stack (Strategico)",
    "🏛️ Sintesi Globale (Apex + Convex)",
    "⚡ Apex Engine (Tattico)",
])

# ==============================================================================
# TAB 1: 🛡️ CONVEX STACK (IL MOTORE STRATEGICO PAC)
# ==============================================================================
with tab_convex:
    st_html(f"""
    <div class="glass-card">
        <div style="font-family: {FRAUNCES}; font-size: 18px; font-weight: 600; color: {BADGE_TEXT}; margin-bottom: 6px;">
            Filosofia Operativa: Accumulo a Lungo Termine e Crescita Composta
        </div>
        <div style="font-size: 13px; color: {MUTED}; line-height: 1.6;">
            {m_convex['philosophy']}
            Non richiede debito a margine personale: <strong>la leva 1.5x di NTSG è interamente interna all'ETF</strong> (futures istituzionali a tassi repo). I Managed Futures (DBMFE) forniscono protezione attiva nei bear market inflattivi, mentre Oro e Bitcoin fungono da riserve reali contro la svalutazione monetaria.
        </div>
    </div>
    """)

    # Scorecard Metriche Convex
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Crescita Annua Netta (24a)", f"{m_convex['cagr_net']*100:.2f}%", f"Lordo {m_convex['cagr_gross']*100:.2f}%",
              help="CAGR netto se liquidato oggi (tasse comprese) e, sotto, lordo (prima delle tasse). Convex non vende se non per rari trim: il valore reale del portafoglio oggi è quello lordo.")
    c2.metric("Oscillazione", f"{m_convex['volatility']*100:.2f}%", help="Volatilità: quanto varia il valore nel tempo.")
    c3.metric("Rendimento/Rischio", f"{m_convex['sharpe']:.2f}", help="Sharpe: rendimento ottenuto per ogni unità di rischio.")
    c4.metric("Rendimento/Ribassi", f"{m_convex['sortino']:.2f}", help="Sortino: come Sharpe, ma guarda solo ai cali, non alle oscillazioni positive.")
    c5.metric("Perdita Massima", f"{m_convex['max_drawdown']*100:.2f}%", help="Il calo peggiore mai registrato dal punto più alto al più basso.")
    c6.metric("Rendimento/Perdita Max", f"{m_convex['calmar']:.2f}", help="Calmar: crescita annua rapportata alla peggior perdita subita.")

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

    # Box PAC automatico
    st_html(section_title("Calcolatore PAC Mensile"))
    st.caption("Ogni mese il versamento va all'asset più sottopesato rispetto al target, per riportarlo in linea.")
    pac_act = convex_report.pac_action
    if pac_act:
        st_html(f"""
        <div class="glass-card-accent">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 8px;">
                <div style="color: {ACCENT}; font-weight: 700; font-size: 15px;">
                    🎯 AZIONE PAC CONSIGLIATA PER IL 1° DEL MESE
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
                <em>Motivazione Quantitativa:</em> {pac_act.reason}
            </div>
        </div>
        """)

    # Tabella 5 Strumenti UCITS
    st_html(section_title("Stato dei 5 Strumenti Convex"))
    if convex_holdings_are_simulated:
        st.caption("Nessuna posizione salvata: quote simulate ai pesi target. Aggiorna convex_portfolio.json con le tue quote reali.")
    _n_live = sum(convex_prices_live.values())
    if _n_live < len(convex_prices_live):
        st.caption(f"Prezzo di mercato non raggiungibile per {len(convex_prices_live) - _n_live}/{len(convex_prices_live)} titoli: usato un prezzo di base, non il prezzo reale.")
    cx_rows = []
    for k, st_info in convex_report.assets.items():
        cx_rows.append({
            "Strumento": k,
            "Nome / Ruolo": st_info.name,
            "ISIN": st_info.isin,
            "Peso Target": f"{st_info.target_weight*100:.1f}%",
            "Banda Tolleranza": f"[{st_info.tolerance_min*100:.1f}% - {st_info.tolerance_max*100:.1f}%]",
            "Controvalore (€)": f"€ {st_info.current_value:,.0f}",
            "Peso Attuale": f"{st_info.current_weight*100:.2f}%",
            "Regime Fiscale": "Reddito Diverso (Compensa Minus)" if st_info.tax_type == "REDDITO_DIVERSO" else "Reddito di Capitale (ETF)"
        })
    st_html(render_html_table(pd.DataFrame(cx_rows), right_align_cols=["Peso Target", "Controvalore (€)", "Peso Attuale"]))

    # Box Allerte Trim & Ribilanciamento
    st_html(section_title("Monitoraggio Soglie di Trim & Ottimizzazione Fiscale"))
    if convex_report.trim_alerts:
        for al in convex_report.trim_alerts:
            st_html(f"""
            <div style="background: rgba(236,101,123,0.08); border: 1px solid rgba(236,101,123,0.3); border-radius: 8px; padding: 14px; margin-bottom: 10px;">
                <div style="color:{NEG}; font-weight:700; font-size:14px;">⚠️ SFORAMENTO SOGLIA DI TRIM: {al['asset']} ({al['name']})</div>
                <div style="font-size:12.5px; color:{BADGE_TEXT}; margin-top:4px;">
                    Peso attuale: <strong>{al['current_weight']*100:.1f}%</strong> (Soglia Max: {al['threshold_max']*100:.1f}%). Eccesso da vendere: <strong>€ {al['excess_eur']:,.0f}</strong> (~{al['shares_to_sell']} quote).
                </div>
                <div style="font-size:11.5px; color:{MUTED}; margin-top:6px;">
                    {al['tax_note']}
                </div>
            </div>
            """)
    else:
        st_html(f"""
        <div style="background: rgba(61,220,151,0.06); border: 1px solid rgba(61,220,151,0.25); border-radius: 8px; padding: 14px;">
            <div style="color:{POS}; font-weight:700; font-size:13.5px;">✓ TUTTI GLI ASSET SONO DENTRO LE BANDE DI TOLLERANZA</div>
            <div style="font-size:12px; color:{MUTED}; margin-top:3px;">
                Nessuna vendita necessaria. Bitcoin (WBTC) e Oro (PPFB) sono entrambi sotto la soglia dell'11.25% (target ×1.5). L'interesse composto procede indisturbato senza addebiti fiscali anticipati.
            </div>
        </div>
        """)

    # Curva Storica, Calo dal Massimo e Matrice dei Rendimenti — stessa
    # profondità di Apex, adattata a Convex: qui la fonte non è un conto
    # live tracciato giorno per giorno, ma il backtest corretto di questa
    # sessione (research/convex/, pesi e costi corretti, senza l'estensione
    # Fama-French fabbricata) — dichiarato esplicitamente, mai spacciato per
    # storico di conto reale.
    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
    st_html(section_title("Storico del Backtest Corretto (2000–2026)"))
    st.caption("Serie mensile ricostruita da dati reali, non storico del tuo conto — Convex non tiene un registro di versamenti/trim passati.")
    _cx_ret_path = os.path.join(os.path.dirname(__file__), "convex_monthly_returns.csv")
    if os.path.exists(_cx_ret_path):
        _cx_ret = pd.read_csv(_cx_ret_path, index_col=0, parse_dates=True).iloc[:, 0]
        _cx_nav = pd.DataFrame({"value": (1.0 + _cx_ret).cumprod() * 100.0})
        _cx_nav["roll_max"] = _cx_nav["value"].cummax()
        _cx_nav["drawdown"] = (_cx_nav["value"] - _cx_nav["roll_max"]) / _cx_nav["roll_max"] * 100.0

        fig_cx_eq = go.Figure()
        fig_cx_eq.add_trace(go.Scatter(x=_cx_nav.index, y=_cx_nav["value"], mode="lines",
                                        name="Convex Stack", line=dict(color=POS, width=2)))
        fig_cx_eq.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color=MUTED, family="Inter"),
            margin=dict(t=10, b=10, l=10, r=10), height=280, showlegend=False,
            yaxis_title="Base 100"
        )
        st.plotly_chart(fig_cx_eq, use_container_width=True)

        st_html(section_title("Calo dal Massimo Storico"))
        fig_cx_dd = go.Figure()
        fig_cx_dd.add_trace(go.Scatter(
            x=_cx_nav.index, y=_cx_nav["drawdown"], fill="tozeroy", mode="lines",
            line=dict(color=NEG, width=1.2), fillcolor="rgba(236,101,123,0.15)",
            hovertemplate="%{x|%d %b %Y}<br>Calo: %{y:.2f}%<extra></extra>", name="Calo"
        ))
        fig_cx_dd.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color=MUTED, family="Inter"),
            xaxis=dict(showgrid=False, tickfont=dict(size=10)),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,247,237,0.05)', tickfont=dict(size=10), ticksuffix="%"),
            margin=dict(t=4, b=10, l=10, r=10), height=110, showlegend=False
        )
        st.plotly_chart(fig_cx_dd, use_container_width=True)

        st_html(section_title("Matrice dei Rendimenti"))
        st_html(render_monthly_returns_html_table(_cx_nav))

        # Costo reale del TER — l'unica "statistica operativa" che ha senso
        # per un PAC buy-and-hold: non ci sono operazioni da misurare (tasso
        # di successo, fattore di profitto), c'è solo il costo strutturale.
        _cx_ter_annual = 0.003788  # TER ponderato corretto — vedi research/convex/, pesi capitale 45/15/25/7.5/7.5
        _cx_ter_eur_year = cap_convex_input * _cx_ter_annual
        _cx_pos_months = int((_cx_ret > 0).sum())
        _cx_tot_months = int(len(_cx_ret))
        st_html(section_title("Costo Strutturale e Regolarità"))
        st.caption("Convex non ha operazioni da misurare (nessun tasso di successo/fattore di profitto: è un portafoglio a lungo termine, non trading attivo). Ciò che conta è il costo ricorrente e la costanza dei rendimenti.")
        e1, e2, e3 = st.columns(3)
        e1.metric("TER Ponderato Reale", f"{_cx_ter_annual*100:.3f}%/anno", help="Costo dei 5 ETF pesato sul capitale reale (non sul nozionale a leva) — corretto rispetto al whitepaper originale.")
        e2.metric("Costo TER su Capitale Attuale", f"€ {_cx_ter_eur_year:,.0f}/anno", help="TER ponderato × capitale Convex inserito nella barra laterale.")
        e3.metric("Mesi Positivi (storico)", f"{_cx_pos_months}/{_cx_tot_months} ({_cx_pos_months/_cx_tot_months*100:.0f}%)", help="Quota di mesi con rendimento positivo sul backtest corretto 2000–2026.")


# ==============================================================================
# TAB 2: 🏛️ SINTESI GLOBALE (DUAL-ENGINE: APEX + CONVEX)
# ==============================================================================
with tab_dual:
    st_html(f"""
    <div class="glass-card-accent">
        <div style="font-family: {FRAUNCES}; font-size: 19px; font-weight: 600; color: {BADGE_TEXT}; margin-bottom: 6px;">
            La Sinergia Quantitativa: Perché Insieme Abbattono il Rischio
        </div>
        <div style="font-size: 13.5px; color: {MUTED}; line-height: 1.6;">
            {m_dual['synergy_summary']}
            <br>La correlazione reale tra i due motori è <strong>+{m_dual['correlation']:.2f}</strong> (calcolata sulla serie storica comune, non stimata): quando uno rallenta o si rifugia in Cash, l'altro continua a comporre capitale, generando una curva di equity più lineare.
        </div>
    </div>
    """)

    # Scorecard Congiunta
    d1, d2, d3, d4, d5, d6 = st.columns(6)
    d1.metric("Patrimonio Totale", f"€ {unified['total_wealth_eur']:,.0f}")
    d2.metric("Crescita Annua Netta", f"{m_dual['cagr_net']*100:.2f}%", f"Lordo {m_dual['cagr_gross']*100:.2f}%",
              help="CAGR netto (tasse comprese) e, sotto, lordo (prima delle tasse).")
    d3.metric("Oscillazione Combinata", f"{m_dual['volatility']*100:.2f}%", help="Volatilità: quanto varia il valore nel tempo.")
    d4.metric("Rendimento/Rischio", f"{m_dual['sharpe']:.2f}", help="Sharpe: rendimento ottenuto per ogni unità di rischio.")
    d5.metric("Perdita Massima Storica", f"{m_dual['max_drawdown']*100:.2f}%", f"vs {m_apex['max_drawdown']*100:.1f}% Apex da solo", help="Il calo peggiore mai registrato dal punto più alto al più basso.")
    d6.metric("Rendimento/Perdita Max", f"{m_dual['calmar']:.2f}", help="Calmar: crescita annua rapportata alla peggior perdita subita.")

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

    # Raggi X Asset Class Aggregate
    col_chart, col_bars = st.columns([1.2, 1.0])
    with col_chart:
        st_html(section_title("Raggi X dell'Esposizione Macro Aggregata"))
        macro_b = dict(unified["macro_breakdown"])
        macro_b["Liquidità Reale"] = unified["idle_cash_pct"]
        labels = list(macro_b.keys())
        values_pct = [v * 100.0 for v in macro_b.values()]

        fig_donut = go.Figure(data=[go.Pie(
            labels=labels,
            values=values_pct,
            hole=.55,
            marker=dict(colors=[POS, "#8B7FC7", "#E0A96D", ACCENT, "#F7931A", "#5B534B"]),
            textinfo='label+percent',
            textposition='outside',
            showlegend=False
        )])
        fig_donut.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color=MUTED, family="Inter"),
            margin=dict(t=10, b=10, l=10, r=10),
            height=300
        )
        st.plotly_chart(fig_donut, use_container_width=True)

    with col_bars:
        st_html(section_title("Ripartizione Dettagliata per Classe"))
        for cls_name, w_val in macro_b.items():
            st_html(f"""
            <div style="margin-bottom: 10px;">
                <div style="display:flex; justify-content:space-between; font-size:12.5px; margin-bottom:3px;">
                    <span style="color:{BADGE_TEXT}; font-weight:600;">{cls_name}</span>
                    <span style="font-family:{MONO}; color:{ACCENT}; font-weight:700;">{w_val*100:.1f}%</span>
                </div>
                <div style="width:100%; height:6px; background:rgba(255,247,237,0.08); border-radius:3px; overflow:hidden;">
                    <div style="width:{min(100, w_val*100):.1f}%; height:100%; background:{ACCENT}; border-radius:3px;"></div>
                </div>
            </div>
            """)
        st.caption(
            f"Esposizione nozionale totale: {unified['total_notional_pct']*100:.0f}% del capitale "
            f"(oltre il 100% è normale — leva 1.5x di NTSG interamente incorporata nell'ETF, "
            f"nessun debito a margine personale)."
        )

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

    # Proiezione a lungo termine — stima deterministica basata su CAGR e
    # volatilità storici reali, NON una simulazione Monte Carlo (non genera
    # scenari casuali): il ventaglio P10/P90 è ottenuto scalando il CAGR
    # storico di ± una deviazione standard della volatilità osservata.
    st_html(section_title(f"Proiezione a Lungo Termine (Capitale Iniziale €{unified['total_wealth_eur']:,.0f} + PAC €{pac_input:.0f}/m)"))
    st.caption("Stima da CAGR e volatilità storici reali, non una simulazione: i risultati futuri potranno differire.")

    horizons = [5, 10, 15, 20]
    proj_rows = []
    cagr_m = m_dual["cagr_net"]
    vol_m = m_dual["volatility"]

    for yr in horizons:
        tot_v = unified["total_wealth_eur"]
        for m in range(yr * 12):
            tot_v += pac_input * ((1.0 + pac_growth_input) ** (m // 12))

        p50 = tot_v * ((1.0 + cagr_m) ** yr)
        p10 = tot_v * ((1.0 + max(cagr_m - vol_m, -0.5)) ** yr)
        p90 = tot_v * ((1.0 + cagr_m + vol_m) ** yr)

        proj_rows.append({
            "Orizzonte": f"{yr} Anni",
            "Totale Versato": f"€ {tot_v:,.0f}",
            "Scenario Prudente": f"€ {p10:,.0f}",
            "Scenario Base": f"€ {p50:,.0f}",
            "Scenario Favorevole": f"€ {p90:,.0f}",
        })
    st_html(render_html_table(pd.DataFrame(proj_rows), right_align_cols=["Totale Versato", "Scenario Prudente", "Scenario Base", "Scenario Favorevole"]))
    st.caption(f"Massimo ribasso storico del portafoglio combinato: {m_dual['max_drawdown']*100:.1f}%.")


# ==============================================================================
# TAB 3: ⚡ APEX ENGINE (IL MOTORE TATTICO ALPHA — automatico, solo monitoraggio)
# ==============================================================================
with tab_apex:
    # ==========================================================================
    # VERSIONE — Completa (basket 15 titoli) o Semplice (1 ETF, USMV). Un
    # precedente candidato (VLUE) è stato scartato: il suo apparente vantaggio
    # derivava per ~25% da un solo titolo (Micron) durante un rally isolato
    # 2025-2026, non da un vero effetto fattoriale (VLUE ha perso in 3 dei 5
    # anni testati — research/test_weekly_apex_vlue_deep_dive.py). USMV è
    # scelto per bassa concentrazione (titolo più pesante ~1.6%), non perché
    # batte la versione Completa — vedi research/apex_simple_etf_README.md.
    # ==========================================================================
    apex_versione = st.segmented_control(
        "Versione", options=["Completa", "Semplice"], default="Completa",
        label_visibility="collapsed", key="apex_versione"
    ) or "Completa"

    _apex_simple_path = os.path.join(os.path.dirname(__file__), "apex_simple_etf_returns.csv")
    _m_apex_active = m_apex
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

    st_html(f"""
    <div class="glass-card">
        <div style="font-family: {FRAUNCES}; font-size: 18px; font-weight: 600; color: {BADGE_TEXT}; margin-bottom: 6px;">
            Filosofia Operativa: Precisione Tattica & Difesa Attiva
        </div>
        <div style="font-size: 13px; color: {MUTED}; line-height: 1.6;">
            {m_apex['philosophy'] if apex_versione == "Completa" else "Stesso motore di timing macro (trend 40w/20w con isteresi, vol-targeting di portafoglio). La sleeve azionaria è un unico ETF (USMV) invece del basket di 15 titoli a bassa volatilità."}
            Nei periodi di stress sistemico (come il crollo COVID o il bear market 2022), Apex chiude progressivamente le classi in rottura di trend e <strong>si rifugia fino al 100% in Liquidità/Cash</strong>, azzerando le perdite di coda. Il motore opera in automatico (decisione venerdì, esecuzione lunedì) — questa scheda è solo monitoraggio, nessuna azione manuale è richiesta.
        </div>
    </div>
    """)

    # Scorecard Metriche Apex
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Crescita Annua Netta (9a)", f"{_m_apex_active['cagr_net']*100:.2f}%", f"Lordo {_m_apex_active['cagr_gross']*100:.2f}%",
              help="CAGR netto (tasse comprese) e, sotto, lordo (prima delle tasse).")
    k2.metric("Oscillazione", f"{_m_apex_active['volatility']*100:.2f}%", help="Volatilità: quanto varia il valore nel tempo.")
    k3.metric("Rendimento/Rischio", f"{_m_apex_active['sharpe']:.2f}", help="Sharpe: rendimento ottenuto per ogni unità di rischio.")
    k4.metric("Rendimento/Ribassi", f"{_m_apex_active['sortino']:.2f}", help="Sortino: come Sharpe, ma guarda solo ai cali, non alle oscillazioni positive.")
    k5.metric("Perdita Massima", f"{_m_apex_active['max_drawdown']*100:.2f}%", help="Il calo peggiore mai registrato dal punto più alto al più basso.")
    k6.metric("Rendimento/Perdita Max", f"{_m_apex_active['calmar']:.2f}", help="Calmar: crescita annua rapportata alla peggior perdita subita.")

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

    # Dati live reali per lo stato macro settimanale — niente più prezzi
    # d'esempio hardcoded: se il dato non è disponibile viene mostrato "N/D",
    # mai un valore inventato spacciato per reale.
    _class_info = [
        ("Equities", "SPY", "Azionario"),
        ("Bonds", "IEF", "Obbligazioni"),
        ("Gold", "GLD", "Oro Fisico"),
        ("Crypto", "BTC-USD", "Bitcoin"),
    ]
    _macro_live = apex_data.get("macro", {})
    _hyst = apex_data.get("v2_state", {}).get("hysteresis", {})
    _alloc_live = apex_data.get("allocations", {})

    col_macro, col_ord = st.columns([1.4, 1.0])
    with col_macro:
        st_html(section_title("Stato Trend Macro Settimanale"))
        macro_table_data = []
        for cls, ticker, label in _class_info:
            _px = _macro_live.get(ticker, {}).get("price")
            _active = _hyst.get(cls)
            _w = _alloc_live.get(cls)
            macro_table_data.append({
                "Classe": f"{label} ({ticker})",
                "Stato": ("ATTIVO" if _active else "IN LIQUIDITÀ") if _active is not None else "N/D",
                "Prezzo": f"${_px:,.2f}" if _px is not None else "N/D",
                "Peso Attuale": f"{_w:.1f}%" if _w is not None else "N/D",
            })
        st_html(render_html_table(pd.DataFrame(macro_table_data), right_align_cols=["Prezzo", "Peso Attuale"]))
        if not _hyst:
            st.caption("Dati live non raggiungibili in questo momento — tabella non disponibile.")

    with col_ord:
        st_html(section_title("Stato Operativo Settimanale"))
        if _hyst:
            _active_classes = [c for c, v in _hyst.items() if v]
            _inactive_classes = [c for c, v in _hyst.items() if not v]
            _cash_w = float(_alloc_live.get("Cash", 0.0))
            if _cash_w >= 50.0:
                _status_color, _status_title = NEG, "⚠ REGIME DIFENSIVO"
                _status_body = (
                    f"Il {_cash_w:.0f}% del capitale Apex è in liquidità. "
                    f"Classi ancora in trend positivo: {', '.join(_active_classes) if _active_classes else 'nessuna'}."
                )
            else:
                _status_color, _status_title = POS, "✓ NESSUN ORDINE DI EMERGENZA"
                _inactive_txt = f" In liquidità: {', '.join(_inactive_classes)}." if _inactive_classes else ""
                _status_body = (
                    f"{len(_active_classes)}/4 classi macro attive.{_inactive_txt} "
                    f"Il paniere azionario è confermato per il trimestre in corso."
                )
        else:
            _status_color, _status_title = MUTED, "STATO NON DISPONIBILE"
            _status_body = "Dati live di Apex non raggiungibili in questo momento."

        st_html(f"""
        <div style="background: rgba(255,247,237,0.03); border: 1px solid {BORDER}; border-radius: 8px; padding: 16px;">
            <div style="color: {_status_color}; font-weight: 700; font-size: 14px; margin-bottom: 4px;">{_status_title}</div>
            <div style="font-size: 12.5px; color: {MUTED}; line-height: 1.5;">{_status_body}</div>
            <div style="font-size: 11px; color: {MUTED_2}; margin-top: 10px; border-top: 1px solid {BORDER}; padding-top: 8px;">
                Cadenza operativa: decisione venerdì, esecuzione lunedì (automatica).
            </div>
        </div>
        """)

    if apex_versione == "Semplice":
        st_html(section_title("Sleeve Azionaria — USMV (ETF Unico)"))
        st.caption("Nessun paniere: quando la classe Azionario è attiva, il 100% dell'esposizione è su un unico ETF (USMV, iShares MSCI USA Min Vol Factor).")
    else:
        st_html(section_title("Paniere Azionario S&P 500 Low-Vol (15 Titoli - Buffer Rank 20)"))
        open_pos = apex_portfolio.get("open_positions", {})
        if open_pos:
            pos_rows = []
            for sym, pinfo in open_pos.items():
                if not pinfo.get("is_crypto", False):
                    pos_rows.append({
                        "Titolo": sym,
                        "Data Ingresso": pinfo.get("entry_date", "N/A"),
                        "Prezzo Carico ($)": f"${pinfo.get('entry_price', 0):.2f}",
                        "Prezzo Attuale ($)": f"${pinfo.get('current_price', 0):.2f}",
                        "Peso (%)": f"{pinfo.get('weight', 0)*100:.2f}%",
                        "Controvalore (€)": f"€ {cap_apex_input * pinfo.get('weight', 0):,.0f}"
                    })
            st_html(render_html_table(pd.DataFrame(pos_rows), right_align_cols=["Prezzo Carico ($)", "Prezzo Attuale ($)", "Peso (%)", "Controvalore (€)"]))

    st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)

    # Curva Equity vs Benchmark — dati reali da equity.json, confrontati con
    # SPY (proxy azionario globale) recuperato live. Nessun dato inventato:
    # se lo storico o il benchmark non sono disponibili, il grafico è omesso.
    st_html(section_title("Curva Equity vs Benchmark (SPY)"))
    if apex_versione == "Semplice":
        st.caption("Backtest su USMV (2017+) — Apex non ha mai tradato realmente questa versione: solo i 15 titoli (Completa) sono il conto vero.")
    if apex_versione == "Semplice" and os.path.exists(_apex_simple_path):
        _eq_hist = [{"date": d.strftime("%Y-%m-%d"), "close": v} for d, v in _se_df["nav_net"].items()]
    else:
        _eq_path = os.path.join(os.path.dirname(__file__), "equity.json")
        _eq_hist = json.load(open(_eq_path)).get("history", []) if os.path.exists(_eq_path) else []
    if _eq_hist:
        _eq_df = pd.DataFrame(_eq_hist)
        _eq_df["date"] = pd.to_datetime(_eq_df["date"])
        _eq_df = _eq_df.sort_values("date").drop_duplicates("date", keep="last")
        _eq_base = _eq_df["close"].iloc[0]
        _eq_norm = (_eq_df["close"] / _eq_base) * 100.0

        fig_eq = go.Figure()
        fig_eq.add_trace(go.Scatter(x=_eq_df["date"], y=_eq_norm, mode="lines",
                                     name="Apex Engine", line=dict(color=POS, width=2)))

        @st.cache_data(ttl=3600)
        def _fetch_spy_benchmark(start_date_str):
            try:
                url = f"https://query2.finance.yahoo.com/v8/finance/chart/SPY?period1={int(pd.Timestamp(start_date_str).timestamp())}&period2={int(pd.Timestamp.now().timestamp())}&interval=1d"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                d = json.loads(urllib.request.urlopen(req, timeout=4).read().decode())
                r = d["chart"]["result"][0]
                ts = pd.to_datetime(r["timestamp"], unit="s")
                closes = r["indicators"]["quote"][0]["close"]
                return pd.Series(closes, index=ts).dropna()
            except Exception:
                return None

        _spy = _fetch_spy_benchmark(str(_eq_df["date"].iloc[0].date()))
        if _spy is not None and len(_spy) > 1:
            _spy_norm = (_spy / _spy.iloc[0]) * 100.0
            fig_eq.add_trace(go.Scatter(x=_spy_norm.index, y=_spy_norm.values, mode="lines",
                                         name="SPY (benchmark)", line=dict(color=MUTED, width=1.5, dash="dot")))
        else:
            st.caption("Benchmark SPY non raggiungibile in questo momento — mostrata solo la curva Apex.")

        fig_eq.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color=MUTED, family="Inter"),
            margin=dict(t=10, b=10, l=10, r=10), height=320,
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            yaxis_title="Base 100"
        )
        st.plotly_chart(fig_eq, use_container_width=True)

        # Calo dal Massimo Storico — stessa logica di Apex Engine, dati reali
        _eq_dd = _eq_df.set_index("date")[["close"]].rename(columns={"close": "value"})
        _eq_dd["roll_max"] = _eq_dd["value"].cummax()
        _eq_dd["drawdown"] = (_eq_dd["value"] - _eq_dd["roll_max"]) / _eq_dd["roll_max"] * 100.0
        st_html(section_title("Calo dal Massimo Storico"))
        if apex_versione == "Semplice":
            st.caption(
                f"Backtest USMV, stessa finestra delle metriche sopra "
                f"({_eq_df['date'].iloc[0].date()} → {_eq_df['date'].iloc[-1].date()})."
            )
        else:
            st.caption(
                f"Grafico dai {len(_eq_df)} punti di storico reale disponibili "
                f"({_eq_df['date'].iloc[0].date()} → {_eq_df['date'].iloc[-1].date()}). "
                "Il Calo Massimo mostrato nelle metriche sopra copre un periodo più lungo "
                "e validato: numeri diversi, finestre diverse, non un errore."
            )
        fig_dd = go.Figure()
        fig_dd.add_trace(go.Scatter(
            x=_eq_dd.index, y=_eq_dd["drawdown"], fill="tozeroy", mode="lines",
            line=dict(color=NEG, width=1.2), fillcolor="rgba(236,101,123,0.15)",
            hovertemplate="%{x|%d %b %Y}<br>Calo: %{y:.2f}%<extra></extra>", name="Calo"
        ))
        fig_dd.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color=MUTED, family="Inter"),
            xaxis=dict(showgrid=False, tickfont=dict(size=10)),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,247,237,0.05)', tickfont=dict(size=10), ticksuffix="%"),
            margin=dict(t=4, b=10, l=10, r=10), height=110, showlegend=False
        )
        st.plotly_chart(fig_dd, use_container_width=True)

        # Matrice dei Rendimenti Mensili e Annuali — stessa logica di Apex Engine
        st_html(section_title("Matrice dei Rendimenti"))
        st_html(render_monthly_returns_html_table(_eq_dd))
    else:
        st.caption("Storico equity non disponibile in questo momento.")

    # Statistiche Operative — stessa logica di Apex Engine, dati reali da
    # portfolio.json/trade_history. Nessun dato inventato: se non c'è storico
    # di operazioni chiuse, la sezione è omessa. Non si applica alla versione
    # Semplice: quello storico è delle operazioni reali sui 15 titoli, non di
    # un backtest ipotetico su USMV — mostrarlo sarebbe fuorviante, non un dato
    # inventato ma un dato reale usato nel contesto sbagliato.
    _hist_stats = apex_portfolio.get("trade_history", []) if apex_versione == "Completa" else []
    if apex_versione == "Semplice":
        st.caption("Statistiche Operative e Ultime Operazioni non disponibili per la versione Semplice: è un backtest, non ha uno storico di operazioni reali proprio (quello mostrato in Completa è dei 15 titoli).")
    if _hist_stats:
        _wins = [t for t in _hist_stats if t.get("profit_pct", 0) > 0]
        _losses = [t for t in _hist_stats if t.get("profit_pct", 0) <= 0]
        _win_rate = (len(_wins) / len(_hist_stats) * 100) if _hist_stats else 0.0
        _gross_profit = sum(t["profit_pct"] for t in _wins)
        _gross_loss = abs(sum(t["profit_pct"] for t in _losses))
        _profit_factor = _gross_profit / _gross_loss if _gross_loss != 0 else 0.0
        _expectancy_pct = sum(t["profit_pct"] for t in _hist_stats) / len(_hist_stats) if _hist_stats else 0.0

        def _kpi_item(title, value, subtext="", badge_text=None, badge_color=None, val_color=None):
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

        st_html(section_title("Statistiche Operative"))
        _strip_items = [
            _kpi_item("Tasso di Successo", f"{_win_rate:.1f}%", f"{len(_wins)} vincenti su {len(_hist_stats)}",
                       badge_text=f"{len(_wins)}/{len(_hist_stats)}"),
            _kpi_item("Aspettativa per Trade", f"{_expectancy_pct:+.2f}%", "Rendimento atteso medio",
                       badge_text="EDGE STATISTICO", badge_color=BADGE_POS_BG, val_color=POS if _expectancy_pct > 0 else NEG),
            _kpi_item("Fattore di Profitto", f"{_profit_factor:.2f}", "Profitti lordi / perdite",
                       badge_text=("ECCELLENTE" if _profit_factor >= 1.5 else "STABILE"),
                       badge_color=(BADGE_POS_BG if _profit_factor >= 1.5 else BADGE_NEUTRAL_BG)),
        ]
        _p_list = [t.get("profit_pct", 0.0) for t in _hist_stats]
        _max_idx, _min_idx = _p_list.index(max(_p_list)), _p_list.index(min(_p_list))
        _durations = []
        for t in _hist_stats:
            try:
                _d_in = datetime.datetime.strptime(str(t.get("entry_date", "")), "%Y-%m-%d")
                _d_out = datetime.datetime.strptime(str(t.get("exit_date", "")), "%Y-%m-%d")
                _durations.append(max(1, (_d_out - _d_in).days))
            except Exception:
                pass
        _avg_days = int(round(sum(_durations) / len(_durations))) if _durations else 0
        _strip_items += [
            _kpi_item("Miglior Operazione", _hist_stats[_max_idx].get("ticker", "-"), f"{_hist_stats[_max_idx].get('profit_pct', 0.0):+.2f}%", val_color=POS),
            _kpi_item("Peggior Operazione", _hist_stats[_min_idx].get("ticker", "-"), f"{_hist_stats[_min_idx].get('profit_pct', 0.0):+.2f}%", val_color=NEG),
            _kpi_item("Durata Media", f"{_avg_days}g", "giorni in posizione"),
        ]
        st_html(f'<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 4px 8px; background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 10px 14px; margin-bottom: 20px;">{"".join(_strip_items)}</div>')

    # Ultime Operazioni Eseguite — dati reali da portfolio.json/trade_history
    if apex_versione == "Completa":
        st_html(section_title("Ultime Operazioni Eseguite"))
    _trades = apex_portfolio.get("trade_history", []) if apex_versione == "Completa" else []
    if _trades:
        _tr_rows = []
        for t in _trades[-15:][::-1]:
            _tr_rows.append({
                "Titolo": t.get("ticker", "—"),
                "Ingresso": t.get("entry_date", "—"),
                "Uscita": t.get("exit_date", "—"),
                "Rendimento %": f"{t.get('profit_pct', 0):+.2f}%",
                "Motivazione": t.get("reason", "—"),
            })
        st_html(render_html_table(pd.DataFrame(_tr_rows), right_align_cols=["Rendimento %"]))
    else:
        st.caption("Nessuna operazione storica disponibile in questo momento.")
