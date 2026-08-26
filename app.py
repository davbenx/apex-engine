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
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

    html, body, [class*="css"], .stApp {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        letter-spacing: -0.01em;
    }

    /* Tabular numbers for financial metrics and dataframes */
    [data-testid="stMetricValue"], [data-testid="stMetricLabel"], .stDataFrame, div[data-testid="stTable"], table {
        font-family: 'JetBrains Mono', monospace !important;
        font-variant-numeric: tabular-nums !important;
    }

    [data-testid="stMetricValue"] {
        font-size: 1.45rem !important;
        font-weight: 700 !important;
    }

    [data-testid="stMetricLabel"] {
        font-size: 0.8rem !important;
        opacity: 0.75 !important;
        font-family: 'Inter', sans-serif !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
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

    /* Clean cards transition */
    div[style*="border-radius"] {
        transition: transform 0.15s ease-in-out, box-shadow 0.15s ease-in-out;
    }
</style>
""")


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
    st.error("🚨 Dati non disponibili. In attesa del ricalcolo notturno su GitHub.")
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
        entry_d = datetime.datetime.strptime(entry_date_str, "%Y-%m-%d")
        return (datetime.datetime.now() - entry_d).days
    except Exception:
        return 0


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
# HEADER & MACRO STATUS
# ==============================================================================
last_update = data.get("timestamp", "Sincronizzazione in corso...")
logo_b64 = get_logo_b64()
logo_tag = f'<img src="data:image/png;base64,{logo_b64}" style="height: 75px; width: auto; object-fit: contain;" />' if logo_b64 else '🦅'

col_title, col_meta = st.columns([3, 2])
with col_title:
    st_html(f"""
    <div style="display: flex; align-items: center; gap: 16px; padding: 6px 0;">
        <div style="background: rgba(128, 128, 128, 0.08); border: 1px solid rgba(128, 128, 128, 0.18); padding: 6px 10px; border-radius: 12px; display: flex; align-items: center; justify-content: center; box-shadow: 0 4px 12px rgba(0,0,0,0.25);">
            {logo_tag}
        </div>
        <div>
            <div style="font-size: 28px; font-weight: 800; letter-spacing: -0.8px; line-height: 1.15;">APEX ENGINE</div>
            <div style="font-size: 12px; font-weight: 600; opacity: 0.75; letter-spacing: 0.6px; text-transform: uppercase; margin-top: 3px;">Sistema Quantitativo Multi-Asset<br><span style='color: #3B82F6; font-weight: 700;'>v1.0 Genesis</span></div>
        </div>
    </div>
    """)

with col_meta:
    st_html(f"""
    <div style="text-align: right; padding-top: 8px;">
        <div style="display: flex; justify-content: flex-end; align-items: center; gap: 8px; margin-bottom: 5px;">
            <a href="https://t.me/apex_multiasset" target="_blank" style="text-decoration: none; display: inline-flex; align-items: center; gap: 4px; background: rgba(0, 136, 204, 0.12); color: #0088cc; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; border: 1px solid rgba(0, 136, 204, 0.3);">
                ✈️ Notifiche @apex_multiasset
            </a>
            <span style="background: rgba(16, 185, 129, 0.15); color: #10B981; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; border: 1px solid rgba(16, 185, 129, 0.3);">🟢 Motore Attivo</span>
        </div>
        <div style="opacity: 0.75; font-size: 11.5px;">
            🕒 <strong>Aggiornato:</strong> {last_update} &nbsp;•&nbsp; ⏳ <strong>Ricalcolo:</strong> 01:30 UTC
        </div>
    </div>
    """)

# Macro Engine Status Chips
alloc = data.get('allocations', {"Equities": 0, "Crypto": 0, "Gold": 0, "Bonds": 0, "Cash": 100})
raw_ts = data.get('timestamp', '')
ts_date = raw_ts.split(',')[0].strip() if ',' in raw_ts else (raw_ts.split(' ')[0] if raw_ts else datetime.datetime.now().strftime('%Y-%m-%d'))
macro_dates = data.get("macro_dates", {})

d_eq = macro_dates.get("Equities", ts_date)
d_cr = macro_dates.get("Crypto", ts_date)
d_g = macro_dates.get("Gold", ts_date)
d_b = macro_dates.get("Bonds", ts_date)


def make_chip(icon, name, alloc_pct, is_active, since_date, is_cash=False):
    if is_cash:
        border_color = "#3B82F6" if alloc_pct > 0 else "#6B7280"
        bg_color = "rgba(59, 130, 246, 0.10)" if alloc_pct > 0 else "rgba(107, 114, 128, 0.06)"
        badge_bg = "#1E40AF" if alloc_pct > 0 else "#374151"
        status_text = "🟢 ATTIVO" if alloc_pct > 0 else "⚪ STBY"
        subtitle = "Parcheggio Sicuro"
    else:
        border_color = "#10B981" if is_active else "rgba(128,128,128,0.2)"
        bg_color = "rgba(16, 185, 129, 0.08)" if is_active else "rgba(128, 128, 128, 0.04)"
        badge_bg = "#065F46" if is_active else "#374151"
        status_text = "🟢 ATTIVO" if is_active else "🔴 OFF"
        subtitle = f"Dal {since_date}" if is_active else f"Spento {since_date}"

    opacity = "1" if (is_active or (is_cash and alloc_pct > 0)) else "0.55"

    return f"""
    <div style="background: {bg_color}; border: 1px solid {border_color}; border-radius: 8px; padding: 7px 12px; display: flex; align-items: center; justify-content: space-between; flex: 1 1 150px; min-width: 140px; opacity: {opacity};">
        <div style="display: flex; align-items: center; gap: 8px;">
            <span style="font-size: 16px;">{icon}</span>
            <div>
                <div style="font-weight: 700; font-size: 12.5px; line-height: 1.1;">{name} <span style="font-family: 'JetBrains Mono', monospace; font-size: 12px; opacity: 0.9;">({alloc_pct}%)</span></div>
                <div style="opacity: 0.65; font-size: 10px; margin-top: 1px;">{subtitle}</div>
            </div>
        </div>
        <span style="background: {badge_bg}; color: #ffffff; padding: 2px 6px; border-radius: 4px; font-size: 9.5px; font-weight: 700; letter-spacing: 0.3px;">{status_text}</span>
    </div>
    """

chip_eq = make_chip("📈", "Azioni", alloc.get('Equities', 0), alloc.get('Equities', 0) > 0, d_eq)
chip_cr = make_chip("🪙", "Crypto", alloc.get('Crypto', 0), alloc.get('Crypto', 0) > 0, d_cr)
chip_g = make_chip("🥇", "Oro", alloc.get('Gold', 0), alloc.get('Gold', 0) > 0, d_g)
chip_b = make_chip("🛡️", "Bond", alloc.get('Bonds', 0), alloc.get('Bonds', 0) > 0, d_b)
chip_c = make_chip("💵", "Liquidità", alloc.get('Cash', 0), False, "", is_cash=True)

st_html(f'<div style="display: flex; flex-wrap: wrap; gap: 8px; margin: 10px 0 16px 0;">{chip_eq}{chip_cr}{chip_g}{chip_b}{chip_c}</div>')


# ==============================================================================
# PORTFOLIO DATA EXTRACTION
# ==============================================================================
pf = load_portfolio()
op_eq = []
op_cr = []
num_eq = 0
num_cr = 0

if pf:
    for ticker, info in pf.get("open_positions", {}).items():
        entry_d = info.get("entry_date", "N/A")
        days_open = calculate_days(entry_d) if entry_d != "N/A" else 0
        entry_formatted = f"{entry_d} ({days_open}g)" if entry_d != "N/A" else "N/A"

        curr_p = info.get("current_price", info.get("entry_price", 0.0))
        stop_p = info.get("stop_loss", 0.0)
        pnl_pct = ((curr_p / info["entry_price"]) - 1.0) * 100 if info.get("entry_price", 0) > 0 else 0.0
        dist_stop_pct = ((stop_p / curr_p) - 1.0) * 100 if curr_p > 0 else 0.0

        row = {
            "Titolo": ticker,
            "Data Ingresso": entry_formatted,
            "Ingresso ($)": info.get("entry_price", 0.0),
            "Attuale ($)": curr_p,
            "Stop Loss ($)": stop_p,
            "Distanza Stop": dist_stop_pct,
            "Rendimento %": pnl_pct
        }
        if info.get("is_crypto", False):
            op_cr.append(row)
            num_cr += 1
        else:
            op_eq.append(row)
            num_eq += 1


# ==============================================================================
# MAIN TABS DECLARATION (PORTAFOGLIO, METRICHE, RADAR, GUIDA)
# ==============================================================================
tab_pf, tab_perf, tab_radar, tab_guide = st.tabs([
    "💼 Portafoglio",
    "📊 Metriche",
    "📡 Radar",
    "📖 Guida"
])


# ==============================================================================
# TAB 1: PORTAFOGLIO & ALLOCAZIONE
# ==============================================================================
with tab_pf:
    c_inp, c_pnl = st.columns([3, 2])
    with c_inp:
        capitale = st.number_input(
            "💰 Capitale Broker Reale (€ / $)", min_value=1000, value=100000, step=1000, format="%d"
        )
        st.caption("Le quote e i controvalori si adattano istantaneamente al capitale impostato.")

    capitale_azionario = capitale * (alloc.get('Equities', 0) / 100)
    single_eq = capitale_azionario / 20 if alloc.get('Equities', 0) > 0 else 0
    crypto_cap = capitale * (alloc.get('Crypto', 0) / 100)
    gold_cap = capitale * (alloc.get('Gold', 0) / 100)
    bond_cap = capitale * (alloc.get('Bonds', 0) / 100)

    # Calcolo Floating P&L
    tot_pnl_usd = 0.0
    tot_invested_usd = 0.0

    for r in op_eq:
        pnl_val = (r["Rendimento %"] / 100) * single_eq
        tot_pnl_usd += pnl_val
        tot_invested_usd += single_eq

    for r in op_cr:
        cr_size = capitale * (0.10 if r['Titolo'] == 'BTC' else 0.05)
        pnl_val = (r["Rendimento %"] / 100) * cr_size
        tot_pnl_usd += pnl_val
        tot_invested_usd += cr_size

    macro_pos = pf.get("macro_positions", {}) if pf else {}
    if alloc.get('Gold', 0) > 0:
        g_pnl_usd = 0.0
        if "Gold" in macro_pos:
            g_pos = macro_pos["Gold"]
            c_p = g_pos.get("current_price", g_pos.get("entry_price", 0))
            if g_pos.get("entry_price", 0) > 0:
                g_pnl_usd = ((c_p / g_pos["entry_price"]) - 1.0) * gold_cap
        tot_pnl_usd += g_pnl_usd
        tot_invested_usd += gold_cap

    if alloc.get('Bonds', 0) > 0:
        b_pnl_usd = 0.0
        if "Bonds" in macro_pos:
            b_pos = macro_pos["Bonds"]
            c_p = b_pos.get("current_price", b_pos.get("entry_price", 0))
            if b_pos.get("entry_price", 0) > 0:
                b_pnl_usd = ((c_p / b_pos["entry_price"]) - 1.0) * bond_cap
        tot_pnl_usd += b_pnl_usd
        tot_invested_usd += bond_cap

    tot_pnl_pct = (tot_pnl_usd / tot_invested_usd * 100) if tot_invested_usd > 0 else 0.0

    with c_pnl:
        num_pos = len(op_eq) + len(op_cr) + (1 if alloc.get('Gold', 0) > 0 else 0) + (1 if alloc.get('Bonds', 0) > 0 else 0)
        if num_pos > 0:
            pnl_sign = "+" if tot_pnl_usd >= 0 else ""
            pnl_col = "#10B981" if tot_pnl_usd >= 0 else "#EF4444"
            pnl_val_str = f"{pnl_sign}{tot_pnl_usd:,.0f}"
            pnl_pct_str = f"{pnl_sign}{tot_pnl_pct:.2f}%"
            sub_text = f"Su {num_pos} posizioni aperte"
        else:
            pnl_col = "gray"
            pnl_val_str = "0"
            pnl_pct_str = "0.00%"
            sub_text = "Nessuna posizione aperta (attesa venerdì)"

        st_html(f"""
        <div style="background: rgba(128,128,128,0.06); border: 1px solid rgba(128,128,128,0.15); border-radius: 8px; padding: 10px 16px; margin-top: 2px;">
            <div style="opacity: 0.75; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Rendimento Galleggiante Aperto</div>
            <div style="font-size: 20px; font-weight: 700; color: {pnl_col}; font-family: 'JetBrains Mono', monospace; margin: 2px 0;">
                {pnl_val_str} <span style="font-size: 13px; font-weight: 600;">({pnl_pct_str})</span>
            </div>
            <div style="opacity: 0.65; font-size: 10.5px;">{sub_text}</div>
        </div>
        """)

    st.write("")

    def color_pnl(val):
        color = '#10B981' if val > 0 else '#EF4444' if val < 0 else 'gray'
        return f'color: {color}; font-weight: 700;'

    def color_stop_dist(val):
        if val > -5.0:
            return 'color: #EF4444; font-weight: 700;'
        elif val > -10.0:
            return 'color: #F59E0B; font-weight: 600;'
        return ''

    col_az, col_cr = st.columns([2, 1])

    with col_az:
        st_html(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 1.1rem; font-weight: 600;">📈 Azioni in Portafoglio</span>
            <span style="background: rgba(16, 185, 129, 0.15); color: #10B981; padding: 2px 8px; border-radius: 6px; font-size: 11.5px; font-weight: 700; font-family: 'JetBrains Mono', monospace;">{num_eq} / 20</span>
        </div>
        """)

        if op_eq:
            df_op_eq = pd.DataFrame(op_eq)
            df_op_eq["Importo"] = single_eq
            df_op_eq["P&L (€)"] = (df_op_eq["Rendimento %"] / 100) * df_op_eq["Importo"]

            df_eq_styled = df_op_eq.style.format({
                "Ingresso ($)": "{:.2f}",
                "Attuale ($)": "{:.2f}",
                "Stop Loss ($)": "{:.2f}",
                "Distanza Stop": "{:.1f}%",
                "Importo": "{:,.0f}",
                "Rendimento %": "{:+.2f}%",
                "P&L (€)": "{:+,.0f}"
            }).map(color_pnl, subset=['Rendimento %', 'P&L (€)']).map(color_stop_dist, subset=['Distanza Stop'])

            st.dataframe(df_eq_styled, use_container_width=True, hide_index=True)
        else:
            st.info("Nessuna azione in portafoglio. In attesa del ricalcolo del venerdì.")

    with col_cr:
        st_html(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 1.1rem; font-weight: 600;">🪙 Crypto in Portafoglio</span>
            <span style="background: rgba(16, 185, 129, 0.15); color: #10B981; padding: 2px 8px; border-radius: 6px; font-size: 11.5px; font-weight: 700; font-family: 'JetBrains Mono', monospace;">{num_cr} / 3</span>
        </div>
        """)

        if op_cr:
            df_op_cr = pd.DataFrame(op_cr)
            df_op_cr["Importo"] = [capitale * (0.10 if r['Titolo'] == 'BTC' else 0.05) for _, r in df_op_cr.iterrows()]
            df_op_cr["P&L (€)"] = (df_op_cr["Rendimento %"] / 100) * df_op_cr["Importo"]

            df_cr_styled = df_op_cr.style.format({
                "Ingresso ($)": format_price,
                "Attuale ($)": format_price,
                "Stop Loss ($)": format_price,
                "Distanza Stop": "{:.1f}%",
                "Importo": "{:,.0f}",
                "Rendimento %": "{:+.2f}%",
                "P&L (€)": "{:+,.0f}"
            }).map(color_pnl, subset=['Rendimento %', 'P&L (€)']).map(color_stop_dist, subset=['Distanza Stop'])

            st.dataframe(df_cr_styled, use_container_width=True, hide_index=True)
        else:
            st.info("Nessuna crypto in portafoglio. In attesa del ricalcolo del venerdì.")


# ==============================================================================
# TAB 2: METRICHE (CANDLESTICK EQUITY CURVE, KPI, STORICO)
# ==============================================================================
with tab_perf:
    col_chart_hdr, col_chart_mode = st.columns([3, 1])
    with col_chart_hdr:
        st.markdown("#### 🕯️ Andamento Strategia Apex (Candele Giapponesi)")
    with col_chart_mode:
        timeframe = st.radio("Frequenza", ["Giornaliero", "Settimanale"], horizontal=True, label_visibility="collapsed")

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

        # Normalizzazione Base 100
        base_val = initial_val if initial_val > 0 else 100000.0
        df_eq['norm_open'] = (df_eq['open'] / base_val) * 100
        df_eq['norm_high'] = (df_eq['high'] / base_val) * 100
        df_eq['norm_low'] = (df_eq['low'] / base_val) * 100
        df_eq['norm_close'] = (df_eq['close'] / base_val) * 100

        # Timeframe aggregation
        if timeframe == "Settimanale" and len(df_eq) >= 5:
            df_plot = df_eq.resample('W-FRI').agg({
                'norm_open': 'first',
                'norm_high': 'max',
                'norm_low': 'min',
                'norm_close': 'last',
                'close': 'last'
            }).dropna()
        else:
            df_plot = df_eq

        fig = go.Figure()

        # 1. Candele Giapponesi per Strategia Apex
        fig.add_trace(
            go.Candlestick(
                x=df_plot.index,
                open=df_plot['norm_open'],
                high=df_plot['norm_high'],
                low=df_plot['norm_low'],
                close=df_plot['norm_close'],
                increasing_line_color='#10B981',
                decreasing_line_color='#EF4444',
                increasing_fillcolor='#10B981',
                decreasing_fillcolor='#EF4444',
                name='Strategia Apex'
            )
        )

        # 2. Benchmark S&P 500 (Linea di Riferimento)
        if not df_spy.empty:
            start_date = df_plot.index[0]
            df_spy_aligned = df_spy[df_spy.index >= start_date].copy()
            if not df_spy_aligned.empty:
                first_spy = df_spy_aligned['close'].iloc[0]
                if timeframe == "Settimanale" and len(df_spy_aligned) >= 5:
                    df_spy_plot = df_spy_aligned['close'].resample('W-FRI').last().dropna()
                else:
                    df_spy_plot = df_spy_aligned['close']
                df_spy_norm = (df_spy_plot / first_spy) * 100

                fig.add_trace(go.Scatter(
                    x=df_spy_plot.index,
                    y=df_spy_norm,
                    mode='lines',
                    name="S&P 500 Benchmark",
                    line=dict(color='#9CA3AF', width=1.8, dash='dot'),
                    opacity=0.75
                ))

        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.1)', tickfont=dict(size=11)),
            yaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.1)', tickfont=dict(size=11), title="Base 100"),
            xaxis_rangeslider_visible=False,
            margin=dict(l=0, r=0, t=15, b=0),
            height=430,
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor='rgba(128,128,128,0.08)')
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("📊 In attesa del file di tracciamento storico.")

    st.write("")

    # Mathematical Advantage & Operating KPI Cards
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

        def make_kpi_card(title, value, subtext="", val_color=""):
            col_attr = f'color: {val_color};' if val_color else ''
            sub_html = f'<div style="color: #6B7280; font-size: 10.5px;">{subtext}</div>' if subtext else ''
            return f"""
            <div style="background: rgba(128,128,128,0.06); border: 1px solid rgba(128,128,128,0.18); border-radius: 8px; padding: 12px 14px; display: flex; flex-direction: column; justify-content: space-between;">
                <div style="opacity: 0.75; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">{title}</div>
                <div style="font-size: 21px; font-weight: 700; {col_attr} font-family: 'JetBrains Mono', monospace; margin-bottom: 2px;">{value}</div>
                {sub_html}
            </div>
            """

        c_tot = "#10B981" if total_ret_pct >= 0 else "#EF4444"
        c_win = "#10B981" if win_rate >= 50 else ("#3B82F6" if win_rate >= 40 else "#9CA3AF")
        c_pf = "#10B981" if profit_factor >= 1.5 else ("#F59E0B" if profit_factor >= 1.0 else "#9CA3AF")
        c_payoff = "#10B981" if payoff_ratio >= 2.0 else ("#F59E0B" if payoff_ratio >= 1.0 else "#9CA3AF")
        c_dd = "#EF4444" if max_dd < -10 else "#F59E0B"

        kpi_ret = make_kpi_card("Rendimento Netto", f"{total_ret_pct:+.2f}%", "Performance cumulativa", c_tot)
        kpi_win = make_kpi_card("Tasso di Successo", f"{win_rate:.1f}%", f"{len(wins)} vincenti su {len(hist)}", c_win)
        kpi_pf = make_kpi_card("Fattore di Profitto", f"{profit_factor:.2f}", "Profitti lordi / perdite", c_pf)
        kpi_po = make_kpi_card("Rapporto Win/Loss", f"{payoff_ratio:.2f}x", "Vincita media / perdita media", c_payoff)
        kpi_dd = make_kpi_card("Max Drawdown", f"{max_dd:.2f}%", "Massima perdita storica", c_dd)

        st_html(f'<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; margin-bottom: 20px;">{kpi_ret}{kpi_win}{kpi_pf}{kpi_po}{kpi_dd}</div>')

        st.markdown("#### 📜 Registro Operazioni Chiuse")
        if hist:
            df_hist = pd.DataFrame(hist).sort_values("exit_date", ascending=False)

            def color_trade_pnl(val):
                if isinstance(val, (int, float)):
                    color = '#10B981' if val > 0 else '#EF4444' if val < 0 else 'gray'
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
            cols_to_drop = [c for c in ["is_crypto", "weight"] if c in df_hist.columns]
            if cols_to_drop:
                df_hist = df_hist.drop(columns=cols_to_drop)

            st.dataframe(
                df_hist.style.format({
                    "Prezzo Ingresso": format_price,
                    "Prezzo Uscita": format_price,
                    "Rendimento %": "{:+.2f}%"
                }).map(color_trade_pnl, subset=['Rendimento %'] if 'Rendimento %' in df_hist.columns else None),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("Nessuna operazione chiusa registrata.")


# ==============================================================================
# TAB 3: RADAR ROTAZIONE
# ==============================================================================
with tab_radar:
    st_html("""
    <div style="background: rgba(59, 130, 246, 0.08); border-left: 4px solid #3B82F6; padding: 10px 14px; border-radius: 0 8px 8px 0; margin-bottom: 15px; font-size: 13px;">
        💡 <strong>Radar di Rotazione:</strong> Questi sono i titoli con il momentum più alto <strong>Oggi</strong>. I titoli già presenti in portafoglio sono marcati con ⭐, mentre i nuovi candidati verranno acquistati solo se rimarranno in classifica nel giorno di Rotazione (ultimo venerdì del mese).
    </div>
    """)

    held_tickers = set(pf.get("open_positions", {}).keys()) if pf else set()

    def style_radar_status(val):
        if "⭐" in str(val):
            return 'background-color: rgba(16, 185, 129, 0.15); color: #10B981; font-weight: 700;'
        return ''

    rc1, rc2 = st.columns([2, 1])
    with rc1:
        st.markdown("#### 📈 Top 20 Azioni S&P 500")
        if alloc.get("Equities", 0) > 0:
            top20 = data.get("top20", [])
            if top20:
                df_eq = pd.DataFrame(top20)
                if "Momentum Score" in df_eq.columns:
                    df_eq = df_eq.drop(columns=["Momentum Score"])
                df_eq = df_eq.rename(columns={"Ticker": "Titolo", "Prezzo": "Prezzo ($)", "Stop Loss": "Stop Loss ($)"})
                df_eq["Pos"] = df_eq["Titolo"].apply(lambda t: "⭐" if t in held_tickers else "🆕")
                cols = ["Pos", "Titolo", "Prezzo ($)", "Stop Loss ($)"]
                df_eq = df_eq[[c for c in cols if c in df_eq.columns]]

                st.dataframe(
                    df_eq.style.format({"Prezzo ($)": "{:.2f}", "Stop Loss ($)": "{:.2f}"}).map(
                        style_radar_status, subset=['Pos'] if 'Pos' in df_eq.columns else None
                    ),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("Nessun dato Top 20 disponibile.")
        else:
            st.warning("Motore Azionario OFF (Semaforo Rosso). Nessun acquisto previsto.")

    with rc2:
        st.markdown("#### 🪙 Top 3 Crypto")
        if alloc.get("Crypto", 0) > 0:
            cr_top = data.get("crypto_top", [])
            if cr_top:
                df_c = pd.DataFrame(cr_top)
                if "Momentum Score" in df_c.columns:
                    df_c = df_c.drop(columns=["Momentum Score"])
                df_c = df_c.rename(columns={"Ticker": "Titolo", "Prezzo": "Prezzo ($)", "Stop Loss": "Stop Loss ($)"})
                df_c["Pos"] = df_c["Titolo"].apply(lambda t: "⭐" if t in held_tickers else "🆕")
                cols = ["Pos", "Titolo", "Prezzo ($)", "Stop Loss ($)"]
                df_c = df_c[[c for c in cols if c in df_c.columns]]

                st.dataframe(
                    df_c.style.format({"Prezzo ($)": format_price, "Stop Loss ($)": format_price}).map(
                        style_radar_status, subset=['Pos'] if 'Pos' in df_c.columns else None
                    ),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("Nessun dato Crypto disponibile.")
        else:
            st.warning("Motore Crypto OFF (Semaforo Rosso).")


# ==============================================================================
# TAB 4: GUIDA & STRATEGIA
# ==============================================================================
with tab_guide:
    st_html('''
    <div style="background: rgba(0, 136, 204, 0.08); border-left: 4px solid #0088cc; padding: 12px 16px; border-radius: 0 8px 8px 0; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
        <div>
            <div style="font-weight: 700; font-size: 14px; color: #0088cc; margin-bottom: 2px;">📢 Canale Ufficiale Notifiche Telegram</div>
            <div style="font-size: 12.5px; opacity: 0.85;">Ricevi in tempo reale i cambi di mercato, gli ordini di rotazione e i livelli di protezione aggiornati.</div>
        </div>
        <a href="https://t.me/apex_multiasset" target="_blank" style="background: #0088cc; color: #ffffff; text-decoration: none; padding: 6px 14px; border-radius: 6px; font-size: 12.5px; font-weight: 700; display: inline-flex; align-items: center; gap: 5px;">
            Unisciti al Canale ✈️
        </a>
    </div>
    ''')

    st.markdown("#### 📖 Regole Operative")
    st_html("""
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 20px;">
        <div style="background: rgba(128,128,128,0.06); border: 1px solid rgba(128,128,128,0.18); border-radius: 8px; padding: 14px;">
            <div style="font-weight: 700; color: #3B82F6; margin-bottom: 6px;">📅 1. Controllo mensile</div>
            <div style="font-size: 13px; opacity: 0.85;">L'ultimo venerdì del mese l'app vende i titoli deboli e li sostituisce con i nuovi primi in classifica per mantenere il portafoglio forte.</div>
        </div>
        <div style="background: rgba(128,128,128,0.06); border: 1px solid rgba(128,128,128,0.18); border-radius: 8px; padding: 14px;">
            <div style="font-weight: 700; color: #8B5CF6; margin-bottom: 6px;">⚙️ 2. Controllo settimanale</div>
            <div style="font-size: 13px; opacity: 0.85;">Ogni venerdì aggiorna i livelli di protezione. Se in settimana sono state chiuse delle posizioni, queste vengono sostituite con nuovi ingressi.</div>
        </div>
        <div style="background: rgba(128,128,128,0.06); border: 1px solid rgba(128,128,128,0.18); border-radius: 8px; padding: 14px;">
            <div style="font-weight: 700; color: #10B981; margin-bottom: 6px;">🛡️ 3. Cambi di Mercato</div>
            <div style="font-size: 13px; opacity: 0.85;">Se l'app spegne un settore, viene liquidato interamente il venerdì. Se il prezzo crolla sotto il livello di protezione, l'app chiude l'investimento.</div>
        </div>
    </div>
    """)

    st.divider()

    st.markdown("#### 🧠 Documentazione Strategica")
    st.markdown('''
    ##### Obiettivo
    Crescita del capitale nei mercati positivi e protezione totale durante i ribassi, eliminando ogni componente emotiva.

    ##### Il Sistema
    **Distribuzione del Capitale:** I fondi vengono versati solo nei settori con andamento positivo, riempiendo prima le attività a maggior rendimento e dirottando il resto sui beni difensivi:
    * **Azioni:** fino al 70%, motore primario di crescita.
    * **Criptovalute:** fino al 15%, comparto ad alto rendimento.
    * **Oro:** fino al 10%, protezione contro inflazione e incertezza.
    * **Obbligazioni:** titoli di stato sicuri che assorbono tutto lo spazio libero quando l'economia frena.
    * **Liquidità:** rifugio sicuro in cui parcheggiare tutto se tutti i mercati scendono.

    **Selezione dei Titoli:** Tra le centinaia di titoli disponibili, il sistema acquista solo quelli con la crescita più rapida e solida negli ultimi sei mesi.

    ---

    > ⚠️ **Note Legali ed Esclusione di Responsabilità**  
    > Questa piattaforma ha scopo puramente informativo e di analisi statistica. Non fornisce consulenza finanziaria né raccomandazioni personalizzate ai sensi delle normative vigenti.  
    > I rendimenti passati non garantiscono risultati futuri. Ogni investimento comporta il rischio di perdita del capitale ed è effettuato sotto la totale ed esclusiva responsabilità dell'utente. L'autore declina qualsiasi responsabilità per eventuali perdite derivanti dall'uso di questi dati.
    ''')
