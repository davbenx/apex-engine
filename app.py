import streamlit as st
import pandas as pd
import json
import os

# Configurazione base della pagina (a11y)
st.set_page_config(page_title="Apex Multi-Asset", page_icon="🦅", layout="wide")

st.title("🦅 Apex Multi-Asset Engine")
st.markdown("Dashboard quantitativa per il trend-following istituzionale.")

# Guida integrata e Lean
with st.expander("📖 Guida Rapida e Regole Operative", expanded=False):
    st.markdown("""
    ### 🦅 Regole Operative (Il Ritmo della Strategia)

**📅 1 VOLTA AL MESE: La Rotazione**
L'ultimo venerdì del mese, guarda le classifiche dell'App. Se un'Azione o una Crypto che possiedi è uscita dalla tabella, vendila e usa i soldi per comprare il nuovo asset che ne ha preso il posto in classifica. *(Oro e Bond non ruotano: si tengono finché il Semaforo è verde).*

**📅 1 VOLTA A SETTIMANA: Aggiornamento Stop e Macro**
Durante il weekend controlla due cose:
1. **Semafori Macro:** Se S&P 500 o Bitcoin sono diventati 🔴 Rossi, il lunedì vendi immediatamente tutto il comparto (non aspettare fine mese) e passa al porto sicuro in liquidità (ETF **IB01** per le Azioni, USDT per le Crypto).
2. **Trailing Stop:** Verifica i nuovi valori di Stop sull'App. Entra nel tuo broker (Banca o Exchange) e "alza" il prezzo dell'ordine di Stop Loss automatico per proteggere i nuovi profitti.

**⚡ AUTOMATICO: Esecuzione dello Stop Loss**
Se un martedì a caso il mercato crolla, il broker venderà l'asset in automatico al prezzo del tuo Stop Loss. Tu non fare nulla: tieni i soldi al sicuro in Cassa/USDT fino al giorno della successiva Rotazione Mensile.
       

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
# 0. CALCOLATORE ALLOCAZIONE E PESI
# ==========================================
st.header("💰 Calcolatore Allocazione")
capitale = st.number_input("Inserisci il tuo Capitale Totale ($ o €)", min_value=1000, value=100000, step=1000, format="%d")

# Calcoli delle proporzioni (100% Attivo)
eq_cap = capitale * 0.70
gold_cap = capitale * 0.10
bond_cap = capitale * 0.10
btc_cap = capitale * 0.10
single_crypto_cap = btc_cap / 3
single_stock_cap = eq_cap / 20

st.success(f"""
### Allocazione del Portafoglio
**Totale:** **{capitale:,.2f}**

* 📈 **Motore Azionario Top 20 (70%):** {eq_cap:,.2f} (Esattamente **{single_stock_cap:,.2f}** per ogni singola azione)
* 🥇 **Motore Oro (10%):** {gold_cap:,.2f}
* 🛡️ **Motore Obbligazioni (10%):** {bond_cap:,.2f}
* ₿ **Motore Criptovalute Top 3 (10%):** {btc_cap:,.2f} (Esattamente **{single_crypto_cap:,.2f}** per le prime 3 in classifica)

*(Se un motore qui sotto è 🔴 ROSSO, la sua quota va parcheggiata in ETF liquidità IB01/XEON)*
""")

st.divider()

# ==========================================
# 1. MOTORE AZIONARIO (RSP + TOP 20)
# ==========================================
st.header("📈 1. Motore Azionario")

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
        st.success(f"""🟢 **Trend: BULL MARKET**
        
**Azione:** Compra le Top 20 
*(Quota da usare: {eq_cap:,.2f})*""")
    else:
        st.error(f"""🔴 **Trend: BEAR MARKET**
        
**Azione:** Vendi le 20 azioni -> Vai in Cassa (IB01) 
*(Cassa obiettivo: {eq_cap:,.2f})*""")

with col_rsp_2:
    if is_bull_eq:
        top20 = data.get("top20", [])
        if top20:
            df = pd.DataFrame(top20)
            df.index += 1
            if "Momentum Score" in df.columns:
                df = df.drop(columns=["Momentum Score"])
            if "Trail Stop (Chandelier) ($)" in df.columns:
                df = df.rename(columns={"Trail Stop (Chandelier) ($)": "Trail Stop ($)"})
            st.dataframe(
                df.style.format({
                    "Prezzo ($)": "{:.2f}",
                    "Init Stop ($)": "{:.2f}",
                    "Trail Stop ($)": "{:.2f}"
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
st.header("🛡️ 2. Motori Alternativi")
c1, c2 = st.columns(2)

# ORO
with c1:
    g_p = gold.get('price', 0)
    g_ma = gold.get('ma200', 0)
    st.metric(label="Oro Fisico (GC=F)", value=f"${g_p:,.2f}", delta=f"MA200: ${g_ma:,.2f}", delta_color="off")
    if g_p > g_ma:
        st.success(f"""🟢 **BULL MARKET**
        
**Azione:** Compra/Mantieni
*(Quota: {gold_cap:,.2f})*""")
    else:
        st.error(f"""🔴 **BEAR MARKET**
        
**Azione:** Vendi Oro -> Vai in Cassa
*(Cassa obiettivo: {gold_cap:,.2f})*""")

# BOND
with c2:
    i_p = ief.get('price', 0)
    i_ma = ief.get('ma200', 0)
    st.metric(label="Obbligazioni USA (IEF)", value=f"${i_p:.2f}", delta=f"MA200: ${i_ma:.2f}", delta_color="off", help="Riferimento: Treasury USA 7-10 anni")
    if i_p > i_ma:
        st.success(f"""🟢 **BULL MARKET**
        
**Azione:** Compra/Mantieni
*(Quota: {bond_cap:,.2f})*""")
    else:
        st.error(f"""🔴 **BEAR MARKET**
        
**Azione:** Vendi IBTM -> Vai in Cassa
*(Cassa obiettivo: {bond_cap:,.2f})*""")


st.divider()

# ==========================================
# 3. MOTORE ALTCOIN (TOP 10 CRIPTO)
# ==========================================
st.header("🪙 3. Motore Criptovalute")
st.markdown("L'universo si auto-aggiorna prelevando le prime 50 crypto mondiali (escluse stablecoin). Algoritmo: **ROC a 90 Giorni** e filtro saltuario tollerante fino al **40%**. Il Semaforo Macro è dettato dal **Bitcoin (BTC-USD)**.")

col_btc_1, col_btc_2 = st.columns([1, 3])
is_bull_btc = btc.get('price', 0) > btc.get('ma200', 0)

with col_btc_1:
    st.metric(
        label="Semaforo Macro (Bitcoin)", 
        value=f"${btc.get('price', 0):,.2f}", 
        delta=f"MA200: ${btc.get('ma200', 0):,.2f}", 
        delta_color="off"
    )
    if is_bull_btc:
        st.success(f"""🟢 **Trend: BULL MARKET**
        
**Azione:** Compra le Top 3 (Quota: {btc_cap:,.2f} -> {single_crypto_cap:,.2f} a moneta)""")
    else:
        st.error(f"""🔴 **Trend: BEAR MARKET**
        
**Azione:** Vendi tutto -> Vai in USDT / Cassa / Dollari""")

with col_btc_2:
    if is_bull_btc:
        cryptotop = data.get("crypto_top", [])
        if cryptotop:
            df_c = pd.DataFrame(cryptotop).head(3)
            df_c.index += 1
            if "Momentum Score" in df_c.columns:
                df_c = df_c.drop(columns=["Momentum Score"])
            st.dataframe(
                df_c.style.format({
                    "Prezzo ($)": "{:.4f}",
                    "Init Stop ($)": "{:.4f}",
                    "Trail Stop ($)": "{:.4f}"
                }),
                use_container_width=True
            )
            st.caption("💡 I prezzi delle Altcoin sono mostrati con 4 decimali. Inserire sempre l'Init Stop all'acquisto.")
    else:
        st.info("La classifica Cripto è disattivata. Quando il Bitcoin scende sotto la Media 200, le altcoin crollano matematicamente. Tieni la liquidità al sicuro.")
