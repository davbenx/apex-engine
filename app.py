import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import json
import os

st.set_page_config(page_title="Apex Multi-Asset", page_icon="🦅", layout="wide")

st.title("🦅 Apex Multi-Asset Engine")
st.markdown("##### Il tuo portafoglio sistematico a guida autonoma.")

@st.cache_data(ttl=60)
def load_data():
    import urllib.request
    import json
    # Prova prima a scaricare il file aggiornato dal Cloud (GitHub)
    url = f"https://raw.githubusercontent.com/davbenx/apex-engine/main/apex_data.json?token={urllib.request.urlopen('https://api.github.com/repos/davbenx/apex-engine/commits/main').read().hex()[:10]}" # Cache buster
    try:
        req = urllib.request.Request("https://raw.githubusercontent.com/davbenx/apex-engine/main/apex_data.json")
        return json.loads(urllib.request.urlopen(req).read().decode())
    except:
        # Fallback locale se internet è giù
        if os.path.exists('apex_data.json'):
            with open('apex_data.json', 'r') as f:
                return json.load(f)
    return None

data = load_data()
if not data:
    st.error("🚨 Dati non disponibili. In attesa del ricalcolo notturno su GitHub.")
    st.stop()

# --- TIMESTAMPS ---
last_update = data.get("timestamp", "Sincronizzazione in corso...")
st.caption(f"🕒 **Aggiornato:** {last_update}")
st.caption("⏳ **Prossimo Ricalcolo:** 01:30")

with st.expander("📖 Regole Operative (Come usare questa Dashboard)", expanded=False):
    st.markdown('''
    - **📅 Rotazione Mensile:** L'ultimo venerdì del mese, controlla le Tabelle Operative. Vendi chi è uscito dalla Top, compra chi è entrato.
    - **🛡️ Gestione Cockpit:** 
        - Se un motore è **🟢 ATTIVO**, mantieni l'investimento nei rispettivi asset e aggiorna i Trailing Stop sul broker.
        - Se un motore diventa **🔴 DISATTIVATO**, vendi tutto il comparto lunedì mattina.
    - **💵 Liquidità (Fondo Monetario):** Il capitale parcheggiato in "Cash / Monetario" non va tenuto sul conto corrente, ma investito in ETF Monetari (es. XEON o IB01) per generare una rendita risk-free.
    - **⚡ Automazione:** Se durante la settimana il prezzo tocca lo Stop Loss sul broker, l'ordine scatterà automaticamente. Sposta i soldi nel Fondo Monetario fino alla rotazione successiva.
    ''')

# --- EQUITY CURVE ---
st.header("📈 Performance Live")
@st.cache_data(ttl=60)

@st.cache_data(ttl=3600)
def load_benchmark():
    import urllib.request
    import json
    import pandas as pd
    import datetime
    
    url = "https://query2.finance.yahoo.com/v8/finance/chart/SPY?interval=1d&range=5y"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        res = urllib.request.urlopen(req).read().decode()
        data = json.loads(res)['chart']['result'][0]
        timestamps = data['timestamp']
        closes = data['indicators']['quote'][0]['close']
        
        dates = [datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d') for ts in timestamps]
        df = pd.DataFrame({'date': dates, 'SPY': closes})
        df['date'] = pd.to_datetime(df['date'])
        df.set_index('date', inplace=True)
        return df
    except:
        return pd.DataFrame()
def load_equity():
    import urllib.request
    import json
    try:
        req = urllib.request.Request("https://raw.githubusercontent.com/davbenx/apex-engine/main/equity.json")
        return json.loads(urllib.request.urlopen(req).read().decode()).get("history", [])
    except:
        if os.path.exists('equity.json'):
            with open('equity.json', 'r') as f:
                return json.load(f).get("history", [])
    return []

eq_history = load_equity()
if len(eq_history) > 1:
    df_eq = pd.DataFrame(eq_history)
    df_eq['date'] = pd.to_datetime(df_eq['date'])
    df_eq.set_index('date', inplace=True)
    
    start_val = df_eq['value'].iloc[0]
    end_val = df_eq['value'].iloc[-1]
    perf_pct = ((end_val / start_val) - 1) * 100
    
    peak = df_eq['value'].cummax()
    drawdown = ((df_eq['value'] - peak) / peak) * 100
    current_dd = drawdown.iloc[-1]
    max_dd = drawdown.min()
    
    m1, m2, m3 = st.columns(3)
    m1.metric(label="Valore Attuale (Base 100k)", value=f"{end_val:,.0f}", delta=f"{perf_pct:.2f}% dal lancio")
    m2.metric(label="Drawdown Attuale", value=f"{current_dd:.2f}%", delta="Distanza dal picco massimo", delta_color="inverse")
    m3.metric(label="Max Drawdown", value=f"{max_dd:.2f}%", delta="Peggior caduta dal lancio", delta_color="off")
    
    # Resample to weekly OHLC for candlestick
    df_weekly = df_eq['value'].resample('W-FRI').ohlc()
    df_weekly.dropna(inplace=True)
    
    fig = go.Figure()
    
    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df_weekly.index,
        open=df_weekly['open'],
        high=df_weekly['high'],
        low=df_weekly['low'],
        close=df_weekly['close'],
        name='Portfolio',
        increasing_line_color='#00ff00',
        decreasing_line_color='#ff0000'
    ))
    
    # SPY Benchmark
    df_spy = load_benchmark()
    if not df_spy.empty:
        df_spy = df_spy[df_spy.index >= df_eq.index[0]]
        if not df_spy.empty:
            start_val_spy = df_spy['SPY'].iloc[0]
            our_start_val = df_eq['value'].iloc[0]
            df_spy['Normalized'] = (df_spy['SPY'] / start_val_spy) * our_start_val
            
            fig.add_trace(go.Scatter(
                x=df_spy.index,
                y=df_spy['Normalized'],
                mode='lines',
                line=dict(color='rgba(255, 255, 255, 0.5)', width=2, dash='dot'),
                name='S&P 500 (Benchmark)'
            ))
            

                  
    fig.update_layout(
        template='plotly_dark',
        xaxis_rangeslider_visible=False,
        margin=dict(l=0, r=0, t=30, b=0),
        height=500,
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01)
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
elif len(eq_history) == 1:
    st.info("📊 Tracking avviato. Il grafico dell'Equity Curve apparirà domani con il primo aggiornamento dei prezzi.")
else:
    st.info("📊 In attesa del file Equity Curve.")

st.divider()

# --- COCKPIT ---
st.header("🎛️ Allocazione Portafoglio")
capitale = st.number_input("Imposta il Capitale Totale ($ o €)", min_value=1000, value=100000, step=1000, format="%d")

alloc = data.get("allocations", {"Equities": 0, "Crypto": 0, "Gold": 0, "Bonds": 0, "Cash": 100})

is_bull_eq = alloc.get("Equities", 0) > 0
is_bull_cr = alloc.get("Crypto", 0) > 0
is_bull_g = alloc.get("Gold", 0) > 0
is_bull_b = alloc.get("Bonds", 0) > 0

eq_cap = capitale * (alloc["Equities"] / 100.0)
single_eq = eq_cap / 20 if alloc["Equities"] > 0 else 0

btc_cap = capitale * (alloc["Crypto"] / 100.0)
cr_list = data.get('crypto_top', [])


gold_cap = capitale * (alloc["Gold"] / 100.0)
bond_cap = capitale * (alloc["Bonds"] / 100.0)
cash_cap = capitale * (alloc["Cash"] / 100.0)

c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    st.markdown(f"### 📈 Azioni `{alloc['Equities']}%`")
    if is_bull_eq: st.success(f"**🟢 ATTIVO**\n\nBudget: **{eq_cap:,.0f}**")
    else: st.error(f"**🔴 DISATTIVATO**\n\nBudget: **{eq_cap:,.0f}**")

with c2:
    st.markdown(f"### 🪙 Crypto `{alloc['Crypto']}%`")
    if is_bull_cr: 
        btc_stop = None
        for c in data.get("crypto_top", []):
            if c["Ticker"] == "BTC":
                btc_stop = c["Stop Loss"]
                break
        
        if btc_stop:
            st.success(f"**🟢 ATTIVO**\n\nBudget: **{btc_cap:,.0f}**\n\n*(Stop BTC: {btc_stop:,.0f})*")
        else:
            st.success(f"**🟢 ATTIVO**\n\nBudget: **{btc_cap:,.0f}**")
    else: 
        st.error(f"**🔴 DISATTIVATO**\n\nBudget: **{btc_cap:,.0f}**")

with c3:
    st.markdown(f"### 🥇 Oro `{alloc['Gold']}%`")
    if is_bull_g: st.success(f"**🟢 ATTIVO**\n\nBudget: **{gold_cap:,.0f}**")
    else: st.error(f"**🔴 DISATTIVATO**\n\nBudget: **{gold_cap:,.0f}**")

with c4:
    st.markdown(f"### 🛡️ Obbligazioni `{alloc['Bonds']}%`")
    if is_bull_b: st.success(f"**🟢 ATTIVO**\n\nBudget: **{bond_cap:,.0f}**")
    else: st.error(f"**🔴 DISATTIVATO**\n\nBudget: **{bond_cap:,.0f}**")
    
with c5:
    st.markdown(f"### 💵 Monetario `{alloc['Cash']}%`")
    st.info(f"**⚪ FONDO MONETARIO**\n\nBudget: **{cash_cap:,.0f}**")

st.divider()

# --- TABELLE OPERATIVE ---
st.header("📋 Liste Operative")
def format_price(x):
    if x >= 1000: return f"{x:,.2f}"
    elif x >= 1: return f"{x:,.4f}"
    elif x >= 0.01: return f"{x:,.6f}"
    else: return f"{x:,.8f}"

col_az, col_cr = st.columns([2, 1])

with col_az:
    st.subheader("📈 Top 20 Azioni")
    
    if is_bull_eq:
        top20 = data.get("top20", [])
        if top20:
            df_eq = pd.DataFrame(top20)
            if "Momentum Score" in df_eq.columns: df_eq = df_eq.drop(columns=["Momentum Score"])
            df_eq["Budget"] = single_eq
            df_eq = df_eq.rename(columns={"Prezzo ($)": "Prezzo", "Stop Loss ($)": "Stop Loss", "Budget ($)": "Budget"})
            st.dataframe(df_eq.style.format({"Prezzo": "{:.2f}", "Stop Loss": "{:.2f}", "Budget": "{:,.0f}"}), use_container_width=True, hide_index=True)
    else:
        st.info("Semaforo Rosso. Tabella disattivata per prevenire acquisti.")

with col_cr:
    st.subheader("🪙 Top 3 Crypto")
    
    if is_bull_cr:
        cr_top = data.get("crypto_top", [])
        if cr_top:
            df_c = pd.DataFrame(cr_top)
            if "Momentum Score" in df_c.columns: df_c = df_c.drop(columns=["Momentum Score"])
            
            budgets = []
            has_btc = any(r['Ticker'] == 'BTC' for r in cr_top)
            num_cr = len(cr_top)
            
            for _, r in df_c.iterrows():
                if has_btc:
                    if num_cr == 1:
                        budgets.append(capitale * 0.10)
                    elif num_cr == 2:
                        budgets.append(capitale * 0.10 if r['Ticker'] == 'BTC' else capitale * 0.05)
                    else:
                        budgets.append(capitale * 0.05)
                else:
                    budgets.append(capitale * 0.05)
                    
            df_c["Budget"] = budgets
            df_c = df_c.rename(columns={"Prezzo ($)": "Prezzo", "Stop Loss ($)": "Stop Loss", "Budget ($)": "Budget"})
            
            st.dataframe(df_c.style.format({"Prezzo": format_price, "Stop Loss": format_price, "Budget": "{:,.0f}"}), use_container_width=True, hide_index=True)
    else:
        st.info("Semaforo Rosso. Tabella disattivata.")



st.divider()

# --- METRICHE DI RISCHIO E TRADE LOG ---
with st.expander("📊 Metriche di Rischio & Trade Log", expanded=False):
    # pf is loaded above
    if pf:
    if pf:
        hist = pf.get("trade_history", [])
        open_pos = pf.get("open_positions", {})
        
        wins = [t for t in hist if t.get("profit_pct", 0) > 0]
        losses = [t for t in hist if t.get("profit_pct", 0) <= 0]
        
        win_rate = (len(wins) / len(hist) * 100) if hist else 0.0
        avg_win = sum(t["profit_pct"] for t in wins) / len(wins) if wins else 0.0
        avg_loss = sum(t["profit_pct"] for t in losses) / len(losses) if losses else 0.0
        
        expectancy = (win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss)
        
        rm1, rm2, rm3, rm4 = st.columns(4)
        rm1.metric("Win Rate", f"{win_rate:.1f}%")
        rm2.metric("Expectancy per Trade", f"{expectancy:.2f}%")
        rm3.metric("Trade Chiusi", f"{len(hist)}")
        rm4.metric("Posizioni Aperte", f"{len(open_pos)}")
        
        st.markdown("##### Registro Operazioni Chiuse")
        if hist:
            df_hist = pd.DataFrame(hist)
            df_hist = df_hist.sort_values("exit_date", ascending=False)
            st.dataframe(df_hist, use_container_width=True)
        else:
            st.info("Nessuna operazione chiusa registrata.")
    else:
        st.info("Portfolio Logger non ancora inizializzato.")

# --- DOCUMENTAZIONE E STRATEGIA ---
with st.expander("🧠 Documentazione Strategia e Backtest", expanded=False):
    st.markdown('''
    ### Apex Multi-Asset Engine
    Apex è un motore quantitativo a guida autonoma progettato per generare **Alpha assoluto**, battendo l'S&P 500 nel lungo termine e proteggendo al contempo il capitale dai crolli di mercato (Drawdown). 
    L'approccio è sistematico al 100%, eliminando le emozioni e la discrezionalità umana.

    #### 1. Il Motore Macro (Waterfall Allocation)
    È il cuore difensivo della strategia. Misura il trend strutturale del mercato.
    - Se l'S&P 500 è in trend rialzista (sopra la sua media mobile a 200 giorni), il sistema alloca il capitale sugli asset di rischio (Azioni e Crypto).
    - Se l'S&P 500 crolla, il sistema attiva il protocollo *Waterfall*: sposta i fondi prima sull'Oro (GLD). Se anche l'Oro è negativo, si rifugia nei Titoli di Stato a lungo termine (TLT). Se c'è un crollo sistemico, parcheggia tutto nel Fondo Monetario (Risk-Free).

    #### 2. Il Motore Azionario (Momentum Cross-Sectional)
    Quando il semaforo Macro è verde, non compriamo l'intero indice, ma applichiamo una selezione *Momentum*.
    - Il motore analizza tutti i 500 titoli dell'S&P 500 e calcola il Rate of Change (ROC) a 130 giorni.
    - Seleziona solo i **20 migliori titoli** (equi-pesati al 5% ciascuno) che stanno sovraperformando il mercato.
    - Questo genera l'extra-rendimento (Alpha) necessario per battere i benchmark passivi.

    #### 3. Il Motore Crypto
    Un satellite ad alto rendimento, attivato solo se il Bitcoin è in trend rialzista (sopra la sua MA200).
    - Alloca fino al 10% del capitale.
    - Cerca le migliori altcoin tradabili come contratti Perpetual (Futures) su Kraken.
    - Applica una formula dinamica 10-5-5: se c'è solo BTC in trend, prende il 10%. Se emergono altcoin forti, scala dinamicamente per includerle senza aumentare il rischio complessivo.

    #### 4. Gestione del Rischio (Trailing Stop)
    Ogni singola operazione (sia Azionaria che Crypto) è protetta da un **Trailing Stop Loss Dinamico**.
    - Lo stop viene calcolato matematicamente usando l'**Average True Range (ATR)** moltiplicato per 2 (o 3).
    - Questo stop si "alza" man mano che il prezzo sale, bloccando i profitti.
    - Se il prezzo inverte e tocca lo Stop Loss, la posizione viene liquidata istantaneamente e il capitale parcheggiato nel Fondo Monetario fino alla prossima rotazione, senza pietà.

    #### 5. Backtest e Obiettivi
    I backtest eseguiti sulle decadi passate (incluse le crisi del 2008 e del 2020) dimostrano che questa combinazione di Momentum + Macro + ATR Trailing Stop è in grado di:
    - **Tagliare i Drawdown** dell'indice azionario di oltre il 50%.
    - **Aumentare il CAGR** (Tasso di crescita annuo composto) spingendo sull'acceleratore nei mercati Toro.
    - Ridurre il tempo a mercato (*Time in Market*) diminuendo il rischio sistemico senza sacrificare il rendimento.
    ''')
