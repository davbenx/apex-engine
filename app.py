import streamlit as st
import pandas as pd
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
st.caption(f"🕒 **Ultimo Ricalcolo:** {last_update}")
st.caption("⏳ **Prossimo Aggiornamento Previsto:** Stanotte, 23:30 UTC")

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
    m1.metric(label="Valore Attuale (Base $100k)", value=f"${end_val:,.0f}", delta=f"{perf_pct:.2f}% dal lancio")
    m2.metric(label="Drawdown Attuale", value=f"{current_dd:.2f}%", delta="Distanza dal picco massimo", delta_color="inverse")
    m3.metric(label="Max Drawdown", value=f"{max_dd:.2f}%", delta="Peggior caduta dal lancio", delta_color="off")
    
    st.line_chart(df_eq['value'], use_container_width=True, color="#00ff00")
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
single_cr = btc_cap / 3 if alloc["Crypto"] > 0 else 0

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
                btc_stop = c["Stop Loss ($)"]
                break
        
        if btc_stop:
            st.success(f"**🟢 ATTIVO**\n\nBudget: **{btc_cap:,.0f}**\n\n*(Stop BTC: ${btc_stop:,.0f})*")
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
    st.caption(f"Size per singola posizione: **{single_eq:,.0f}**")
    if is_bull_eq:
        top20 = data.get("top20", [])
        if top20:
            df_eq = pd.DataFrame(top20)
            if "Momentum Score" in df_eq.columns: df_eq = df_eq.drop(columns=["Momentum Score"])
            st.dataframe(df_eq.style.format({"Prezzo ($)": "{:.2f}", "Stop Loss ($)": "{:.2f}"}), use_container_width=True, hide_index=True)
    else:
        st.info("Semaforo Rosso. Tabella disattivata per prevenire acquisti.")

with col_cr:
    st.subheader("🪙 Top 3 Crypto")
    st.caption(f"Size per singola posizione: **{single_cr:,.0f}**")
    if is_bull_cr:
        cr_top = data.get("crypto_top", [])
        if cr_top:
            df_c = pd.DataFrame(cr_top)
            if "Momentum Score" in df_c.columns: df_c = df_c.drop(columns=["Momentum Score"])
            st.dataframe(df_c.style.format({"Prezzo ($)": format_price, "Stop Loss ($)": format_price}), use_container_width=True, hide_index=True)
    else:
        st.info("Semaforo Rosso. Tabella disattivata.")
