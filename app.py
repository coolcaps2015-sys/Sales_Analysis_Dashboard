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

from pathlib import Path

import streamlit as st
import pandas as pd

from modules.data_loader import load_sales_data
from modules.data_cleaner import clean_data


# Resolve asset paths relative to THIS FILE, not the current working
# directory - st.image()/page_icon paths are read relative to wherever
# `streamlit run` was launched from, which breaks if you run it from an
# IDE or a different folder. Anchoring to __file__ makes it launch-location-proof.
BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = BASE_DIR / "assets"
COOLCAPS_LOGO = ASSETS_DIR / "coolcaps_logo.png"
PURV_LOGO = ASSETS_DIR / "purv_group_logo.png"

st.set_page_config(
    page_title="Sales Performance Dashboard",
    page_icon=str(COOLCAPS_LOGO) if COOLCAPS_LOGO.exists() else "📊",
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
        if COOLCAPS_LOGO.exists():
            st.image(str(COOLCAPS_LOGO), width=120)
        else:
            st.markdown("**Cool Caps Industries**")
    with logo_col2:
        if PURV_LOGO.exists():
            st.image(str(PURV_LOGO), width=120)
        else:
            st.markdown("**PURV Group**")
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

if "proceed" not in st.session_state:
    st.session_state.proceed = False

if not st.session_state.proceed:
    if st.button("Proceed to Dashboard", type="primary"):
        st.session_state.proceed = True
        st.rerun()
    st.stop()


# ---------------------------------------------------------------------------
# Sidebar: page navigation + global date filter
# ---------------------------------------------------------------------------

full_df = clean_result.dataframe

with st.sidebar:
    st.markdown("### Dashboard Pages")
    page = st.radio(
        "Navigate",
        [
            "Executive Overview",
            "Customer Analysis (coming soon)",
            "Geographic Analysis (coming soon)",
            "Sales & Operations (coming soon)",
            "Data Explorer (coming soon)",
        ],
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown("### Filters")

    valid_dates = full_df.loc[full_df["date"].notna(), "date"]
    min_date, max_date = valid_dates.min().date(), valid_dates.max().date()
    date_range = st.date_input(
        "Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date
    )

    if st.button("Reset Filters"):
        st.rerun()

# Apply the global date filter once, upstream of every page.
if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
    mask = full_df["date"].between(pd.Timestamp(start_date), pd.Timestamp(end_date)) | full_df["date"].isna()
    df = full_df[mask]
else:
    df = full_df

theme = LIGHT_THEME if st.session_state.theme_mode == "Light" else DARK_THEME


# ---------------------------------------------------------------------------
# KPI card helper
# ---------------------------------------------------------------------------

def kpi_card(label: str, value: str) -> str:
    return f'<div class="kpi-card"><div class="kpi-label">{label}</div><div class="kpi-value">{value}</div></div>'


def insight_line(text: str) -> None:
    st.markdown(f'<div class="insight-box">{text}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Page 1: Executive Overview
# ---------------------------------------------------------------------------

if page == "Executive Overview":
    from modules import calculations as calc, customer_analysis as ca, geographic_analysis as geo, charts
    from modules.utils import format_inr_short, format_pct

    st.markdown("## Sales Performance Dashboard")
    fy_list = clean_result.quality.financial_years
    fy_caption = fy_list[0] if len(fy_list) == 1 else (
        f"{fy_list[0]} to {fy_list[-1]}" if fy_list else "period"
    )
    st.caption(f"Dynamic analysis generated from uploaded sales data — {fy_caption}")

    # --- KPI cards ---------------------------------------------------------
    k = calc.compute_headline_kpis(df)
    kpi_cols = st.columns(4 if not k.quantity_available else 6)
    kpi_cols[0].markdown(kpi_card("Total Sales", format_inr_short(k.total_sales)), unsafe_allow_html=True)
    kpi_cols[1].markdown(kpi_card("Total Invoices", f"{k.total_invoices:,}"), unsafe_allow_html=True)
    kpi_cols[2].markdown(kpi_card("Total Customers", f"{k.total_customers:,}"), unsafe_allow_html=True)
    kpi_cols[3].markdown(kpi_card("Avg Invoice Value", format_inr_short(k.avg_invoice_value)), unsafe_allow_html=True)
    if k.quantity_available:
        kpi_cols[4].markdown(kpi_card("Total Quantity", f"{k.total_quantity:,.0f}"), unsafe_allow_html=True)
        kpi_cols[5].markdown(kpi_card("Avg Selling Rate", f"₹{k.avg_selling_rate:.2f}"), unsafe_allow_html=True)

    st.write("")

    # --- Monthly sales analysis ---------------------------------------------
    st.markdown("### Monthly Sales Analysis")
    metric_choice = st.radio(
        "Metric", ["Sales", "Invoices", "Customers"], horizontal=True, label_visibility="collapsed"
    )
    monthly = calc.monthly_summary(df)
    fig = charts.monthly_trend_chart(monthly, metric_choice.lower(), theme)
    st.plotly_chart(fig, use_container_width=True)

    hl = calc.monthly_highlights(monthly)
    if hl.highest_month:
        growth_txt = (
            f" Sales moved {format_pct(hl.latest_mom_growth_pct)} month-over-month most recently."
            if hl.latest_mom_growth_pct is not None else ""
        )
        insight_line(
            f"📈 <b>{hl.highest_month}</b> was the strongest month at {format_inr_short(hl.highest_sales)}, "
            f"while <b>{hl.lowest_month}</b> was the softest at {format_inr_short(hl.lowest_sales)}.{growth_txt}"
        )

    st.write("")

    # --- H1 vs H2 ------------------------------------------------------------
    st.markdown("### First Half vs Second Half")
    h1h2 = calc.h1_h2_comparison(df)
    if h1h2.both_halves_present:
        fig = charts.h1_h2_chart(h1h2.h1_sales, h1h2.h2_sales, theme)
        st.plotly_chart(fig, use_container_width=True)
        direction = "grew" if (h1h2.h2_growth_pct or 0) >= 0 else "declined"
        insight_line(
            f"🔄 Second-half sales {direction} by {format_pct(abs(h1h2.h2_growth_pct) if h1h2.h2_growth_pct else None)} "
            f"compared to the first half."
        )
    else:
        st.info("Not enough date coverage yet to compare first-half vs second-half sales.")

    st.write("")

    # --- Top customers ---------------------------------------------------
    st.markdown("### Top Customers")
    top_n = st.select_slider("Show top", options=[5, 10, 20, 50], value=10)
    top_cust = ca.top_customers(df, top_n)
    fig = charts.top_customers_chart(top_cust, theme)
    st.plotly_chart(fig, use_container_width=True)
    if not top_cust.empty:
        insight_line(
            f"🏆 Your top {top_n} customers contribute {format_pct(top_cust['sales_pct'].sum())} of total sales."
        )

    st.write("")

    # --- Customer concentration (Pareto) --------------------------------
    st.markdown("### Customer Concentration")
    pareto = ca.pareto_analysis(df)
    fig = charts.pareto_chart(pareto.table, theme=theme)
    st.plotly_chart(fig, use_container_width=True)
    if not pareto.table.empty:
        insight_line(
            f"⚖️ Top 10 customers = {format_pct(pareto.top10_contribution_pct)} of revenue, "
            f"top 20 = {format_pct(pareto.top20_contribution_pct)}. "
            f"{'Revenue is fairly concentrated — worth strengthening key-account retention.' if pareto.top10_contribution_pct > 50 else 'Revenue is reasonably spread across your customer base.'}"
        )

    st.write("")

    # --- Geographic snapshot ----------------------------------------------
    st.markdown("### Geographic Sales Snapshot")
    if geo.geographic_data_available(df):
        states = geo.sales_by_state(df)
        fig = charts.state_sales_chart(states, top_n=10, theme=theme)
        st.plotly_chart(fig, use_container_width=True)
        top_state = states.iloc[0]
        insight_line(
            f"📍 <b>{top_state['state']}</b> is your largest market at {format_pct(top_state['sales_pct'])} of total sales."
        )
    else:
        st.info("Geographic analysis unavailable because GSTIN data was not detected in this file.")

else:
    st.info("This page is coming in the next build step — stay tuned.")