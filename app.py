import streamlit as st
import pandas as pd
import json
import os

st.set_page_config(page_title="Apex Multi-Asset (Cloud)", layout="wide")
st.title("🦅 Apex Multi-Asset Engine (Cloud Version)")

@st.cache_data(ttl=60)
def load_data():
    if os.path.exists('apex_data.json'):
        with open('apex_data.json', 'r') as f:
            return json.load(f)
    return None

data = load_data()

if not data:
    st.error("🚨 Dati non ancora calcolati. Il backend sta girando su GitHub.")
    st.stop()

st.markdown("Questa versione si carica all'istante leggendo i dati elaborati di notte. Calcoli allineati allo standard istituzionale (Wilder's ATR, Chandelier Exit, RSP).")

macro = data.get("macro", {})
rsp = macro.get("RSP", {})

st.markdown("---")
st.header("📈 1. Motore Azionario (Top 20 Leader)")
# Controllo macro su RSP (S&P 500 Equal Weight)
if rsp.get("price", 0) > rsp.get("ma200", 0):
    st.success(f"🟢 **Azionario: BULL MARKET** (RSP Equal Weight = {rsp.get('price', 0):.2f} > MA200 = {rsp.get('ma200', 0):.2f}).")
    top20 = data.get("top20", [])
    if top20:
        df = pd.DataFrame(top20)
        df.index += 1
        st.dataframe(df)
else:
    st.error(f"🔴 **Azionario: BEAR MARKET** (RSP Equal Weight = {rsp.get('price', 0):.2f} < MA200 = {rsp.get('ma200', 0):.2f}). CASSA.")

st.markdown("---")
st.header("🛡️ 2. Motori Alternativi Indipendenti")
col1, col2, col3 = st.columns(3)

gold = macro.get("GC=F", {})
ief = macro.get("IEF", {})
btc = macro.get("BTC-USD", {})

with col1:
    st.subheader("Oro Fisico")
    if gold.get("price", 0) > gold.get("ma200", 0):
        st.success(f"🟢 **BULL MARKET**\nOro ($) = {gold.get('price', 0):.2f}\nMA200 = {gold.get('ma200', 0):.2f}")
    else:
        st.error(f"🔴 **BEAR MARKET**\nOro ($) = {gold.get('price', 0):.2f}\nMA200 = {gold.get('ma200', 0):.2f}")

with col2:
    st.subheader("Obbligazioni USA")
    if ief.get("price", 0) > ief.get("ma200", 0):
        st.success(f"🟢 **BULL MARKET**\nIEF = {ief.get('price', 0):.2f}\nMA200 = {ief.get('ma200', 0):.2f}")
    else:
        st.error(f"🔴 **BEAR MARKET**\nIEF = {ief.get('price', 0):.2f}\nMA200 = {ief.get('ma200', 0):.2f}")

with col3:
    st.subheader("Bitcoin")
    if btc.get("price", 0) > btc.get("ma200", 0):
        hh = btc.get('highest_high_60', btc.get('price', 0))
        stop_btc_init = btc.get('price', 0) - (2.0 * btc.get('atr', 0))
        stop_btc_trail = hh - (2.0 * btc.get('atr', 0))
        st.success(f"🟢 **BULL MARKET**\nBTC = ${btc.get('price', 0):,.0f}\nMA200 = ${btc.get('ma200', 0):,.0f}\nInit Stop: **${stop_btc_init:,.0f}**\nTrail Stop: **${stop_btc_trail:,.0f}**")
    else:
        st.error(f"🔴 **BEAR MARKET**\nBTC = ${btc.get('price', 0):,.0f}\nMA200 = ${btc.get('ma200', 0):,.0f}")
