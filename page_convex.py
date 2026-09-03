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

import convex_engine

# st.set_page_config() rimosso: la pagina gira dentro main.py (st.navigation), che lo imposta una sola volta.

# ==============================================================================
# HTML RENDERING HELPERS & STYLING (DARK GLASSMORPHISM — identici ad Apex Engine)
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
</style>
""")

# Design Tokens (identici ad Apex Engine — stesso sistema visivo)
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

FRAUNCES = "'Fraunces', Georgia, serif"
MONO = "'JetBrains Mono', monospace"

MESI_IT = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]

def section_title(text, top="26px", bottom="10px"):
    """Identico ad Apex Engine (davbenx/apex-engine/app.py) — niente emoji,
    solo tipografia Fraunces."""
    return f'<div style="font-family:{FRAUNCES}; font-size:16px; font-weight:600; letter-spacing:-0.1px; margin:{top} 0 {bottom};">{text}</div>'

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

def render_html_table(df, right_align_cols=None):
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
# PREZZI LIVE DEI 5 STRUMENTI (cache 15 minuti, fallback dichiarato se il
# recupero fallisce — mai spacciato per prezzo di mercato)
# ==============================================================================
_CONVEX_BASE_PRICES = {"NTSG": 100.0, "AVWS": 50.0, "DBMFE": 25.0, "PPFB": 50.0, "WBTC": 100.0}
_CONVEX_YF_TICKERS = {"NTSG": "NTSG.MI", "AVWS": "AVWS.DE", "DBMFE": "DBMF", "PPFB": "PPFB.MI", "WBTC": "BTC-USD"}

@st.cache_data(ttl=900)
def fetch_convex_live_prices():
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

# Benchmark SPY — stesso strumento e stesso meccanismo di fetch usato da
# Apex Engine (query2.finance.yahoo.com, cache 1h). VT sarebbe un confronto
# più aderente per la sola sleeve azionaria di Convex, ma non esiste ancora
# una serie storica scaricata in questo progetto: SPY resta la scelta più
# semplice e coerente con la convenzione già usata da Apex.
@st.cache_data(ttl=3600)
def load_benchmark_spy():
    try:
        url = "https://query2.finance.yahoo.com/v8/finance/chart/SPY?range=2y&interval=1d"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        res = json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
        data_spy = res['chart']['result'][0]
        timestamps = pd.to_datetime(data_spy['timestamp'], unit='s')
        close = data_spy['indicators']['quote'][0]['close']
        return pd.Series(close, index=timestamps).ffill().dropna()
    except Exception:
        return pd.Series(dtype=float)

convex_prices, convex_prices_live = fetch_convex_live_prices()

# ==============================================================================
# INTESTAZIONE
# ==============================================================================
_logo_b64 = get_logo_b64()
_logo_tag = (f'<img src="data:image/png;base64,{_logo_b64}" style="height: 48px; width: auto; object-fit: contain;" />'
             if _logo_b64 else '🛡️')

_cp_path = os.path.join(os.path.dirname(__file__), "convex_portfolio.json")
_last_updated = None
if os.path.exists(_cp_path):
    try:
        with open(_cp_path, "r", encoding="utf-8") as f:
            _last_updated = json.load(f).get("last_updated")
    except Exception:
        pass
_is_fresh = False
if _last_updated:
    try:
        _days = (datetime.date.today() - datetime.datetime.strptime(_last_updated, "%Y-%m-%d").date()).days
        _is_fresh = _days <= 35
    except Exception:
        pass
_status_color = POS if _is_fresh else MUTED_DOT
_status_label = f"Aggiornato al {_last_updated}" if _last_updated else "Nessun dato salvato"

col_logo, col_stat = st.columns([3, 2])
with col_logo:
    st_html(f"""
    <div style="display: flex; align-items: center; gap: 14px; padding: 6px 0;">
        <div style="background: {SURFACE}; border: 1px solid {BORDER}; padding: 5px 9px; border-radius: 10px; display: flex; align-items: center; justify-content: center;">
            {_logo_tag}
        </div>
        <div>
            <div style="font-family: {FRAUNCES}; font-size: 22px; font-weight: 600; letter-spacing: -0.4px; line-height: 1.2; color: {BADGE_TEXT};">Convex Stack</div>
            <div style="font-size: 11px; font-weight: 600; opacity: 0.65; letter-spacing: 0.4px; text-transform: uppercase; margin-top: 1px;">
                Portafoglio Multi-Asset a Leva Sistematica
            </div>
        </div>
    </div>
    """)
with col_stat:
    st_html(f"""
    <div style="text-align: right; padding-top: 10px;">
        <div style="font-size: 11px; color: {MUTED};">
            <span style="width:6px; height:6px; border-radius:50%; background:{_status_color}; display:inline-block; margin-right:5px;"></span>{_status_label}
        </div>
        <div style="font-size: 11px; color: {MUTED_2}; margin-top: 2px;">
            Ribilanciamento PAC: 1° del mese
        </div>
    </div>
    """)

# ==============================================================================
# SCHEDE: PORTAFOGLIO, METRICHE, GUIDA — stessi 3 nomi e stesso ordine di
# Apex Engine, senza emoji (Apex reale non ne usa nei nomi di scheda).
# ==============================================================================
tab_pf, tab_metriche, tab_guida = st.tabs(["Portafoglio", "Metriche", "Guida"])

with tab_pf:
    # ==========================================================================
    # VERSIONE — Completa (5 strumenti) o Semplice (4, senza AVWS). Validato:
    # research/convex/test_convex_ntsg_grid_extended.py — redistribuzione
    # proporzionale, nessun costo su Sharpe/MaxDD sul periodo reale 2019+,
    # piccolo costo di MaxDD sulla storia intera pre-2019 (proxy).
    # ==========================================================================
    versione = st.segmented_control(
        "Versione", options=["Completa", "Semplice"], default="Completa",
        label_visibility="collapsed", key="convex_versione"
    ) or "Completa"
    active_instruments = (
        convex_engine.CONVEX_INSTRUMENTS if versione == "Completa"
        else convex_engine.CONVEX_INSTRUMENTS_SIMPLE
    )
    if versione == "Semplice":
        st.caption(
            "4 strumenti invece di 5: niente AVWS (small cap value), 15% del capitale "
            "redistribuito su NTSG/DBMFE/PPFB/WBTC. Sul periodo con dati reali (2019+) "
            "il costo è nullo (Sharpe e MaxDD leggermente migliori); sulla storia intera "
            "dal 2000 (in parte ricostruita per proxy) costa ~2.6 punti di MaxDD in più "
            "a fronte di uno Sharpe quasi identico."
        )

    # ==========================================================================
    # MODULO DI INPUT — le quote per strumento non le conosce nessun motore
    # automatico: le sai solo tu, che tieni il conto reale. Nessun campo
    # "capitale totale" a parte: il valore si ricava da quote × prezzo + cassa.
    # ==========================================================================
    st_html(section_title("I Tuoi Numeri", top="8px"))
    st.caption("Inserisci le quote possedute di ciascuno strumento e la liquidità pronta per il PAC di questo mese.")

    _saved_holdings = {}
    if os.path.exists(_cp_path):
        try:
            with open(_cp_path, "r", encoding="utf-8") as f:
                _saved_holdings = {k: v.get("shares", 0.0) for k, v in json.load(f).get("holdings", {}).items()}
        except Exception:
            pass

    h_cols = st.columns(len(active_instruments))
    convex_holdings = {}
    for i, (key, info) in enumerate(active_instruments.items()):
        with h_cols[i]:
            convex_holdings[key] = st.number_input(
                f"{key} — {info['name']}",
                min_value=0.0,
                value=float(_saved_holdings.get(key, 0.0)),
                step=1.0,
                format="%.2f",
                help=f"Quote possedute. Prezzo attuale: {convex_prices[key]:.2f} €"
                     + ("" if convex_prices_live[key] else " (prezzo di base, mercato non raggiungibile)")
            )

    c_pac, c_cash = st.columns(2)
    with c_pac:
        pac_input = st.number_input("Liquidità Pronta per il PAC di Questo Mese (€)", min_value=0.0, value=600.0, step=50.0, format="%.0f")
    with c_cash:
        cash_input = st.number_input("Cassa Residua Non Investita (€)", min_value=0.0, value=0.0, step=50.0, format="%.0f")

    _n_live = sum(convex_prices_live.values())
    if _n_live < len(convex_prices_live):
        st.caption(f"Prezzo di mercato non raggiungibile per {len(convex_prices_live) - _n_live}/{len(convex_prices_live)} titoli: usato un prezzo di base, non il prezzo reale.")

    convex_report = convex_engine.evaluate_convex_stack(
        current_holdings=convex_holdings,
        market_prices=convex_prices,
        monthly_pac_eur=pac_input,
        cash_balance=cash_input,
        instruments=active_instruments
    )

    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)

    # ==========================================================================
    # AZIONE DEL MESE — sempre visibile, nessun click richiesto
    # ==========================================================================
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
                Nessuna vendita necessaria. Bitcoin e Oro sono entrambi sotto la soglia dell'11.25% (target ×1.5).
            </div>
        </div>
        """)

    # ==========================================================================
    # IL "PERCHÉ" DEL CONSIGLIO
    # ==========================================================================
    if convex_report.total_value > 0:
        col_chart, col_bars = st.columns([1.1, 1.0])
        with col_chart:
            st_html(section_title("Composizione del Portafoglio"))
            _COLOR_MAP = {"NTSG": POS, "AVWS": "#8B7FC7", "DBMFE": "#E0A96D", "PPFB": ACCENT, "WBTC": "#F7931A"}
            labels = [f"{k} ({i['name'][:18]})" for k, i in active_instruments.items()]
            values_pct = [convex_report.assets[k].current_weight * 100.0 for k in active_instruments]
            fig_donut = go.Figure(data=[go.Pie(
                labels=labels, values=values_pct, hole=.55,
                marker=dict(colors=[_COLOR_MAP[k] for k in active_instruments]),
                textinfo='label+percent', textposition='outside', showlegend=False
            )])
            fig_donut.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color=MUTED, family="Inter"),
                margin=dict(t=10, b=10, l=10, r=10), height=300
            )
            st.plotly_chart(fig_donut, use_container_width=True)

        with col_bars:
            st_html(section_title("Pesi Attuali vs Target"))
            for k, st_info in convex_report.assets.items():
                if st_info.current_weight < st_info.tolerance_min:
                    stato, col = "sottopesato", ACCENT
                elif st_info.current_weight > st_info.tolerance_max:
                    stato, col = "sopra soglia", NEG
                else:
                    stato, col = "in banda", POS
                st_html(f"""
                <div style="margin-bottom: 10px;">
                    <div style="display:flex; justify-content:space-between; font-size:12.5px; margin-bottom:3px;">
                        <span style="color:{BADGE_TEXT}; font-weight:600;">{k} — {stato}</span>
                        <span style="font-family:{MONO}; color:{col}; font-weight:700;">{st_info.current_weight*100:.1f}% / {st_info.target_weight*100:.1f}%</span>
                    </div>
                    <div style="width:100%; height:6px; background:rgba(255,247,237,0.08); border-radius:3px; overflow:hidden;">
                        <div style="width:{min(100, st_info.current_weight*100):.1f}%; height:100%; background:{col}; border-radius:3px;"></div>
                    </div>
                </div>
                """)

        st_html(section_title("Posizioni Attuali"))
        cx_rows = []
        for k, st_info in convex_report.assets.items():
            cx_rows.append({
                "Strumento": k,
                "Nome": st_info.name,
                "Quote": f"{st_info.current_shares:,.2f}",
                "Prezzo": f"€ {st_info.current_price:,.2f}",
                "Peso": f"{st_info.current_weight*100:.2f}%",
                "Controvalore": f"€ {st_info.current_value:,.0f}",
                "Regime Fiscale": "Reddito Diverso (compensa minus)" if st_info.tax_type == "REDDITO_DIVERSO" else "Reddito di Capitale (non compensa)"
            })
        st_html(render_html_table(pd.DataFrame(cx_rows), right_align_cols=["Quote", "Prezzo", "Peso", "Controvalore"]))
        st.caption(f"Patrimonio totale: € {convex_report.total_value:,.0f}")

with tab_metriche:
    _cx_ret_filename = "convex_monthly_returns.csv" if versione == "Completa" else "convex_simple_no_avws_returns.csv"
    _cx_ret_path = os.path.join(os.path.dirname(__file__), _cx_ret_filename)
    if versione == "Semplice":
        st.caption("Statistiche calcolate sulla versione a 4 strumenti (senza AVWS).")
    if os.path.exists(_cx_ret_path):
        _cx_ret = pd.read_csv(_cx_ret_path, index_col=0, parse_dates=True).iloc[:, 0]
        _cx_nav = pd.DataFrame({"value": (1.0 + _cx_ret).cumprod() * 100.0})
        _cx_nav["roll_max"] = _cx_nav["value"].cummax()
        _cx_nav["drawdown"] = (_cx_nav["value"] - _cx_nav["roll_max"]) / _cx_nav["roll_max"] * 100.0

        n_yrs = len(_cx_ret) / 12.0
        cagr_gross = (_cx_nav["value"].iloc[-1] / _cx_nav["value"].iloc[0]) ** (1.0 / n_yrs) - 1.0
        # netto: fattore derivato dal modello fiscale a due categorie (UCITS senza
        # compensazione minusvalenze, ETC/ETP con compensazione) calcolato sulla
        # finestra piena 2000-2026 in research/convex/convex_twobucket_v2.pkl
        # ("full": gross 8.01%/anno, netto 6.96%/anno) — applicato come fattore
        # relativo, non ricalcolato da zero qui: approssimazione dichiarata.
        _NET_OVER_GROSS_FACTOR = 1.0696 / 1.0801  # ≈ 0.9903
        cagr_net = (1.0 + cagr_gross) * _NET_OVER_GROSS_FACTOR - 1.0
        cagr = cagr_gross  # retro-compatibilità con il resto della sezione (Sharpe/Sortino sotto restano sul lordo)
        vol = _cx_ret.std() * (12 ** 0.5)
        sharpe = (cagr - 0.03) / vol if vol > 0 else 0.0
        mdd = _cx_nav["drawdown"].min() / 100.0
        downside = _cx_ret[_cx_ret < 0]
        sortino = (cagr - 0.03) / (downside.std() * (12 ** 0.5)) if len(downside) > 0 and downside.std() > 0 else 0.0

        st.caption("Statistiche dal backtest corretto di Convex Stack (2000–2026, dati reali, pesi e costi corretti — non l'estensione Fama-French fabbricata dello script originale). La curva è LORDA (prima delle tasse): Convex non vende se non per rari trim, quindi il valore reale del portafoglio oggi è quello lordo — il netto sotto è una stima di quanto resterebbe se lo liquidassi oggi.")
        k1, k2, k3, k4, k5 = st.columns(5)
        k1.metric("Crescita Annua Lorda (CAGR)", f"{cagr_gross*100:.2f}%", f"Netto (se liquidato oggi) {cagr_net*100:.2f}%",
                  help="CAGR lordo, prima delle tasse — è la curva mostrata sotto. Sotto: stima del netto se vendessi tutto oggi.")
        k2.metric("Oscillazione", f"{vol*100:.2f}%", help="Volatilità: quanto varia il valore nel tempo.")
        k3.metric("Rendimento/Rischio", f"{sharpe:.2f}", help="Sharpe: rendimento ottenuto per ogni unità di rischio.")
        k4.metric("Rendimento/Ribassi", f"{sortino:.2f}", help="Sortino: come Sharpe, ma guarda solo ai cali.")
        k5.metric("Perdita Massima", f"{mdd*100:.2f}%", help="Il calo peggiore mai registrato dal punto più alto al più basso.")

        # ----------------------------------------------------------------------
        # Crescita Patrimoniale — selettore di periodo e benchmark, stesso
        # meccanismo di Apex Engine (segmented_control 1M/3M/6M/1A/Tutto,
        # normalizzazione Base 100 dal primo punto visibile, SPY come
        # riferimento). La serie di Convex è mensile (backtest storico), non
        # giornaliera come quella live di Apex: "1M" mostra quindi 1-2 punti
        # soltanto — limite reale del dato disponibile, non nascosto.
        # ----------------------------------------------------------------------
        st_html(section_title("Crescita Patrimoniale nel Tempo", top="8px", bottom="8px"))
        st.caption(
            "Serie mensile dal backtest corretto 2000–2026 — non lo storico del tuo conto: "
            "Convex non tiene un registro di versamenti/trim passati. Prima del 2019-09 la "
            "serie è ricostruita da proxy (non gli strumenti UCITS reali, non ancora quotati "
            "all'epoca); da lì in poi sono dati reali degli strumenti — marcato nel grafico."
        )

        selected_range = st.segmented_control(
            "Periodo", options=["1M", "3M", "6M", "1A", "Tutto"],
            default="Tutto", label_visibility="collapsed", key="cx_chart_range_ctrl"
        )
        if not selected_range:
            selected_range = "Tutto"

        last_dt = _cx_nav.index[-1]
        if selected_range == "1M":
            start_dt = last_dt - pd.DateOffset(months=1)
        elif selected_range == "3M":
            start_dt = last_dt - pd.DateOffset(months=3)
        elif selected_range == "6M":
            start_dt = last_dt - pd.DateOffset(months=6)
        elif selected_range == "1A":
            start_dt = last_dt - pd.DateOffset(years=1)
        else:
            start_dt = _cx_nav.index[0]
        _nav_plot = _cx_nav[_cx_nav.index >= start_dt].copy()
        _nav_plot["norm"] = (_nav_plot["value"] / _nav_plot["value"].iloc[0]) * 100.0

        df_spy = load_benchmark_spy()

        fig_cx_eq = go.Figure()
        fig_cx_eq.add_trace(go.Scatter(
            x=_nav_plot.index, y=_nav_plot["norm"], mode="lines", name="Convex Stack",
            line=dict(color=ACCENT, width=2), fill="tozeroy", fillcolor="rgba(201, 164, 76, 0.10)",
            hovertemplate="Base 100: %{y:.2f}<extra></extra>"
        ))
        if not df_spy.empty:
            _spy_aligned = df_spy[df_spy.index >= _nav_plot.index[0]]
            if not _spy_aligned.empty:
                _spy_m = _spy_aligned.resample("ME").last().dropna()
                _spy_norm = (_spy_m / _spy_m.iloc[0]) * 100.0
                fig_cx_eq.add_trace(go.Scatter(
                    x=_spy_norm.index, y=_spy_norm, mode="lines", name="S&P 500 Benchmark",
                    line=dict(color='#7A7266', width=1.5, dash='dot'),
                    hovertemplate="S&P 500: %{y:.2f}<extra></extra>"
                ))
        # Marcatore proxy→reale: prima del 2019-09 la serie è ricostruita per
        # concatenazione di proxy (SPY/EFA/AGG/IEF/IJS/EFV/DLS/GC=F), non dati
        # reali dei singoli strumenti UCITS — segnalato in chiaro, non nascosto.
        _real_start = pd.Timestamp("2019-09-30")
        if _nav_plot.index[0] < _real_start <= _nav_plot.index[-1]:
            fig_cx_eq.add_vline(x=_real_start, line=dict(color=MUTED, width=1, dash="dash"))
            fig_cx_eq.add_annotation(x=_real_start, y=1.0, yref="paper", yanchor="bottom",
                                      text="dati reali →", showarrow=False,
                                      font=dict(size=9, color=MUTED))
        fig_cx_eq.update_layout(
            template="plotly_dark",
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color=MUTED, family="Inter"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, font=dict(size=10)),
            margin=dict(t=30, b=10, l=10, r=10), height=280,
            yaxis_title="Base 100"
        )
        st.plotly_chart(fig_cx_eq, use_container_width=True)

        st_html(section_title("Calo dal Massimo Storico", top="14px", bottom="6px"))
        fig_cx_dd = go.Figure()
        fig_cx_dd.add_trace(go.Scatter(
            x=_cx_nav.index, y=_cx_nav["drawdown"], fill="tozeroy", mode="lines",
            line=dict(color=NEG, width=1.2), fillcolor="rgba(236,101,123,0.15)",
            hovertemplate="%{x|%d %b %Y}<br>Calo: %{y:.2f}%<extra></extra>", name="Calo"
        ))
        if _cx_nav.index[0] < _real_start <= _cx_nav.index[-1]:
            fig_cx_dd.add_vline(x=_real_start, line=dict(color=MUTED, width=1, dash="dash"))
        fig_cx_dd.update_layout(
            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color=MUTED, family="Inter"),
            xaxis=dict(showgrid=False, tickfont=dict(size=10)),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,247,237,0.05)', tickfont=dict(size=10), ticksuffix="%"),
            margin=dict(t=4, b=10, l=10, r=10), height=140, showlegend=False
        )
        st.plotly_chart(fig_cx_dd, use_container_width=True)

        st_html(section_title("Matrice dei Rendimenti"))
        st_html(render_monthly_returns_html_table(_cx_nav))

        st_html(section_title("Costo e Regolarità"))
        st.caption("Convex non ha operazioni da misurare (nessun tasso di successo o fattore di profitto: è un portafoglio a lungo termine, non trading attivo). Ciò che conta è il costo ricorrente e la costanza dei rendimenti.")
        # TER ponderato reale sui pesi ATTUALI (non i target): riusa
        # convex_report.ter_weighted, la stessa fonte già validata in
        # convex_engine.py — evita di ricalcolarlo qui sui pesi target,
        # che ignorerebbe lo scostamento reale del portafoglio dell'utente.
        _cx_ter_annual = convex_report.ter_weighted if convex_report.total_value > 0 else \
            sum(i["ter"] * i["target_weight"] for i in active_instruments.values())
        _cx_ter_eur_year = convex_report.total_value * _cx_ter_annual if convex_report.total_value > 0 else 0.0
        _cx_pos_months = int((_cx_ret > 0).sum())
        _cx_tot_months = int(len(_cx_ret))
        e1, e2, e3 = st.columns(3)
        e1.metric("TER Ponderato Reale", f"{_cx_ter_annual*100:.3f}%/anno", help="Costo dei 5 ETF pesato sul capitale reale, non sul nozionale a leva.")
        e2.metric("Costo TER sul Tuo Capitale", f"€ {_cx_ter_eur_year:,.0f}/anno", help="TER ponderato × il tuo patrimonio Convex attuale.")
        e3.metric("Mesi Positivi (storico)", f"{_cx_pos_months}/{_cx_tot_months} ({_cx_pos_months/_cx_tot_months*100:.0f}%)", help="Quota di mesi con rendimento positivo sul backtest corretto 2000–2026.")
    else:
        st.warning("Dati storici non trovati (convex_monthly_returns.csv).")

with tab_guida:
    st_html(section_title("La Routine Operativa", top="0"))
    r1, r2, r3 = st.columns(3)
    for col, num, title, body in [
        (r1, "1", "Ricevi il versamento", "Quando arriva la liquidità del mese, apri questa pagina."),
        (r2, "2", "Inserisci i tuoi numeri", "Aggiorna le quote possedute e la liquidità pronta per il PAC."),
        (r3, "3", "Segui il consiglio", "Deposita dove indicato. Se c'è un avviso di trim, vendi l'eccesso."),
    ]:
        with col:
            st_html(f"""
            <div class="glass-card" style="text-align:center; height: 130px;">
                <div style="font-family:{FRAUNCES}; font-size:24px; color:{ACCENT}; font-weight:700;">{num}</div>
                <div style="font-size:13.5px; font-weight:700; color:{BADGE_TEXT}; margin:6px 0;">{title}</div>
                <div style="font-size:12px; color:{MUTED}; line-height:1.4;">{body}</div>
            </div>
            """)

    st_html(section_title(f"I {len(active_instruments)} Strumenti"))
    instr_cols = st.columns(len(active_instruments))
    for i, (key, info) in enumerate(active_instruments.items()):
        with instr_cols[i]:
            st_html(f"""
            <div class="glass-card" style="height: 190px;">
                <div style="font-family:{MONO}; font-size:13px; font-weight:700; color:{ACCENT};">{key}</div>
                <div style="font-size:11.5px; font-weight:700; color:{BADGE_TEXT}; margin:4px 0 8px 0; line-height:1.3;">{info['name']}</div>
                <div style="font-size:11px; color:{MUTED}; line-height:1.4;">{info['asset_class']}</div>
                <div style="font-size:11px; color:{MUTED_2}; margin-top:8px;">Target: {info['target_weight']*100:.1f}% · TER {info['ter']*100:.2f}%</div>
            </div>
            """)

    # Nozionale = 100% capitale + la parte extra della leva 1.5x incorporata
    # solo in NTSG (unico strumento a leva) — cambia con NTSG% se si passa
    # a Semplice, dove NTSG pesa di più (52.9% vs 45%).
    _ntsg_w = active_instruments.get("NTSG", {}).get("target_weight", 0.0)
    _notional_pct = (1.0 + 0.5 * _ntsg_w) * 100.0
    _motori_txt = (
        "cinque motori strutturalmente diversi: azionario, fattore value, trend-following anti-crisi, oro, Bitcoin"
        if versione == "Completa" else
        "quattro motori strutturalmente diversi: azionario, trend-following anti-crisi, oro, Bitcoin"
    )
    st_html(section_title("Controllo del Rischio"))
    st_html(f"""
    <div class="glass-card">
        <div style="font-size: 13px; color: {MUTED}; line-height: 1.6;">
            Convex Stack <strong>non è a leva zero</strong>: l'esposizione nozionale totale è il {_notional_pct:.1f}% del capitale,
            interamente tramite la leva 1.5x incorporata in NTSG (futures istituzionali, nessun debito a margine
            personale). Il vero controllo del rischio sono le <strong>bande di trim all'11.25%</strong> su Bitcoin e
            Oro — i due strumenti più volatili — che riportano automaticamente la posizione in linea quando supera
            1,5 volte il suo peso target. Il resto della protezione viene dalla diversificazione tra {_motori_txt} —
            pensati per non muoversi tutti insieme nello stesso momento.
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
