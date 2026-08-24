import streamlit as st
import pandas as pd
import json
import os

st.set_page_config(page_title="Apex Multi-Asset", page_icon="🦅", layout="wide")

st.title("🦅 Apex Multi-Asset Engine")

@st.cache_data(ttl=60)
def load_data():
    if os.path.exists('apex_data.json'):
        with open('apex_data.json', 'r') as f:
            return json.load(f)
    return None

data = load_data()
if not data:
    st.error("🚨 Dati non disponibili. Attendi l'aggiornamento notturno su GitHub.")
    st.stop()

# --- TIMESTAMPS ---
last_update = data.get("timestamp", "In attesa del ricalcolo notturno (Esegui il Workflow su GitHub)")
st.caption(f"🕒 **Ultimo Ricalcolo:** {last_update}")
st.caption("⏳ **Prossimo Aggiornamento Previsto:** Stanotte alle 23:30")

with st.expander("📖 Regole Operative", expanded=False):
    st.markdown("""
    **📅 1 VOLTA AL MESE (Rotazione):** L'ultimo venerdì del mese, vendi gli asset usciti dalle tabelle sottostanti e compra i nuovi entrati. (Oro e Bond non ruotano, si tengono finché verdi).
    
    **📅 1 VOLTA A SETTIMANA (Macro & Stop):** Nel weekend, controlla se un semaforo nel Cockpit è diventato 🔴 ROSSO. In tal caso, il lunedì vendi tutto quel comparto e vai in Cassa. Se è verde, aggiorna sul broker i nuovi livelli di **Stop Loss ($)** indicati nelle tabelle.
    
    **⚡ AUTOMATICO (Esecuzione):** Se in un giorno qualsiasi il prezzo crolla sotto lo Stop Loss, il broker venderà in automatico. Tieni i soldi in cassa fino alla successiva rotazione mensile.
    """)

st.divider()

# --- COCKPIT ALLOCAZIONE ---
st.header("🎛️ Cockpit Allocazione")
capitale = st.number_input("Capitale Totale Operativo", min_value=1000, value=100000, step=1000, format="%d", help="Inserisci il capitale totale. L'algoritmo calcolerà i pesi esatti per ogni comparto.")

eq_cap = capitale * 0.70
btc_cap = capitale * 0.10
gold_cap = capitale * 0.10
bond_cap = capitale * 0.10

single_stock_cap = eq_cap / 20
single_crypto_cap = btc_cap / 3

macro = data.get("macro", {})
is_bull_eq = macro.get("RSP", {}).get("price", 0) > macro.get("RSP", {}).get("ma200", 0)
is_bull_cr = macro.get("BTC-USD", {}).get("price", 0) > macro.get("BTC-USD", {}).get("ma200", 0)
is_bull_g = macro.get("GC=F", {}).get("price", 0) > macro.get("GC=F", {}).get("ma200", 0)
is_bull_b = macro.get("IEF", {}).get("price", 0) > macro.get("IEF", {}).get("ma200", 0)

# 4 Colonne visive per lo stato istantaneo
c1, c2, c3, c4 = st.columns(4)

with c1:
    st.markdown("### 📈 Azioni (70%)")
    if is_bull_eq: st.success(f"**🟢 INVESTITO**\n\nQuota: {eq_cap:,.0f}")
    else: st.error(f"**🔴 CASSA (IB01)**\n\nQuota: {eq_cap:,.0f}")

with c2:
    st.markdown("### 🪙 Crypto (10%)")
    if is_bull_cr:
        btc_hh = macro.get("BTC-USD", {}).get("highest_high_60", 0)
        btc_a = macro.get("BTC-USD", {}).get("atr", 0)
        btc_stop = btc_hh - (2.0 * btc_a)
        st.success(f"**🟢 INVESTITO**

Quota: {btc_cap:,.0f}

*(Stop BTC: ${btc_stop:,.0f})*")
    else:
        st.error(f"**🔴 CASSA (USDT)**

Quota: {btc_cap:,.0f}")

with c3:
    st.markdown("### 🥇 Oro (10%)")
    if is_bull_g: st.success(f"**🟢 MANTIENI**\n\nQuota: {gold_cap:,.0f}")
    else: st.error(f"**🔴 CASSA (IB01)**\n\nQuota: {gold_cap:,.0f}")

with c4:
    st.markdown("### 🛡️ Bond (10%)")
    if is_bull_b: st.success(f"**🟢 MANTIENI**\n\nQuota: {bond_cap:,.0f}")
    else: st.error(f"**🔴 CASSA (IB01)**\n\nQuota: {bond_cap:,.0f}")

st.divider()

# --- TABELLE OPERATIVE (Solo Motori Attivi e Rotazionali) ---
st.header("📋 Liste Operative")
st.caption("Usa queste tabelle solo durante la Rotazione Mensile per sapere cosa comprare, e ogni weekend per aggiornare lo Stop Loss sul broker.")

col_az, col_cr = st.columns([2, 1])

with col_az:
    st.subheader(f"📈 Top 20 Azioni ({single_stock_cap:,.0f} cad.)")
    if is_bull_eq:
        top20 = data.get("top20", [])
        if top20:
            df_eq = pd.DataFrame(top20)
            df_eq.index += 1
            if "Momentum Score" in df_eq.columns: df_eq = df_eq.drop(columns=["Momentum Score"])
            st.dataframe(df_eq.style.format({"Prezzo ($)": "{:.2f}", "Stop Loss ($)": "{:.2f}"}), use_container_width=True)
    else:
        st.info("Semaforo Azionario Rosso. Tabella disattivata, mantieni il capitale in IB01.")

with col_cr:
    st.subheader(f"🪙 Top 3 Crypto ({single_crypto_cap:,.0f} cad.)")
    if is_bull_cr:
        cryptotop = data.get("crypto_top", [])
        if cryptotop:
            df_c = pd.DataFrame(cryptotop)
            df_c.index += 1
            if "Momentum Score" in df_c.columns: df_c = df_c.drop(columns=["Momentum Score"])
            st.dataframe(df_c.style.format({"Prezzo ($)": "{:.4f}", "Stop Loss ($)": "{:.4f}"}), use_container_width=True)
    else:
        st.info("Semaforo Crypto Rosso. Tabella disattivata, mantieni il capitale in USDT.")
