"""
main.py — Punto di ingresso della dashboard unificata Apex Convex
==================================================================================
Naviga tra tre pagine (st.navigation, Streamlit >=1.36): Vista d'Insieme,
Apex Engine, Convex Stack. `app.py` e `convex_stack_app.py` restano
invariati come app autonome (porte separate, già in uso) — le pagine qui
sono copie compatibili con la navigazione multipagina (Streamlit permette
un solo st.set_page_config() per intera app, quindi le pagine non possono
chiamarlo una seconda volta: `page_apex.py`/`page_convex.py` sono quelle
stesse app con solo quella chiamata rimossa, nessun'altra differenza).

Avvio: streamlit run main.py --server.port <porta libera>
==================================================================================
"""

import streamlit as st

st.set_page_config(
    page_title="Apex Convex",
    page_icon="🏛️",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    /* Rimuove completamente la sidebar e i controlli di apertura/chiusura */
    [data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"],
    section[data-testid="stSidebar"] {
        display: none !important;
    }
    
    /* Stile della barra di navigazione in alto */
    header[data-testid="stHeader"] {
        background: rgba(20, 18, 16, 0.92) !important;
        backdrop-filter: blur(12px) !important;
        border-bottom: 1px solid rgba(255, 247, 237, 0.09) !important;
    }
</style>
""", unsafe_allow_html=True)

pg = st.navigation([
    st.Page("home_app.py", title="Vista d'Insieme", icon="🏛️", default=True),
    st.Page("page_apex.py", title="Apex Engine", icon="⚡"),
    st.Page("page_convex.py", title="Convex Stack", icon="🛡️"),
], position="top")
pg.run()

