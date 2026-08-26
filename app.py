import base64
import datetime
import json
import os
import urllib.request

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="Apex Multi-Asset",
    page_icon="logo_icon.png" if os.path.exists("logo_icon.png") else "🦅",
    layout="wide"
)

# ==============================================================================
# HTML RENDERING HELPER (PREVENTS UNRENDERED CODE BLOCKS)
# ==============================================================================
def st_html(html_str):
    """Renders raw HTML safely without Markdown parser indentation issues."""
    cleaned = "\n".join(line.strip() for line in html_str.strip().splitlines())
    try:
        st.html(cleaned)
    except AttributeError:
        st.markdown(cleaned, unsafe_allow_html=True)


# ==============================================================================
# THEME & GLOBAL STYLING
# ==============================================================================
st_html("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"], .stApp {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
        letter-spacing: -0.01em;
    }

    /* Tabular numbers for financial metrics and dataframes */
    [data-testid="stMetricValue"], [data-testid="stMetricLabel"], .stDataFrame, div[data-testid="stTable"], table {
        font-family: 'JetBrains Mono', monospace !important;
        font-variant-numeric: tabular-nums !important;
    }

    /* Standardized typography for section headers */
    h4, .section-title {
        font-family: 'Inter', sans-serif !important;
        font-size: 16px !important;
        font-weight: 700 !important;
        letter-spacing: -0.2px !important;
        margin-top: 14px !important;
        margin-bottom: 8px !important;
    }

    h5, .subsection-title {
        font-family: 'Inter', sans-serif !important;
        font-size: 14px !important;
        font-weight: 700 !important;
        margin-top: 12px !important;
        margin-bottom: 6px !important;
    }

    /* Tab navigation polish */
    .stTabs [data-baseweb="tab-list"] {
        gap: 6px;
        border-bottom: 1px solid rgba(128,128,128,0.2);
    }
    .stTabs [data-baseweb="tab"] {
        padding: 8px 18px;
        border-radius: 8px 8px 0px 0px;
        font-weight: 600;
        font-size: 13.5px;
    }

    /* Clean cards transition */
    div[style*="border-radius"] {
        transition: transform 0.15s ease-in-out, box-shadow 0.15s ease-in-out;
    }
</style>
""")


# ==============================================================================
# DATA LOADING & SYNC
# ==============================================================================
@st.cache_data(ttl=60)
def fetch_json_from_github(filename):
    url = f"https://raw.githubusercontent.com/davbenx/apex-engine/main/{filename}"
    try:
        buster = int(datetime.datetime.now().timestamp() // 60)
        req = urllib.request.Request(f"{url}?t={buster}", headers={'User-Agent': 'Mozilla/5.0'})
        return json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
    except Exception:
        if os.path.exists(filename):
            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
    return None


def load_data():
    return fetch_json_from_github('apex_data.json')


def load_portfolio():
    return fetch_json_from_github('portfolio.json')


def load_equity():
    return fetch_json_from_github('equity.json')


data = load_data()
if not data:
    st.error("🚨 Dati non disponibili. In attesa del ricalcolo notturno su GitHub.")
    st.stop()


# ==============================================================================
# FORMATTING & HELPERS
# ==============================================================================
def format_price(val):
    if val is None or pd.isna(val):
        return "$0.00"
    try:
        num = float(val)
        return f"${num:,.2f}" if abs(num) >= 1.0 else f"${num:,.6f}"
    except Exception:
        return f"${val}"


def calculate_days(entry_date_str):
    try:
        entry_d = datetime.datetime.strptime(entry_date_str, "%Y-%m-%d").date()
        today = datetime.datetime.now().date()
        return max(0, (today - entry_d).days)
    except Exception:
        return 0


def get_logo_b64():
    for p in ["logo_icon.png", "logo.png"]:
        if os.path.exists(p):
            try:
                with open(p, "rb") as f:
                    return base64.b64encode(f.read()).decode()
            except Exception:
                pass
    return ""


# ==============================================================================
# HEADER & BRANDING
# ==============================================================================
last_update = data.get("timestamp", "Sincronizzazione in corso...")
logo_b64 = get_logo_b64()
logo_tag = f'<img src="data:image/png;base64,{logo_b64}" style="height: 75px; width: auto; object-fit: contain;" />' if logo_b64 else '🦅'

col_title, col_meta = st.columns([3, 2])
with col_title:
    st_html(f"""
    <div style="display: flex; align-items: center; gap: 16px; padding: 6px 0;">
        <div style="background: rgba(128, 128, 128, 0.08); border: 1px solid rgba(128, 128, 128, 0.18); padding: 6px 10px; border-radius: 12px; display: flex; align-items: center; justify-content: center; box-shadow: 0 4px 12px rgba(0,0,0,0.25);">
            {logo_tag}
        </div>
        <div>
            <div style="font-size: 28px; font-weight: 800; letter-spacing: -0.8px; line-height: 1.15;">APEX ENGINE</div>
            <div style="font-size: 12px; font-weight: 600; opacity: 0.75; letter-spacing: 0.6px; text-transform: uppercase; margin-top: 3px; line-height: 1.35;">
                Sistema Quantitativo<br>
                Multi-Asset<br>
                <span style='color: #3B82F6; font-weight: 700;'>v1.0 Genesis</span>
            </div>
        </div>
    </div>
    """)

with col_meta:
    st_html(f"""
    <div style="text-align: right; padding-top: 8px;">
        <div style="display: flex; justify-content: flex-end; align-items: center; gap: 8px; margin-bottom: 5px;">
            <a href="https://t.me/apex_multiasset" target="_blank" style="text-decoration: none; display: inline-flex; align-items: center; gap: 4px; background: rgba(0, 136, 204, 0.12); color: #0088cc; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; border: 1px solid rgba(0, 136, 204, 0.3);">
                ✈️ Notifiche @apex_multiasset
            </a>
            <span style="background: rgba(16, 185, 129, 0.15); color: #10B981; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; border: 1px solid rgba(16, 185, 129, 0.3);">🟢 Motore Attivo</span>
        </div>
        <div style="opacity: 0.75; font-size: 11.5px; line-height: 1.4;">
            🕒 <strong>Aggiornato:</strong> {last_update}<br>
            ⏳ <strong>Ricalcolo:</strong> 01:30 UTC
        </div>
    </div>
    """)

# ==============================================================================
# MACRO ENGINE CARDS
# ==============================================================================
alloc = data.get('allocations', {"Equities": 0, "Crypto": 0, "Gold": 0, "Bonds": 0, "Cash": 100})
raw_ts = data.get('timestamp', '')
ts_date = raw_ts.split(',')[0].strip() if ',' in raw_ts else (raw_ts.split(' ')[0] if raw_ts else datetime.datetime.now().strftime('%Y-%m-%d'))
macro_dates = data.get("macro_dates", {})

d_eq = macro_dates.get("Equities", ts_date)
d_cr = macro_dates.get("Crypto", ts_date)
d_g = macro_dates.get("Gold", ts_date)
d_b = macro_dates.get("Bonds", ts_date)


def make_engine_card(icon, name, alloc_pct, is_active, since_date, is_cash=False):
    if is_cash:
        border_color = "#3B82F6" if alloc_pct > 0 else "#4B5563"
        bg_color = "rgba(59, 130, 246, 0.08)" if alloc_pct > 0 else "rgba(107, 114, 128, 0.05)"
        badge_bg = "#1E40AF" if alloc_pct > 0 else "#374151"
        status_text = "🟢 ATTIVO" if alloc_pct > 0 else "⚪ STBY"
        status_color = "#60A5FA" if alloc_pct > 0 else "#9CA3AF"
        date_str = "Rifugio Sicuro"
        opacity = "1"
    else:
        border_color = "#10B981" if is_active else "#EF4444"
        bg_color = "rgba(16, 185, 129, 0.08)" if is_active else "rgba(239, 68, 68, 0.06)"
        badge_bg = "#065F46" if is_active else "#7F1D1D"
        status_text = "🟢 ATTIVO" if is_active else "🔴 DISATTIVO"
        status_color = "#34D399" if is_active else "#F87171"
        date_str = f"dal {since_date}" if since_date and since_date != "-" else ""
        opacity = "1" if is_active else "0.75"

    return f"""
    <div style="flex: 1 1 180px; min-width: 155px; background: {bg_color}; border: 1px solid {border_color}; border-radius: 10px; padding: 11px 14px; display: flex; flex-direction: column; justify-content: space-between; box-shadow: 0 2px 6px rgba(0,0,0,0.12); opacity: {opacity};">
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-weight: 700; font-size: 13.5px; letter-spacing: 0.2px;">{icon} {name}</span>
            <span style="background: {badge_bg}; color: #ffffff; font-size: 11.5px; font-weight: 700; padding: 2px 8px; border-radius: 6px; font-family: 'JetBrains Mono', monospace;">{alloc_pct}%</span>
        </div>
        <div style="display: flex; justify-content: space-between; align-items: baseline;">
            <span style="color: {status_color}; font-weight: 700; font-size: 11.5px; letter-spacing: 0.3px;">{status_text}</span>
            <span style="opacity: 0.65; font-size: 10.5px;">{date_str}</span>
        </div>
    </div>
    """

card_eq = make_engine_card("📈", "Azioni", alloc.get('Equities', 0), alloc.get('Equities', 0) > 0, d_eq)
card_cr = make_engine_card("🪙", "Crypto", alloc.get('Crypto', 0), alloc.get('Crypto', 0) > 0, d_cr)
card_g = make_engine_card("🥇", "Oro", alloc.get('Gold', 0), alloc.get('Gold', 0) > 0, d_g)
card_b = make_engine_card("🛡️", "Obbligazioni", alloc.get('Bonds', 0), alloc.get('Bonds', 0) > 0, d_b)
card_c = make_engine_card("💵", "Monetario", alloc.get('Cash', 0), False, "", is_cash=True)

st_html(f'<div style="display: flex; gap: 10px; flex-wrap: wrap; margin: 12px 0 18px 0;">{card_eq}{card_cr}{card_g}{card_b}{card_c}</div>')


# ==============================================================================
# PORTFOLIO DATA EXTRACTION
# ==============================================================================
pf = load_portfolio()
op_eq = []
op_cr = []
num_eq = 0
num_cr = 0

if pf:
    for ticker, info in pf.get("open_positions", {}).items():
        entry_d = info.get("entry_date", "N/A")
        days_open = calculate_days(entry_d) if entry_d != "N/A" else 0
        entry_formatted = f"{entry_d} ({days_open}g)" if entry_d != "N/A" else "N/A"

        curr_p = info.get("current_price", info.get("entry_price", 0.0))
        stop_p = info.get("stop_loss", info.get("stop_price", 0.0))
        pnl_pct = ((curr_p / info["entry_price"]) - 1.0) * 100 if info.get("entry_price", 0) > 0 else 0.0
        dist_stop_pct = ((stop_p / curr_p) - 1.0) * 100 if curr_p > 0 else 0.0

        is_crypto = info.get("is_crypto", False)
        is_new_this_week = days_open <= 7
        badge_icon = "🆕" if is_new_this_week else "⭐"

        if is_crypto:
            num_cr += 1
            pos_str = f"{badge_icon} {num_cr}"
        else:
            num_eq += 1
            pos_str = f"{badge_icon} {num_eq}"

        row = {
            "Pos": pos_str,
            "Titolo": ticker,
            "Data Ingresso": entry_formatted,
            "Ingresso ($)": info.get("entry_price", 0.0),
            "Attuale ($)": curr_p,
            "Stop Loss ($)": stop_p,
            "Distanza Stop": dist_stop_pct,
            "Rendimento %": pnl_pct
        }
        if is_crypto:
            op_cr.append(row)
        else:
            op_eq.append(row)


# ==============================================================================
# MAIN TABS DECLARATION (PORTAFOGLIO, METRICHE, RADAR, GUIDA)
# ==============================================================================
tab_pf, tab_perf, tab_radar, tab_guide = st.tabs([
    "💼 Portafoglio",
    "📊 Metriche",
    "📡 Radar",
    "📖 Guida"
])


# ==============================================================================
# TAB 1: PORTAFOGLIO & ALLOCAZIONE
# ==============================================================================
with tab_pf:
    c_inp, c_pnl = st.columns([3, 2])
    with c_inp:
        c_val, c_cur = st.columns([3, 2])
        with c_val:
            capitale_input = st.number_input(
                "💰 Capitale Broker Reale", min_value=1000, value=100000, step=1000, format="%d"
            )
        with c_cur:
            valuta_sel = st.segmented_control("Valuta Conto", ["USD ($)", "EUR (€)"], default="USD ($)")

        eur_usd_rate = float(data.get("eur_usd", 1.085))
        is_eur = (valuta_sel == "EUR (€)")
        curr_sym = "€" if is_eur else "$"
        fx_ratio = (1.0 / eur_usd_rate) if is_eur else 1.0

        if is_eur:
            capitale = capitale_input * eur_usd_rate
            st.caption(f"💶 Conto: **€{capitale_input:,.0f}** | 💵 Potere d'acquisto: **${capitale:,.0f} USD** (Tasso EUR/USD: `{eur_usd_rate:.4f}`)")
        else:
            capitale = float(capitale_input)
            st.caption(f"💵 Conto Operativo: **${capitale:,.0f} USD** (Prezzi e quote calcolati in dollari)")

    capitale_azionario = capitale * (alloc.get('Equities', 0) / 100)
    single_eq = capitale_azionario / 20 if alloc.get('Equities', 0) > 0 else 0
    crypto_cap = capitale * (alloc.get('Crypto', 0) / 100)
    gold_cap = capitale * (alloc.get('Gold', 0) / 100)
    bond_cap = capitale * (alloc.get('Bonds', 0) / 100)

    # Calcolo Floating P&L
    tot_pnl_usd = 0.0
    tot_invested_usd = 0.0

    for r in op_eq:
        pnl_val = (r["Rendimento %"] / 100) * single_eq
        tot_pnl_usd += pnl_val
        tot_invested_usd += single_eq

    for r in op_cr:
        cr_size = capitale * (0.10 if r['Titolo'] == 'BTC' else 0.05)
        pnl_val = (r["Rendimento %"] / 100) * cr_size
        tot_pnl_usd += pnl_val
        tot_invested_usd += cr_size

    macro_pos = pf.get("macro_positions", {}) if pf else {}
    g_pnl_usd = 0.0
    g_pnl_pct = 0.0
    if alloc.get('Gold', 0) > 0:
        if "Gold" in macro_pos:
            g_pos = macro_pos["Gold"]
            c_p = g_pos.get("current_price", g_pos.get("entry_price", 0))
            if g_pos.get("entry_price", 0) > 0:
                g_pnl_pct = ((c_p / g_pos["entry_price"]) - 1.0) * 100
                g_pnl_usd = (g_pnl_pct / 100) * gold_cap
        tot_pnl_usd += g_pnl_usd
        tot_invested_usd += gold_cap

    b_pnl_usd = 0.0
    b_pnl_pct = 0.0
    if alloc.get('Bonds', 0) > 0:
        if "Bonds" in macro_pos:
            b_pos = macro_pos["Bonds"]
            c_p = b_pos.get("current_price", b_pos.get("entry_price", 0))
            if b_pos.get("entry_price", 0) > 0:
                b_pnl_pct = ((c_p / b_pos["entry_price"]) - 1.0) * 100
                b_pnl_usd = (b_pnl_pct / 100) * bond_cap
        tot_pnl_usd += b_pnl_usd
        tot_invested_usd += bond_cap

    tot_pnl_pct = (tot_pnl_usd / tot_invested_usd * 100) if tot_invested_usd > 0 else 0.0
    tot_pnl_user = tot_pnl_usd * fx_ratio

    with c_pnl:
        num_pos = len(op_eq) + len(op_cr) + (1 if alloc.get('Gold', 0) > 0 else 0) + (1 if alloc.get('Bonds', 0) > 0 else 0)
        if num_pos > 0:
            pnl_sign = "+" if tot_pnl_user >= 0 else "-"
            pnl_col = "#10B981" if tot_pnl_user >= 0 else "#EF4444"
            pnl_val_str = f"{pnl_sign}{curr_sym}{abs(tot_pnl_user):,.0f}"
            pnl_pct_str = f"{'+' if tot_pnl_pct>=0 else ''}{tot_pnl_pct:.2f}%"
            sub_text = f"Su {num_pos} posizioni ({'+' if tot_pnl_usd>=0 else ''}${tot_pnl_usd:,.0f} USD)" if is_eur else f"Su {num_pos} posizioni aperte"
        else:
            pnl_col = "gray"
            pnl_val_str = f"{curr_sym}0"
            pnl_pct_str = "0.00%"
            sub_text = "Nessuna posizione aperta (attesa venerdì)"

        st_html(f"""
        <div style="background: rgba(128,128,128,0.06); border: 1px solid rgba(128,128,128,0.15); border-radius: 8px; padding: 10px 16px; margin-top: 2px;">
            <div style="opacity: 0.75; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px;">Rendimento Galleggiante ({curr_sym})</div>
            <div style="font-size: 20px; font-weight: 700; color: {pnl_col}; font-family: 'JetBrains Mono', monospace; margin: 2px 0;">
                {pnl_val_str} <span style="font-size: 13px; font-weight: 600;">({pnl_pct_str})</span>
            </div>
            <div style="opacity: 0.65; font-size: 10.5px;">{sub_text}</div>
        </div>
        """)

    st.write("")

    # Coperture Macro & Monetario Cards
    def make_asset_card(icon, label, amount_usd, subtext, border_col, is_active=True, pnl_pct=0.0, pnl_val_usd=0.0):
        opacity = "1" if is_active else "0.55"
        amount_user = amount_usd * fx_ratio
        pnl_val_user = pnl_val_usd * fx_ratio
        pnl_badge = ""
        if is_active and pnl_pct != 0.0:
            pnl_col = "#10B981" if pnl_pct >= 0 else "#EF4444"
            pnl_badge = f'<div style="font-size: 11px; font-weight: 700; color: {pnl_col}; font-family: \'JetBrains Mono\', monospace; margin-top: 3px;">Rendimento: {pnl_val_user:+,.0f} {curr_sym} ({pnl_pct:+.2f}%)</div>'

        return f"""
        <div style="background: rgba(128,128,128,0.06); border: 1px solid {border_col}; border-radius: 8px; padding: 10px 14px; opacity: {opacity}; display: flex; flex-direction: column; justify-content: space-between;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 2px;">
                <span style="font-weight: 600; font-size: 12px; color: #9CA3AF;">{icon} {label}</span>
                <span style="font-size: 12px; font-weight: 700; font-family: 'JetBrains Mono', monospace;">{curr_sym}{amount_user:,.0f}</span>
            </div>
            <div style="opacity: 0.65; font-size: 10.5px;">{subtext}</div>
            {pnl_badge}
        </div>
        """

    real_cash_usd = capitale * (alloc.get('Cash', 0) / 100) + (capitale_azionario - (len(op_eq) * single_eq))
    card_cash = make_asset_card("💵", "MONETARIO", real_cash_usd, "Parcheggio strategico e riserve", "#3B82F6", True)
    card_gold = make_asset_card("🥇", "ORO", gold_cap, "Copertura Macro", "#F59E0B" if alloc.get('Gold', 0) > 0 else "#4B5563", alloc.get('Gold', 0) > 0, g_pnl_pct, g_pnl_usd)
    card_bond = make_asset_card("🛡️", "OBBLIGAZIONI", bond_cap, "Copertura Tassi", "#8B5CF6" if alloc.get('Bonds', 0) > 0 else "#4B5563", alloc.get('Bonds', 0) > 0, b_pnl_pct, b_pnl_usd)

    st_html(f'<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin-bottom: 18px;">{card_cash}{card_gold}{card_bond}</div>')

    def color_pnl(val):
        color = '#10B981' if val > 0 else '#EF4444' if val < 0 else 'gray'
        return f'color: {color}; font-weight: 700;'

    def color_stop_dist(val):
        if val > -5.0:
            return 'color: #EF4444; font-weight: 700;'
        elif val > -10.0:
            return 'color: #F59E0B; font-weight: 600;'
        return ''

    def style_pos(val):
        if "🆕" in str(val):
            return 'background-color: rgba(59, 130, 246, 0.15); color: #3B82F6; font-weight: 700; text-align: center;'
        return 'background-color: rgba(16, 185, 129, 0.15); color: #10B981; font-weight: 700; text-align: center;'

    col_val_label = f"Valore ({curr_sym})"
    col_rend_label = f"Rendimento ({curr_sym})"

    col_az, col_cr = st.columns([2, 1])

    with col_az:
        st_html(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 15px; font-weight: 700; letter-spacing: -0.2px;">📈 Azioni in Portafoglio</span>
            <span style="background: rgba(16, 185, 129, 0.15); color: #10B981; padding: 2px 8px; border-radius: 6px; font-size: 11.5px; font-weight: 700; font-family: 'JetBrains Mono', monospace;">{num_eq} / 20</span>
        </div>
        """)

        if op_eq:
            df_op_eq = pd.DataFrame(op_eq)
            df_op_eq["Quote"] = [max(1, int(round(single_eq / r["Ingresso ($)"]))) if r["Ingresso ($)"] > 0 else 0 for _, r in df_op_eq.iterrows()]
            df_op_eq[col_val_label] = [r["Quote"] * r["Attuale ($)"] * fx_ratio for _, r in df_op_eq.iterrows()]
            df_op_eq[col_rend_label] = df_op_eq[col_val_label] - (df_op_eq["Quote"] * df_op_eq["Ingresso ($)"] * fx_ratio)

            cols_eq = ["Pos", "Titolo", "Data Ingresso", "Quote", "Ingresso ($)", "Attuale ($)", "Stop Loss ($)", "Distanza Stop", col_val_label, "Rendimento %", col_rend_label]
            df_op_eq = df_op_eq[[c for c in cols_eq if c in df_op_eq.columns]]

            df_eq_styled = df_op_eq.style.format({
                "Quote": "{:d}",
                "Ingresso ($)": "{:.2f}",
                "Attuale ($)": "{:.2f}",
                "Stop Loss ($)": "{:.2f}",
                "Distanza Stop": "{:.1f}%",
                col_val_label: "{:,.0f}",
                "Rendimento %": "{:+.2f}%",
                col_rend_label: "{:+,.0f}"
            }).map(color_pnl, subset=['Rendimento %', col_rend_label]).map(color_stop_dist, subset=['Distanza Stop']).map(style_pos, subset=['Pos'])

            st.dataframe(df_eq_styled, use_container_width=True, hide_index=True)
        else:
            st.info("Nessuna azione in portafoglio. In attesa del ricalcolo del venerdì.")

    with col_cr:
        st_html(f"""
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
            <span style="font-size: 15px; font-weight: 700; letter-spacing: -0.2px;">🪙 Crypto in Portafoglio</span>
            <span style="background: rgba(16, 185, 129, 0.15); color: #10B981; padding: 2px 8px; border-radius: 6px; font-size: 11.5px; font-weight: 700; font-family: 'JetBrains Mono', monospace;">{num_cr} / 3</span>
        </div>
        """)

        if op_cr:
            df_op_cr = pd.DataFrame(op_cr)
            alloc_moneys = [capitale * (0.10 if r['Titolo'] == 'BTC' else 0.05) for _, r in df_op_cr.iterrows()]
            df_op_cr["Quote"] = [m / r["Ingresso ($)"] if r["Ingresso ($)"] > 0 else 0 for m, (_, r) in zip(alloc_moneys, df_op_cr.iterrows())]
            df_op_cr[col_val_label] = [r["Quote"] * r["Attuale ($)"] * fx_ratio for _, r in df_op_cr.iterrows()]
            df_op_cr[col_rend_label] = df_op_cr[col_val_label] - (df_op_cr["Quote"] * df_op_cr["Ingresso ($)"] * fx_ratio)

            cols_cr = ["Pos", "Titolo", "Data Ingresso", "Quote", "Ingresso ($)", "Attuale ($)", "Stop Loss ($)", "Distanza Stop", col_val_label, "Rendimento %", col_rend_label]
            df_op_cr = df_op_cr[[c for c in cols_cr if c in df_op_cr.columns]]

            def format_crypto_shares(val):
                if val >= 1.0:
                    return f"{val:.4f}"
                return f"{val:.6f}"

            df_cr_styled = df_op_cr.style.format({
                "Quote": format_crypto_shares,
                "Ingresso ($)": format_price,
                "Attuale ($)": format_price,
                "Stop Loss ($)": format_price,
                "Distanza Stop": "{:.1f}%",
                col_val_label: "{:,.0f}",
                "Rendimento %": "{:+.2f}%",
                col_rend_label: "{:+,.0f}"
            }).map(color_pnl, subset=['Rendimento %', col_rend_label]).map(color_stop_dist, subset=['Distanza Stop']).map(style_pos, subset=['Pos'])

            st.dataframe(df_cr_styled, use_container_width=True, hide_index=True)
        else:
            st.info("Nessuna crypto in portafoglio. In attesa del ricalcolo del venerdì.")


# ==============================================================================
# TAB 2: METRICHE (CANDLESTICK EQUITY CURVE, KPI, STORICO)
# ==============================================================================
with tab_perf:
    selected_range = st.segmented_control(
        "Periodo",
        options=["1M", "3M", "6M", "1A", "Tutto"],
        default="6M",
        label_visibility="collapsed",
        key="chart_range_ctrl"
    )
    if not selected_range:
        selected_range = "6M"

    @st.cache_data(ttl=3600)
    def load_benchmark():
        try:
            url = "https://query2.finance.yahoo.com/v8/finance/chart/SPY?range=2y&interval=1d"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            res = json.loads(urllib.request.urlopen(req, timeout=5).read().decode())
            data_spy = res['chart']['result'][0]
            timestamps = pd.to_datetime(data_spy['timestamp'], unit='s')
            quote = data_spy['indicators']['quote'][0]
            df_b = pd.DataFrame({
                'open': quote['open'],
                'high': quote['high'],
                'low': quote['low'],
                'close': quote['close']
            }, index=timestamps).ffill().dropna()
            return df_b
        except Exception:
            return pd.DataFrame()

    df_spy = load_benchmark()
    eq_curve = load_equity()

    total_ret_pct = 0.0
    max_dd = 0.0

    if eq_curve and "history" in eq_curve and len(eq_curve["history"]) > 0:
        df_eq = pd.DataFrame(eq_curve["history"])
        df_eq['date'] = pd.to_datetime(df_eq['date'])
        df_eq = df_eq.set_index('date')

        if 'open' not in df_eq.columns or df_eq['open'].isna().all():
            df_eq['open'] = df_eq['value'].shift(1).fillna(df_eq['value'].iloc[0])
            df_eq['high'] = df_eq[['open', 'value']].max(axis=1)
            df_eq['low'] = df_eq[['open', 'value']].min(axis=1)
            df_eq['close'] = df_eq['value']

        df_eq['roll_max'] = df_eq['close'].cummax()
        df_eq['drawdown'] = (df_eq['close'] - df_eq['roll_max']) / df_eq['roll_max'] * 100
        max_dd = df_eq['drawdown'].min()

        initial_val = df_eq['open'].iloc[0]
        final_val = df_eq['close'].iloc[-1]
        total_ret_pct = ((final_val / initial_val) - 1.0) * 100

        # Normalizzazione Base 100
        base_val = initial_val if initial_val > 0 else 100000.0
        df_eq['norm_open'] = (df_eq['open'] / base_val) * 100
        df_eq['norm_high'] = (df_eq['high'] / base_val) * 100
        df_eq['norm_low'] = (df_eq['low'] / base_val) * 100
        df_eq['norm_close'] = (df_eq['close'] / base_val) * 100

        # Pure Weekly Candlestick Aggregation (W-FRI)
        if len(df_eq) >= 5:
            df_agg = df_eq.resample('W-FRI').agg({
                'norm_open': 'first',
                'norm_high': 'max',
                'norm_low': 'min',
                'norm_close': 'last',
                'close': 'last'
            }).dropna()
            df_agg['norm_high'] = df_agg[['norm_open', 'norm_close', 'norm_high']].max(axis=1)
            df_agg['norm_low'] = df_agg[['norm_open', 'norm_close', 'norm_low']].min(axis=1)
        else:
            df_agg = df_eq

        # Range filter
        last_dt = df_agg.index[-1]
        if selected_range == "1M":
            start_dt = last_dt - pd.DateOffset(months=1)
        elif selected_range == "3M":
            start_dt = last_dt - pd.DateOffset(months=3)
        elif selected_range == "6M":
            start_dt = last_dt - pd.DateOffset(months=6)
        elif selected_range == "1A":
            start_dt = last_dt - pd.DateOffset(years=1)
        else:  # "Tutto"
            start_dt = df_agg.index[0]

        df_plot = df_agg[df_agg.index >= start_dt].copy()

        IT_MONTHS = {1: 'Gen', 2: 'Feb', 3: 'Mar', 4: 'Apr', 5: 'Mag', 6: 'Giu', 7: 'Lug', 8: 'Ago', 9: 'Set', 10: 'Ott', 11: 'Nov', 12: 'Dic'}

        ticks = []
        tick_labels = []
        if not df_plot.empty:
            start_d = df_plot.index[0]
            end_d = df_plot.index[-1]
            total_days = (end_d - start_d).days
            all_days = pd.date_range(start_d, end_d, freq='D')

            if total_days <= 45:
                ticks = [all_days[i] for i in range(0, len(all_days), 7)]
                tick_labels = [f"{d.day} {IT_MONTHS[d.month]}" for d in ticks]
            elif total_days <= 120:
                ticks = [d for d in all_days if d.day in [1, 15]]
                tick_labels = [f"{d.day:02d} {IT_MONTHS[d.month]}" for d in ticks]
            elif total_days <= 450:
                ticks = [d for d in all_days if d.day == 1]
                tick_labels = [f"{IT_MONTHS[d.month]} '{d.strftime('%y')}" if (d.month in [1, 7] or (len(ticks) > 0 and d == ticks[0])) else IT_MONTHS[d.month] for d in ticks]
            else:
                ticks = [d for d in all_days if d.day == 1 and d.month in [1, 4, 7, 10]]
                tick_labels = [f"{IT_MONTHS[d.month]} '{d.strftime('%y')}" for d in ticks]

        fig = go.Figure()

        it_dates_str = [f"{d.day:02d} {IT_MONTHS[d.month]} {d.year}" for d in df_plot.index]

        # 1. Candele Giapponesi Settimanali per Strategia Apex
        fig.add_trace(
            go.Candlestick(
                x=df_plot.index,
                open=df_plot['norm_open'],
                high=df_plot['norm_high'],
                low=df_plot['norm_low'],
                close=df_plot['norm_close'],
                hovertext=it_dates_str,
                hovertemplate="<b>%{hovertext}</b><br>Apertura: %{open:.2f}<br>Massimo: %{high:.2f}<br>Minimo: %{low:.2f}<br>Chiusura: %{close:.2f}<extra></extra>",
                increasing_line_color='#10B981',
                decreasing_line_color='#EF4444',
                increasing_fillcolor='#10B981',
                decreasing_fillcolor='#EF4444',
                name='Strategia Apex'
            )
        )

        # 2. Benchmark S&P 500 (Linea di Riferimento Settimanale)
        if not df_spy.empty:
            start_date = df_plot.index[0]
            df_spy_aligned = df_spy[df_spy.index >= start_date].copy()
            if not df_spy_aligned.empty:
                first_spy = df_spy_aligned['close'].iloc[0]
                df_spy_plot = df_spy_aligned['close'].resample('W-FRI').last().dropna() if len(df_spy_aligned) >= 5 else df_spy_aligned['close']
                df_spy_norm = (df_spy_plot / first_spy) * 100

                spy_it_dates = [f"{d.day:02d} {IT_MONTHS[d.month]} {d.year}" for d in df_spy_plot.index]
                fig.add_trace(go.Scatter(
                    x=df_spy_plot.index,
                    y=df_spy_norm,
                    text=spy_it_dates,
                    hovertemplate="<b>%{text}</b><br>S&P 500: %{y:.2f}<extra></extra>",
                    mode='lines',
                    name="S&P 500 Benchmark",
                    line=dict(color='#9CA3AF', width=1.8, dash='dot'),
                    opacity=0.75
                ))

        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            xaxis=dict(
                showgrid=True,
                gridcolor='rgba(128,128,128,0.1)',
                tickfont=dict(size=11),
                tickmode='array' if len(ticks) > 0 else 'auto',
                tickvals=ticks if len(ticks) > 0 else None,
                ticktext=tick_labels if len(tick_labels) > 0 else None
            ),
            yaxis=dict(showgrid=True, gridcolor='rgba(128,128,128,0.1)', tickfont=dict(size=11), title="Base 100"),
            xaxis_rangeslider_visible=False,
            margin=dict(l=0, r=0, t=10, b=0),
            height=430,
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor='rgba(128,128,128,0.08)')
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("📊 In attesa del file di tracciamento storico.")

    st.write("")

    # Mathematical Advantage & Operating KPI Cards
    if pf:
        hist = pf.get("trade_history", [])
        wins = [t for t in hist if t.get("profit_pct", 0) > 0]
        losses = [t for t in hist if t.get("profit_pct", 0) <= 0]

        win_rate = (len(wins) / len(hist) * 100) if hist else 0.0
        avg_win = sum(t["profit_pct"] for t in wins) / len(wins) if wins else 0.0
        avg_loss = sum(t["profit_pct"] for t in losses) / len(losses) if losses else 0.0
        gross_profit = sum(t["profit_pct"] for t in wins)
        gross_loss = abs(sum(t["profit_pct"] for t in losses))

        payoff_ratio = avg_win / abs(avg_loss) if avg_loss != 0 else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss != 0 else 0.0

        def make_kpi_card(icon, title, value, subtext, badge_text, border_color, bg_color, badge_bg, val_color):
            return f"""
            <div style="flex: 1 1 180px; min-width: 155px; background: {bg_color}; border: 1px solid {border_color}; border-radius: 10px; padding: 11px 14px; display: flex; flex-direction: column; justify-content: space-between; box-shadow: 0 2px 6px rgba(0,0,0,0.12);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                    <span style="font-weight: 700; font-size: 13px; letter-spacing: 0.2px;">{icon} {title}</span>
                    <span style="background: {badge_bg}; color: #ffffff; font-size: 10.5px; font-weight: 700; padding: 2px 7px; border-radius: 6px; font-family: 'JetBrains Mono', monospace;">{badge_text}</span>
                </div>
                <div style="font-size: 22px; font-weight: 800; color: {val_color}; font-family: 'JetBrains Mono', monospace; margin: 2px 0;">
                    {value}
                </div>
                <div style="opacity: 0.65; font-size: 10.5px; margin-top: 2px;">{subtext}</div>
            </div>
            """

        kpi_ret = make_kpi_card(
            "📈", "Rendimento Netto", f"{total_ret_pct:+.2f}%", "Performance cumulativa",
            "🟢 POSITIVO" if total_ret_pct >= 0 else "🔴 NEGATIVO",
            "#10B981" if total_ret_pct >= 0 else "#EF4444",
            "rgba(16, 185, 129, 0.08)" if total_ret_pct >= 0 else "rgba(239, 68, 68, 0.06)",
            "#065F46" if total_ret_pct >= 0 else "#7F1D1D",
            "#34D399" if total_ret_pct >= 0 else "#F87171"
        )
        kpi_win = make_kpi_card(
            "🎯", "Win Rate", f"{win_rate:.1f}%", f"{len(wins)} vincenti su {len(hist)}",
            f"{len(wins)}/{len(hist)}",
            "#3B82F6", "rgba(59, 130, 246, 0.08)", "#1E40AF", "#60A5FA"
        )
        kpi_pf = make_kpi_card(
            "⚖️", "Profit Factor", f"{profit_factor:.2f}", "Profitti lordi / perdite",
            "ECCELLENTE" if profit_factor >= 1.5 else "STABILE",
            "#10B981" if profit_factor >= 1.5 else "#F59E0B",
            "rgba(16, 185, 129, 0.08)" if profit_factor >= 1.5 else "rgba(245, 158, 11, 0.08)",
            "#065F46" if profit_factor >= 1.5 else "#78350F",
            "#34D399" if profit_factor >= 1.5 else "#FBBF24"
        )
        kpi_po = make_kpi_card(
            "💎", "Payoff Ratio", f"{payoff_ratio:.2f}x", "Vincita media / perdita media",
            "ASIMMETRIA" if payoff_ratio >= 2.0 else "EQUILIBRATO",
            "#8B5CF6", "rgba(139, 92, 246, 0.08)", "#5B21B6", "#A78BFA"
        )
        kpi_dd = make_kpi_card(
            "🛡️", "Max Drawdown", f"{max_dd:.2f}%", "Massima perdita storica",
            "PROTETTO" if max_dd > -15 else "ATTENZIONE",
            "#F59E0B" if max_dd > -15 else "#EF4444",
            "rgba(245, 158, 11, 0.08)" if max_dd > -15 else "rgba(239, 68, 68, 0.06)",
            "#78350F" if max_dd > -15 else "#7F1D1D",
            "#FBBF24" if max_dd > -15 else "#F87171"
        )

        st_html(f'<div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px;">{kpi_ret}{kpi_win}{kpi_pf}{kpi_po}{kpi_dd}</div>')

        if hist:
            p_list = [t.get("profit_pct", 0.0) for t in hist]
            max_val = max(p_list)
            min_val = min(p_list)
            max_idx = p_list.index(max_val)
            min_idx = p_list.index(min_val)
            best_trade_t = hist[max_idx].get("ticker", "-")
            best_trade_p = hist[max_idx].get("profit_pct", 0.0)
            worst_trade_t = hist[min_idx].get("ticker", "-")
            worst_trade_p = hist[min_idx].get("profit_pct", 0.0)

            durations = []
            for t in hist:
                try:
                    d_in = datetime.datetime.strptime(str(t.get("entry_date", "")), "%Y-%m-%d")
                    d_out = datetime.datetime.strptime(str(t.get("exit_date", "")), "%Y-%m-%d")
                    durations.append(max(1, (d_out - d_in).days))
                except Exception:
                    pass
            avg_days_val = int(round(sum(durations) / len(durations))) if durations else 0

            st_html(f"""
            <div style="display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 24px; font-size: 12.5px;">
                <div style="flex: 1 1 200px; background: rgba(16, 185, 129, 0.08); border: 1px solid rgba(16, 185, 129, 0.2); border-radius: 8px; padding: 9px 14px; display: flex; justify-content: space-between; align-items: center;">
                    <span style="opacity: 0.85;">🏆 Miglior Trade</span>
                    <span style="font-weight: 700; color: #10B981; font-family: 'JetBrains Mono', monospace;">{best_trade_t} ({best_trade_p:+.2f}%)</span>
                </div>
                <div style="flex: 1 1 200px; background: rgba(239, 68, 68, 0.06); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 8px; padding: 9px 14px; display: flex; justify-content: space-between; align-items: center;">
                    <span style="opacity: 0.85;">🛑 Peggior Trade</span>
                    <span style="font-weight: 700; color: #EF4444; font-family: 'JetBrains Mono', monospace;">{worst_trade_t} ({worst_trade_p:+.2f}%)</span>
                </div>
                <div style="flex: 1 1 200px; background: rgba(139, 92, 246, 0.08); border: 1px solid rgba(139, 92, 246, 0.2); border-radius: 8px; padding: 9px 14px; display: flex; justify-content: space-between; align-items: center;">
                    <span style="opacity: 0.85;">⏱️ Durata Media Trade</span>
                    <span style="font-weight: 700; color: #A78BFA; font-family: 'JetBrains Mono', monospace;">{avg_days_val} giorni</span>
                </div>
            </div>
            """)

            st_html('<div style="font-size: 15px; font-weight: 700; letter-spacing: -0.2px; margin-bottom: 8px;">📜 Registro Operazioni Chiuse</div>')

            df_hist = pd.DataFrame(hist).sort_values("exit_date", ascending=False)

            def calc_duration(r):
                try:
                    d_in = datetime.datetime.strptime(str(r.get("entry_date", "")), "%Y-%m-%d")
                    d_out = datetime.datetime.strptime(str(r.get("exit_date", "")), "%Y-%m-%d")
                    return f"{max(1, (d_out - d_in).days)}g"
                except Exception:
                    return "-"

            df_hist["Durata"] = df_hist.apply(calc_duration, axis=1)

            def color_trade_pnl(val):
                if isinstance(val, (int, float)):
                    color = '#10B981' if val > 0 else '#EF4444' if val < 0 else 'gray'
                    return f'color: {color}; font-weight: 700;'
                return ''

            df_hist = df_hist.rename(columns={
                "ticker": "Titolo",
                "entry_date": "Data Ingresso",
                "exit_date": "Data Uscita",
                "entry_price": "Prezzo Ingresso",
                "exit_price": "Prezzo Uscita",
                "profit_pct": "Rendimento %",
                "reason": "Motivazione"
            })

            reason_map = {
                'Trailing Stop': '🛡️ Trailing Stop',
                'Stop Loss': '🛡️ Stop Loss',
                'Monthly Rotation Out': '🔄 Rotazione Mensile',
                'Rotation Out': '🔄 Rotazione Mensile',
                'Macro Bearish Regime': '⚠️ Regime Ribassista',
                'Bearish Regime': '⚠️ Regime Ribassista'
            }
            if "Motivazione" in df_hist.columns:
                df_hist["Motivazione"] = df_hist["Motivazione"].apply(lambda r: reason_map.get(str(r), str(r)))

            cols_hist = ["Titolo", "Data Ingresso", "Data Uscita", "Durata", "Prezzo Ingresso", "Prezzo Uscita", "Rendimento %", "Motivazione"]
            df_hist = df_hist[[c for c in cols_hist if c in df_hist.columns]]

            # Search & Filter Controls
            c_srch, c_flt = st.columns([2, 1])
            with c_srch:
                search_t = st.text_input("Cerca Ticker", placeholder="🔍 Cerca per ticker (es. NVDA, AAPL, BTC...)", label_visibility="collapsed")
            with c_flt:
                flt_reason = st.selectbox("Filtro Uscita", ["Tutte le Motivazioni", "🛡️ Trailing Stop", "🔄 Rotazione Mensile", "⚠️ Regime Ribassista"], label_visibility="collapsed")

            if search_t:
                df_hist = df_hist[df_hist["Titolo"].str.contains(search_t.strip().upper(), na=False)]
            if flt_reason != "Tutte le Motivazioni":
                df_hist = df_hist[df_hist["Motivazione"] == flt_reason]

            st.dataframe(
                df_hist.style.format({
                    "Prezzo Ingresso": format_price,
                    "Prezzo Uscita": format_price,
                    "Rendimento %": "{:+.2f}%"
                }).map(color_trade_pnl, subset=['Rendimento %'] if 'Rendimento %' in df_hist.columns else None),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.info("Nessuna operazione chiusa registrata.")


# ==============================================================================
# TAB 3: RADAR ROTAZIONE
# ==============================================================================
with tab_radar:
    st_html("""
    <div style="background: rgba(59, 130, 246, 0.08); border-left: 4px solid #3B82F6; padding: 10px 14px; border-radius: 0 8px 8px 0; margin-bottom: 15px; font-size: 13px; line-height: 1.5;">
        💡 <strong>Radar di Rotazione:</strong> Classifica dei titoli con la maggior forza relativa consolidata su base settimanale. I titoli già in portafoglio sono contrassegnati con ⭐ e aggiornano la protezione ogni venerdì, mentre i nuovi candidati (🆕) subentrano alla rotazione mensile o per rimpiazzare posizioni chiuse su stop loss.
    </div>
    """)

    held_tickers = set(pf.get("open_positions", {}).keys()) if pf else set()

    def style_radar_status(val):
        if "🆕" in str(val):
            return 'background-color: rgba(59, 130, 246, 0.15); color: #3B82F6; font-weight: 700; text-align: center;'
        return 'background-color: rgba(16, 185, 129, 0.15); color: #10B981; font-weight: 700; text-align: center;'

    rc1, rc2 = st.columns([2, 1])
    with rc1:
        st_html('<div style="font-size: 15px; font-weight: 700; letter-spacing: -0.2px; margin-bottom: 8px;">📈 Top 20 Azioni S&P 500</div>')
        if alloc.get("Equities", 0) > 0:
            top20 = data.get("top20", [])
            if top20:
                df_eq = pd.DataFrame(top20)
                if "Momentum Score" in df_eq.columns:
                    df_eq = df_eq.drop(columns=["Momentum Score"])
                df_eq = df_eq.rename(columns={"Ticker": "Titolo", "Prezzo": "Prezzo ($)", "Stop Loss": "Stop Loss ($)"})
                df_eq["Pos"] = [f"⭐ {i+1}" if tkr in held_tickers else f"🆕 {i+1}" for i, tkr in enumerate(df_eq["Titolo"])]
                cols = ["Pos", "Titolo", "Prezzo ($)", "Stop Loss ($)"]
                df_eq = df_eq[[c for c in cols if c in df_eq.columns]]

                st.dataframe(
                    df_eq.style.format({"Prezzo ($)": "{:.2f}", "Stop Loss ($)": "{:.2f}"}).map(
                        style_radar_status, subset=['Pos'] if 'Pos' in df_eq.columns else None
                    ),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("Nessun dato Top 20 disponibile.")
        else:
            st.warning("Motore Azionario DISATTIVO (Semaforo Rosso). Nessun acquisto previsto.")

    with rc2:
        st_html('<div style="font-size: 15px; font-weight: 700; letter-spacing: -0.2px; margin-bottom: 8px;">🪙 Top 3 Crypto</div>')
        if alloc.get("Crypto", 0) > 0:
            cr_top = data.get("crypto_top", [])
            if cr_top:
                df_c = pd.DataFrame(cr_top)
                if "Momentum Score" in df_c.columns:
                    df_c = df_c.drop(columns=["Momentum Score"])
                df_c = df_c.rename(columns={"Ticker": "Titolo", "Prezzo": "Prezzo ($)", "Stop Loss": "Stop Loss ($)"})
                df_c["Pos"] = [f"⭐ {i+1}" if tkr in held_tickers else f"🆕 {i+1}" for i, tkr in enumerate(df_c["Titolo"])]
                cols = ["Pos", "Titolo", "Prezzo ($)", "Stop Loss ($)"]
                df_c = df_c[[c for c in cols if c in df_c.columns]]

                st.dataframe(
                    df_c.style.format({"Prezzo ($)": format_price, "Stop Loss ($)": format_price}).map(
                        style_radar_status, subset=['Pos'] if 'Pos' in df_c.columns else None
                    ),
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("Nessun dato Crypto disponibile.")
        else:
            st.warning("Motore Crypto DISATTIVO (Semaforo Rosso).")


# ==============================================================================
# TAB 4: GUIDA & STRATEGIA
# ==============================================================================
with tab_guide:
    st_html('''
    <div style="background: rgba(0, 136, 204, 0.08); border-left: 4px solid #0088cc; padding: 12px 16px; border-radius: 0 8px 8px 0; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;">
        <div>
            <div style="font-weight: 700; font-size: 14px; color: #0088cc; margin-bottom: 2px;">📢 Canale Ufficiale Notifiche Telegram</div>
            <div style="font-size: 12.5px; opacity: 0.85;">Ricevi in tempo reale i cambi di mercato, gli ordini di rotazione e i livelli di protezione aggiornati.</div>
        </div>
        <a href="https://t.me/apex_multiasset" target="_blank" style="background: #0088cc; color: #ffffff; text-decoration: none; padding: 6px 14px; border-radius: 6px; font-size: 12.5px; font-weight: 700; display: inline-flex; align-items: center; gap: 5px;">
            Unisciti al Canale ✈️
        </a>
    </div>
    ''')

    st_html('<div style="font-size: 15px; font-weight: 700; letter-spacing: -0.2px; margin-bottom: 10px;">📖 Regole Operative</div>')
    st_html("""
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px; margin-bottom: 20px;">
        <div style="background: rgba(128,128,128,0.06); border: 1px solid rgba(128,128,128,0.18); border-radius: 8px; padding: 14px;">
            <div style="font-weight: 700; font-size: 13.5px; color: #3B82F6; margin-bottom: 6px;">📅 1. Controllo mensile</div>
            <div style="font-size: 12.5px; opacity: 0.85; line-height: 1.5;">L'ultimo venerdì del mese l'app vende i titoli deboli e li sostituisce con i nuovi primi in classifica per mantenere il portafoglio forte.</div>
        </div>
        <div style="background: rgba(128,128,128,0.06); border: 1px solid rgba(128,128,128,0.18); border-radius: 8px; padding: 14px;">
            <div style="font-weight: 700; font-size: 13.5px; color: #8B5CF6; margin-bottom: 6px;">⚙️ 2. Controllo settimanale</div>
            <div style="font-size: 12.5px; opacity: 0.85; line-height: 1.5;">Ogni venerdì aggiorna i livelli di protezione. Se in settimana sono state chiuse delle posizioni, queste vengono sostituite con nuovi ingressi.</div>
        </div>
        <div style="background: rgba(128,128,128,0.06); border: 1px solid rgba(128,128,128,0.18); border-radius: 8px; padding: 14px;">
            <div style="font-weight: 700; font-size: 13.5px; color: #10B981; margin-bottom: 6px;">🛡️ 3. Cambi di Mercato</div>
            <div style="font-size: 12.5px; opacity: 0.85; line-height: 1.5;">Se l'app spegne un settore, viene liquidato interamente il venerdì. Se il prezzo crolla sotto il livello di protezione, l'app chiude l'investimento.</div>
        </div>
    </div>
    """)

    st.divider()

    st_html('<div style="font-size: 15px; font-weight: 700; letter-spacing: -0.2px; margin-bottom: 12px;">🧠 Documentazione Strategica</div>')
    st_html('''
    <div style="background: rgba(128,128,128,0.06); border: 1px solid rgba(128,128,128,0.18); border-radius: 8px; padding: 14px; margin-bottom: 14px;">
        <div style="font-weight: 700; font-size: 13.5px; color: #3B82F6; margin-bottom: 4px;">🎯 Obiettivo Primario</div>
        <div style="font-size: 12.5px; opacity: 0.85; line-height: 1.5;">Crescita costante del capitale nei mercati rialzisti e protezione totale durante i ribassi, eliminando ogni componente emotiva attraverso l'allocazione dinamica quantitativa.</div>
    </div>

    <div style="font-size: 13px; font-weight: 700; color: #9CA3AF; text-transform: uppercase; letter-spacing: 0.5px; margin: 16px 0 8px 0;">⚙️ Il Sistema — Distribuzione del Capitale</div>
    <div style="font-size: 12.5px; opacity: 0.85; line-height: 1.5; margin-bottom: 10px;">I fondi vengono versati solo nei settori con andamento positivo, riempiendo prima le attività a maggior rendimento e dirottando il resto sui beni difensivi:</div>

    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 10px; margin-bottom: 14px;">
        <div style="background: rgba(16, 185, 129, 0.08); border: 1px solid #10B981; border-radius: 8px; padding: 10px 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-weight: 700; font-size: 13px;">📈 Azioni</span>
                <span style="background: #065F46; color: #ffffff; font-size: 10.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: 'JetBrains Mono', monospace;">Fino al 70%</span>
            </div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.4;">Motore primario di crescita del capitale.</div>
        </div>
        <div style="background: rgba(16, 185, 129, 0.08); border: 1px solid #10B981; border-radius: 8px; padding: 10px 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-weight: 700; font-size: 13px;">🪙 Criptovalute</span>
                <span style="background: #065F46; color: #ffffff; font-size: 10.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: 'JetBrains Mono', monospace;">Fino al 15%</span>
            </div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.4;">Comparto asimmetrico ad alto rendimento.</div>
        </div>
        <div style="background: rgba(245, 158, 11, 0.08); border: 1px solid #F59E0B; border-radius: 8px; padding: 10px 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-weight: 700; font-size: 13px;">🥇 Oro</span>
                <span style="background: #78350F; color: #ffffff; font-size: 10.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: 'JetBrains Mono', monospace;">Fino al 10%</span>
            </div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.4;">Protezione contro inflazione e incertezza.</div>
        </div>
        <div style="background: rgba(139, 92, 246, 0.08); border: 1px solid #8B5CF6; border-radius: 8px; padding: 10px 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-weight: 700; font-size: 13px;">🛡️ Obbligazioni</span>
                <span style="background: #5B21B6; color: #ffffff; font-size: 10.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: 'JetBrains Mono', monospace;">Fino al 100%</span>
            </div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.4;">Titoli di stato sicuri nei rallentamenti economici.</div>
        </div>
        <div style="background: rgba(59, 130, 246, 0.08); border: 1px solid #3B82F6; border-radius: 8px; padding: 10px 12px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px;">
                <span style="font-weight: 700; font-size: 13px;">💵 Monetario</span>
                <span style="background: #1E40AF; color: #ffffff; font-size: 10.5px; font-weight: 700; padding: 2px 6px; border-radius: 4px; font-family: 'JetBrains Mono', monospace;">Fino al 100%</span>
            </div>
            <div style="font-size: 12px; opacity: 0.85; line-height: 1.4;">Rifugio sicuro e liquidità in attesa di trend.</div>
        </div>
    </div>

    <div style="background: rgba(128,128,128,0.06); border: 1px solid rgba(128,128,128,0.18); border-radius: 8px; padding: 14px; margin-bottom: 18px;">
        <div style="font-weight: 700; font-size: 13.5px; color: #3B82F6; margin-bottom: 4px;">⚡ Selezione dei Titoli ad Alto Momentum</div>
        <div style="font-size: 12.5px; opacity: 0.85; line-height: 1.5;">Tra centinaia di titoli quotati, il sistema acquista solo quelli con la crescita più rapida e solida negli ultimi sei mesi, mantenendo in portafoglio solo la forza relativa leader di mercato.</div>
    </div>
    ''')

    st.divider()

    st_html('''
    <div style="background: rgba(239, 68, 68, 0.05); border: 1px solid rgba(239, 68, 68, 0.2); border-radius: 8px; padding: 12px 14px; font-size: 11.5px; opacity: 0.85; line-height: 1.5;">
        ⚠️ <strong>Note Legali ed Esclusione di Responsabilità:</strong><br>
        Questa piattaforma ha scopo puramente informativo e di analisi statistica. Non fornisce consulenza finanziaria né raccomandazioni personalizzate ai sensi delle normative vigenti.<br>
        I rendimenti passati non garantiscono risultati futuri. Ogni investimento comporta il rischio di perdita del capitale ed è effettuato sotto la totale ed esclusiva responsabilità dell'utente. L'autore declina qualsiasi responsabilità per eventuali perdite derivanti dall'uso di questi dati.
    </div>
    ''')
