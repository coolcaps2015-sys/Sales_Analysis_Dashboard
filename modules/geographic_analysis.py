"""
geographic_analysis.py
-----------------------
State-level rollups derived from GSTIN. Every function degrades gracefully
if GSTIN wasn't detected in the source file - callers should check
`geographic_data_available(df)` first and show the "unavailable" message
from the spec instead of calling these functions blind.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from modules.data_cleaner import is_valid_sale
from modules.utils import extract_state_from_gstin


def geographic_data_available(df: pd.DataFrame) -> bool:
    """True if there's at least one usable GSTIN to derive a state from."""
    if "gstin" not in df.columns:
        return False
    valid = df[is_valid_sale(df)]
    return valid["gstin"].notna().any()


def _with_state(df: pd.DataFrame) -> pd.DataFrame:
    """Valid sales rows with a `state` column derived from GSTIN."""
    valid = df[is_valid_sale(df)].copy()
    valid["state"] = valid["gstin"].apply(extract_state_from_gstin)
    return valid[valid["state"].notna()]


# ---------------------------------------------------------------------------
# Sales by state
# ---------------------------------------------------------------------------

def sales_by_state(df: pd.DataFrame) -> pd.DataFrame:
    """
    One row per state: sales, sales_pct, customers, invoices,
    avg_invoice_value. Sorted by sales descending.
    """
    with_state = _with_state(df)
    if with_state.empty:
        return pd.DataFrame(
            columns=["state", "sales", "sales_pct", "customers", "invoices", "avg_invoice_value"]
        )

    total_sales = with_state["sales_value"].sum()
    grouped = (
        with_state.groupby("state")
        .agg(
            sales=("sales_value", "sum"),
            customers=("customer", "nunique"),
            invoices=("invoice_number", "nunique"),
        )
        .reset_index()
    )
    grouped["sales_pct"] = grouped["sales"] / total_sales * 100 if total_sales else 0.0
    grouped["avg_invoice_value"] = grouped["sales"] / grouped["invoices"].replace(0, pd.NA)

    return grouped.sort_values("sales", ascending=False).reset_index(drop=True)


def monthly_sales_by_state(df: pd.DataFrame) -> pd.DataFrame:
    """Month x State sales matrix (long format: month_start, state, sales)."""
    with_state = _with_state(df)
    if with_state.empty:
        return pd.DataFrame(columns=["month_label", "month_start", "state", "sales"])

    with_state["month_start"] = with_state["date"].dt.to_period("M").dt.to_timestamp()
    grouped = (
        with_state.groupby(["month_start", "state"])["sales_value"]
        .sum()
        .reset_index()
        .rename(columns={"sales_value": "sales"})
        .sort_values("month_start")
    )
    grouped["month_label"] = grouped["month_start"].dt.strftime("%b %Y")
    return grouped[["month_label", "month_start", "state", "sales"]]


# ---------------------------------------------------------------------------
# Single-state drill-down
# ---------------------------------------------------------------------------

@dataclass
class StateDrilldown:
    state: str = ""
    total_sales: float = 0.0
    customer_count: int = 0
    invoice_count: int = 0
    avg_invoice_value: float = 0.0
    monthly_trend: pd.DataFrame = field(default_factory=pd.DataFrame)
    top_customers: pd.DataFrame = field(default_factory=pd.DataFrame)


def state_drilldown(df: pd.DataFrame, state: str, top_n: int = 10) -> StateDrilldown:
    """Detailed view for one state: totals, monthly trend, top customers there."""
    with_state = _with_state(df)
    state_df = with_state[with_state["state"] == state]

    if state_df.empty:
        return StateDrilldown(state=state)

    total_sales = float(state_df["sales_value"].sum())
    invoice_count = int(state_df["invoice_number"].nunique())

    state_df = state_df.copy()
    state_df["month_start"] = state_df["date"].dt.to_period("M").dt.to_timestamp()
    monthly_trend = (
        state_df.groupby("month_start")["sales_value"].sum()
        .reset_index().rename(columns={"sales_value": "sales"})
        .sort_values("month_start")
    )
    monthly_trend["month_label"] = monthly_trend["month_start"].dt.strftime("%b %Y")

    top_customers = (
        state_df.groupby("customer")["sales_value"].sum()
        .sort_values(ascending=False).head(top_n)
        .reset_index().rename(columns={"sales_value": "sales"})
    )

    return StateDrilldown(
        state=state,
        total_sales=total_sales,
        customer_count=int(state_df["customer"].nunique()),
        invoice_count=invoice_count,
        avg_invoice_value=total_sales / invoice_count if invoice_count else 0.0,
        monthly_trend=monthly_trend[["month_label", "month_start", "sales"]],
        top_customers=top_customers,
    )


def available_states(df: pd.DataFrame) -> list[str]:
    """Sorted list of states present in the data, for a state-picker dropdown."""
    with_state = _with_state(df)
    if with_state.empty:
        return []
    return sorted(with_state["state"].dropna().unique().tolist())