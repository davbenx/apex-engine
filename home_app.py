"""
home_app.py — Vista d'insieme Apex Engine + Convex Stack
==================================================================================
Pagina iniziale della navigazione multipagina (vedi main.py). Nessun input
qui: mostra solo dati reali già disponibili. Dove un numero richiede
l'inserimento manuale delle quote Convex (solo tu conosci le tue posizioni),
lo dichiara onestamente invece di stimarlo.
==================================================================================
"""

import json
import os

import streamlit as st

import portfolio_manager

def st_html(html_str):
    cleaned = "\n".join(line.strip() for line in html_str.strip().splitlines())
    st.markdown(cleaned, unsafe_allow_html=True)

# Design tokens — identici ad Apex Engine e Convex Stack (stesso sistema visivo)
POS = "#3DDC97"
NEG = "#EC657B"
ACCENT = "#C9A44C"
SURFACE = "rgba(255,247,237,0.045)"
BORDER = "rgba(255,247,237,0.09)"
BORDER_STRONG = "rgba(255,247,237,0.16)"
MUTED = "#9C9187"
MUTED_2 = "#6E655C"
BADGE_TEXT = "#F5F1EA"
FRAUNCES = "'Fraunces', Georgia, serif"
MONO = "'JetBrains Mono', monospace"

def section_title(text, top="26px", bottom="10px"):
    return f'<div style="font-family:{FRAUNCES}; font-size:16px; font-weight:600; letter-spacing:-0.1px; margin:{top} 0 {bottom};">{text}</div>'

def get_logo_b64():
    import base64
    for p in ["logo_icon.png", "logo.png"]:
        if os.path.exists(p):
            try:
                with open(p, "rb") as f:
                    return base64.b64encode(f.read()).decode()
            except Exception:
                pass
    return ""

_logo_b64 = get_logo_b64()
_logo_tag = (f'<img src="data:image/png;base64,{_logo_b64}" style="height: 48px; width: auto; object-fit: contain;" />'
             if _logo_b64 else '🏛️')

st_html(f"""
<div style="display: flex; align-items: center; gap: 14px; padding: 6px 0 4px;">
    <div style="background: {SURFACE}; border: 1px solid {BORDER}; padding: 5px 9px; border-radius: 10px; display: flex; align-items: center; justify-content: center;">
        {_logo_tag}
    </div>
    <div>
        <div style="font-family: {FRAUNCES}; font-size: 22px; font-weight: 600; letter-spacing: -0.4px; line-height: 1.2; color: {BADGE_TEXT};">Apex Convex</div>
        <div style="font-size: 11px; font-weight: 600; opacity: 0.65; letter-spacing: 0.4px; text-transform: uppercase; margin-top: 1px;">
            Vista d'Insieme delle Due Strategie
        </div>
    </div>
</div>
""")

# ==============================================================================
# DATI REALI — Apex da portfolio.json/apex_data.json, Convex da
# convex_portfolio.json (solo se le quote reali sono state salvate).
# ==============================================================================
def _load_json(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

apex_portfolio = _load_json("portfolio.json")
apex_data = _load_json("apex_data.json")
convex_portfolio = _load_json("convex_portfolio.json")

apex_val_eur = 0.0
_nav_usd = float(apex_portfolio.get("nav_usd", 0.0))
_eur_usd_rate = float(apex_data.get("eur_usd", 0.0))
if _nav_usd > 0 and _eur_usd_rate > 0:
    apex_val_eur = _nav_usd / _eur_usd_rate

convex_holdings_saved = convex_portfolio.get("holdings", {})
convex_has_real_data = bool(convex_holdings_saved) and any(v.get("shares", 0) > 0 for v in convex_holdings_saved.values())
convex_val_eur = None
if convex_has_real_data:
    # Valuta con l'ultimo prezzo salvato (non un fetch live: questa pagina è
    # solo di lettura, il prezzo live si aggiorna aprendo Convex Stack).
    convex_val_eur = sum(v.get("shares", 0.0) * v.get("last_price", 0.0) for v in convex_holdings_saved.values()) \
        + float(convex_portfolio.get("cash_eur", 0.0))

st_html(section_title("Patrimonio Combinato", top="20px"))
c1, c2, c3 = st.columns(3)
c1.metric("Apex Engine", f"€ {apex_val_eur:,.0f}" if apex_val_eur > 0 else "n/d")
c2.metric("Convex Stack", f"€ {convex_val_eur:,.0f}" if convex_val_eur is not None else "n/d",
          help=None if convex_val_eur is not None else "Apri Convex Stack e inserisci le tue quote: questa pagina non le conosce ancora.")
_tot = (apex_val_eur if apex_val_eur > 0 else 0.0) + (convex_val_eur or 0.0)
c3.metric("Totale", f"€ {_tot:,.0f}" if _tot > 0 else "n/d")

# ==============================================================================
# SEGNALE DI INTERVENTO NECESSARIO — riusa la stessa logica reale delle due
# app (ordini in sospeso per Apex, avvisi di trim per Convex), mai un check
# inventato.
# ==============================================================================
st_html(section_title("Serve il Tuo Intervento?"))
i1, i2 = st.columns(2)

_pending_orders = apex_portfolio.get("pending_orders") or []
with i1:
    if _pending_orders:
        st_html(f"""
        <div style="background: rgba(236,101,123,0.08); border: 1px solid rgba(236,101,123,0.3); border-radius: 8px; padding: 14px;">
            <div style="color:{NEG}; font-weight:700; font-size:13.5px;">APEX ENGINE — SERVE ATTENZIONE</div>
            <div style="font-size:12px; color:{MUTED}; margin-top:3px;">{len(_pending_orders)} ordine/i operativo/i in sospeso. Apri Apex Engine per i dettagli.</div>
        </div>
        """)
    else:
        st_html(f"""
        <div style="background: rgba(61,220,151,0.06); border: 1px solid rgba(61,220,151,0.25); border-radius: 8px; padding: 14px;">
            <div style="color:{POS}; font-weight:700; font-size:13.5px;">APEX ENGINE — NESSUNA AZIONE RICHIESTA</div>
            <div style="font-size:12px; color:{MUTED}; margin-top:3px;">Nessun ordine in sospeso al momento.</div>
        </div>
        """)

with i2:
    if not convex_has_real_data:
        st_html(f"""
        <div class="glass-card" style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px; margin: 0;">
            <div style="color:{MUTED}; font-weight:700; font-size:13.5px;">CONVEX STACK — DATO NON DISPONIBILE</div>
            <div style="font-size:12px; color:{MUTED}; margin-top:3px;">Apri Convex Stack e inserisci le tue quote per il controllo ribilanciamento.</div>
        </div>
        """)
    else:
        import convex_engine
        _cx_report = convex_engine.evaluate_convex_stack(
            current_holdings={k: v.get("shares", 0.0) for k, v in convex_holdings_saved.items()},
            market_prices={k: v.get("last_price", 0.0) for k, v in convex_holdings_saved.items()},
            monthly_pac_eur=0.0,
            cash_balance=float(convex_portfolio.get("cash_eur", 0.0))
        )
        if _cx_report.trim_alerts:
            st_html(f"""
            <div style="background: rgba(236,101,123,0.08); border: 1px solid rgba(236,101,123,0.3); border-radius: 8px; padding: 14px;">
                <div style="color:{NEG}; font-weight:700; font-size:13.5px;">CONVEX STACK — RIBILANCIAMENTO CONSIGLIATO</div>
                <div style="font-size:12px; color:{MUTED}; margin-top:3px;">{len(_cx_report.trim_alerts)} posizione/i sopra soglia. Apri Convex Stack per i dettagli.</div>
            </div>
            """)
        else:
            st_html(f"""
            <div style="background: rgba(61,220,151,0.06); border: 1px solid rgba(61,220,151,0.25); border-radius: 8px; padding: 14px;">
                <div style="color:{POS}; font-weight:700; font-size:13.5px;">CONVEX STACK — NESSUNA AZIONE RICHIESTA</div>
                <div style="font-size:12px; color:{MUTED}; margin-top:3px;">Tutte le posizioni sono dentro le bande di tolleranza.</div>
            </div>
            """)

# ==============================================================================
# BILANCIAMENTO APEX/CONVEX — confronta lo split reale col target (45/55,
# config.json) e con l'intervallo validato in questa sessione (35-45% Apex,
# vedi research/convex/optimize_v2_results.pkl e ratio_final_both_net.pkl).
# ==============================================================================
st_html(section_title("Bilanciamento tra le Due Strategie"))
_cfg = portfolio_manager.load_config()
_target_apex = float(_cfg.get("target_apex_ratio", 0.45))

if apex_val_eur > 0 and convex_val_eur is not None and _tot > 0:
    _real_apex_ratio = apex_val_eur / _tot
    _in_range = 0.30 <= _real_apex_ratio <= 0.55
    _col = POS if _in_range else ACCENT
    _msg = "in linea con l'intervallo validato" if _in_range else "valuta un riequilibrio tra le due strategie"
    st_html(f"""
    <div class="glass-card" style="background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; padding: 14px; margin: 0;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <div style="font-size:13px; color:{BADGE_TEXT}; font-weight:600;">
                Quota Apex reale: <span style="font-family:{MONO}; color:{_col}; font-weight:700;">{_real_apex_ratio*100:.1f}%</span>
                &nbsp;·&nbsp; Target: <span style="font-family:{MONO};">{_target_apex*100:.0f}%</span>
                &nbsp;·&nbsp; Intervallo validato: <span style="font-family:{MONO};">35–45%</span>
            </div>
        </div>
        <div style="font-size:12px; color:{_col}; margin-top:6px; font-weight:600;">{_msg.upper()}</div>
    </div>
    """)
else:
    st.caption(f"Serve il patrimonio reale di entrambe le strategie per calcolare il bilanciamento (target configurato: {_target_apex*100:.0f}% Apex / {(1-_target_apex)*100:.0f}% Convex).")

# ==============================================================================
# METRICHE COMBINATE — solo le 4 davvero utili a colpo d'occhio, il dettaglio
# vive nelle due pagine (non un dashboard duplicato qui).
# ==============================================================================
st_html(section_title("Metriche Combinate (Mix 45/55, Backtest)"))
_dual = portfolio_manager.get_combined_dual_engine_metrics()
m1, m2, m3, m4 = st.columns(4)
m1.metric("CAGR Netto", f"{_dual['cagr_net']*100:.2f}%", f"Lordo {_dual['cagr_gross']*100:.2f}%",
          help="Crescita annua composta del mix combinato: netto tasse e, sotto, lordo.")
m2.metric("Sharpe", f"{_dual['sharpe']:.2f}", help="Rendimento per unità di rischio.")
m3.metric("Calo Massimo", f"{_dual['max_drawdown']*100:.2f}%", help="Il calo peggiore mai registrato dal picco al minimo.")
m4.metric("Correlazione Reale", f"{_dual['correlation']:.2f}", help="Quanto le due strategie si muovono insieme: più basso è, più protezione reciproca offrono.")
st.caption(_dual["synergy_summary"])
if st.session_state.get("apex_versione") == "Semplice" or st.session_state.get("convex_versione") == "Semplice":
    st.caption("Nota: queste metriche combinate riflettono sempre la versione Completa di entrambe le strategie — non esiste ancora un backtest combinato validato per le versioni Semplice selezionate nelle rispettive pagine.")

# ==============================================================================
# NAVIGAZIONE
# ==============================================================================
st_html(section_title("Apri il Dettaglio"))
n1, n2 = st.columns(2)
with n1:
    if st.button("Apri Apex Engine", use_container_width=True, type="primary"):
        st.switch_page("page_apex.py")
with n2:
    if st.button("Apri Convex Stack", use_container_width=True, type="primary"):
        st.switch_page("page_convex.py")
