"""
charts.py
---------
Plotly chart builders. Pure functions: DataFrame in, plotly.graph_objects
Figure out. No Streamlit calls here - app.py handles st.plotly_chart().

DESIGN PRINCIPLE (per project requirement - dashboard is for a non-technical
audience): every chart favors clarity over density.
  - Only bar / horizontal-bar / line charts - nothing that requires reading
    a legend to decode (no radar, bubble, or dense scatter charts).
  - Values are labeled directly ON the chart (bars/points), so nobody has
    to hover to read a number.
  - Titles are written in plain English ("Monthly Sales Trend", not
    "sales_value by month_start").
  - Currency is shown in Cr/L/K format via utils.format_inr_short, matching
    how the numbers are already written in the KPI cards and insights text.
  - Theme-aware: pass the same theme dict app.py uses for Light/Dark so
    chart backgrounds always match the page around them.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go

from modules.utils import format_inr_short


# ---------------------------------------------------------------------------
# Default theme fallback (used if the caller doesn't pass one, e.g. in tests)
# ---------------------------------------------------------------------------

_DEFAULT_THEME = {
    "bg": "#FFFFFF",
    "card_bg": "#F7F8FA",
    "text": "#1A1A2E",
    "subtext": "#5A5A72",
    "border": "#E4E6EB",
    "accent": "#6C63FF",
}

_PALETTE = ["#6C63FF", "#00C2A8", "#FFB84C", "#FF6B6B", "#4C9AFF", "#B983FF"]


def _apply_common_layout(fig: go.Figure, theme: Optional[dict], title: str, height: int = 380) -> go.Figure:
    theme = theme or _DEFAULT_THEME
    fig.update_layout(
        title=dict(text=title, font=dict(size=16, color=theme["text"]), x=0.0, xanchor="left"),
        plot_bgcolor=theme["bg"],
        paper_bgcolor=theme["bg"],
        font=dict(color=theme["text"], size=13),
        height=height,
        margin=dict(l=10, r=10, t=50, b=10),
        hoverlabel=dict(bgcolor=theme["card_bg"], font_size=13),
        showlegend=False,
    )
    fig.update_xaxes(showgrid=False, color=theme["subtext"])
    fig.update_yaxes(showgrid=True, gridcolor=theme["border"], color=theme["subtext"])
    return fig


# ---------------------------------------------------------------------------
# Monthly trend (metric-switchable: Sales / Invoices / Customers)
# ---------------------------------------------------------------------------

def monthly_trend_chart(
    monthly_df: pd.DataFrame,
    metric: str = "sales",
    theme: Optional[dict] = None,
) -> go.Figure:
    """
    metric must be one of: 'sales', 'invoices', 'customers'.
    Bar chart chosen over line - easier for a non-technical reader to compare
    individual months at a glance.
    """
    theme = theme or _DEFAULT_THEME
    labels = {"sales": "Sales", "invoices": "Invoices", "customers": "Customers", "quantity": "Quantity"}
    metric_label = labels.get(metric, metric.title())

    if monthly_df.empty:
        return _apply_common_layout(go.Figure(), theme, f"Monthly {metric_label} Trend")

    if metric == "sales":
        text = [format_inr_short(v) for v in monthly_df[metric]]
    else:
        text = [f"{v:,.0f}" for v in monthly_df[metric]]

    fig = go.Figure(
        go.Bar(
            x=monthly_df["month_label"],
            y=monthly_df[metric],
            marker_color=theme["accent"],
            text=text,
            textposition="outside",
            hovertemplate="%{x}<br>%{text}<extra></extra>",
        )
    )
    return _apply_common_layout(fig, theme, f"Monthly {metric_label} Trend")


# ---------------------------------------------------------------------------
# H1 vs H2 comparison
# ---------------------------------------------------------------------------

def h1_h2_chart(h1_sales: float, h2_sales: float, theme: Optional[dict] = None) -> go.Figure:
    theme = theme or _DEFAULT_THEME
    values = [h1_sales, h2_sales]
    fig = go.Figure(
        go.Bar(
            x=["H1 (Apr–Sep)", "H2 (Oct–Mar)"],
            y=values,
            marker_color=[theme["accent"], _PALETTE[1]],
            text=[format_inr_short(v) for v in values],
            textposition="outside",
            hovertemplate="%{x}<br>%{text}<extra></extra>",
        )
    )
    return _apply_common_layout(fig, theme, "First Half vs Second Half Sales", height=340)


# ---------------------------------------------------------------------------
# Top customers (horizontal bar - easiest orientation to read long names)
# ---------------------------------------------------------------------------

def top_customers_chart(top_customers_df: pd.DataFrame, theme: Optional[dict] = None) -> go.Figure:
    theme = theme or _DEFAULT_THEME
    if top_customers_df.empty:
        return _apply_common_layout(go.Figure(), theme, "Top Customers by Sales")

    # Reverse so the #1 customer appears at the top of the horizontal bar.
    df = top_customers_df.iloc[::-1]
    fig = go.Figure(
        go.Bar(
            x=df["sales"],
            y=df["customer"],
            orientation="h",
            marker_color=theme["accent"],
            text=[format_inr_short(v) for v in df["sales"]],
            textposition="outside",
            hovertemplate="%{y}<br>%{text}<extra></extra>",
        )
    )
    fig.update_yaxes(showgrid=False)
    fig.update_xaxes(showgrid=True, gridcolor=theme["border"])
    height = max(340, 34 * len(df))
    return _apply_common_layout(fig, theme, "Top Customers by Sales", height=height)


# ---------------------------------------------------------------------------
# Pareto (customer concentration)
# ---------------------------------------------------------------------------

def pareto_chart(pareto_table: pd.DataFrame, top_n: int = 20, theme: Optional[dict] = None) -> go.Figure:
    """
    Bars = individual customer sales %, line = cumulative % running total.
    Capped to top_n customers so the chart stays readable - the cumulative
    line still tells the "how concentrated is our revenue" story clearly
    without needing to plot every single customer.
    """
    theme = theme or _DEFAULT_THEME
    if pareto_table.empty:
        return _apply_common_layout(go.Figure(), theme, "Customer Revenue Concentration")

    df = pareto_table.head(top_n)

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=df["customer"],
            y=df["sales_pct"],
            name="Share of Sales",
            marker_color=theme["accent"],
            yaxis="y1",
            hovertemplate="%{x}<br>%{y:.1f}% of total sales<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["customer"],
            y=df["cumulative_pct"],
            name="Cumulative %",
            mode="lines+markers",
            line=dict(color=_PALETTE[3], width=2),
            yaxis="y2",
            hovertemplate="Cumulative: %{y:.1f}%<extra></extra>",
        )
    )
    fig.update_layout(
        yaxis=dict(title="Share of Sales (%)", showgrid=True, gridcolor=theme["border"]),
        yaxis2=dict(title="Cumulative %", overlaying="y", side="right", range=[0, 105], showgrid=False),
        showlegend=True,
        legend=dict(orientation="h", y=1.15, x=0),
    )
    fig.update_xaxes(tickangle=-45)
    return _apply_common_layout(fig, theme, "Customer Revenue Concentration (Pareto)", height=440)


# ---------------------------------------------------------------------------
# Sales by state (horizontal bar, ranked)
# ---------------------------------------------------------------------------

def state_sales_chart(sales_by_state_df: pd.DataFrame, top_n: int = 15, theme: Optional[dict] = None) -> go.Figure:
    theme = theme or _DEFAULT_THEME
    if sales_by_state_df.empty:
        return _apply_common_layout(go.Figure(), theme, "Sales by State")

    df = sales_by_state_df.head(top_n).iloc[::-1]
    fig = go.Figure(
        go.Bar(
            x=df["sales"],
            y=df["state"],
            orientation="h",
            marker_color=theme["accent"],
            text=[format_inr_short(v) for v in df["sales"]],
            textposition="outside",
            hovertemplate="%{y}<br>%{text}<extra></extra>",
        )
    )
    fig.update_yaxes(showgrid=False)
    height = max(340, 32 * len(df))
    return _apply_common_layout(fig, theme, "Sales by State", height=height)


_INDIA_STATE_GEOJSON = Path(__file__).resolve().parent.parent / "assets" / "india_states.geojson"
_STATE_MAP_ALIASES = {
    "andhra pradesh old": "Andhra Pradesh",
    "arunachal pradesh": "Arunanchal Pradesh",
    "andaman nicobar islands": "Andaman & Nicobar Island",
    "dadra nagar haveli and daman diu": "Dadra & Nagar Havelli and Daman & Diu",
    "daman diu": "Dadra & Nagar Havelli and Daman & Diu",
    "dadra nagar haveli": "Dadra & Nagar Havelli and Daman & Diu",
}


@lru_cache(maxsize=1)
def _load_india_state_geojson() -> dict:
    with _INDIA_STATE_GEOJSON.open(encoding="utf-8") as geojson_file:
        return json.load(geojson_file)


def _india_map_state_name(value: object) -> str | None:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()
    if not normalized:
        return None
    return _STATE_MAP_ALIASES.get(normalized, str(value).strip())


def india_state_choropleth(
    sales_by_state_df: pd.DataFrame,
    metric: str = "sales",
    theme: Optional[dict] = None,
) -> go.Figure:
    """Show state-level sales or quantity on an offline India state map."""
    theme = theme or _DEFAULT_THEME
    metric_column = "quantity" if metric == "quantity" else "sales"
    metric_label = "Quantity" if metric_column == "quantity" else "Sales"
    geojson = _load_india_state_geojson()
    geo_state_names = [feature["properties"]["state_name"] for feature in geojson["features"]]

    state_data = sales_by_state_df.copy()
    if not state_data.empty and metric_column in state_data.columns:
        state_data["map_state"] = state_data["state"].map(_india_map_state_name)
        state_data = state_data[state_data["map_state"].notna()]
        group_columns = [column for column in ("sales", "quantity") if column in state_data.columns]
        state_data = state_data.groupby("map_state", as_index=False)[group_columns].sum(min_count=1)
    else:
        state_data = pd.DataFrame(columns=["map_state", "sales", "quantity"])

    state_lookup = state_data.set_index("map_state").to_dict(orient="index") if not state_data.empty else {}
    raw_z_values = [state_lookup.get(name, {}).get(metric_column) for name in geo_state_names]
    z_values = [value if pd.notna(value) else None for value in raw_z_values]
    customdata = []
    for name in geo_state_names:
        values = state_lookup.get(name, {})
        sales_value = values.get("sales")
        quantity_value = values.get("quantity")
        customdata.append([
            format_inr_short(sales_value) if pd.notna(sales_value) else "No data",
            f"{quantity_value:,.2f}" if pd.notna(quantity_value) else "Not available",
        ])

    colorbar = {"title": metric_label, "len": 0.72, "thickness": 14, "outlinewidth": 0}
    if metric_column == "sales":
        colorbar.update(tickprefix="₹", tickformat=".2s")
    else:
        colorbar.update(tickformat=".2s", ticksuffix=" units")

    fig = go.Figure(
        go.Choropleth(
            geojson=geojson,
            featureidkey="properties.state_name",
            locations=geo_state_names,
            z=z_values,
            customdata=customdata,
            colorscale="Viridis",
            zmin=0,
            zmax=max([float(value) for value in z_values if pd.notna(value)] or [1.0]),
            marker=dict(line=dict(color=theme["border"], width=0.55)),
            colorbar=colorbar,
            hovertemplate=(
                "<b>%{location}</b><br>Sales: %{customdata[0]}<br>"
                "Quantity: %{customdata[1]}<extra></extra>"
            ),
        )
    )
    _apply_common_layout(fig, theme, f"India by {metric_label}", height=600)
    fig.update_geos(
        visible=False,
        bgcolor=theme["bg"],
        projection_type="mercator",
        center=dict(lat=23.0, lon=82.5),
        lataxis_range=[5.0, 39.0],
        lonaxis_range=[66.0, 100.0],
    )
    fig.update_layout(margin=dict(l=0, r=0, t=52, b=0))
    return fig


# ---------------------------------------------------------------------------
# Average Selling Rate trend
# ---------------------------------------------------------------------------

def asr_trend_chart(asr_df: pd.DataFrame, theme: Optional[dict] = None) -> go.Figure:
    theme = theme or _DEFAULT_THEME
    if asr_df.empty:
        return _apply_common_layout(go.Figure(), theme, "Average Selling Rate Trend")

    fig = go.Figure(
        go.Scatter(
            x=asr_df["month_label"],
            y=asr_df["asr"],
            mode="lines+markers+text",
            line=dict(color=theme["accent"], width=3),
            marker=dict(size=8),
            text=[f"₹{v:.2f}" for v in asr_df["asr"]],
            textposition="top center",
            hovertemplate="%{x}<br>₹%{y:.2f} per unit<extra></extra>",
        )
    )
    return _apply_common_layout(fig, theme, "Average Selling Rate Trend", height=360)


# ---------------------------------------------------------------------------
# Invoice frequency distribution
# ---------------------------------------------------------------------------

def frequency_distribution_chart(freq_df: pd.DataFrame, theme: Optional[dict] = None) -> go.Figure:
    theme = theme or _DEFAULT_THEME
    if freq_df.empty:
        return _apply_common_layout(go.Figure(), theme, "Customer Purchase Frequency")

    fig = go.Figure(
        go.Bar(
            x=freq_df["bucket"],
            y=freq_df["customer_count"],
            marker_color=theme["accent"],
            text=[f"{int(v):,}" for v in freq_df["customer_count"]],
            textposition="outside",
            hovertemplate="%{x}<br>%{y} customers<extra></extra>",
        )
    )
    return _apply_common_layout(fig, theme, "Customer Purchase Frequency", height=360)


# ---------------------------------------------------------------------------
# Invoice value buckets
# ---------------------------------------------------------------------------

def invoice_value_bucket_chart(bucket_df: pd.DataFrame, theme: Optional[dict] = None) -> go.Figure:
    theme = theme or _DEFAULT_THEME
    if bucket_df.empty:
        return _apply_common_layout(go.Figure(), theme, "Invoice Value Distribution")

    fig = go.Figure(
        go.Bar(
            x=bucket_df["bucket"],
            y=bucket_df["count"],
            marker_color=theme["accent"],
            text=[f"{int(v):,}" for v in bucket_df["count"]],
            textposition="outside",
            hovertemplate="%{x}<br>%{y} invoices<extra></extra>",
        )
    )
    return _apply_common_layout(fig, theme, "Invoice Value Distribution", height=360)


# ---------------------------------------------------------------------------
# Customer segmentation (simple bar - avoided a pie chart on purpose, pies
# are notoriously hard to read accurately once there are more than ~4 slices)
# ---------------------------------------------------------------------------

def segmentation_chart(segment_counts: pd.Series, theme: Optional[dict] = None) -> go.Figure:
    theme = theme or _DEFAULT_THEME
    if segment_counts.empty:
        return _apply_common_layout(go.Figure(), theme, "Customer Segments")

    df = segment_counts.sort_values(ascending=True)
    fig = go.Figure(
        go.Bar(
            x=df.values,
            y=df.index,
            orientation="h",
            marker_color=[_PALETTE[i % len(_PALETTE)] for i in range(len(df))],
            text=[f"{int(v):,}" for v in df.values],
            textposition="outside",
            hovertemplate="%{y}<br>%{x} customers<extra></extra>",
        )
    )
    fig.update_yaxes(showgrid=False)
    return _apply_common_layout(fig, theme, "Customer Segments", height=340)


# ---------------------------------------------------------------------------
# Generic category-count bar chart (retention buckets, cancellation-by-month,
# or any other "label -> count" breakdown that doesn't need its own function)
# ---------------------------------------------------------------------------

def category_count_chart(
    df: pd.DataFrame,
    category_col: str,
    value_col: str,
    title: str,
    value_is_currency: bool = False,
    theme: Optional[dict] = None,
) -> go.Figure:
    theme = theme or _DEFAULT_THEME
    if df.empty:
        return _apply_common_layout(go.Figure(), theme, title)

    text = (
        [format_inr_short(v) for v in df[value_col]]
        if value_is_currency
        else [f"{v:,.0f}" for v in df[value_col]]
    )
    fig = go.Figure(
        go.Bar(
            x=df[category_col],
            y=df[value_col],
            marker_color=theme["accent"],
            text=text,
            textposition="outside",
            hovertemplate="%{x}<br>%{text}<extra></extra>",
        )
    )
    return _apply_common_layout(fig, theme, title, height=360)
