"""
app.py
------
Entry point for the Sales Analytics Dashboard.

Single fixed dark theme (no toggle - removed after feedback that the
runtime light/dark CSS-swap wasn't rendering smoothly on Streamlit's
native widgets). Header is text-only (company names, no logo images).

All five pages are wired to the real, tested modules:
  Page 0: Upload -> validate -> data quality report
  Page 1: Executive Overview
  Page 2: Customer Analysis
  Page 3: Geographic Analysis
  Page 4: Sales & Operations
  Page 5: Data Explorer
"""

from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import streamlit as st

from modules.data_loader import load_sales_data
from modules.data_cleaner import clean_data
from modules import calculations as calc
from modules import customer_analysis as ca
from modules import geographic_analysis as geo
from modules import charts
from modules.utils import format_inr_short, format_pct

BASE_DIR = Path(__file__).resolve().parent

st.set_page_config(
    page_title="Sales Performance Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Fixed dark theme
# ---------------------------------------------------------------------------

THEME = {
    "bg": "#0E1117",
    "card_bg": "#1A1D27",
    "text": "#F5F5F7",
    "subtext": "#A0A0B2",
    "border": "#2A2D3A",
    "accent": "#8B85FF",
}

st.markdown(
    f"""
    <style>
    .stApp {{
        background-color: {THEME['bg']};
        color: {THEME['text']};
    }}
    section[data-testid="stSidebar"] {{
        background-color: {THEME['card_bg']};
        border-right: 1px solid {THEME['border']};
    }}
    .kpi-card {{
        background-color: {THEME['card_bg']};
        border: 1px solid {THEME['border']};
        border-radius: 12px;
        padding: 18px 20px;
        text-align: left;
    }}
    .kpi-label {{
        color: {THEME['subtext']};
        font-size: 0.85rem;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.03em;
    }}
    .kpi-value {{
        color: {THEME['text']};
        font-size: 1.6rem;
        font-weight: 700;
        margin-top: 4px;
    }}
    .app-title {{
        color: {THEME['text']};
        font-size: 1.5rem;
        font-weight: 700;
        margin: 0;
    }}
    .app-subtitle {{
        color: {THEME['subtext']};
        font-size: 0.9rem;
        margin: 2px 0 0 0;
    }}
    .insight-box {{
        background-color: {THEME['card_bg']};
        border-left: 4px solid {THEME['accent']};
        border-radius: 6px;
        padding: 12px 16px;
        margin: 6px 0;
        color: {THEME['text']};
    }}
    .warning-box {{
        background-color: {THEME['card_bg']};
        border-left: 4px solid #FF6B6B;
        border-radius: 6px;
        padding: 12px 16px;
        margin: 6px 0;
        color: {THEME['text']};
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Header: text-only, both company names, no logo images
# ---------------------------------------------------------------------------

st.markdown(
    """
    <div style="padding: 10px 0 18px 0; border-bottom: 1px solid #2A2D3A; margin-bottom: 20px;">
        <p class="app-title">Cool Caps Industries &nbsp;·&nbsp; PURV Group</p>
        <p class="app-subtitle">Sales Performance Dashboard — dynamic analysis generated from uploaded sales data</p>
    </div>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------

def kpi_card(label: str, value: str) -> str:
    return f'<div class="kpi-card"><div class="kpi-label">{label}</div><div class="kpi-value">{value}</div></div>'


def insight_line(text: str) -> None:
    st.markdown(f'<div class="insight-box">{text}</div>', unsafe_allow_html=True)


def warning_line(text: str) -> None:
    st.markdown(f'<div class="warning-box">⚠️ {text}</div>', unsafe_allow_html=True)


def kpi_row(items: list[tuple[str, str]]) -> None:
    """items = [(label, value), ...] - renders as evenly-spaced KPI cards."""
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items):
        col.markdown(kpi_card(label, value), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Cached loading + cleaning
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Reading Excel file...")
def cached_load_and_clean(file_bytes: bytes, file_name: str):
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
# Sidebar: page navigation + global filters
# ---------------------------------------------------------------------------

full_df = clean_result.dataframe

with st.sidebar:
    st.markdown("### Dashboard Pages")
    page = st.radio(
        "Navigate",
        [
            "Executive Overview",
            "Customer Analysis",
            "Geographic Analysis",
            "Sales & Operations",
            "Data Explorer",
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

    customer_options = sorted(full_df["customer"].dropna().unique().tolist()) if "customer" in full_df.columns else []
    selected_customers = st.multiselect("Customer", customer_options, default=[])

    voucher_options = sorted(full_df["voucher_type"].dropna().unique().tolist()) if "voucher_type" in full_df.columns else []
    selected_vouchers = st.multiselect("Voucher Type", voucher_options, default=[])

    sale_type = st.radio("Sale Type", ["All", "Normal Sale Only", "FOC Only"], index=0)

    if st.button("Reset Filters"):
        for key in ["proceed"]:
            pass  # keep proceed state; just rerun to clear widget defaults
        st.rerun()

# --- Apply global filters once, upstream of every page ---------------------
df = full_df

if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
    date_mask = df["date"].between(pd.Timestamp(start_date), pd.Timestamp(end_date)) | df["date"].isna()
    df = df[date_mask]

if selected_customers:
    df = df[df["customer"].isin(selected_customers) | df["row_type"].ne("Transaction")]

if selected_vouchers:
    df = df[df["voucher_type"].isin(selected_vouchers) | df["row_type"].ne("Transaction")]

if sale_type == "Normal Sale Only":
    df = df[~df["is_foc"].fillna(False)]
elif sale_type == "FOC Only":
    df = df[df["is_foc"].fillna(False)]

theme = THEME


# ---------------------------------------------------------------------------
# Page 1: Executive Overview
# ---------------------------------------------------------------------------

def render_executive_overview(df: pd.DataFrame) -> None:
    st.markdown("## Executive Overview")
    fy_list = clean_result.quality.financial_years
    fy_caption = fy_list[0] if len(fy_list) == 1 else (f"{fy_list[0]} to {fy_list[-1]}" if fy_list else "period")
    st.caption(f"Dynamic analysis generated from uploaded sales data — {fy_caption}")

    k = calc.compute_headline_kpis(df)
    items = [
        ("Total Sales", format_inr_short(k.total_sales)),
        ("Total Invoices", f"{k.total_invoices:,}"),
        ("Total Customers", f"{k.total_customers:,}"),
        ("Avg Invoice Value", format_inr_short(k.avg_invoice_value)),
    ]
    if k.quantity_available:
        items.append(("Total Quantity", f"{k.total_quantity:,.0f}"))
        items.append(("Avg Selling Rate", f"₹{k.avg_selling_rate:.2f}"))
    kpi_row(items)

    st.write("")
    st.markdown("### Monthly Sales Analysis")
    metric_options = ["Sales", "Invoices", "Customers"] + (["Quantity"] if k.quantity_available else [])
    metric_choice = st.radio("Metric", metric_options, horizontal=True, label_visibility="collapsed", key="eo_metric")
    monthly = calc.monthly_summary(df)
    st.plotly_chart(charts.monthly_trend_chart(monthly, metric_choice.lower(), theme), use_container_width=True)

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
    st.markdown("### First Half vs Second Half")
    h1h2 = calc.h1_h2_comparison(df)
    if h1h2.both_halves_present:
        st.plotly_chart(charts.h1_h2_chart(h1h2.h1_sales, h1h2.h2_sales, theme), use_container_width=True)
        direction = "grew" if (h1h2.h2_growth_pct or 0) >= 0 else "declined"
        insight_line(
            f"🔄 Second-half sales {direction} by "
            f"{format_pct(abs(h1h2.h2_growth_pct) if h1h2.h2_growth_pct else None)} compared to the first half."
        )
    else:
        st.info("Not enough date coverage yet to compare first-half vs second-half sales.")

    st.write("")
    st.markdown("### Top Customers")
    top_n = st.select_slider("Show top", options=[5, 10, 20, 50], value=10, key="eo_topn")
    top_cust = ca.top_customers(df, top_n)
    st.plotly_chart(charts.top_customers_chart(top_cust, theme), use_container_width=True)
    if not top_cust.empty:
        insight_line(f"🏆 Your top {top_n} customers contribute {format_pct(top_cust['sales_pct'].sum())} of total sales.")

    st.write("")
    st.markdown("### Customer Concentration")
    pareto = ca.pareto_analysis(df)
    st.plotly_chart(charts.pareto_chart(pareto.table, theme=theme), use_container_width=True)
    if not pareto.table.empty:
        concentration_note = (
            "Revenue is fairly concentrated — worth strengthening key-account retention."
            if pareto.top10_contribution_pct > 50 else "Revenue is reasonably spread across your customer base."
        )
        insight_line(
            f"⚖️ Top 10 customers = {format_pct(pareto.top10_contribution_pct)} of revenue, "
            f"top 20 = {format_pct(pareto.top20_contribution_pct)}. {concentration_note}"
        )

    st.write("")
    st.markdown("### Geographic Sales Snapshot")
    if geo.geographic_data_available(df):
        states = geo.sales_by_state(df)
        st.plotly_chart(charts.state_sales_chart(states, top_n=10, theme=theme), use_container_width=True)
        top_state = states.iloc[0]
        insight_line(f"📍 <b>{top_state['state']}</b> is your largest market at {format_pct(top_state['sales_pct'])} of total sales.")
    else:
        st.info("Geographic analysis unavailable because GSTIN data was not detected in this file.")


# ---------------------------------------------------------------------------
# Page 2: Customer Analysis
# ---------------------------------------------------------------------------

def render_customer_analysis(df: pd.DataFrame) -> None:
    st.markdown("## Customer Analysis")
    st.caption("Segmentation, retention, and purchase-frequency intelligence.")

    ck = ca.customer_kpis(df)
    kpi_row([
        ("Total Customers", f"{ck.total_customers:,}"),
        ("New Customers", f"{ck.new_customers:,}"),
        ("Retained (H1→H2)", f"{ck.retained_customers:,}"),
        ("Inactive / Lost", f"{ck.inactive_customers:,}"),
        ("Top Customer", ck.top_customer if len(ck.top_customer) < 22 else ck.top_customer[:20] + "…"),
        ("Avg Customer Sales", format_inr_short(ck.avg_customer_sales)),
    ])

    st.write("")
    st.markdown("### Customer Segments")
    st.caption(
        "VIP = top 10% by sales · High Value = big spend, low frequency · Regular = frequent, consistent buyers · "
        "New = first purchase in the most recent half · At Risk / Inactive = active before, quiet since."
    )
    segmented = ca.segment_customers(df)
    if not segmented.empty:
        seg_counts = segmented["segment"].value_counts()
        st.plotly_chart(charts.segmentation_chart(seg_counts, theme), use_container_width=True)
        vip_sales_pct = (
            segmented.loc[segmented["segment"] == "VIP", "total_sales"].sum() / segmented["total_sales"].sum() * 100
            if segmented["total_sales"].sum() else 0
        )
        insight_line(
            f"👑 {int(seg_counts.get('VIP', 0))} VIP customers drive {format_pct(vip_sales_pct)} of total revenue. "
            f"{int(seg_counts.get('Inactive/Lost', 0))} customers are inactive/lost and may be worth re-engaging."
        )
    else:
        st.info("Not enough customer data to build segments.")

    st.write("")
    st.markdown("### Retention: H1 vs H2")
    retention = ca.h1_h2_retention(df)
    if not retention.table.empty:
        st.plotly_chart(
            charts.category_count_chart(retention.table, "category", "customer_count", "Customer Retention: H1 vs H2", theme=theme),
            use_container_width=True,
        )
        insight_line(
            f"🔁 {format_pct(retention.retention_rate_pct)} of H1 customers came back and purchased again in H2 "
            f"({retention.both_periods} of {retention.both_periods + retention.h1_only} H1 customers)."
        )
    else:
        st.info("Not enough date coverage yet to compare H1 vs H2 retention.")

    st.write("")
    st.markdown("### Purchase Frequency")
    freq = ca.frequency_distribution(df)
    if not freq.empty:
        st.plotly_chart(charts.frequency_distribution_chart(freq, theme), use_container_width=True)
        one_timers = int(freq.loc[freq["bucket"] == "1 invoice", "customer_count"].sum())
        insight_line(f"🧾 {one_timers} customers have purchased only once — a natural list to prioritize for follow-up.")


# ---------------------------------------------------------------------------
# Page 3: Geographic Analysis
# ---------------------------------------------------------------------------

def render_geographic_analysis(df: pd.DataFrame) -> None:
    st.markdown("## Geographic Analysis")
    st.caption("State-level performance, derived from customer GSTIN.")

    if not geo.geographic_data_available(df):
        st.info("Geographic analysis unavailable because GSTIN data was not detected in this file.")
        return

    states = geo.sales_by_state(df)
    st.markdown("### Sales by State")
    st.plotly_chart(charts.state_sales_chart(states, top_n=len(states), theme=theme), use_container_width=True)
    with st.expander("Full state table"):
        display_df = states.copy()
        display_df["sales"] = display_df["sales"].apply(format_inr_short)
        display_df["sales_pct"] = display_df["sales_pct"].apply(lambda v: format_pct(v))
        display_df["avg_invoice_value"] = display_df["avg_invoice_value"].apply(format_inr_short)
        st.dataframe(display_df, hide_index=True, use_container_width=True)

    top_state = states.iloc[0]
    insight_line(
        f"📍 <b>{top_state['state']}</b> leads at {format_pct(top_state['sales_pct'])} of sales, "
        f"across {int(top_state['customers'])} customers and {int(top_state['invoices'])} invoices."
    )

    st.write("")
    st.markdown("### State Drill-Down")
    all_states = geo.available_states(df)
    selected_state = st.selectbox("Select a state", all_states, index=0)
    dd = geo.state_drilldown(df, selected_state)

    kpi_row([
        ("Total Sales", format_inr_short(dd.total_sales)),
        ("Customers", f"{dd.customer_count:,}"),
        ("Invoices", f"{dd.invoice_count:,}"),
        ("Avg Invoice Value", format_inr_short(dd.avg_invoice_value)),
    ])

    st.write("")
    col1, col2 = st.columns(2)
    with col1:
        if not dd.monthly_trend.empty:
            st.plotly_chart(charts.monthly_trend_chart(dd.monthly_trend, "sales", theme), use_container_width=True)
    with col2:
        if not dd.top_customers.empty:
            st.plotly_chart(charts.top_customers_chart(dd.top_customers, theme), use_container_width=True)


# ---------------------------------------------------------------------------
# Page 4: Sales & Operations
# ---------------------------------------------------------------------------

def render_sales_operations(df: pd.DataFrame) -> None:
    st.markdown("## Sales & Operations")
    st.caption("Quantity, pricing, invoice distribution, cancellations, and FOC activity.")

    k = calc.compute_headline_kpis(df)

    if k.quantity_available:
        st.markdown("### Quantity vs Sales")
        st.caption("Compare monthly quantity against monthly sales to see whether growth is volume-driven or price-driven.")
        monthly = calc.monthly_summary(df)
        col1, col2 = st.columns(2)
        with col1:
            st.plotly_chart(charts.monthly_trend_chart(monthly, "sales", theme), use_container_width=True)
        with col2:
            st.plotly_chart(charts.monthly_trend_chart(monthly, "quantity", theme), use_container_width=True)

        st.write("")
        st.markdown("### Average Selling Rate Trend")
        asr = calc.asr_by_month(df)
        st.plotly_chart(charts.asr_trend_chart(asr, theme), use_container_width=True)
        if len(asr) >= 2:
            change = (asr["asr"].iloc[-1] - asr["asr"].iloc[0]) / asr["asr"].iloc[0] * 100 if asr["asr"].iloc[0] else None
            if change is not None:
                direction = "risen" if change >= 0 else "fallen"
                insight_line(f"💹 Average selling rate has {direction} {format_pct(abs(change))} from {asr['month_label'].iloc[0]} to {asr['month_label'].iloc[-1]}.")
    else:
        st.info("Quantity data was not detected in this file — quantity and ASR analysis are unavailable.")

    st.write("")
    st.markdown("### Invoice Value Distribution")
    ivs = calc.invoice_value_stats(df)
    kpi_row([
        ("Average Invoice", format_inr_short(ivs.average)),
        ("Median Invoice", format_inr_short(ivs.median)),
        ("Largest Invoice", format_inr_short(ivs.maximum)),
        ("Smallest Invoice", format_inr_short(ivs.minimum)),
    ])
    if not ivs.bucket_counts.empty:
        st.plotly_chart(charts.invoice_value_bucket_chart(ivs.bucket_counts, theme), use_container_width=True)

    st.write("")
    st.markdown("### Cancellation Analysis")
    cs = calc.cancellation_stats(df)
    kpi_row([
        ("Cancelled Invoices", f"{cs.cancelled_count:,}"),
        ("Cancellation Rate", format_pct(cs.cancellation_rate_pct)),
        ("Cancelled Value", format_inr_short(cs.cancelled_value)),
    ])
    if cs.high_cancellation_warning:
        warning_line(f"Cancellation rate ({format_pct(cs.cancellation_rate_pct)}) is unusually high — worth investigating root causes.")

    cancelled_df = df[(df["row_type"] == "Transaction") & (df["is_cancelled"].fillna(False))]
    if not cancelled_df.empty:
        col1, col2 = st.columns(2)
        with col1:
            by_month = (
                cancelled_df.assign(month_start=cancelled_df["date"].dt.to_period("M").dt.to_timestamp())
                .groupby("month_start").size().reset_index(name="count").sort_values("month_start")
            )
            by_month["month_label"] = by_month["month_start"].dt.strftime("%b %Y")
            st.plotly_chart(
                charts.category_count_chart(by_month, "month_label", "count", "Cancellations by Month", theme=theme),
                use_container_width=True,
            )
        with col2:
            by_customer = (
                cancelled_df.groupby("customer").size().reset_index(name="count")
                .sort_values("count", ascending=False).head(10)
            )
            st.plotly_chart(
                charts.category_count_chart(by_customer, "customer", "count", "Top Customers by Cancellations", theme=theme),
                use_container_width=True,
            )

    st.write("")
    st.markdown("### FOC / Sample Analysis")
    fs = calc.foc_stats(df)
    foc_items = [("FOC Invoices", f"{fs.foc_count:,}"), ("FOC Customers", f"{fs.foc_customers:,}")]
    if fs.foc_quantity is not None:
        foc_items.append(("FOC Quantity", f"{fs.foc_quantity:,.0f}"))
    kpi_row(foc_items)

    foc_df = df[(df["row_type"] == "Transaction") & (df["is_foc"].fillna(False))]
    if not foc_df.empty:
        by_month = (
            foc_df.assign(month_start=foc_df["date"].dt.to_period("M").dt.to_timestamp())
            .groupby("month_start").size().reset_index(name="count").sort_values("month_start")
        )
        by_month["month_label"] = by_month["month_start"].dt.strftime("%b %Y")
        st.plotly_chart(
            charts.category_count_chart(by_month, "month_label", "count", "FOC Invoices by Month", theme=theme),
            use_container_width=True,
        )


# ---------------------------------------------------------------------------
# Page 5: Data Explorer
# ---------------------------------------------------------------------------

def render_data_explorer(df: pd.DataFrame) -> None:
    st.markdown("## Data Explorer")
    st.caption("Search, filter, and download the cleaned transaction data.")

    search_text = st.text_input("Search customer name", "")
    row_type_options = sorted(df["row_type"].dropna().unique().tolist())
    selected_row_types = st.multiselect("Row Type", row_type_options, default=row_type_options)

    explorer_df = df[df["row_type"].isin(selected_row_types)] if selected_row_types else df
    if search_text:
        explorer_df = explorer_df[explorer_df["customer"].astype(str).str.contains(search_text, case=False, na=False)]

    st.write(f"Showing {len(explorer_df):,} of {len(df):,} rows.")
    st.dataframe(explorer_df, use_container_width=True, height=420)

    st.write("")
    col1, col2 = st.columns(2)
    with col1:
        csv_bytes = explorer_df.to_csv(index=False).encode("utf-8")
        st.download_button("Download filtered data (CSV)", csv_bytes, "filtered_sales_data.csv", "text/csv")
    with col2:
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as writer:
            explorer_df.to_excel(writer, index=False, sheet_name="Filtered Data")
        st.download_button(
            "Download filtered data (Excel)",
            excel_buffer.getvalue(),
            "filtered_sales_data.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


# ---------------------------------------------------------------------------
# Page dispatch
# ---------------------------------------------------------------------------

PAGES = {
    "Executive Overview": render_executive_overview,
    "Customer Analysis": render_customer_analysis,
    "Geographic Analysis": render_geographic_analysis,
    "Sales & Operations": render_sales_operations,
    "Data Explorer": render_data_explorer,
}

PAGES[page](df)