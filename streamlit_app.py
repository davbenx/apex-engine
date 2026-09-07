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
import sys
import streamlit as st

_root = os.path.dirname(os.path.abspath(__file__))
if _root not in sys.path:
    sys.path.insert(0, _root)


st.set_page_config(
    page_title="Apex Convex",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=JetBrains+Mono:wght@400;500;600;700;800&family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200&display=swap');

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

    /* Forza i 3 pulsanti di navigazione a rimanere sempre affiancati su 1 riga (desktop E mobile) senza uscire dallo schermo */
    [data-testid="stHorizontalBlock"]:has(div[data-testid="stPageLink"]) {
        display: flex !important;
        flex-direction: row !important;
        flex-wrap: nowrap !important;
        align-items: stretch !important;
        gap: 6px !important;
        width: 100% !important;
        max-width: 100% !important;
        margin-bottom: 6px !important;
        box-sizing: border-box !important;
    }

    [data-testid="stHorizontalBlock"]:has(div[data-testid="stPageLink"]) > div[data-testid="stColumn"],
    div[data-testid="stColumn"]:has(div[data-testid="stPageLink"]) {
        display: flex !important;
        flex: 1 1 0% !important;
        width: 33.333% !important;
        min-width: 0 !important;
        max-width: 33.333% !important;
        box-sizing: border-box !important;
    }

    [data-testid="stHorizontalBlock"]:has(div[data-testid="stPageLink"]) div[data-testid="stPageLink"],
    div[data-testid="stColumn"]:has(div[data-testid="stPageLink"]) div[data-testid="stPageLink"] {
        width: 100% !important;
        min-width: 0 !important;
        box-sizing: border-box !important;
    }

    /* Stile per i pulsanti di navigazione in alto */
    div[data-testid="stPageLink"] a[data-testid="stPageLink-NavLink"],
    div[data-testid="stPageLink"] a {
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 6px !important;
        background: rgba(255, 247, 237, 0.035) !important;
        border: 1px solid rgba(255, 247, 237, 0.09) !important;
        border-radius: 8px !important;
        padding: 8px 10px !important;
        font-weight: 600 !important;
        font-size: 13px !important;
        color: #FAF8F5 !important;
        transition: all 0.15s ease-in-out !important;
        text-decoration: none !important;
        white-space: nowrap !important;
        width: 100% !important;
        box-sizing: border-box !important;
        min-width: 0 !important;
        overflow: hidden !important;
    }

    div[data-testid="stPageLink"] a[data-testid="stPageLink-NavLink"]:hover,
    div[data-testid="stPageLink"] a:hover {
        background: rgba(201, 164, 76, 0.14) !important;
        border-color: rgba(201, 164, 76, 0.4) !important;
        color: #E6C575 !important;
    }

    div[data-testid="stPageLink"] a[aria-current="page"],
    div[data-testid="stPageLink"] a[data-highlight="true"] {
        background: rgba(201, 164, 76, 0.18) !important;
        border-color: rgba(201, 164, 76, 0.5) !important;
        color: #FAF8F5 !important;
    }

    /* Testo dell etichetta (label) con overflow controllato */
    div[data-testid="stPageLink"] a span:last-child {
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        white-space: nowrap !important;
        min-width: 0 !important;
    }

    /* Rendering delle icone SVG vettoriali per i pulsanti di navigazione */
    div[data-testid="stPageLink"] span[data-testid="stIconMaterial"] {
        display: inline-block !important;
        width: 16px !important;
        height: 16px !important;
        min-width: 16px !important;
        min-height: 16px !important;
        max-width: 16px !important;
        max-height: 16px !important;
        font-size: 0 !important;
        line-height: 0 !important;
        color: transparent !important;
        background-color: #FAF8F5 !important;
        -webkit-mask-size: contain !important;
        mask-size: contain !important;
        -webkit-mask-repeat: no-repeat !important;
        mask-repeat: no-repeat !important;
        -webkit-mask-position: center !important;
        mask-position: center !important;
        flex-shrink: 0 !important;
    }

    div[data-testid="stPageLink"] a:hover span[data-testid="stIconMaterial"] {
        background-color: #E6C575 !important;
    }

    div[data-testid="stPageLink"] a[aria-current="page"] span[data-testid="stIconMaterial"] {
        background-color: #C9A44C !important;
    }

    /* Fallback ::before se lo span stIconMaterial non e presente */
    div[data-testid="stPageLink"] a:not(:has(span[data-testid="stIconMaterial"]))::before {
        content: "" !important;
        display: inline-block !important;
        width: 16px !important;
        height: 16px !important;
        min-width: 16px !important;
        min-height: 16px !important;
        flex-shrink: 0 !important;
        background-color: #FAF8F5 !important;
        -webkit-mask-size: contain !important;
        mask-size: contain !important;
        -webkit-mask-repeat: no-repeat !important;
        mask-repeat: no-repeat !important;
        -webkit-mask-position: center !important;
        mask-position: center !important;
    }

    div[data-testid="stPageLink"] a:hover:not(:has(span[data-testid="stIconMaterial"]))::before {
        background-color: #E6C575 !important;
    }

    /* 1. Icona Home (Panoramica / Dashboard) */
    div[data-testid="stColumn"]:nth-of-type(1) div[data-testid="stPageLink"] a span[data-testid="stIconMaterial"],
    div[data-testid="stColumn"]:nth-of-type(1) div[data-testid="stPageLink"] a:not(:has(span[data-testid="stIconMaterial"]))::before {
        -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'/%3E%3Cpolyline points='9 22 9 12 15 12 15 22'/%3E%3C/svg%3E") !important;
        mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z'/%3E%3Cpolyline points='9 22 9 12 15 12 15 22'/%3E%3C/svg%3E") !important;
    }

    /* 2. Apex - Icona SVG (Trending Up / Trend Following) */
    div[data-testid="stColumn"]:nth-of-type(2) div[data-testid="stPageLink"] a span[data-testid="stIconMaterial"],
    div[data-testid="stColumn"]:nth-of-type(2) div[data-testid="stPageLink"] a:not(:has(span[data-testid="stIconMaterial"]))::before {
        -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='23 6 13.5 15.5 8.5 10.5 1 18'/%3E%3Cpolyline points='17 6 23 6 23 12'/%3E%3C/svg%3E") !important;
        mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='23 6 13.5 15.5 8.5 10.5 1 18'/%3E%3Cpolyline points='17 6 23 6 23 12'/%3E%3C/svg%3E") !important;
    }

    /* 3. Convex - Icona SVG (Shield / Protezione Asimmetrica) */
    div[data-testid="stColumn"]:nth-of-type(3) div[data-testid="stPageLink"] a span[data-testid="stIconMaterial"],
    div[data-testid="stColumn"]:nth-of-type(3) div[data-testid="stPageLink"] a:not(:has(span[data-testid="stIconMaterial"]))::before {
        -webkit-mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'/%3E%3C/svg%3E") !important;
        mask-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpath d='M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z'/%3E%3C/svg%3E") !important;
    }

    /* Responsive Mobile: garantisce affiancamento costante su mobile e proporzioni ottimizzate senza fuoriuscita */
    @media (max-width: 640px) {
        .block-container {
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
            padding-top: 0.8rem !important;
        }
        [data-testid="stHorizontalBlock"]:has(div[data-testid="stPageLink"]) {
            gap: 4px !important;
            width: 100% !important;
            max-width: 100% !important;
            margin-bottom: 4px !important;
        }
        [data-testid="stHorizontalBlock"]:has(div[data-testid="stPageLink"]) > div[data-testid="stColumn"],
        div[data-testid="stColumn"]:has(div[data-testid="stPageLink"]) {
            width: 33.333% !important;
            min-width: 0 !important;
            max-width: 33.333% !important;
            flex: 1 1 0% !important;
        }
        div[data-testid="stPageLink"] a[data-testid="stPageLink-NavLink"],
        div[data-testid="stPageLink"] a {
            padding: 6px 3px !important;
            font-size: 11px !important;
            gap: 3px !important;
            border-radius: 6px !important;
        }
        div[data-testid="stPageLink"] span[data-testid="stIconMaterial"],
        div[data-testid="stPageLink"] a:not(:has(span[data-testid="stIconMaterial"]))::before {
            width: 13px !important;
            height: 13px !important;
            min-width: 13px !important;
            min-height: 13px !important;
        }
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

p_home = st.Page("home_app.py", title="Visione d'Insieme", url_path="home", icon=":material/home:", default=True)
p_apex = st.Page("page_apex.py", title="Apex Engine", url_path="apex", icon=":material/trending_up:")
p_convex = st.Page("page_convex.py", title="Convex Stack", url_path="convex", icon=":material/shield:")

# position="hidden" nasconde la barra interna nativa di Streamlit, evitando doppioni o problemi su mobile
pg = st.navigation([p_home, p_apex, p_convex], position="hidden")

# Tre bottoni di navigazione "Home", "Apex", "Convex" sotto al titolo, sempre affiancati sulla stessa linea
col_nav1, col_nav2, col_nav3 = st.columns(3, gap="small", wrap=False)
with col_nav1:
    st.page_link(p_home, label="Home", icon=":material/home:", width="stretch")
with col_nav2:
    st.page_link(p_apex, label="Apex", icon=":material/trending_up:", width="stretch")
with col_nav3:
    st.page_link(p_convex, label="Convex", icon=":material/shield:", width="stretch")

st.markdown("<div style='margin-bottom: 12px; border-bottom: 1px solid rgba(255,247,237,0.08);'></div>", unsafe_allow_html=True)

pg.run()
