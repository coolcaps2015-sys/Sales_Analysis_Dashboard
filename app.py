"""
app.py
------
Entry point for the Sales Analytics Dashboard.

This build establishes the app shell: page config, light/dark theme toggle,
the dual-logo header, and Page 0 (upload -> validate -> data quality report)
wired to the real data_loader / data_cleaner pipeline. The five analysis
pages (Executive Overview, Customer Analysis, Geographic Analysis, Sales &
Operations, Data Explorer) get added on top of this shell next.
"""

from __future__ import annotations

import streamlit as st
import pandas as pd

from modules.data_loader import load_sales_data
from modules.data_cleaner import clean_data


st.set_page_config(
    page_title="Sales Performance Dashboard",
    page_icon="assets/coolcaps_logo.png",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Theme handling
# ---------------------------------------------------------------------------
# Streamlit's built-in theme is fixed at server start via config.toml, so a
# true runtime toggle is done with a CSS override injected on every rerun.
# session_state holds the current choice so it persists across interactions.

LIGHT_THEME = {
    "bg": "#FFFFFF",
    "card_bg": "#F7F8FA",
    "text": "#1A1A2E",
    "subtext": "#5A5A72",
    "border": "#E4E6EB",
    "accent": "#6C63FF",
}

DARK_THEME = {
    "bg": "#0E1117",
    "card_bg": "#1A1D27",
    "text": "#F5F5F7",
    "subtext": "#A0A0B2",
    "border": "#2A2D3A",
    "accent": "#8B85FF",
}

if "theme_mode" not in st.session_state:
    st.session_state.theme_mode = "Light"


def inject_theme_css(mode: str) -> None:
    colors = LIGHT_THEME if mode == "Light" else DARK_THEME
    st.markdown(
        f"""
        <style>
        .stApp {{
            background-color: {colors['bg']};
            color: {colors['text']};
        }}
        section[data-testid="stSidebar"] {{
            background-color: {colors['card_bg']};
            border-right: 1px solid {colors['border']};
        }}
        .kpi-card {{
            background-color: {colors['card_bg']};
            border: 1px solid {colors['border']};
            border-radius: 12px;
            padding: 18px 20px;
            text-align: left;
        }}
        .kpi-label {{
            color: {colors['subtext']};
            font-size: 0.85rem;
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }}
        .kpi-value {{
            color: {colors['text']};
            font-size: 1.6rem;
            font-weight: 700;
            margin-top: 4px;
        }}
        .app-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 10px 0 18px 0;
            border-bottom: 1px solid {colors['border']};
            margin-bottom: 20px;
        }}
        .app-title {{
            color: {colors['text']};
            font-size: 1.4rem;
            font-weight: 700;
            margin: 0;
        }}
        .app-subtitle {{
            color: {colors['subtext']};
            font-size: 0.9rem;
            margin: 0;
        }}
        .insight-box {{
            background-color: {colors['card_bg']};
            border-left: 4px solid {colors['accent']};
            border-radius: 6px;
            padding: 12px 16px;
            margin: 6px 0;
            color: {colors['text']};
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_theme_css(st.session_state.theme_mode)


# ---------------------------------------------------------------------------
# Header: both logos + title, theme toggle in the sidebar
# ---------------------------------------------------------------------------

header_left, header_right = st.columns([4, 1])

with header_left:
    logo_col1, logo_col2, title_col = st.columns([1, 1, 4])
    with logo_col1:
        st.image("assets/coolcaps_logo.png", width=120)
    with logo_col2:
        st.image("assets/purv_group_logo.png", width=120)
    with title_col:
        st.markdown(
            """
            <div>
                <p class="app-title">Sales Performance Dashboard</p>
                <p class="app-subtitle">Dynamic analysis generated from uploaded sales data</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

with st.sidebar:
    st.markdown("### Settings")
    st.session_state.theme_mode = st.radio(
        "Appearance", ["Light", "Dark"],
        index=0 if st.session_state.theme_mode == "Light" else 1,
        horizontal=True,
    )
    st.divider()


# ---------------------------------------------------------------------------
# Cached loading + cleaning (re-runs only when the uploaded file changes)
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Reading Excel file...")
def cached_load_and_clean(file_bytes: bytes, file_name: str):
    import io
    load_result = load_sales_data(io.BytesIO(file_bytes))
    clean_result = clean_data(load_result)
    return load_result, clean_result


# ---------------------------------------------------------------------------
# Page 0: Upload + Validation
# ---------------------------------------------------------------------------

st.markdown("## Upload Sales Data")
st.caption("Upload your Excel sales file to generate the dashboard.")

uploaded_file = st.file_uploader("Excel file (.xlsx)", type=["xlsx"], label_visibility="collapsed")

if uploaded_file is None:
    st.info("Waiting for a file to be uploaded.")
    st.stop()

file_bytes = uploaded_file.getvalue()
load_result, clean_result = cached_load_and_clean(file_bytes, uploaded_file.name)

if not load_result.is_valid:
    st.error(
        f"Could not build a dashboard from this file. Missing required column(s): "
        f"{', '.join(load_result.missing_required)}. "
        "A valid Date column and a valid Sales Value column are both required."
    )
    st.stop()

st.success(f"Loaded sheet **{load_result.sheet_name}** — {clean_result.quality.total_rows:,} rows detected.")

with st.expander("Data Validation Details", expanded=False):
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Detected column mapping**")
        mapping_df = pd.DataFrame(
            [{"Source Column": k, "Mapped To": v} for k, v in load_result.column_mapping.items()]
        )
        st.dataframe(mapping_df, hide_index=True, use_container_width=True)
    with col2:
        st.markdown("**Data Quality Report**")
        q = clean_result.quality
        st.write(f"- Total rows: {q.total_rows:,}")
        st.write(f"- Valid transactions: {q.valid_transactions:,}")
        st.write(f"- Cancelled transactions: {q.cancelled_transactions:,}")
        st.write(f"- FOC transactions: {q.foc_transactions:,}")
        st.write(f"- Missing dates: {q.missing_dates:,}")
        st.write(f"- Missing customers: {q.missing_customers:,}")
        st.write(f"- Missing GSTIN: {q.missing_gstin:,}")
        st.write(f"- Invalid GSTINs: {q.invalid_gstins:,}")
        st.write(f"- Financial year(s) detected: {', '.join(q.financial_years) if q.financial_years else 'None'}")

    if clean_result.warnings:
        for w in clean_result.warnings:
            st.warning(w)

st.divider()
st.info(
    "Page shell complete — Executive Overview, Customer Analysis, Geographic "
    "Analysis, Sales & Operations, and Data Explorer pages get wired in next."
)