"""
ui.styles — All custom CSS for the Reconciliation Copilot dashboard.

Extracted from app.py so the main application file stays focused on
layout orchestration and the CSS can be reviewed/maintained independently.

The Streamlit theme in .streamlit/config.toml handles:
    primaryColor      = #0E5C4A   (accent: buttons, checkboxes, sliders, focus rings)
    backgroundColor   = #F5F4F0   (main background)
    secondaryBackgroundColor = #EDECEA  (sidebar background)
    textColor          = #14181F   (default text)

This file only contains rules that config.toml *cannot* express.
"""

from __future__ import annotations

import streamlit as st

# ── Design tokens ────────────────────────────────────────────────────────
# Centralised so every rule references the same value.
_BG       = "#F5F4F0"
_SURFACE  = "#FFFFFF"
_BORDER   = "#E4E2DA"
_BORDER_L = "#E3E0D8"
_BORDER_D = "#DDD9D1"
_MUTED    = "#6B6558"
_TEXT     = "#14181F"
_ACCENT   = "#0E5C4A"
_GREEN    = "#1B7A43"
_RED      = "#B3261E"
_AMBER    = "#B5650D"


def inject_css() -> None:
    """Inject all custom CSS into the Streamlit page."""
    st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600&display=swap');

    /* ── Base ─────────────────────────────────────────────── */
    html, body {{
        font-family: 'Inter', sans-serif;
    }}
    /* Apply Inter to text elements but avoid breaking Streamlit's icon spans */
    p, h1, h2, h3, h4, h5, h6, li, label {{
        font-family: 'Inter', sans-serif;
    }}
    .block-container {{
        max-width: min(1060px, 100%);
        padding: 1.5rem clamp(1rem, 3vw, 2rem) 4rem;
    }}

    /* ── Sidebar ──────────────────────────────────────────── */
    section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3 {{
        font-family: 'Source Serif 4', 'Georgia', serif !important;
        color: {_TEXT} !important;
    }}
    .sb-lbl {{
        font-family: 'Inter', sans-serif;
        font-size: 0.62rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: {_MUTED} !important;
        margin: 16px 0 5px;
    }}
    .sb-file {{
        background: {_SURFACE};
        border: 1px solid {_BORDER_D};
        border-radius: 4px;
        padding: 7px 10px;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.78rem;
        color: {_TEXT} !important;
        margin-bottom: 2px;
    }}

    /* ── Letterhead ───────────────────────────────────────── */
    .lh {{
        padding: 24px 0 20px;
        margin-bottom: 24px;
        border-bottom: 1px solid {_BORDER_L};
        display: flex;
        align-items: flex-start;
        gap: 12px;
    }}
    .lh-toggle {{
        background: none;
        border: 1px solid {_BORDER};
        border-radius: 6px;
        width: 38px;
        height: 38px;
        min-width: 38px;
        display: flex;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        color: {_MUTED};
        font-size: 1.3rem;
        transition: background 0.15s, color 0.15s, border-color 0.15s;
        margin-top: 2px;
    }}
    .lh-toggle:hover {{
        background: {_BORDER_L};
        color: {_TEXT};
        border-color: {_ACCENT};
    }}
    .lh-text {{
        flex: 1;
    }}
    .lh-title {{
        font-family: 'Source Serif 4', 'Georgia', serif;
        font-size: 36px !important;
        font-weight: 700;
        color: {_TEXT} !important;
        letter-spacing: -0.01em;
        margin: 0;
        line-height: 1.2;
    }}
    .lh-sub {{
        font-family: 'Inter', sans-serif;
        font-size: 0.85rem;
        color: {_MUTED} !important;
        margin-top: 6px;
    }}

    /* Hide Streamlit's native sidebar toggle buttons so the sidebar
       remains permanently open with no ability to collapse it. */
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapseButton"],
    section[data-testid="stSidebar"] button[kind="header"] {{
        display: none !important;
    }}

    /* Force the sidebar to always be expanded, overriding any collapsed
       state that Streamlit might have saved in the browser's localStorage */
    section[data-testid="stSidebar"] {{
        transform: none !important;
        transform: translateX(0) !important;
        margin-left: 0 !important;
        visibility: visible !important;
        width: 21rem !important;
        min-width: 21rem !important;
        max-width: 21rem !important;
        display: block !important;
    }}

    /* ── Stats row — card surfaces with accent borders ───── */
    .stats {{
        display: flex;
        flex-wrap: wrap;
        gap: 12px;
        margin-bottom: 24px;
    }}
    .stats-cell {{
        flex: 1 1 140px;
        min-width: 0;
        background: {_SURFACE};
        border: 1px solid {_BORDER};
        border-radius: 8px;
        padding: 16px 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
        border-left: 3px solid #C8C4BA;
        overflow: hidden;
    }}
    .stats-cell:nth-child(2) {{ border-left-color: {_GREEN}; }}
    .stats-cell:nth-child(3) {{ border-left-color: {_RED}; }}
    .stats-cell:nth-child(4) {{ border-left-color: {_ACCENT}; }}
    .stats-label {{
        font-family: 'Inter', sans-serif;
        font-size: 0.65rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: {_MUTED} !important;
        margin-bottom: 4px;
        white-space: nowrap;
    }}
    .stats-num {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: clamp(1.3rem, 2.5vw, 1.75rem);
        font-weight: 600;
        color: {_TEXT} !important;
        line-height: 1.2;
    }}

    /* ── Tabs ─────────────────────────────────────────────── */
    .stTabs [data-baseweb="tab-list"] {{
        gap: 0;
        background: transparent;
        border-bottom: 1px solid {_BORDER_L};
        padding: 0;
        border-radius: 0;
    }}
    .stTabs [data-baseweb="tab"] {{
        border-radius: 0;
        padding: 8px 18px 10px;
        font-family: 'Inter', sans-serif;
        font-weight: 600;
        font-size: 0.72rem;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: {_MUTED} !important;
        border-bottom: none !important;
    }}
    .stTabs [aria-selected="true"] {{
        background: transparent !important;
        color: {_TEXT} !important;
        border-bottom: none !important;
        box-shadow: none;
    }}
    /* Tab highlight — now that primaryColor is #0E5C4A the default
       indicator is green.  We override to black for a cleaner look. */
    div.stTabs div[data-baseweb="tab-highlight"] {{
        background-color: #000000 !important;
        height: 2px !important;
    }}
    div.stTabs div[data-baseweb="tab-border"] {{
        background-color: {_BORDER_L} !important;
    }}

    /* ── Mismatch card ────────────────────────────────────── */
    .mx {{
        background: {_SURFACE};
        border: 1px solid {_BORDER};
        border-radius: 8px;
        padding: 24px 28px;
        margin-bottom: 16px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }}
    .mx-head {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 20px;
        flex-wrap: wrap;
        gap: 10px;
    }}
    .mx-bid {{
        font-family: 'IBM Plex Mono', monospace;
        font-weight: 700;
        font-size: 1.05rem;
        color: {_TEXT} !important;
        flex-shrink: 0;
    }}
    .mx-tags {{
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        align-items: center;
    }}

    /* Tags */
    .tag {{
        font-family: 'Inter', sans-serif;
        font-size: 0.62rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        padding: 3px 10px;
        border-radius: 4px;
        white-space: nowrap;
        line-height: 18px;
        display: inline-flex;
        align-items: center;
    }}
    .tag-delta  {{ color: {_ACCENT} !important; background: #E8F3EE; }}
    .tag-review {{ color: {_AMBER} !important; background: #FDF2E0; }}
    .tag-conf   {{ color: {_MUTED} !important; background: #F0EFEC; }}

    /* Metrics row */
    .mx-metrics {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
        gap: 12px 0;
        margin-bottom: 20px;
    }}
    .mx-m-lbl {{
        font-family: 'Inter', sans-serif;
        font-size: 0.58rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: {_MUTED} !important;
        margin-bottom: 2px;
    }}
    .mx-m-val {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.92rem;
        font-weight: 500;
        color: {_TEXT} !important;
    }}

    /* Confidence bar */
    .conf-inline {{
        display: flex;
        align-items: center;
        gap: 8px;
    }}
    .conf-pct {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.92rem;
        font-weight: 500;
        color: {_TEXT} !important;
        white-space: nowrap;
    }}
    .conf-track {{
        flex: 1;
        background: #E8E6E0;
        border-radius: 4px;
        height: 8px;
        overflow: hidden;
        min-width: 60px;
    }}
    .conf-fill {{
        height: 100%;
        border-radius: 4px;
    }}

    /* Explanation block */
    .mx-expl {{
        background: #F7FAF8;
        border-left: 4px solid {_ACCENT};
        border-radius: 0 4px 4px 0;
        padding: 14px 18px;
        font-family: 'Inter', sans-serif;
        font-size: 0.82rem;
        line-height: 1.6;
        color: #2A2A2A !important;
    }}

    /* Fee sub-table */
    .mx-fees {{
        margin-top: 16px;
        padding: 14px;
        background: #F9F8F6;
        border-radius: 6px;
    }}
    .mx-fees-lbl {{
        font-family: 'Inter', sans-serif;
        font-size: 0.58rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        color: {_MUTED} !important;
        margin-bottom: 6px;
    }}

    /* ── Resolved / Ledger table ──────────────────────────── */
    .ltbl {{
        width: 100%;
        border-collapse: collapse;
        font-size: 0.82rem;
    }}
    .ltbl thead th {{
        text-align: left;
        padding: 8px 12px;
        font-family: 'Inter', sans-serif;
        font-weight: 600;
        font-size: 0.62rem;
        color: {_MUTED} !important;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        border-bottom: 2px solid #C8C4BA;
    }}
    .ltbl thead th.r {{ text-align: right; }}
    .ltbl tbody td {{
        padding: 10px 12px;
        color: {_TEXT} !important;
        border-bottom: 1px solid {_BORDER_L};
        font-family: 'Inter', sans-serif;
    }}
    .ltbl tbody tr:last-child td {{ border-bottom: none; }}
    .ltbl tbody tr:hover td {{ background: #F5F3EE; }}
    .ltbl tbody tr {{ transition: background 0.12s ease; }}
    .ltbl tbody td.m {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.8rem;
        text-align: right;
        font-weight: 500;
        font-variant-numeric: tabular-nums;
    }}
    .ltbl tbody td.ml {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.8rem;
        font-weight: 500;
    }}

    /* ── Status pills ────────────────────────────────────── */
    .st-pill {{
        display: inline-flex;
        align-items: center;
        padding: 3px 10px;
        border-radius: 4px;
        font-family: 'Inter', sans-serif;
        font-size: 0.6rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        line-height: 18px;
    }}
    .st-pill-green {{ background: #E4F2E8; color: {_GREEN} !important; }}
    .st-pill-amber {{ background: #FDF2E0; color: {_AMBER} !important; }}
    .st-pill-red   {{ background: #FBEAE9; color: {_RED} !important; }}

    /* ── Section labels ───────────────────────────────────── */
    .sec-lbl {{
        font-family: 'Inter', sans-serif;
        font-size: 0.6rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        color: {_MUTED} !important;
        margin-bottom: 6px;
    }}
    .sec-title {{
        font-family: 'Source Serif 4', serif;
        font-size: 1.05rem;
        font-weight: 600;
        color: {_TEXT} !important;
        margin-bottom: 2px;
    }}
    .sec-desc {{
        font-family: 'Inter', sans-serif;
        font-size: 0.76rem;
        color: {_MUTED} !important;
        margin-bottom: 14px;
    }}

    /* ── Empty state ──────────────────────────────────────── */
    .empty {{
        text-align: center;
        padding: 56px 32px;
        background: {_SURFACE};
        border: 1px solid {_BORDER};
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }}
    .empty-icon {{
        font-size: 2.5rem;
        margin-bottom: 12px;
        display: block;
    }}
    .empty-title {{
        font-family: 'Source Serif 4', serif;
        font-size: 1.15rem;
        font-weight: 600;
        color: {_TEXT} !important;
        margin-bottom: 8px;
    }}
    .empty-desc {{
        font-family: 'Inter', sans-serif;
        font-size: 0.82rem;
        color: {_MUTED} !important;
        max-width: 420px;
        margin: 0 auto;
        line-height: 1.6;
    }}

    /* ── How-it-works strip ───────────────────────────────── */
    .hiw {{
        display: flex;
        gap: 0;
        background: {_SURFACE};
        border: 1px solid {_BORDER};
        border-radius: 8px;
        overflow: hidden;
        margin-top: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }}
    .hiw-s {{
        flex: 1;
        padding: 18px 14px;
        text-align: center;
        border-right: 1px solid {_BORDER};
        position: relative;
    }}
    .hiw-s:last-child {{ border-right: none; }}
    .hiw-n {{
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.65rem;
        font-weight: 600;
        color: {_ACCENT} !important;
        margin-bottom: 3px;
        width: 24px;
        height: 24px;
        line-height: 24px;
        border-radius: 50%;
        background: #E8F3EE;
        display: inline-block;
    }}
    .hiw-l {{
        font-family: 'Inter', sans-serif;
        font-size: 0.72rem;
        font-weight: 600;
        color: {_TEXT} !important;
        margin-top: 4px;
    }}

    /* ── Buttons ──────────────────────────────────────────── */
    .stButton > button {{
        background: {_ACCENT};
        color: #FFFFFF !important;
        border: none;
        border-radius: 6px;
        padding: 0.65rem 1.4rem;
        font-family: 'Inter', sans-serif;
        font-weight: 600;
        font-size: 0.85rem;
        transition: background 0.15s, box-shadow 0.15s;
        width: 100%;
        box-shadow: 0 1px 3px rgba(14,92,74,0.2);
    }}
    .stButton > button:hover {{
        background: #0A4A3B;
        box-shadow: 0 2px 6px rgba(14,92,74,0.3);
    }}

    /* ── Expanders ────────────────────────────────────────── */
    details[data-testid="stExpander"] {{
        background: #FAFAF8;
        border: 1px solid {_BORDER};
        border-radius: 6px;
        margin-bottom: 8px;
        overflow: hidden;
    }}
    details[data-testid="stExpander"] summary {{
        cursor: pointer;
    }}

    /* ── Material Symbols icon restoration ───────────────── */
    /* Streamlit uses icon ligature spans (class e1a0jn2t0) that
       rely on font-family: "Material Symbols Rounded".  Our global
       html,body {{ font-family: Inter }} cascades down and overrides
       the Emotion-injected font.  The font IS loaded (verified via
       document.fonts.check), so we just need to re-apply it on the
       specific icon elements.  They have no stable class, so we
       target them structurally. */

    /* Expander arrow icons — inside summary > span > span:first-child > span */
    details[data-testid="stExpander"] summary > span > span:first-child,
    details[data-testid="stExpander"] summary > span > span:first-child > span {{
        font-family: 'Material Symbols Rounded' !important;
    }}

    /* Sidebar toggle button icons */
    [data-testid="stSidebarCollapsedControl"] button > span,
    [data-testid="collapsedControl"] button > span,
    section[data-testid="stSidebar"] button[kind="header"] > span {{
        font-family: 'Material Symbols Rounded' !important;
    }}

    /* ── Inputs ───────────────────────────────────────────── */
    /* With primaryColor set in config.toml, Streamlit now uses
       green for focus rings natively.  We only style the border
       appearance and font here. */
    div.stTextInput div[data-baseweb="input"] {{
        background: {_SURFACE} !important;
        border: 1px solid {_BORDER_D} !important;
        border-radius: 6px !important;
    }}
    div.stTextInput div[data-baseweb="input"] input {{
        padding: 8px 12px;
        font-family: 'Inter', sans-serif;
        font-size: 0.82rem;
        color: {_TEXT};
        background: transparent !important;
    }}

    /* Password toggle icon fix */
    .stTextInput [data-baseweb="input"] {{
        display: flex !important;
        align-items: center !important;
    }}
    .stTextInput [data-baseweb="input"] > div:last-child {{
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        flex-shrink: 0 !important;
        padding: 0 8px !important;
    }}
    button[aria-label="Show password"],
    button[aria-label="Hide password"] {{
        font-size: 0 !important;
        color: transparent !important;
        width: 36px !important;
        height: 36px !important;
        min-width: 36px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        overflow: hidden !important;
        padding: 0 !important;
        background: transparent !important;
        border: none !important;
        position: relative !important;
        cursor: pointer !important;
    }}
    button[aria-label="Show password"]::after,
    button[aria-label="Hide password"]::after {{
        content: "\\1F441";
        font-size: 1rem;
        color: {_MUTED};
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
    }}
    button[aria-label="Show password"] span,
    button[aria-label="Hide password"] span,
    button[aria-label="Show password"] span span,
    button[aria-label="Hide password"] span span {{
        font-size: 0 !important;
        color: transparent !important;
        width: 0 !important;
        height: 0 !important;
        overflow: hidden !important;
        position: absolute !important;
        clip: rect(0,0,0,0) !important;
    }}

    /* File uploader */
    [data-testid="stFileUploader"] {{
        background: {_SURFACE};
        border-radius: 6px;
        border: 1px dashed #C8C4BA;
        padding: 8px;
    }}
    .stCheckbox label span {{ color: {_TEXT} !important; }}

    /* Slider tick bar always visible */
    .stSlider div[data-testid="stTickBar"] {{
        opacity: 1 !important;
        visibility: visible !important;
    }}
    .stSlider div[data-testid="stSliderTickBar"] {{
        opacity: 1 !important;
        visibility: visible !important;
    }}

    /* ── Misc ─────────────────────────────────────────────── */
    hr {{ border: none; border-top: 1px solid {_BORDER_L}; margin: 0.8rem 0; }}
    .stDataFrame {{ border-radius: 4px; overflow: hidden; }}

    /* ── Hide Streamlit chrome ────────────────────────────── */
    #MainMenu {{ visibility: hidden; }}
    footer {{ visibility: hidden; }}
    .stDeployButton {{ display: none !important; }}
    .stAppDeployButton {{ display: none !important; }}
    [data-testid="stToolbar"] {{ display: none !important; }}

    /* ── Header bar ──────────────────────────────────────── */
    header[data-testid="stHeader"] {{
        background: transparent !important;
        backdrop-filter: none !important;
    }}
    div[data-testid="stDecoration"] {{ display: none !important; }}
    div[data-testid="stStatusWidget"] {{ display: none !important; }}

    /* ── Sidebar alignment ───────────────────────────────── */
    section[data-testid="stSidebar"] > div:first-child {{
        padding-top: 1.5rem;
        padding-left: 1.2rem;
        padding-right: 1.2rem;
    }}
    section[data-testid="stSidebar"] .block-container {{
        padding: 0;
    }}
    section[data-testid="stSidebar"] [data-testid="stSidebarContent"] {{
        padding-top: 1.5rem;
        padding-left: 1.2rem;
        padding-right: 1.2rem;
    }}
    .stApp .main .block-container {{
        padding-top: 1.5rem;
    }}

    /* ── Responsive ──────────────────────────────────────── */
    @media (max-width: 768px) {{
        .stats {{
            flex-direction: column;
            gap: 10px;
        }}
        .stats-cell {{
            flex: 1 1 100%;
        }}
        .mx-head {{
            flex-direction: column;
            align-items: flex-start;
        }}
        .mx-metrics {{
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }}
        .hiw {{
            flex-direction: column;
        }}
        .hiw-s {{
            border-right: none !important;
            border-bottom: 1px solid {_BORDER};
        }}
        .hiw-s:last-child {{ border-bottom: none; }}
        .ltbl {{ font-size: 0.75rem; }}
        .ltbl thead th, .ltbl tbody td {{ padding: 8px 6px; }}
    }}
    @media (max-width: 480px) {{
        .mx-metrics {{
            grid-template-columns: 1fr;
        }}
        .block-container {{
            padding: 1rem 0.75rem 3rem;
        }}
        .mx {{
            padding: 16px;
        }}
        .stats-num {{
            font-size: 1.3rem;
        }}
    }}
    </style>
    """, unsafe_allow_html=True)
