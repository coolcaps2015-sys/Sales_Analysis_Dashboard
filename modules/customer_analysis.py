"""
customer_analysis.py
---------------------
Customer-level intelligence: top customers, revenue concentration (Pareto),
segmentation, H1-vs-H2 retention, and invoice-frequency distribution.

All functions take the canonical cleaned DataFrame and filter to valid
sales internally (via is_valid_sale) unless explicitly analyzing
cancelled/FOC customers.

SEGMENTATION LOGIC (documented here since the spec asks for it to be
explicit and configurable - see the constants right below the imports):

  1. VIP           -> top 10% of customers, ranked by total sales.
  2. New            -> first purchase falls in H2 and customer had no H1
                        activity (i.e. they only appeared in the second
                        half of the period covered by the data).
  3. Inactive/Lost  -> was active in H1, nothing in H2, AND their last
                        purchase is more than INACTIVE_GAP_DAYS before the
                        latest date in the dataset.
  4. At Risk        -> was active in H1, nothing in H2, but their last
                        purchase is more recent than INACTIVE_GAP_DAYS
                        (i.e. dropped off, but too recently to call "lost").
  5. High Value     -> active in both halves, total sales above the
                        HIGH_VALUE_SALES_PERCENTILE among remaining
                        customers, but invoice count at/below the median
                        (big spender, infrequent buyer).
  6. Regular        -> active in both halves, invoice count at/above the
                        median (frequent, consistent buyer).
  7. Low Value      -> everything left over (active, but low spend and
                        low frequency).

Every threshold below is a module-level constant specifically so it can be
tuned without touching the classification logic itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from modules.data_cleaner import is_valid_sale


# --- Configurable segmentation thresholds ----------------------------------
VIP_TOP_PERCENTILE = 0.90          # top (1 - 0.90) = 10% of customers by sales
HIGH_VALUE_SALES_PERCENTILE = 0.75  # among non-VIP, both-halves-active customers
INACTIVE_GAP_DAYS = 120             # days since last purchase to call a customer "Lost" vs "At Risk"

FREQUENCY_BINS = [0, 1, 5, 12, 25, float("inf")]
FREQUENCY_LABELS = ["1 invoice", "2–5 invoices", "6–12 invoices", "13–25 invoices", "25+ invoices"]


# ---------------------------------------------------------------------------
# Top customers
# ---------------------------------------------------------------------------

def top_customers(df: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Top N customers by sales, with sales %, invoice count, avg invoice value."""
    valid = df[is_valid_sale(df)]
    if valid.empty or "customer" not in valid.columns:
        return pd.DataFrame(columns=["customer", "sales", "sales_pct", "invoices", "avg_invoice_value"])

    total_sales = valid["sales_value"].sum()
    grouped = (
        valid.groupby("customer")
        .agg(sales=("sales_value", "sum"), invoices=("invoice_number", "nunique"))
        .reset_index()
    )
    grouped["sales_pct"] = grouped["sales"] / total_sales * 100 if total_sales else 0.0
    grouped["avg_invoice_value"] = grouped["sales"] / grouped["invoices"].replace(0, pd.NA)

    return grouped.sort_values("sales", ascending=False).head(top_n).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Pareto / concentration analysis
# ---------------------------------------------------------------------------

@dataclass
class ParetoResult:
    table: pd.DataFrame = field(default_factory=pd.DataFrame)
    top5_contribution_pct: float = 0.0
    top10_contribution_pct: float = 0.0
    top20_contribution_pct: float = 0.0
    top50_contribution_pct: float = 0.0


def pareto_analysis(df: pd.DataFrame) -> ParetoResult:
    """
    Full customer list sorted by sales descending with cumulative sales %,
    plus quick-reference contribution of the top 5/10/20/50 customers.
    """
    valid = df[is_valid_sale(df)]
    if valid.empty or "customer" not in valid.columns:
        return ParetoResult()

    total_sales = valid["sales_value"].sum()
    grouped = (
        valid.groupby("customer")["sales_value"].sum()
        .sort_values(ascending=False)
        .reset_index()
        .rename(columns={"sales_value": "sales"})
    )
    grouped["sales_pct"] = grouped["sales"] / total_sales * 100 if total_sales else 0.0
    grouped["cumulative_pct"] = grouped["sales_pct"].cumsum()

    def contribution(n: int) -> float:
        return float(grouped["sales_pct"].head(n).sum())

    return ParetoResult(
        table=grouped,
        top5_contribution_pct=contribution(5),
        top10_contribution_pct=contribution(10),
        top20_contribution_pct=contribution(20),
        top50_contribution_pct=contribution(50),
    )


# ---------------------------------------------------------------------------
# Per-customer profile (shared building block for segmentation & retention)
# ---------------------------------------------------------------------------

def _customer_profile(df: pd.DataFrame) -> pd.DataFrame:
    """
    One row per customer: total_sales, invoice_count, first_purchase,
    last_purchase, active_h1, active_h2. Built once and reused by both
    segment_customers() and h1_h2_retention() so the definitions stay
    consistent between the two analyses.
    """
    valid = df[is_valid_sale(df)]
    if valid.empty or "customer" not in valid.columns:
        return pd.DataFrame(
            columns=["customer", "total_sales", "invoice_count", "first_purchase",
                     "last_purchase", "active_h1", "active_h2"]
        )

    profile = (
        valid.groupby("customer")
        .agg(
            total_sales=("sales_value", "sum"),
            invoice_count=("invoice_number", "nunique"),
            first_purchase=("date", "min"),
            last_purchase=("date", "max"),
        )
        .reset_index()
    )

    h1_customers = set(valid.loc[valid["half_year"] == "H1", "customer"].unique())
    h2_customers = set(valid.loc[valid["half_year"] == "H2", "customer"].unique())
    profile["active_h1"] = profile["customer"].isin(h1_customers)
    profile["active_h2"] = profile["customer"].isin(h2_customers)

    return profile


# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------

def segment_customers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Classify every customer into one segment. Returns the customer profile
    with an added `segment` column. See module docstring for the precedence
    rules and the thresholds used.
    """
    profile = _customer_profile(df)
    if profile.empty:
        return profile.assign(segment=pd.Series(dtype=object))

    max_date = profile["last_purchase"].max()

    # VIP cutoff: sales value at the VIP_TOP_PERCENTILE quantile.
    vip_cutoff = profile["total_sales"].quantile(VIP_TOP_PERCENTILE)

    both_halves = profile[profile["active_h1"] & profile["active_h2"]]
    median_invoice_count = both_halves["invoice_count"].median() if not both_halves.empty else 0
    high_value_cutoff = (
        both_halves["total_sales"].quantile(HIGH_VALUE_SALES_PERCENTILE)
        if not both_halves.empty else float("inf")
    )

    def classify(row) -> str:
        if row["total_sales"] >= vip_cutoff:
            return "VIP"
        if row["active_h2"] and not row["active_h1"]:
            return "New Customer"
        if row["active_h1"] and not row["active_h2"]:
            gap_days = (max_date - row["last_purchase"]).days
            return "Inactive/Lost" if gap_days > INACTIVE_GAP_DAYS else "At Risk"
        if row["active_h1"] and row["active_h2"]:
            if row["total_sales"] >= high_value_cutoff and row["invoice_count"] <= median_invoice_count:
                return "High Value"
            if row["invoice_count"] >= median_invoice_count:
                return "Regular"
            return "Low Value"
        return "Low Value"

    profile["segment"] = profile.apply(classify, axis=1)
    return profile


@dataclass
class CustomerKPIs:
    total_customers: int = 0
    new_customers: int = 0
    existing_customers: int = 0
    retained_customers: int = 0
    inactive_customers: int = 0
    top_customer: str = ""
    top_customer_sales: float = 0.0
    avg_customer_sales: float = 0.0


def customer_kpis(df: pd.DataFrame) -> CustomerKPIs:
    """Summary numbers for the top of the Customer Analysis page."""
    segmented = segment_customers(df)
    if segmented.empty:
        return CustomerKPIs()

    total = len(segmented)
    new = int((segmented["segment"] == "New Customer").sum())
    retained = int((segmented["active_h1"] & segmented["active_h2"]).sum())
    inactive = int((segmented["segment"] == "Inactive/Lost").sum())
    existing = total - new

    top_row = segmented.loc[segmented["total_sales"].idxmax()]

    return CustomerKPIs(
        total_customers=total,
        new_customers=new,
        existing_customers=existing,
        retained_customers=retained,
        inactive_customers=inactive,
        top_customer=str(top_row["customer"]),
        top_customer_sales=float(top_row["total_sales"]),
        avg_customer_sales=float(segmented["total_sales"].mean()),
    )


# ---------------------------------------------------------------------------
# H1 vs H2 retention
# ---------------------------------------------------------------------------

@dataclass
class RetentionResult:
    both_periods: int = 0
    h1_only: int = 0
    h2_only: int = 0
    retention_rate_pct: float = 0.0
    table: pd.DataFrame = field(default_factory=pd.DataFrame)


def h1_h2_retention(df: pd.DataFrame) -> RetentionResult:
    """
    Customers present in H1 only, H2 only (includes new customers), or both.
    Retention rate = (customers active in both) / (customers active in H1) * 100.
    """
    profile = _customer_profile(df)
    if profile.empty:
        return RetentionResult()

    both = profile[profile["active_h1"] & profile["active_h2"]]
    h1_only = profile[profile["active_h1"] & ~profile["active_h2"]]
    h2_only = profile[~profile["active_h1"] & profile["active_h2"]]

    h1_total = profile["active_h1"].sum()
    retention_rate = (len(both) / h1_total * 100) if h1_total else 0.0

    table = pd.DataFrame(
        {
            "category": ["Active in Both (Retained)", "H1 Only (Lapsed)", "H2 Only (New)"],
            "customer_count": [len(both), len(h1_only), len(h2_only)],
        }
    )

    return RetentionResult(
        both_periods=len(both),
        h1_only=len(h1_only),
        h2_only=len(h2_only),
        retention_rate_pct=retention_rate,
        table=table,
    )


# ---------------------------------------------------------------------------
# Invoice frequency distribution
# ---------------------------------------------------------------------------

def frequency_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """How many customers fall into each invoice-count bucket."""
    profile = _customer_profile(df)
    if profile.empty:
        return pd.DataFrame(columns=["bucket", "customer_count"])

    bucketed = pd.cut(
        profile["invoice_count"], bins=FREQUENCY_BINS, labels=FREQUENCY_LABELS, include_lowest=True
    )
    counts = (
        bucketed.value_counts().reindex(FREQUENCY_LABELS).fillna(0).astype(int)
        .rename_axis("bucket").reset_index(name="customer_count")
    )
    return counts