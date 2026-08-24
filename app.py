import streamlit as st
import pandas as pd
import json
import os

# Configurazione base della pagina (a11y)
st.set_page_config(page_title="Apex Multi-Asset", page_icon="🦅", layout="wide")

st.title("🦅 Apex Multi-Asset Engine")
st.markdown("Dashboard quantitativa per il trend-following istituzionale.")

# Guida integrata e Lean (Nascosta di default per non sporcare la UI)
with st.expander("📖 Guida Rapida e Regole Operative", expanded=False):
    st.markdown("""
    ### Architettura del Portafoglio
    Questa App gestisce esclusivamente il **50% Attivo (Apex)** del tuo patrimonio. Il restante 50% (Convex Stack) va mantenuto passivamente a vita.
    
    ### Il tuo Calendario Operativo
    1. **Semafori Macro (Controllo 1 volta a settimana - Venerdì sera):** 
       Guarda i 4 riquadri della dashboard. Se l'indicatore è 🟢 Verde (Prezzo > MA200), mantieni l'asset. Se è 🔴 Rosso (Prezzo < MA200), l'asset è in caduta libera: vendilo e parcheggia il denaro nel porto sicuro in dollari (ETF **IB01**).
    2. **Classifica Top 20 (Rotazione 1 volta al mese):** 
       Se il Motore Azionario è Verde, una volta al mese vendi le azioni che sono uscite dalla classifica e compra le nuove prime classificate.
    3. **Stop Loss (Impostazione Istantanea sul Broker):** 
       * Appena compri un'azione (o Bitcoin), inserisci subito l'**Init Stop** su Interactive Brokers. 
       * Se il trend sale, aggiorna periodicamente lo stop sul broker usando il **Trail Stop (Chandelier)** indicato nell'App. Per Oro e Bond non serve lo stop loss.
    """)

@st.cache_data(ttl=60)
def load_data():
    if os.path.exists('apex_data.json'):
        with open('apex_data.json', 'r') as f:
            return json.load(f)
    return None

data = load_data()
if not data:
    st.error("🚨 Dati non disponibili. Il motore backend su GitHub non ha ancora completato l'aggiornamento notturno.")
    st.stop()

macro = data.get("macro", {})
rsp = macro.get("RSP", {})
gold = macro.get("GC=F", {})
ief = macro.get("IEF", {})
btc = macro.get("BTC-USD", {})

st.divider()

# ==========================================
# 1. MOTORE AZIONARIO (RSP + TOP 20)
# ==========================================
st.header("📈 1. Motore Azionario (S&P 500)")

col_rsp_1, col_rsp_2 = st.columns([1, 3])
rsp_price = rsp.get('price', 0)
rsp_ma200 = rsp.get('ma200', 0)
is_bull_eq = rsp_price > rsp_ma200

with col_rsp_1:
    st.metric(
        label="RSP (S&P 500 Equal Weight)", 
        value=f"${rsp_price:.2f}", 
        delta=f"MA200: ${rsp_ma200:.2f}", 
        delta_color="off",
        help="Interruttore generale del mercato azionario"
    )
    if is_bull_eq:
        st.success("🟢 **Trend: BULL MARKET**\n\n**Azione:** Investi nelle Top 20")
    else:
        st.error("🔴 **Trend: BEAR MARKET**\n\n**Azione:** Vendi le 20 azioni -> Vai in Cassa (IB01)")

with col_rsp_2:
    if is_bull_eq:
        top20 = data.get("top20", [])
        if top20:
            df = pd.DataFrame(top20)
            df.index += 1
            # Formattazione per la leggibilità (a11y)
            st.dataframe(
                df.style.format({
                    "Prezzo ($)": "{:.2f}",
                    "Momentum Score": "{:.2f}",
                    "Init Stop ($)": "{:.2f}",
                    "Trail Stop (Chandelier) ($)": "{:.2f}"
                }),
                use_container_width=True
            )
            st.caption("💡 *Tip Operativo:* L'**Init Stop** va usato solo il giorno in cui acquisti il titolo. Il **Trail Stop** va usato per aggiornare al rialzo l'ordine sul broker nelle settimane successive.")
    else:
        st.info("La classifica Top 20 è nascosta durante i Bear Market per prevenire acquisti accidentali.")

st.divider()

# ==========================================
# 2. MOTORI ALTERNATIVI (ORO, BOND, BTC)
# ==========================================
st.header("🛡️ 2. Motori Alternativi Indipendenti")
c1, c2, c3 = st.columns(3)

# ORO
with c1:
    g_p = gold.get('price', 0)
    g_ma = gold.get('ma200', 0)
    st.metric(label="Oro Fisico (GC=F)", value=f"${g_p:,.2f}", delta=f"MA200: ${g_ma:,.2f}", delta_color="off")
    if g_p > g_ma:
        st.success("🟢 **BULL MARKET**\n\n**Azione:** Compra o Mantieni l'Oro")
    else:
        st.error("🔴 **BEAR MARKET**\n\n**Azione:** Vendi Oro -> Vai in Cassa (IB01)")

# BOND
with c2:
    i_p = ief.get('price', 0)
    i_ma = ief.get('ma200', 0)
    st.metric(label="Obbligazioni USA (IEF)", value=f"${i_p:.2f}", delta=f"MA200: ${i_ma:.2f}", delta_color="off", help="Riferimento: Treasury USA 7-10 anni")
    if i_p > i_ma:
        st.success("🟢 **BULL MARKET**\n\n**Azione:** Compra o Mantieni IBTM")
    else:
        st.error("🔴 **BEAR MARKET**\n\n**Azione:** Vendi IBTM -> Vai in Cassa (IB01)")

# BTC
with c3:
    b_p = btc.get('price', 0)
    b_ma = btc.get('ma200', 0)
    st.metric(label="Bitcoin (BTC-USD)", value=f"${b_p:,.0f}", delta=f"MA200: ${b_ma:,.0f}", delta_color="off")
    if b_p > b_ma:
        hh = btc.get('highest_high_60', b_p)
        atr = btc.get('atr', 0)
        st_init = b_p - (2.0 * atr)
        st_trail = hh - (2.0 * atr)
        st.success(f"🟢 **BULL MARKET**\n\n**Azione:** Compra o Mantieni BTC\n\n🛡️ **Init Stop:** ${st_init:,.0f}\n🎯 **Trail Stop:** ${st_trail:,.0f}")
    else:
        st.error("🔴 **BEAR MARKET**\n\n**Azione:** Vendi BTC -> Vai in Cassa (IB01)")
