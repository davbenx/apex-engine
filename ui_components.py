"""
ui_components.py — Modulo Condiviso UI e Design System di Apex Convex
==================================================================================
Fornisce il design system coerente Dark Glassmorphism, funzioni di rendering HTML,
metriche istituzionali e componenti riutilizzabili per Home, Apex Engine e Convex Stack.
Zero emoji, determinismo visivo e massima efficienza.
==================================================================================
"""

import base64
import os
from typing import Optional
import pandas as pd
import streamlit as st

# ==============================================================================
# DESIGN TOKENS (Standard Istituzionale Dark Glassmorphism)
# ==============================================================================
POS = "#3DDC97"
NEG = "#EC657B"
MUTED_DOT = "#5B534B"
ACCENT = "#C9A44C"
ACCENT_SOFT = "rgba(201,164,76,0.10)"
SURFACE = "rgba(255,247,237,0.045)"
BORDER = "rgba(255,247,237,0.09)"
BORDER_STRONG = "rgba(255,247,237,0.16)"
BORDER_GOLD = "rgba(201,164,76,0.22)"
MUTED = "#9C9187"
MUTED_2 = "#6E655C"
BADGE_TEXT = "#F5F1EA"

FRAUNCES = "'Fraunces', Georgia, serif"
MONO = "'JetBrains Mono', monospace"
MESI_IT = ["Gen", "Feb", "Mar", "Apr", "Mag", "Giu", "Lug", "Ago", "Set", "Ott", "Nov", "Dic"]


# ==============================================================================
# HTML RENDERING HELPERS
# ==============================================================================
def st_html(html_str: str) -> None:
    """Emette HTML ripulito direttamente in Streamlit."""
    cleaned = "\n".join(line.strip() for line in html_str.strip().splitlines())
    st.markdown(cleaned, unsafe_allow_html=True)


def fill_slot(slot, html_str: str) -> None:
    """Riempie un st.empty() con markup HTML ripulito."""
    cleaned = "\n".join(line.strip() for line in html_str.strip().splitlines())
    slot.markdown(cleaned, unsafe_allow_html=True)


def inject_page_styles() -> None:
    """Inietta il foglio di stile globale Dark Glassmorphism per l'intera app."""
    st_html("""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700&family=JetBrains+Mono:wght@400;500;600;700;800&display=swap');

        html, body, [class*="css"], .stApp {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important;
            letter-spacing: -0.01em;
        }

        [data-testid="stMetricValue"], [data-testid="stMetricLabel"], .stDataFrame, div[data-testid="stTable"], table {
            font-family: 'JetBrains Mono', monospace !important;
            font-variant-numeric: tabular-nums !important;
        }

        .stTabs [data-baseweb="tab-list"] {
            gap: 6px;
            border-bottom: 1px solid rgba(255,247,237,0.12);
        }
        .stTabs [data-baseweb="tab"] {
            padding: 8px 18px;
            border-radius: 8px 8px 0px 0px;
            font-weight: 600;
            font-size: 13.5px;
        }

        div[style*="border-radius"] {
            transition: border-color 0.15s ease-in-out;
        }

        .glass-card {
            background: rgba(255, 247, 237, 0.045);
            border: 1px solid rgba(255, 247, 237, 0.09);
            border-radius: 8px;
            padding: 14px 16px;
            margin-bottom: 16px;
        }
        .glass-card-accent {
            background: rgba(201, 164, 76, 0.10);
            border: 1px solid rgba(201, 164, 76, 0.22);
            border-radius: 8px;
            padding: 14px 16px;
            margin-bottom: 16px;
        }

        [data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"],
        section[data-testid="stSidebar"] {
            display: none !important;
        }
    </style>
    """)


# ==============================================================================
# COMPONENTI VISIVI STANDARD
# ==============================================================================
def section_title(text: str, top: str = "26px", bottom: str = "10px") -> str:
    """Genera l'intestazione standard di sezione istituzionale."""
    return f'<div style="font-family:{FRAUNCES}; font-size:16px; font-weight:600; letter-spacing:-0.1px; margin:{top} 0 {bottom};">{text}</div>'


def sub_hero_metric(label: str, value: str, subtext: str = "", val_color: Optional[str] = None, primary: bool = False) -> str:
    """Genera una cella per metrica di riepilogo con tipografia e allineamento rigorosi."""
    val_size = "32px" if primary else "20px"
    return f"""
    <div style="flex: 1 1 {'160px' if primary else '130px'};">
        <div style="font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.6px; color: {MUTED}; margin-bottom: 5px;">{label}</div>
        <div style="font-family: {MONO}; font-size: {val_size}; font-weight: 800; color: {val_color or 'inherit'};">{value}</div>
        <div style="font-size: 11px; color: {MUTED}; margin-top: 2px;">{subtext}</div>
    </div>
    """


def get_logo_b64() -> str:
    """Carica e codifica il logo dell'applicazione in formato Base64."""
    base_dir = os.path.dirname(__file__)
    for name in ["logo_icon.png", "logo.png"]:
        path = os.path.join(base_dir, name)
        if os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    return base64.b64encode(f.read()).decode()
            except Exception:
                pass
    return ""


# ==============================================================================
# TABELLA RENDIMENTI MENSILI (ISTITUZIONALE)
# ==============================================================================
def render_monthly_returns_html_table(df_eq: Optional[pd.DataFrame]) -> str:
    """Genera la matrice istituzionale completa dei rendimenti mensili e annuali."""
    if df_eq is None or df_eq.empty:
        return ""
    df = df_eq.copy()
    years = sorted(df.index.year.unique(), reverse=True)
    months = list(range(1, 13))

    th_cells = [f'<th style="padding:8px 10px; font-weight:600; color:{MUTED}; font-size:11px; text-align:left; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">Anno</th>']
    for m_name in MESI_IT:
        th_cells.append(f'<th style="padding:8px 8px; font-weight:600; color:{MUTED}; font-size:11px; text-align:right; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">{m_name}</th>')
    th_cells.append(f'<th style="padding:8px 12px; font-weight:700; color:{ACCENT}; font-size:11px; text-align:right; text-transform:uppercase; border-bottom:1px solid {BORDER_STRONG}; border-left:1px solid {BORDER_STRONG}; position:sticky; top:0; background:#141210; z-index:2;">Tot Anno</th>')

    rows_html = []
    for y in years:
        td_cells = [f'<td style="padding:8px 10px; font-size:12px; font-weight:700; color:{BADGE_TEXT}; font-family:{MONO};">{y}</td>']
        df_y = df[df.index.year == y]
        df_prev = df[df.index.year < y]
        y_start_val = df_prev["value"].iloc[-1] if not df_prev.empty else df_y["value"].iloc[0]
        y_end_val = df_y["value"].iloc[-1]
        y_ret = ((y_end_val / y_start_val) - 1.0) * 100.0 if y_start_val > 0 else 0.0

        for m in months:
            df_ym = df[(df.index.year == y) & (df.index.month == m)]
            if df_ym.empty:
                td_cells.append(f'<td style="padding:8px 8px; font-size:11.5px; text-align:center; color:{MUTED}; font-family:{MONO}; opacity:0.4;">—</td>')
            else:
                df_before = df[df.index < df_ym.index[0]]
                m_start_val = df_before["value"].iloc[-1] if not df_before.empty else df_ym["value"].iloc[0]
                m_end_val = df_ym["value"].iloc[-1]
                m_ret = ((m_end_val / m_start_val) - 1.0) * 100.0 if m_start_val > 0 else 0.0

                col = POS if m_ret > 0 else NEG if m_ret < 0 else MUTED
                bg = "rgba(61,220,151,0.07)" if m_ret > 0 else "rgba(236,101,123,0.08)" if m_ret < 0 else "transparent"
                td_cells.append(f'<td style="padding:8px 8px; font-size:11.5px; text-align:right; font-family:{MONO}; font-weight:600; color:{col}; background:{bg}; white-space:nowrap;">{m_ret:+.1f}%</td>')

        y_col = POS if y_ret > 0 else NEG if y_ret < 0 else MUTED
        y_bg = "rgba(61,220,151,0.12)" if y_ret > 0 else "rgba(236,101,123,0.12)" if y_ret < 0 else "transparent"
        td_cells.append(f'<td style="padding:8px 12px; font-size:12px; text-align:right; font-family:{MONO}; font-weight:700; color:{y_col}; background:{y_bg}; border-left:1px solid {BORDER_STRONG}; white-space:nowrap;">{y_ret:+.1f}%</td>')
        rows_html.append(f'<tr style="border-bottom:1px solid {BORDER}; transition:background 0.15s ease;">{"".join(td_cells)}</tr>')

    return f'<div style="width:100%; overflow-x:auto; border:1px solid {BORDER}; border-radius:8px; background:rgba(255,247,237,0.02); margin-bottom:22px;"><table style="width:100%; border-collapse:collapse; text-align:left;"><thead><tr>{"".join(th_cells)}</tr></thead><tbody>{"".join(rows_html)}</tbody></table></div>'
