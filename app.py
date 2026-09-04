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
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    /* Rimuove completamente la sidebar, i controlli e l'header nativo sovrapposto */
    [data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"],
    section[data-testid="stSidebar"],
    header[data-testid="stHeader"] {
        display: none !important;
    }

    /* Spazio pulito in cima alla schermata per la barra di navigazione */
    .block-container {
        padding-top: 1.5rem !important;
    }


    /* Stile per i pulsanti di navigazione in alto */
    div[data-testid="stPageLink"] a {
        background: rgba(255, 247, 237, 0.03) !important;
        border: 1px solid rgba(255, 247, 237, 0.09) !important;
        border-radius: 8px !important;
        padding: 8px 12px !important;
        font-weight: 600 !important;
        transition: all 0.15s ease-in-out !important;
        justify-content: center !important;
    }
    div[data-testid="stPageLink"] a:hover {
        background: rgba(201, 164, 76, 0.12) !important;
        border-color: rgba(201, 164, 76, 0.35) !important;
    }
</style>
""", unsafe_allow_html=True)

p_home = st.Page("home_app.py", title="Vista d'Insieme", url_path="home", icon=None, default=True)
p_apex = st.Page("page_apex.py", title="Apex Engine", url_path="apex", icon=None)
p_convex = st.Page("page_convex.py", title="Convex Stack", url_path="convex", icon=None)



# position="hidden" nasconde la barra interna nativa di Streamlit, evitando doppioni o problemi su mobile
pg = st.navigation([p_home, p_apex, p_convex], position="hidden")

# Unica barra di navigazione istituzionale in alto, sempre visibile su ogni dispositivo
col_nav1, col_nav2, col_nav3 = st.columns(3)
with col_nav1:
    st.page_link(p_home, label="Vista d'Insieme", use_container_width=True)
with col_nav2:
    st.page_link(p_apex, label="Apex Engine", use_container_width=True)
with col_nav3:
    st.page_link(p_convex, label="Convex Stack", use_container_width=True)

st.markdown("<div style='margin-bottom: 12px; border-bottom: 1px solid rgba(255,247,237,0.08);'></div>", unsafe_allow_html=True)

pg.run()




