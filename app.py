"""
Punto di ingresso della dashboard unificata Apex Convex.
==================================================================================
Naviga tra tre pagine (st.navigation, Streamlit >=1.36): Visione d'Insieme,
Apex Engine, Convex Stack. `page_apex.py`/`page_convex.py`/`home_app.py` sono i
contenuti reali; questo file e' solo il router st.navigation + set_page_config.

Questo stesso file esiste come 4 copie identiche — `main.py`, `app.py`,
`convex_stack_app.py`, `streamlit_app.py` — perche' Streamlit Cloud individua
l'entrypoint in base al nome file a seconda di come l'app e' configurata nel
progetto; avere lo stesso router sotto piu' nomi evita di legare il deploy a
una convenzione di naming specifica. Sono tenute sincronizzate manualmente:
se modifichi una delle quattro, replica la stessa modifica identica nelle
altre tre.

Avvio locale: streamlit run main.py --server.port <porta libera>
==================================================================================
"""

import base64
import os
import streamlit as st

st.set_page_config(
    page_title="Apex Convex",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=JetBrains+Mono:wght@400;500;600;700;800&display=swap');

    /* Rimuove completamente la sidebar, i controlli e l'header nativo sovrapposto */
    [data-testid="stSidebar"],
    [data-testid="stSidebarCollapsedControl"],
    section[data-testid="stSidebar"],
    header[data-testid="stHeader"] {
        display: none !important;
    }

    /* Spazio pulito in cima alla schermata per la barra di navigazione */
    .block-container {
        padding-top: 1.2rem !important;
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


def _get_logo_b64():
    base_dir = os.path.dirname(__file__)
    for p in ["logo_icon.png", "logo.png"]:
        full_p = os.path.join(base_dir, p)
        if os.path.exists(full_p):
            try:
                with open(full_p, "rb") as f:
                    return base64.b64encode(f.read()).decode()
            except Exception:
                pass
    return ""


_logo_b64 = _get_logo_b64()
_logo_tag = (f'<img src="data:image/png;base64,{_logo_b64}" style="height: 38px; width: auto; object-fit: contain;" />'
             if _logo_b64 else '')

# Titolo principale in alto
st.markdown(f"""
<div style="display: flex; align-items: center; gap: 14px; padding: 2px 0 12px 0;">
    <div style="background: rgba(255, 247, 237, 0.045); border: 1px solid rgba(255, 247, 237, 0.09); padding: 5px 9px; border-radius: 10px; display: flex; align-items: center; justify-content: center;">
        {_logo_tag}
    </div>
    <div>
        <div style="font-family: 'Fraunces', Georgia, serif; font-size: 22px; font-weight: 600; letter-spacing: -0.4px; line-height: 1.2; color: #FAF8F5;">Apex Convex</div>
        <div style="font-size: 11px; font-weight: 600; opacity: 0.65; letter-spacing: 0.4px; text-transform: uppercase; margin-top: 1px; color: #C9A44C;">
            Visione d'Insieme & Gestione Portafoglio
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

p_home = st.Page("home_app.py", title="Visione d'Insieme", url_path="home", icon=None, default=True)
p_apex = st.Page("page_apex.py", title="Apex Engine", url_path="apex", icon=None)
p_convex = st.Page("page_convex.py", title="Convex Stack", url_path="convex", icon=None)

# position="hidden" nasconde la barra interna nativa di Streamlit, evitando doppioni o problemi su mobile
pg = st.navigation([p_home, p_apex, p_convex], position="hidden")

# Tre bottoni di navigazione "Home", "Apex", "Convex" sotto al titolo, sulla stessa linea
col_nav1, col_nav2, col_nav3 = st.columns(3)
with col_nav1:
    st.page_link(p_home, label="Home", use_container_width=True)
with col_nav2:
    st.page_link(p_apex, label="Apex", use_container_width=True)
with col_nav3:
    st.page_link(p_convex, label="Convex", use_container_width=True)

st.markdown("<div style='margin-bottom: 12px; border-bottom: 1px solid rgba(255,247,237,0.08);'></div>", unsafe_allow_html=True)

pg.run()
