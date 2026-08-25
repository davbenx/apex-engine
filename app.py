import datetime
import json
import os
import urllib.request

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Apex Multi-Asset", page_icon="🦅", layout="wide")

# --- CUSTOM THEME ENHANCEMENTS ---
st.markdown("""
<style>
    /* Metric styling */
    [data-testid="stMetricValue"] {
        font-size: 1.6rem !important;
        font-weight: 700 !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.85rem !important;
        color: #9CA3AF !important;
    }
    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 16px;
        border-radius: 8px 8px 0px 0px;
        font-weight: 600;
        font-size: 14px;
    }
</style>
""", unsafe_allow_html=True)


@st.cache_data(ttl=60)
def load_data():
    try:
        url = f"https://raw.githubusercontent.com/davbenx/apex-engine/main/apex_data.json?token={urllib.request.urlopen('https://api.github.com/repos/davbenx/apex-engine/commits/main').read().hex()[:10]}"
        req = urllib.request.Request(
            "https://raw.githubusercontent.com/davbenx/apex-engine/main/apex_data.json")
        return json.loads(urllib.request.urlopen(req).read().decode())
    except BaseException:
        if os.path.exists('apex_data.json'):
            with open('apex_data.json', 'r') as f:
                return json.load(f)
    return None


data = load_data()
if not data:
    st.error("🚨 Dati non disponibili. In attesa del ricalcolo notturno su GitHub.")
    st.stop()

# --- HEADER & STATUS BAR ---
last_update = data.get("timestamp", "Sincronizzazione in corso...")

col_title, col_meta = st.columns([3, 2])
with col_title:
    st.title("🦅 Apex Multi-Asset Engine")
with col_meta:
    st.markdown(f"""
    <div style="text-align: right; padding-top: 15px;">
        <span style="background: rgba(16, 185, 129, 0.15); color: #10B981; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; border: 1px solid rgba(16, 185, 129, 0.3);">🟢 Motore Live</span>
        <div style="color: #9CA3AF; font-size: 12px; margin-top: 5px;">
            🕒 <strong>Aggiornato:</strong> {last_update}<br>
            ⏳ <strong>Prossimo Ricalcolo:</strong> 01:30 UTC
        </div>
    </div>
    """, unsafe_allow_html=True)

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
chip_b = make_chip("🛡️", "Bond", alloc['Bonds'], is_bull_b, d_b)
chip_c = make_chip("💵", "Cash", alloc['Cash'], True, "", is_cash=True)

chips_html = f'<div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 12px;">{chip_eq}{chip_cr}{chip_g}{chip_b}{chip_c}</div>'

try:
    st.html(chips_html)
except BaseException:
    st.markdown(chips_html, unsafe_allow_html=True)

st.write("")

# --- TABS LAYOUT ---
tab_pf, tab_perf, tab_radar, tab_log, tab_guide = st.tabs([
    "💼 Portafoglio & Allocazione",
    "📈 Metriche & Grafico",
    "🔮 Radar Rotazione",
    "📜 Trade Log",
    "📖 Guida & Strategia"
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


def load_portfolio():
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://raw.githubusercontent.com/davbenx/apex-engine/main/portfolio.json")
        return json.loads(urllib.request.urlopen(req).read().decode())
    except BaseException:
        if os.path.exists('portfolio.json'):
            with open('portfolio.json', 'r') as f:
                return json.load(f)
        return None


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

        row = {
            "Ticker": ticker,
            "Data Ingresso": info.get("entry_date", "-"),
            "Ingresso ($)": info["entry_price"],
            "Attuale ($)": curr_p,
            "Stop Loss ($)": info["stop_loss"],
            "P&L (%)": pnl_pct
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
    c_inp, c_space = st.columns([1, 2])
    with c_inp:
        capitale = st.number_input(
            "💰 Inserisci Capitale Broker Reale", min_value=1000.0, value=100000.0, step=1000.0)
    st.caption(
        "Tutte le size monetarie vengono ricalcolate istantaneamente sul capitale inserito.")

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

    st.write("")

    # Liquidità & Coperture Cards
    def make_asset_card(icon, label, amount, subtext, border_col, is_active=True):
        opacity = "1" if is_active else "0.5"
        return (
            f'<div style="background: rgba(128,128,128,0.06); border: 1px solid {border_col}; border-radius: 8px; padding: 12px 16px; opacity: {opacity};">'
            f'<div style="color: #9CA3AF; font-size: 12px; font-weight: 600;">{icon} {label}</div>'
            f'<div style="font-size: 20px; font-weight: 700; margin: 4px 0;">{amount:,.0f}</div>'
            f'<div style="color: #6B7280; font-size: 11px;">{subtext}</div>'
            f'</div>'
        )

    card_cash = make_asset_card("💵", "CASH / FONDO MONETARIO", real_cash,
                                "Liquidità strategica + stop scattati", "#3B82F6", True)
    card_gold = make_asset_card("🥇", "ORO (GLD)", gold_cap, "Copertura Macro",
                                "#F59E0B" if alloc['Gold'] > 0 else "#4B5563", alloc['Gold'] > 0)
    card_bond = make_asset_card("🛡️", "BOND (TLT)", bond_cap, "Copertura Tassi",
                                "#8B5CF6" if alloc['Bonds'] > 0 else "#4B5563", alloc['Bonds'] > 0)

    st.html(
        f'<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-bottom: 20px;">{card_cash}{card_gold}{card_bond}</div>')

    def color_pnl(val):
        color = '#10B981' if val > 0 else '#EF4444' if val < 0 else 'gray'
        return f'color: {color}; font-weight: 700;'

    col_az, col_cr = st.columns([2, 1])

    with col_az:
        st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-weight: 700; font-size: 15px;">📈 Azioni in Portafoglio</span>
            <span style="background: rgba(16, 185, 129, 0.15); color: #10B981; padding: 2px 8px; border-radius: 6px; font-size: 12px; font-weight: 700;">{num_eq} / 20</span>
        </div>
        """, unsafe_allow_html=True)

        if op_eq:
            df_op_eq = pd.DataFrame(op_eq)
            df_op_eq["Size"] = single_eq
            df_op_eq["P&L Monetario"] = (
                df_op_eq["P&L (%)"] / 100) * df_op_eq["Size"]

            df_eq_styled = df_op_eq.style.format({
                "Ingresso ($)": "{:.2f}",
                "Attuale ($)": "{:.2f}",
                "Stop Loss ($)": "{:.2f}",
                "Size": "{:,.0f}",
                "P&L (%)": "{:+.2f}%",
                "P&L Monetario": "{:+,.0f}"
            }).map(color_pnl, subset=['P&L (%)', 'P&L Monetario'])

            st.dataframe(df_eq_styled, use_container_width=True,
                         hide_index=True)
        else:
            st.info(
                "Nessuna azione in portafoglio. In attesa del ricalcolo del venerdì.")

    with col_cr:
        st.markdown(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-weight: 700; font-size: 15px;">🪙 Crypto in Portafoglio</span>
            <span style="background: rgba(16, 185, 129, 0.15); color: #10B981; padding: 2px 8px; border-radius: 6px; font-size: 12px; font-weight: 700;">{num_cr} / 3</span>
        </div>
        """, unsafe_allow_html=True)

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
            df_op_cr["Size"] = budgets
            df_op_cr["P&L Monetario"] = (
                df_op_cr["P&L (%)"] / 100) * df_op_cr["Size"]

            df_cr_styled = df_op_cr.style.format({
                "Ingresso ($)": format_price,
                "Attuale ($)": format_price,
                "Stop Loss ($)": format_price,
                "Size": "{:,.0f}",
                "P&L (%)": "{:+.2f}%",
                "P&L Monetario": "{:+,.0f}"
            }).map(color_pnl, subset=['P&L (%)', 'P&L Monetario'])

            st.dataframe(df_cr_styled, use_container_width=True,
                         hide_index=True)
        else:
            st.info("Nessuna crypto in portafoglio.")


# ==============================================================================
# TAB 2: METRICHE & GRAFICO
# ==============================================================================
with tab_perf:
    st.markdown("#### 📈 Equity Curve Live (vs S&P 500)")

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
            return df
        except BaseException:
            return pd.DataFrame()

    eq_history = []
    if os.path.exists('equity_curve.json'):
        try:
            with open('equity_curve.json', 'r') as f:
                eq_history = json.load(f)
        except BaseException:
            pass

    if len(eq_history) > 1:
        df_eq = pd.DataFrame(eq_history)
        df_eq['date'] = pd.to_datetime(df_eq['date'])
        df_eq.set_index('date', inplace=True)

        start_date = df_eq.index[0]
        base_val = df_eq['equity'].iloc[0]
        df_eq['Apex'] = (df_eq['equity'] / base_val) * 100

        df_spy = load_benchmark()
        if not df_spy.empty:
            df_spy = df_spy.loc[df_spy.index >= start_date]
            if not df_spy.empty:
                spy_base = df_spy['SPY'].iloc[0]
                df_spy['Normalized'] = (df_spy['SPY'] / spy_base) * 100

        fig = go.Figure()

        fig.add_trace(
            go.Scatter(
                x=df_eq.index,
                y=df_eq['Apex'],
                mode='lines',
                line=dict(
                    color='#10B981',
                    width=3),
                name='Apex Multi-Asset (Strategy)'))

        if not df_spy.empty:
            fig.add_trace(
                go.Scatter(
                    x=df_spy.index,
                    y=df_spy['Normalized'],
                    mode='lines',
                    line=dict(
                        color='#94A3B8',
                        width=2,
                        dash='dot'),
                    name='S&P 500 (Benchmark)'))

        fig.update_layout(
            template='plotly_dark',
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.06)'),
            yaxis=dict(showgrid=True, gridcolor='rgba(255,255,255,0.06)'),
            xaxis_rangeslider_visible=False,
            margin=dict(l=0, r=0, t=20, b=0),
            height=420,
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01)
        )

        st.plotly_chart(fig, use_container_width=True)

    elif len(eq_history) == 1:
        st.info("📊 Tracking avviato. Il grafico dell'Equity Curve apparirà domani con il primo aggiornamento dei prezzi.")
    else:
        st.info("📊 In attesa del file Equity Curve.")

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

        st.markdown("#### 🎯 Vantaggio Matematico (The Edge)")
        rm1, rm2, rm3, rm4 = st.columns(4)
        rm1.metric("Win Rate", f"{win_rate:.1f}%")
        rm2.metric("Payoff Ratio (R:R)", f"{payoff_ratio:.2f}x")
        rm3.metric("Profit Factor", f"{profit_factor:.2f}")
        rm4.metric("Expectancy", f"{expectancy:+.2f}%")

        st.write("")

        st.markdown("#### ⚙️ Statistiche Operative")
        om1, om2, om3, om4 = st.columns(4)
        om1.metric("Trade Chiusi", f"{len(hist)}")
        om2.metric("Vincita Media", f"{avg_win:+.2f}%")
        om3.metric("Perdita Media", f"{avg_loss:+.2f}%")
        om4.metric("Posizioni Aperte", f"{len(open_pos)}")


# ==============================================================================
# TAB 3: RADAR ROTAZIONE
# ==============================================================================
with tab_radar:
    st.markdown("""
    <div style="background: rgba(59, 130, 246, 0.08); border-left: 4px solid #3B82F6; padding: 10px 14px; border-radius: 0 8px 8px 0; margin-bottom: 15px; font-size: 13px; color: #93C5FD;">
        💡 <strong>Radar di Rotazione:</strong> Questi sono i titoli con il momentum più alto <strong>Oggi</strong>. Verranno acquistati solo se rimarranno in classifica nel giorno di Rotazione (ultimo venerdì del mese).
    </div>
    """, unsafe_allow_html=True)

    rc1, rc2 = st.columns([2, 1])
    with rc1:
        st.markdown("**📈 Top 20 Azioni (S&P 500 Momentum)**")
        if is_bull_eq:
            top20 = data.get("top20", [])
            if top20:
                df_eq = pd.DataFrame(top20)
                if "Momentum Score" in df_eq.columns:
                    df_eq = df_eq.drop(columns=["Momentum Score"])
                st.dataframe(df_eq.style.format(
                    {"Prezzo ($)": "{:.2f}", "Stop Loss ($)": "{:.2f}"}), use_container_width=True, hide_index=True)
            else:
                st.info("Nessun dato Top 20 disponibile.")
        else:
            st.warning(
                "Motore Azionario OFF (Semaforo Rosso). Nessun acquisto previsto.")

    with rc2:
        st.markdown("**🪙 Top 3 Crypto Momentum**")
        if is_bull_cr:
            cr_top = data.get("crypto_top", [])
            if cr_top:
                df_c = pd.DataFrame(cr_top)
                if "Momentum Score" in df_c.columns:
                    df_c = df_c.drop(columns=["Momentum Score"])
                st.dataframe(df_c.style.format(
                    {"Prezzo ($)": format_price, "Stop Loss ($)": format_price}), use_container_width=True, hide_index=True)
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

            st.dataframe(
                df_hist.style.format({
                    "entry_price": "{:.2f}",
                    "exit_price": "{:.2f}",
                    "profit_pct": "{:+.2f}%"
                }).map(color_trade_pnl, subset=['profit_pct']),
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
    st.markdown("#### 📖 Regole Operative (Come usare la Dashboard)")
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

    st.markdown("#### 🧠 Documentazione Strategia e Backtest")
    st.markdown('''
    **Apex Multi-Asset Engine** è un motore quantitativo a guida autonoma progettato per generare **Alpha assoluto**, battendo l'S&P 500 nel lungo termine e proteggendo al contempo il capitale dai crolli di mercato (Drawdown).

    ##### 1. Il Motore Macro (Waterfall Allocation)
    È il cuore difensivo della strategia. Misura il trend strutturale del mercato:
    - Se l'S&P 500 è sopra la sua media mobile a 200 giorni, il sistema alloca il capitale sugli asset di rischio (**Azioni** e **Crypto**).
    - Se l'S&P 500 crolla, il sistema attiva il protocollo *Waterfall*: sposta i fondi prima sull'**Oro (GLD)**. Se anche l'Oro è negativo, si rifugia nei **Titoli di Stato USA (TLT)**. Se c'è un crollo sistemico, parcheggia tutto nel **Fondo Monetario**.

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
