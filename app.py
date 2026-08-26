import base64
import datetime
import json
import os
import urllib.request

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Apex Multi-Asset",
                   page_icon="logo_icon.png" if os.path.exists("logo_icon.png") else "🦅", layout="wide")

# --- CUSTOM THEME & POLISH ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

    html, body, [class*="css"], .stApp {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        letter-spacing: -0.01em;
    }

    /* Tabular numbers for financial metrics and tables */
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
        color: #9CA3AF !important;
        font-family: 'Inter', sans-serif !important;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 6px;
        border-bottom: 1px solid rgba(255,255,255,0.08);
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 18px;
        border-radius: 8px 8px 0px 0px;
        font-weight: 600;
        font-size: 13.5px;
    }

    /* Clean cards */
    div[style*="border-radius"] {
        transition: transform 0.15s ease-in-out, box-shadow 0.15s ease-in-out;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=60)
def fetch_json_from_github(filename):
    url = f"https://raw.githubusercontent.com/davbenx/apex-engine/main/{filename}"
    try:
        buster = int(datetime.datetime.now().timestamp() // 60)
        req = urllib.request.Request(f"{url}?t={buster}", headers={'User-Agent': 'Mozilla/5.0'})
        return json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
    except Exception:
        if os.path.exists(filename):
            with open(filename, 'r') as f:
                return json.load(f)
    return None

def load_data():
    return fetch_json_from_github('apex_data.json')


data = load_data()
if not data:
    st.error("🚨 Dati non disponibili. In attesa del ricalcolo notturno su GitHub.")
    st.stop()

# --- HEADER & STATUS BAR ---
last_update = data.get("timestamp", "Sincronizzazione in corso...")


def get_logo_b64():
    for p in ["logo_icon.png", "logo.png"]:
        if os.path.exists(p):
            with open(p, "rb") as f:
                return base64.b64encode(f.read()).decode()
    return ""


logo_b64 = get_logo_b64()
logo_tag = f'<img src="data:image/png;base64,{logo_b64}" style="height: 55px; width: auto; object-fit: contain;" />' if logo_b64 else '🦅'

col_title, col_meta = st.columns([3, 2])
with col_title:
    st.markdown(f'''
    <div style="display: flex; align-items: center; gap: 14px; padding: 6px 0;">
        <div style="display: flex; align-items: center; gap: 14px; padding: 6px 0;">
            <div style="background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.12); padding: 6px 10px; border-radius: 12px; display: flex; align-items: center; justify-content: center; box-shadow: 0 4px 12px rgba(0,0,0,0.25);">
                {logo_tag}
            </div>
            <div>
                <div style="font-size: 22px; font-weight: 800; letter-spacing: -0.5px; color: #F9FAFB;">APEX ENGINE</div>
                <div style="font-size: 11.5px; font-weight: 600; color: #9CA3AF; letter-spacing: 0.6px; text-transform: uppercase;">Sistema Quantitativo Multi-Asset &bull; v1.0 Genesis</div>
            </div>
        </div>
    </div>
    ''', unsafe_allow_html=True)
with col_meta:
    st.markdown(f'''
    <div style="text-align: right; padding-top: 10px;">
        <span style="background: rgba(16, 185, 129, 0.15); color: #10B981; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; border: 1px solid rgba(16, 185, 129, 0.3);">🟢 Motore Attivo</span>
        <div style="color: #9CA3AF; font-size: 11.5px; margin-top: 5px;">
            🕒 <strong>Aggiornato:</strong> {last_update} &nbsp;•&nbsp; ⏳ <strong>Ricalcolo:</strong> 01:30 UTC
        </div>
    </div>
    ''', unsafe_allow_html=True)

# --- MACRO ENGINE STATUS CHIPS ---
alloc = data['allocations']
is_bull_eq = alloc['Equities'] > 0
is_bull_cr = alloc['Crypto'] > 0
is_bull_g = alloc['Gold'] > 0
is_bull_b = alloc['Bonds'] > 0

raw_ts = data.get('timestamp', '')
ts_date = raw_ts.split(',')[0].strip() if ',' in raw_ts else (raw_ts.split(
    ' ')[0] if raw_ts else datetime.datetime.now().strftime('%Y-%m-%d'))
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
        status_color = "#60A5FA" if alloc_pct > 0 else "#9CA3AF"
        date_str = "Rifugio"
    else:
        border_color = "#10B981" if is_active else "#EF4444"
        bg_color = "rgba(16, 185, 129, 0.10)" if is_active else "rgba(239, 68, 68, 0.08)"
        badge_bg = "#065F46" if is_active else "#7F1D1D"
        status_text = "🟢 ATTIVO" if is_active else "🔴 OFF"
        status_color = "#10B981" if is_active else "#EF4444"
        date_str = f"dal {since_date}" if since_date else ""

    return (
        f'<div style="flex: 1 1 150px; min-width: 140px; background: {bg_color}; border: 1px solid {border_color}; border-radius: 10px; padding: 10px 14px; display: flex; flex-direction: column; justify-content: space-between; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">'
        f'<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">'
        f'<span style="font-weight: 700; font-size: 13px; letter-spacing: 0.2px;">{icon} {name}</span>'
        f'<span style="background: {badge_bg}; color: #fff; font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 6px;">{alloc_pct}%</span>'
        f'</div>'
        f'<div style="display: flex; justify-content: space-between; align-items: baseline;">'
        f'<span style="color: {status_color}; font-weight: 700; font-size: 12px;">{status_text}</span>'
        f'<span style="color: #9CA3AF; font-size: 10px;">{date_str}</span>'
        f'</div>'
        f'</div>'
    )


chip_eq = make_chip("📈", "Azioni", alloc['Equities'], is_bull_eq, d_eq)
chip_cr = make_chip("🪙", "Crypto", alloc['Crypto'], is_bull_cr, d_cr)
chip_g = make_chip("🥇", "Oro", alloc['Gold'], is_bull_g, d_g)
chip_b = make_chip("🛡️", "Obbligazioni", alloc['Bonds'], is_bull_b, d_b)
chip_c = make_chip("💵", "Liquidità / Monetario",
                   alloc['Cash'], True, "", is_cash=True)

chips_html = f'<div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px;">{chip_eq}{chip_cr}{chip_g}{chip_b}{chip_c}</div>'

try:
    st.html(chips_html)
except BaseException:
    st.markdown(chips_html, unsafe_allow_html=True)

st.write("")

# --- TABS LAYOUT ---
tab_pf, tab_perf, tab_radar, tab_log, tab_guide = st.tabs([
    "💼 Portafoglio",
    "📈 Metriche",
    "🔮 Radar",
    "📜 Storico",
    "📖 Guida"
])


def format_price(x):
    if x >= 1000:
        return f"{x:,.2f}"
    elif x >= 1:
        return f"{x:,.4f}"
    elif x >= 0.01:
        return f"{x:,.6f}"
    else:
        return f"{x:,.8f}"


def calculate_days(date_str):
    try:
        if not date_str or date_str == "-":
            return ""
        for fmt in ("%Y-%m-%d", "%d %b %Y", "%Y/%m/%d"):
            try:
                d = datetime.datetime.strptime(date_str.split(" ")[0], fmt)
                diff = (datetime.datetime.now() - d).days
                return f"{diff}g"
            except BaseException:
                pass
        return ""
    except BaseException:
        return ""


def load_portfolio():
    return fetch_json_from_github('portfolio.json')


pf = load_portfolio()

op_eq = []
op_cr = []
num_eq = 0
num_cr = 0

if pf and "open_positions" in pf:
    for ticker, info in pf["open_positions"].items():
        curr_p = info.get("current_price", info["entry_price"])
        pnl_pct = (curr_p / info["entry_price"] - 1.0) * \
            100 if info["entry_price"] > 0 else 0
        stop_p = info["stop_loss"]
        dist_stop_pct = (stop_p / curr_p - 1.0) * 100 if curr_p > 0 else 0

        entry_raw = info.get("entry_date", "-")
        days_str = calculate_days(entry_raw)
        entry_formatted = f"{entry_raw} ({days_str})" if days_str else entry_raw

        row = {
            "Titolo": ticker,
            "Data Ingresso": entry_formatted,
            "Ingresso ($)": info["entry_price"],
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
# TAB 1: PORTAFOGLIO & ALLOCAZIONE
# ==============================================================================
with tab_pf:
    c_inp, c_pnl = st.columns([3, 2])
    with c_inp:
        capitale = st.number_input(
            "💰 Capitale Broker Reale", min_value=1000, value=100000, step=1000, format="%d")
        st.caption(
            "Le size e le metriche si adattano istantaneamente al capitale inserito.")

    capitale_azionario = capitale * (alloc['Equities'] / 100)
    single_eq = capitale_azionario / 20 if alloc['Equities'] > 0 else 0
    crypto_cap = capitale * (alloc['Crypto'] / 100)
    gold_cap = capitale * (alloc['Gold'] / 100)
    bond_cap = capitale * (alloc['Bonds'] / 100)
    cash_cap = capitale * (alloc['Cash'] / 100)

    # Calcolo del Cash Reale
    real_cash = cash_cap
    if alloc['Equities'] > 0:
        real_cash += (20 - num_eq) * single_eq
    if alloc['Crypto'] > 0:
        real_cash += (3 - num_cr) * (capitale * 0.05)

    # Calcolo del P&L Totale Galleggiante Aperto
    tot_pnl_usd = 0.0
    tot_invested_usd = 0.0
    for r in op_eq:
        pnl_val = (r["P&L (%)"] / 100) * single_eq
        tot_pnl_usd += pnl_val
        tot_invested_usd += single_eq

    has_btc = any(r['Ticker'] == 'BTC' for r in op_cr)
    for r in op_cr:
        if has_btc:
            if num_cr == 1:
                cr_size = capitale * 0.10
            elif num_cr == 2:
                cr_size = capitale * \
                    0.10 if r['Ticker'] == 'BTC' else capitale * 0.05
            else:
                cr_size = capitale * 0.05
        else:
            cr_size = capitale * 0.05
        pnl_val = (r["P&L (%)"] / 100) * cr_size
        tot_pnl_usd += pnl_val
        tot_invested_usd += cr_size

    tot_pnl_pct = (tot_pnl_usd / tot_invested_usd *
                   100) if tot_invested_usd > 0 else 0.0

    with c_pnl:
        num_pos = len(op_eq) + len(op_cr)
        if num_pos > 0:
            pnl_sign = "+" if tot_pnl_usd >= 0 else ""
            pnl_col = "#10B981" if tot_pnl_usd >= 0 else "#EF4444"
            pnl_text = f"{pnl_sign}{
                tot_pnl_usd:,.0f} <span style='font-size: 13px; font-weight: 600;'>({pnl_sign}{
                tot_pnl_pct:.2f}%)</span>"
            sub_text = f"Su {num_pos} posizioni aperte"
        else:
            pnl_col = "#9CA3AF"
            pnl_text = "0 <span style='font-size: 13px; font-weight: 600;'>(0.00%)</span>"
            sub_text = "Nessuna posizione aperta (attesa venerdì)"

        st.markdown(f'''
        <div style="background: rgba(128,128,128,0.06); border: 1px solid rgba(128,128,128,0.15); border-radius: 8px; padding: 10px 16px; margin-top: 2px;">
            <div style="color: #9CA3AF; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Rendimento Galleggiante Aperto</div>
            <div style="font-size: 19px; font-weight: 700; color: {pnl_col}; font-family: 'JetBrains Mono', monospace; margin: 2px 0;">
                {pnl_text}
            </div>
            <div style="color: #6B7280; font-size: 10.5px;">{sub_text}</div>
        </div>
        ''', unsafe_allow_html=True)

    st.write("")

    # Liquidità & Coperture Cards (3 pure asset buckets)
    def make_asset_card(icon, label, amount, subtext,
                        border_col, is_active=True):
        opacity = "1" if is_active else "0.4"
        return (
            f'<div style="background: rgba(128,128,128,0.06); border: 1px solid {border_col}; border-radius: 8px; padding: 10px 14px; opacity: {opacity};">'
            f'<div style="color: #9CA3AF; font-size: 11px; font-weight: 600;">{icon} {label}</div>'
            f'<div style="font-size: 18px; font-weight: 700; font-family: \'JetBrains Mono\', monospace; margin: 3px 0;">{
                amount:,.0f}</div>'
            f'<div style="color: #6B7280; font-size: 10.5px;">{subtext}</div>'
            f'</div>'
        )

    card_cash = make_asset_card("💵", "LIQUIDITÀ / MONETARIO", real_cash,
                                "Liquidità strategica + transitoria", "#3B82F6", True)
    card_gold = make_asset_card("🥇", "ORO", gold_cap, "Copertura Macro",
                                "#F59E0B" if alloc['Gold'] > 0 else "#4B5563", alloc['Gold'] > 0)
    card_bond = make_asset_card("🛡️", "OBBLIGAZIONI", bond_cap, "Copertura Tassi",
                                "#8B5CF6" if alloc['Bonds'] > 0 else "#4B5563", alloc['Bonds'] > 0)

    st.html(
        f'<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin-bottom: 18px;">{card_cash}{card_gold}{card_bond}</div>')

    def color_pnl(val):
        color = '#10B981' if val > 0 else '#EF4444' if val < 0 else 'gray'
        return f'color: {color}; font-weight: 700;'

    def color_stop_dist(val):
        if val > -5.0:
            return 'color: #EF4444; font-weight: 700;'
        elif val > -10.0:
            return 'color: #F59E0B; font-weight: 600;'
        else:
            return 'color: #9CA3AF;'

    col_az, col_cr = st.columns([2, 1])

    with col_az:
        st.markdown(f'''
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 1.1rem; font-weight: 600;">📈 Azioni in Portafoglio</span>
            <span style="background: rgba(16, 185, 129, 0.15); color: #10B981; padding: 2px 8px; border-radius: 6px; font-size: 11.5px; font-weight: 700; font-family: 'JetBrains Mono', monospace;">{num_eq} / 20</span>
        </div>
        ''', unsafe_allow_html=True)

        if op_eq:
            df_op_eq = pd.DataFrame(op_eq)
            df_op_eq["Importo"] = single_eq
            df_op_eq["P&L Monetario"] = (
                df_op_eq["P&L (%)"] / 100) * df_op_eq["Size"]

            df_eq_styled = df_op_eq.style.format({
                "Ingresso ($)": "{:.2f}",
                "Attuale ($)": "{:.2f}",
                "Stop Loss ($)": "{:.2f}",
                "Distanza Stop": "{:.1f}%",
                "Importo": "{:,.0f}",
                "Rendimento %": "{:+.2f}%",
                "Rendimento Netto": "{:+,.0f}"
            }).map(color_pnl, subset=['Rendimento %', 'Rendimento Netto']).map(color_stop_dist, subset=['Distanza Stop'])

            st.dataframe(df_eq_styled, use_container_width=True,
                         hide_index=True)
        else:
            st.info(
                "Nessuna azione in portafoglio. In attesa del ricalcolo del venerdì.")

    with col_cr:
        st.markdown(f'''
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 1.1rem; font-weight: 600;">🪙 Crypto in Portafoglio</span>
            <span style="background: rgba(16, 185, 129, 0.15); color: #10B981; padding: 2px 8px; border-radius: 6px; font-size: 11.5px; font-weight: 700; font-family: 'JetBrains Mono', monospace;">{num_cr} / 3</span>
        </div>
        ''', unsafe_allow_html=True)

        if op_cr:
            df_op_cr = pd.DataFrame(op_cr)
            budgets = []
            has_btc = any(r['Ticker'] == 'BTC' for r in op_cr)
            for _, r in df_op_cr.iterrows():
                if has_btc:
                    if num_cr == 1:
                        budgets.append(capitale * 0.10)
                    elif num_cr == 2:
                        budgets.append(
                            capitale * 0.10 if r['Ticker'] == 'BTC' else capitale * 0.05)
                    else:
                        budgets.append(capitale * 0.05)
                else:
                    budgets.append(capitale * 0.05)
            df_op_cr["Importo"] = budgets
            df_op_cr["P&L Monetario"] = (
                df_op_cr["P&L (%)"] / 100) * df_op_cr["Size"]

            df_cr_styled = df_op_cr.style.format({
                "Ingresso ($)": format_price,
                "Attuale ($)": format_price,
                "Stop Loss ($)": format_price,
                "Distanza Stop": "{:.1f}%",
                "Importo": "{:,.0f}",
                "Rendimento %": "{:+.2f}%",
                "Rendimento Netto": "{:+,.0f}"
            }).map(color_pnl, subset=['Rendimento %', 'Rendimento Netto']).map(color_stop_dist, subset=['Distanza Stop'])

            st.dataframe(df_cr_styled, use_container_width=True,
                         hide_index=True)
        else:
            st.info("Nessuna crypto in portafoglio.")
# ==============================================================================
# TAB 2: METRICHE & GRAFICO
# ==============================================================================
with tab_perf:
    col_chart_hdr, col_chart_mode = st.columns([3, 1])
    with col_chart_hdr:
        st.markdown("#### 📈 Andamento del Portafoglio")
    with col_chart_mode:
        timeframe = st.radio("Timeframe", [
                             "Settimanale", "Giornaliero"], horizontal=True, label_visibility="collapsed")

    @st.cache_data(ttl=3600)
    def load_benchmark():
        url = "https://query2.finance.yahoo.com/v8/finance/chart/SPY?interval=1d&range=5y"
        req = urllib.request.Request(
            url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            res = urllib.request.urlopen(req).read().decode()
            data = json.loads(res)['chart']['result'][0]
            timestamps = data['timestamp']
            closes = data['indicators']['quote'][0]['close']

            dates = [datetime.datetime.fromtimestamp(
                ts).strftime('%Y-%m-%d') for ts in timestamps]
            df = pd.DataFrame({'date': dates, 'SPY': closes})
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            return df.dropna()
        except BaseException:
            return pd.DataFrame()

    @st.cache_data(ttl=60)
    def load_equity():
        data = fetch_json_from_github('equity.json')
        return data.get("history", []) if data else []

    eq_history = load_equity()

    max_dd = 0.0
    current_dd = 0.0

    if len(eq_history) >= 1:
        df_eq = pd.DataFrame(eq_history)
        df_eq['date'] = pd.to_datetime(df_eq['date'])
        df_eq.set_index('date', inplace=True)

        base_val = df_eq['value'].iloc[0] if 'value' in df_eq.columns else df_eq['close'].iloc[0]

        # Generazione OHLC per le Candele se non presente
        if 'open' not in df_eq.columns:
            df_eq['close'] = df_eq['value']
            df_eq['open'] = df_eq['close'].shift(1).fillna(df_eq['close'])
            df_eq['high'] = df_eq[['open', 'close']].max(axis=1) * 1.002
            df_eq['low'] = df_eq[['open', 'close']].min(axis=1) * 0.998
            df_eq.loc[df_eq.index[0],
                      'high'] = df_eq.loc[df_eq.index[0], 'close'] * 1.001
            df_eq.loc[df_eq.index[0],
                      'low'] = df_eq.loc[df_eq.index[0], 'close'] * 0.999

        if timeframe == "Settimanale":
            df_plot = df_eq.resample('W-FRI').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last'
            }).dropna()
            date_fmt = '%d %b %Y'
        else:
            df_plot = df_eq.copy()
            date_fmt = '%d %b'

        first_open = df_eq['open'].iloc[0]
        df_plot['norm_open'] = (df_plot['open'] / first_open) * 100
        df_plot['norm_high'] = (df_plot['high'] / first_open) * 100
        df_plot['norm_low'] = (df_plot['low'] / first_open) * 100
        df_plot['norm_close'] = (df_plot['close'] / first_open) * 100

        # Calcolo Drawdown
        cummax = df_plot['norm_close'].cummax()
        dd_series = (df_plot['norm_close'] - cummax) / cummax * 100
        max_dd = dd_series.min()
        current_dd = dd_series.iloc[-1]

        x_labels = [d.strftime(date_fmt) for d in df_plot.index]

        # Benchmark Alignment
        df_spy = load_benchmark()
        spy_norm = []
        if not df_spy.empty:
            if timeframe == "Settimanale":
                df_spy_resampled = df_spy.resample('W-FRI').last().dropna()
            else:
                df_spy_resampled = df_spy.copy()

            for dt in df_plot.index:
                if dt in df_spy_resampled.index:
                    spy_norm.append(df_spy_resampled.loc[dt, 'SPY'])
                else:
                    prior = df_spy_resampled.loc[df_spy_resampled.index <= dt]
                    spy_norm.append(
                        prior['SPY'].iloc[-1] if not prior.empty else df_spy_resampled['SPY'].iloc[0])

            if spy_norm:
                spy_base = spy_norm[0]
                spy_norm = [(s / spy_base) * 100 for s in spy_norm]

        fig = go.Figure()

        # 1. Candele Giapponesi per Strategia Apex
        fig.add_trace(
            go.Candlestick(
                x=x_labels,
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

        # 2. Linea per S&P 500 (Benchmark)
        if spy_norm:
            fig.add_trace(
                go.Scatter(
                    x=x_labels,
                    y=spy_norm,
                    mode='lines+markers',
                    line=dict(color='#94A3B8', width=2, dash='dot'),
                    marker=dict(size=6, color='#94A3B8'),
                    name='S&P 500'
                )
            )

        fig.update_layout(
            template='plotly_dark',
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(type='category', showgrid=True,
                       gridcolor='rgba(255,255,255,0.06)'),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.06)'),
            xaxis_rangeslider_visible=False,
            margin=dict(l=0, r=0, t=20, b=0),
            height=440,
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01)
        )

        st.plotly_chart(fig, use_container_width=True)

    else:
        st.info("📊 In attesa del file di tracciamento storico.")

    st.write("")

    if pf:
        hist = pf.get("trade_history", [])
        open_pos = pf.get("open_positions", {})

        wins = [t for t in hist if t.get("profit_pct", 0) > 0]
        losses = [t for t in hist if t.get("profit_pct", 0) <= 0]

        win_rate = (len(wins) / len(hist) * 100) if hist else 0.0
        avg_win = sum(t["profit_pct"]
                      for t in wins) / len(wins) if wins else 0.0
        avg_loss = sum(t["profit_pct"]
                       for t in losses) / len(losses) if losses else 0.0

        gross_profit = sum(t["profit_pct"] for t in wins)
        gross_loss = abs(sum(t["profit_pct"] for t in losses))

        payoff_ratio = avg_win / abs(avg_loss) if avg_loss != 0 else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss != 0 else 0.0
        expectancy = (win_rate / 100 * avg_win) + \
            (1 - win_rate / 100) * avg_loss

        st.markdown("#### 🎯 Vantaggio Matematico")

        def make_kpi_card(title, value, subtext="", val_color="#F9FAFB", border_color="rgba(128,128,128,0.18)"):
            return (
                f'<div style="background: rgba(128,128,128,0.06); border: 1px solid {border_color}; border-radius: 10px; padding: 12px 16px; display: flex; flex-direction: column; justify-content: space-between;">'
                f'<div style="color: #9CA3AF; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">{title}</div>'
                f'<div style="font-size: 22px; font-weight: 700; color: {val_color}; font-family: \'JetBrains Mono\', monospace; margin-bottom: 2px;">{value}</div>'
                f'{f"<div style='color: #6B7280; font-size: 10.5px;'>{subtext}</div>" if subtext else ""}'
                f'</div>'
            )

        c_win = "#10B981" if win_rate >= 50 else (
            "#3B82F6" if win_rate >= 40 else "#9CA3AF")
        c_payoff = "#10B981" if payoff_ratio >= 2.0 else (
            "#F59E0B" if payoff_ratio >= 1.0 else "#9CA3AF")
        c_pf = "#10B981" if profit_factor >= 1.5 else (
            "#F59E0B" if profit_factor >= 1.0 else ("#EF4444" if hist else "#9CA3AF"))
        c_exp = "#10B981" if expectancy > 0 else (
            "#EF4444" if expectancy < 0 else "#9CA3AF")

        card_m1 = make_kpi_card("Tasso di Successo", f"{win_rate:.1f}%", "% operazioni chiuse in profitto",
                                c_win, "#10B981" if win_rate >= 50 else "rgba(128,128,128,0.18)")
        card_m2 = make_kpi_card("Rapporto Guadagno / Perdita", f"{payoff_ratio:.2f}x", "Dimensione vincite vs stop loss",
                                c_payoff, "#10B981" if payoff_ratio >= 2.0 else "rgba(128,128,128,0.18)")
        card_m3 = make_kpi_card("Fattore di Profitto", f"{profit_factor:.2f}", "Profitti lordi / perdite lorde",
                                c_pf, "#10B981" if profit_factor >= 1.5 else "rgba(128,128,128,0.18)")
        card_m4 = make_kpi_card("Valore Atteso", f"{expectancy:+.2f}%", "Aspettativa media per trade",
                                c_exp, "#10B981" if expectancy > 0 else "rgba(128,128,128,0.18)")

        st.html(
            f'<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin-bottom: 24px;">{card_m1}{card_m2}{card_m3}{card_m4}</div>')

        st.markdown("#### ⚙️ Statistiche Operative")

        c_win_avg = "#10B981" if avg_win > 0 else "#9CA3AF"
        c_loss_avg = "#EF4444" if avg_loss < 0 else "#9CA3AF"
        c_dd = "#F87171" if max_dd < 0 else "#9CA3AF"

        card_o1 = make_kpi_card(
            "Operazioni Chiuse", f"{len(hist)}", "Campione statistico complessivo", "#F9FAFB")
        card_o2 = make_kpi_card(
            "Vincita Media", f"{avg_win:+.2f}%", "Rendimento medio trade vincenti", c_win_avg)
        card_o3 = make_kpi_card(
            "Perdita Media", f"{avg_loss:+.2f}%", "Perdita media stop loss scattati", c_loss_avg)
        card_o4 = make_kpi_card(
            "Perdita Massima Storica", f"{max_dd:.2f}%", "Drawdown massimo registrato", c_dd)

        st.html(
            f'<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 12px; margin-bottom: 15px;">{card_o1}{card_o2}{card_o3}{card_o4}</div>')


# ==============================================================================
# TAB 3: RADAR ROTAZIONE
# ==============================================================================
with tab_radar:
    st.markdown("""
    <div style="background: rgba(59, 130, 246, 0.08); border-left: 4px solid #3B82F6; padding: 10px 14px; border-radius: 0 8px 8px 0; margin-bottom: 15px; font-size: 13px; color: #93C5FD;">
        💡 <strong>Radar di Rotazione:</strong> Questi sono i titoli con il momentum più alto <strong>Oggi</strong>. I titoli già presenti in portafoglio sono marcati con ⭐, mentre i nuovi candidati verranno acquistati solo se rimarranno in classifica nel giorno di Rotazione (ultimo venerdì del mese).
    </div>
    """, unsafe_allow_html=True)

    held_tickers = set(pf.get("open_positions", {}).keys()) if pf else set()

    def style_radar_status(val):
        if "⭐" in str(val):
            return 'background-color: rgba(16, 185, 129, 0.15); color: #10B981; font-weight: 700;'
        return 'color: #93C5FD;'

    rc1, rc2 = st.columns([2, 1])
    with rc1:
        st.markdown("#### 📈 Top 20 Azioni")
        if is_bull_eq:
            top20 = data.get("top20", [])
            if top20:
                df_eq = pd.DataFrame(top20)
                if "Momentum Score" in df_eq.columns:
                    df_eq = df_eq.drop(columns=["Momentum Score"])
                df_eq = df_eq.rename(columns={"Ticker": "Titolo"})

                df_eq["Pos"] = df_eq["Titolo"].apply(
                    lambda t: "⭐" if t in held_tickers else "🆕")

                cols = ["Pos", "Titolo", "Prezzo ($)", "Stop Loss ($)"]
                df_eq = df_eq[[c for c in cols if c in df_eq.columns]]

                st.dataframe(
                    df_eq.style.format({"Prezzo ($)": "{:.2f}", "Stop Loss ($)": "{:.2f}"}).map(
                        style_radar_status, subset=['Pos'] if 'Pos' in df_eq.columns else None),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("Nessun dato Top 20 disponibile.")
        else:
            st.warning(
                "Motore Azionario OFF (Semaforo Rosso). Nessun acquisto previsto.")

    with rc2:
        st.markdown("#### 🪙 Top 3 Crypto")
        if is_bull_cr:
            cr_top = data.get("crypto_top", [])
            if cr_top:
                df_c = pd.DataFrame(cr_top)
                if "Momentum Score" in df_c.columns:
                    df_c = df_c.drop(columns=["Momentum Score"])
                df_c = df_c.rename(columns={"Ticker": "Titolo"})

                df_c["Pos"] = df_c["Titolo"].apply(
                    lambda t: "⭐" if t in held_tickers else "🆕")
                cols = ["Pos", "Titolo", "Prezzo ($)", "Stop Loss ($)"]
                df_c = df_c[[c for c in cols if c in df_c.columns]]

                st.dataframe(
                    df_c.style.format({"Prezzo ($)": format_price, "Stop Loss ($)": format_price}).map(
                        style_radar_status, subset=['Pos'] if 'Pos' in df_c.columns else None),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("Nessun dato Crypto disponibile.")
        else:
            st.warning("Motore Crypto OFF (Semaforo Rosso).")


# ==============================================================================
# TAB 4: TRADE LOG
# ==============================================================================
with tab_log:
    st.markdown("#### 📜 Registro Operazioni Chiuse")
    if pf:
        hist = pf.get("trade_history", [])
        if hist:
            df_hist = pd.DataFrame(hist)
            df_hist = df_hist.sort_values("exit_date", ascending=False)

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
            # Drop is_crypto column if present for cleaner view
            if "is_crypto" in df_hist.columns:
                df_hist = df_hist.drop(columns=["is_crypto"])

            st.dataframe(
                df_hist.style.format({
                    "Prezzo Ingresso": "{:.2f}",
                    "Prezzo Uscita": "{:.2f}",
                    "Rendimento %": "{:+.2f}%"
                }).map(color_trade_pnl, subset=['Rendimento %'] if 'Rendimento %' in df_hist.columns else None),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("Nessuna operazione chiusa registrata.")
    else:
        st.info("Portfolio Logger non ancora inizializzato.")


# ==============================================================================
# TAB 5: GUIDA & STRATEGIA
# ==============================================================================
with tab_guide:
    st.markdown("#### 📖 Regole Operative")
    st.markdown("""
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 20px;">
        <div style="background: rgba(128,128,128,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 14px;">
            <div style="font-weight: 700; color: #60A5FA; margin-bottom: 6px;">📅 1. Rotazione Mensile</div>
            <div style="font-size: 13px; color: #D1D5DB;">L'ultimo venerdì del mese, controlla le Tabelle Operative. Vendi chi è uscito dalla Top, compra chi è entrato.</div>
        </div>
        <div style="background: rgba(128,128,128,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 14px;">
            <div style="font-weight: 700; color: #34D399; margin-bottom: 6px;">🛡️ 2. Gestione Cockpit</div>
            <div style="font-size: 13px; color: #D1D5DB;">Se un motore è <strong>🟢 ATTIVO</strong>, mantieni gli asset e aggiorna i trailing stop. Se diventa <strong>🔴 DISATTIVATO</strong>, vendi tutto il comparto lunedì mattina.</div>
        </div>
        <div style="background: rgba(128,128,128,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 14px;">
            <div style="font-weight: 700; color: #FBBF24; margin-bottom: 6px;">💵 3. Fondo Monetario</div>
            <div style="font-size: 13px; color: #D1D5DB;">La liquidità parcheggiata in Cash non va tenuta sul conto, ma investita in ETF Monetari (es. XEON o IB01) per rendita risk-free.</div>
        </div>
        <div style="background: rgba(128,128,128,0.06); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 14px;">
            <div style="font-weight: 700; color: #F87171; margin-bottom: 6px;">⚡ 4. Stop Loss Automatico</div>
            <div style="font-size: 13px; color: #D1D5DB;">Se il prezzo tocca lo Stop Loss sul broker, l'ordine scatterà automaticamente. Sposta il ricavato nel Fondo Monetario fino al venerdì.</div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.divider()

    st.markdown("#### 🧠 Documentazione Strategica")
    st.markdown('''
    **Apex Multi-Asset Engine** è un motore quantitativo a guida autonoma progettato per generare **Alpha assoluto**, battendo l'S&P 500 nel lungo termine e proteggendo al contempo il capitale dai crolli di mercato (Drawdown).

    ##### 1. Il Motore Macro (Waterfall Allocation)
    È il cuore difensivo della strategia. Misura il trend strutturale del mercato:
    - Se l'S&P 500 è sopra la sua media mobile a 200 giorni, il sistema alloca il capitale sugli asset di rischio (**Azioni** e **Crypto**).
    - Se l'S&P 500 crolla, il sistema attiva il protocollo *Waterfall*: sposta i fondi prima sull'**Oro**. Se anche l'Oro è negativo, si rifugia nelle **Obbligazioni**. Se c'è un crollo sistemico, parcheggia tutto nel **Fondo Monetario**.

    ##### 2. Il Motore Azionario (Momentum Cross-Sectional)
    Quando il semaforo Macro è verde:
    - Il motore analizza tutti i 500 titoli dell'S&P 500 e calcola il Rate of Change (ROC) a 130 giorni.
    - Seleziona solo i **20 migliori titoli** (equi-pesati al 5% ciascuno) che stanno sovraperformando il mercato.

    ##### 3. Il Motore Crypto
    Satellite ad alto rendimento, attivato solo se Bitcoin è sopra la sua MA200:
    - Alloca fino al 10-15% del capitale.
    - Seleziona fino a 3 altcoin con il momentum più esplosivo con stop loss dedicati (ATR x 2).

    ##### 4. Gestione del Rischio (ATR Trailing Stop)
    Ogni operazione è protetta da un **Trailing Stop Loss Dinamico** basato sulla volatilità reale (ATR).
    ''')
