"""
calculations.py
----------------
Core KPI engine. Every function here takes the canonical cleaned DataFrame
(from data_cleaner.clean_data) and returns plain Python numbers / small
DataFrames - no Streamlit, no Plotly. Keeping this pure makes it testable
and reusable by the Excel/PDF export module later.

Convention: every function filters to `is_valid_sale(df)` internally unless
its whole purpose is to look at cancelled/FOC rows (those are explicit,
named functions so it's never ambiguous which rows are included).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from modules.data_cleaner import is_valid_sale


MONTH_ORDER = [
    "Apr", "May", "Jun", "Jul", "Aug", "Sep",
    "Oct", "Nov", "Dec", "Jan", "Feb", "Mar",
]


# ---------------------------------------------------------------------------
# Headline KPIs
# ---------------------------------------------------------------------------

@dataclass
class HeadlineKPIs:
    total_sales: float = 0.0
    total_invoices: int = 0
    total_customers: int = 0
    avg_invoice_value: float = 0.0
    total_quantity: Optional[float] = None
    avg_selling_rate: Optional[float] = None
    quantity_available: bool = False


def compute_headline_kpis(df: pd.DataFrame) -> HeadlineKPIs:
    """The top-row KPI cards on the Executive Overview page."""
    valid = df[is_valid_sale(df)]

    total_sales = float(valid["sales_value"].sum())
    total_invoices = int(valid["invoice_number"].nunique())
    total_customers = int(valid["customer"].nunique()) if "customer" in valid.columns else 0
    avg_invoice_value = total_sales / total_invoices if total_invoices else 0.0

    quantity_available = "quantity" in valid.columns and valid["quantity"].notna().any()
    total_quantity = None
    avg_selling_rate = None
    if quantity_available:
        total_quantity = float(valid["quantity"].sum())
        avg_selling_rate = total_sales / total_quantity if total_quantity else None

    return HeadlineKPIs(
        total_sales=total_sales,
        total_invoices=total_invoices,
        total_customers=total_customers,
        avg_invoice_value=avg_invoice_value,
        total_quantity=total_quantity,
        avg_selling_rate=avg_selling_rate,
        quantity_available=quantity_available,
    )


# ---------------------------------------------------------------------------
# Monthly analysis
# ---------------------------------------------------------------------------

def monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    One row per calendar month present in the data, chronologically sorted
    (not alphabetically - "Apr" must come before "Nov").

    Columns: month_label, month_start, sales, invoices, customers,
             mom_growth_pct
    """
    valid = df[is_valid_sale(df)].copy()
    if valid.empty:
        return pd.DataFrame(
            columns=["month_label", "month_start", "sales", "invoices", "customers", "mom_growth_pct"]
        )

    valid["month_start"] = valid["date"].dt.to_period("M").dt.to_timestamp()

    agg_dict = {
        "sales": ("sales_value", "sum"),
        "invoices": ("invoice_number", "nunique"),
        "customers": ("customer", "nunique"),
    }
    quantity_available = "quantity" in valid.columns and valid["quantity"].notna().any()
    if quantity_available:
        agg_dict["quantity"] = ("quantity", "sum")

    grouped = (
        valid.groupby("month_start")
        .agg(**agg_dict)
        .reset_index()
        .sort_values("month_start")
    )
    grouped["month_label"] = grouped["month_start"].dt.strftime("%b %Y")
    grouped["mom_growth_pct"] = grouped["sales"].pct_change() * 100

    cols = ["month_label", "month_start", "sales", "invoices", "customers", "mom_growth_pct"]
    if quantity_available:
        cols.insert(-1, "quantity")
    return grouped[cols]


@dataclass
class MonthlyHighlights:
    highest_month: Optional[str] = None
    highest_sales: Optional[float] = None
    lowest_month: Optional[str] = None
    lowest_sales: Optional[float] = None
    latest_mom_growth_pct: Optional[float] = None


def monthly_highlights(monthly_df: pd.DataFrame) -> MonthlyHighlights:
    """Best/worst month and the most recent month-over-month growth figure."""
    if monthly_df.empty:
        return MonthlyHighlights()

    top = monthly_df.loc[monthly_df["sales"].idxmax()]
    bottom = monthly_df.loc[monthly_df["sales"].idxmin()]
    latest_growth = monthly_df["mom_growth_pct"].iloc[-1] if len(monthly_df) > 1 else None

    return MonthlyHighlights(
        highest_month=top["month_label"],
        highest_sales=float(top["sales"]),
        lowest_month=bottom["month_label"],
        lowest_sales=float(bottom["sales"]),
        latest_mom_growth_pct=float(latest_growth) if pd.notna(latest_growth) else None,
    )


# ---------------------------------------------------------------------------
# H1 vs H2
# ---------------------------------------------------------------------------

@dataclass
class HalfYearComparison:
    h1_sales: float = 0.0
    h2_sales: float = 0.0
    h2_growth_pct: Optional[float] = None
    both_halves_present: bool = False


def h1_h2_comparison(df: pd.DataFrame) -> HalfYearComparison:
    """
    H1 = Apr-Sep, H2 = Oct-Mar (financial-year halves, from the `half_year`
    column data_cleaner already derived). Growth = (H2-H1)/H1 * 100.
    """
    valid = df[is_valid_sale(df)]
    h1_sales = float(valid.loc[valid["half_year"] == "H1", "sales_value"].sum())
    h2_sales = float(valid.loc[valid["half_year"] == "H2", "sales_value"].sum())

    both_present = (valid["half_year"] == "H1").any() and (valid["half_year"] == "H2").any()
    growth = ((h2_sales - h1_sales) / h1_sales * 100) if h1_sales else None

    return HalfYearComparison(
        h1_sales=h1_sales,
        h2_sales=h2_sales,
        h2_growth_pct=growth,
        both_halves_present=both_present,
    )


# ---------------------------------------------------------------------------
# Invoice value distribution
# ---------------------------------------------------------------------------

DEFAULT_INVOICE_BUCKETS = [
    (0, 50_000, "Below ₹50K"),
    (50_000, 100_000, "₹50K–₹1L"),
    (100_000, 500_000, "₹1L–₹5L"),
    (500_000, 1_000_000, "₹5L–₹10L"),
    (1_000_000, float("inf"), "Above ₹10L"),
]


@dataclass
class InvoiceValueStats:
    average: float = 0.0
    median: float = 0.0
    maximum: float = 0.0
    minimum: float = 0.0
    bucket_counts: pd.DataFrame = field(default_factory=pd.DataFrame)


def invoice_value_stats(
    df: pd.DataFrame, buckets: list[tuple[float, float, str]] = None
) -> InvoiceValueStats:
    """Per-invoice value distribution (one row per invoice, not per line item)."""
    valid = df[is_valid_sale(df)]
    per_invoice = valid.groupby("invoice_number")["sales_value"].sum()

    if per_invoice.empty:
        return InvoiceValueStats(bucket_counts=pd.DataFrame(columns=["bucket", "count"]))

    buckets = buckets or DEFAULT_INVOICE_BUCKETS
    labels = [b[2] for b in buckets]
    edges = [b[0] for b in buckets] + [buckets[-1][1]]

    bucket_series = pd.cut(per_invoice, bins=edges, labels=labels, include_lowest=True)
    bucket_counts = (
        bucket_series.value_counts().reindex(labels).fillna(0).astype(int)
        .rename_axis("bucket").reset_index(name="count")
    )

    return InvoiceValueStats(
        average=float(per_invoice.mean()),
        median=float(per_invoice.median()),
        maximum=float(per_invoice.max()),
        minimum=float(per_invoice.min()),
        bucket_counts=bucket_counts,
    )


# ---------------------------------------------------------------------------
# Cancellation & FOC summaries
# ---------------------------------------------------------------------------

@dataclass
class CancellationStats:
    cancelled_count: int = 0
    cancellation_rate_pct: float = 0.0
    cancelled_value: float = 0.0
    high_cancellation_warning: bool = False


def cancellation_stats(df: pd.DataFrame, warning_threshold_pct: float = 5.0) -> CancellationStats:
    txn = df[df["row_type"] == "Transaction"]
    total_txn = len(txn)
    cancelled = txn[txn["is_cancelled"]]
    rate = (len(cancelled) / total_txn * 100) if total_txn else 0.0

    return CancellationStats(
        cancelled_count=len(cancelled),
        cancellation_rate_pct=rate,
        cancelled_value=float(cancelled["sales_value"].sum()),
        high_cancellation_warning=rate > warning_threshold_pct,
    )


@dataclass
class FocStats:
    foc_count: int = 0
    foc_quantity: Optional[float] = None
    foc_customers: int = 0


def foc_stats(df: pd.DataFrame) -> FocStats:
    txn = df[df["row_type"] == "Transaction"]
    foc = txn[txn["is_foc"]]
    quantity_available = "quantity" in foc.columns and foc["quantity"].notna().any()

    return FocStats(
        foc_count=len(foc),
        foc_quantity=float(foc["quantity"].sum()) if quantity_available else None,
        foc_customers=int(foc["customer"].nunique()) if "customer" in foc.columns else 0,
    )


# ---------------------------------------------------------------------------
# Average Selling Rate (ASR) trend
# ---------------------------------------------------------------------------

def asr_by_month(df: pd.DataFrame) -> pd.DataFrame:
    """Monthly Average Selling Rate = sales_value / quantity, when quantity exists."""
    valid = df[is_valid_sale(df)].copy()
    if valid.empty or "quantity" not in valid.columns or not valid["quantity"].notna().any():
        return pd.DataFrame(columns=["month_label", "month_start", "asr"])

    valid["month_start"] = valid["date"].dt.to_period("M").dt.to_timestamp()
    grouped = (
        valid.groupby("month_start")
        .agg(sales=("sales_value", "sum"), quantity=("quantity", "sum"))
        .reset_index()
        .sort_values("month_start")
    )
    grouped["asr"] = grouped["sales"] / grouped["quantity"].replace(0, np.nan)
    grouped["month_label"] = grouped["month_start"].dt.strftime("%b %Y")
    return grouped[["month_label", "month_start", "asr"]]