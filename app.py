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
    st.success(f"🟢 **Azionario: BULL MARKET** (RSP Equal Weight = {rsp['price']:.2f} > MA200 = {rsp['ma200']:.2f}).")
    top20 = data.get("top20", [])
    if top20:
        df = pd.DataFrame(top20)
        df.index += 1
        st.dataframe(df)
else:
    st.error(f"🔴 **Azionario: BEAR MARKET** (RSP Equal Weight = {rsp['price']:.2f} < MA200 = {rsp['ma200']:.2f}). CASSA.")

st.markdown("---")
st.header("🛡️ 2. Motori Alternativi Indipendenti")
col1, col2, col3 = st.columns(3)

gld = macro.get("GLD", {})
ief = macro.get("IEF", {})
btc = macro.get("BTC-USD", {})

with col1:
    st.subheader("Oro Fisico")
    if gld.get("price", 0) > gld.get("ma200", 0):
        st.success(f"🟢 **BULL MARKET**\nGLD = {gld['price']:.2f}\nMA200 = {gld['ma200']:.2f}")
    else:
        st.error(f"🔴 **BEAR MARKET**\nGLD = {gld['price']:.2f}\nMA200 = {gld['ma200']:.2f}")

with col2:
    st.subheader("Obbligazioni USA")
    if ief.get("price", 0) > ief.get("ma200", 0):
        st.success(f"🟢 **BULL MARKET**\nIEF = {ief['price']:.2f}\nMA200 = {ief['ma200']:.2f}")
    else:
        st.error(f"🔴 **BEAR MARKET**\nIEF = {ief['price']:.2f}\nMA200 = {ief['ma200']:.2f}")

with col3:
    st.subheader("Bitcoin")
    if btc.get("price", 0) > btc.get("ma200", 0):
        stop_btc = btc['price'] - (2.0 * btc['atr'])
        st.success(f"🟢 **BULL MARKET**\nBTC = ${btc['price']:,.0f}\nMA200 = ${btc['ma200']:,.0f}\nStop: **${stop_btc:,.0f}**")
    else:
        st.error(f"🔴 **BEAR MARKET**\nBTC = ${btc['price']:,.0f}\nMA200 = ${btc['ma200']:,.0f}")
