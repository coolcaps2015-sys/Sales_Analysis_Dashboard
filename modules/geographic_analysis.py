"""
geographic_analysis.py
-----------------------
State-level rollups derived from GSTIN plus a country-level summary of
international/export sales when the source workbook includes location clues.
The rollup functions return empty dataframes when their required data is absent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

import pandas as pd

from modules.data_cleaner import is_valid_sale
from modules.utils import extract_state_from_gstin


_INDIA_COUNTRY_NAMES = {"india", "bharat", "ind", "in", "republic of india"}
_EMPTY_COUNTRY_VALUES = {"", "na", "n a", "n/a", "none", "null", "unknown", "not available"}
_FOREIGN_COUNTRY_ALIASES = {
    "afghanistan": "Afghanistan",
    "australia": "Australia",
    "austria": "Austria",
    "bahrain": "Bahrain",
    "bangladesh": "Bangladesh",
    "belgium": "Belgium",
    "bhutan": "Bhutan",
    "brazil": "Brazil",
    "canada": "Canada",
    "china": "China",
    "denmark": "Denmark",
    "egypt": "Egypt",
    "france": "France",
    "germany": "Germany",
    "hong kong": "Hong Kong",
    "indonesia": "Indonesia",
    "iran": "Iran",
    "iraq": "Iraq",
    "ireland": "Ireland",
    "israel": "Israel",
    "italy": "Italy",
    "japan": "Japan",
    "kenya": "Kenya",
    "kuwait": "Kuwait",
    "malaysia": "Malaysia",
    "maldives": "Maldives",
    "mauritius": "Mauritius",
    "mexico": "Mexico",
    "myanmar": "Myanmar",
    "nepal": "Nepal",
    "netherlands": "Netherlands",
    "new zealand": "New Zealand",
    "nigeria": "Nigeria",
    "norway": "Norway",
    "oman": "Oman",
    "pakistan": "Pakistan",
    "philippines": "Philippines",
    "qatar": "Qatar",
    "russia": "Russia",
    "saudi arabia": "Saudi Arabia",
    "singapore": "Singapore",
    "south africa": "South Africa",
    "south korea": "South Korea",
    "sri lanka": "Sri Lanka",
    "sweden": "Sweden",
    "switzerland": "Switzerland",
    "taiwan": "Taiwan",
    "thailand": "Thailand",
    "turkey": "Turkey",
    "ukraine": "Ukraine",
    "united arab emirates": "United Arab Emirates",
    "uae": "United Arab Emirates",
    "dubai": "United Arab Emirates",
    "abu dhabi": "United Arab Emirates",
    "united kingdom": "United Kingdom",
    "great britain": "United Kingdom",
    "england": "United Kingdom",
    "scotland": "United Kingdom",
    "uk": "United Kingdom",
    "united states of america": "United States",
    "united states": "United States",
    "usa": "United States",
    "us": "United States",
    "vietnam": "Vietnam",
}
_COUNTRY_TEXT_PATTERNS = [
    (re.compile(rf"\b{re.escape(alias)}\b"), country)
    for alias, country in sorted(_FOREIGN_COUNTRY_ALIASES.items(), key=lambda item: len(item[0]), reverse=True)
]


def _normalize_geo_text(value: object) -> str:
    """Normalize country/address text so common country names match reliably."""
    if value is None or pd.isna(value):
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()


def _foreign_country_in_text(value: object) -> str | None:
    text = _normalize_geo_text(value)
    for pattern, country in _COUNTRY_TEXT_PATTERNS:
        if pattern.search(text):
            return country
    return None


def _international_country_for_row(
    row: pd.Series,
    country_columns: list[object],
    location_columns: list[object],
    export_columns: list[object],
) -> str | None:
    """Return a foreign country only when the source row says so explicitly."""
    for column in country_columns:
        raw_value = row.get(column)
        normalized = _normalize_geo_text(raw_value)
        if normalized in _EMPTY_COUNTRY_VALUES:
            continue
        if normalized in _INDIA_COUNTRY_NAMES:
            return None
        return (
            _FOREIGN_COUNTRY_ALIASES.get(normalized)
            or _foreign_country_in_text(raw_value)
            or str(raw_value).strip().title()
        )

    for column in location_columns:
        country = _foreign_country_in_text(row.get(column))
        if country:
            return country

    for column in export_columns:
        value = _normalize_geo_text(row.get(column))
        if re.search(r"\b(export|overseas|international)\b", value):
            return "International / Export"
    return None


def geographic_data_available(df: pd.DataFrame) -> bool:
    """True if there's at least one usable GSTIN to derive a state from."""
    if "gstin" not in df.columns:
        return False
    valid = df[is_valid_sale(df)]
    return valid["gstin"].apply(extract_state_from_gstin).notna().any()


def _with_state(df: pd.DataFrame) -> pd.DataFrame:
    """Valid sales rows with a `state` column derived from GSTIN."""
    valid = df[is_valid_sale(df)].copy()
    if "gstin" not in valid.columns:
        valid["state"] = pd.NA
        return valid
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
            columns=["state", "sales", "sales_pct", "quantity", "customers", "invoices", "avg_invoice_value"]
        )

    total_sales = with_state["sales_value"].sum()
    aggregations = {
        "sales": ("sales_value", "sum"),
        "customers": ("customer", "nunique"),
        "invoices": ("invoice_number", "nunique"),
    }
    quantity_available = "quantity" in with_state.columns and with_state["quantity"].notna().any()
    if quantity_available:
        aggregations["quantity"] = ("quantity", "sum")
    grouped = (
        with_state.groupby("state")
        .agg(**aggregations)
        .reset_index()
    )
    if not quantity_available:
        grouped["quantity"] = pd.NA
    grouped["sales_pct"] = grouped["sales"] / total_sales * 100 if total_sales else 0.0
    grouped["avg_invoice_value"] = grouped["sales"] / grouped["invoices"].replace(0, pd.NA)

    return grouped[
        ["state", "sales", "sales_pct", "quantity", "customers", "invoices", "avg_invoice_value"]
    ].sort_values("sales", ascending=False).reset_index(drop=True)


def international_sales_by_country(df: pd.DataFrame) -> pd.DataFrame:
    """Valid international/export sales grouped by country where source fields allow detection.

    International sales are detected from an explicit non-India country field,
    a recognized foreign country in a destination/address field, or an export /
    overseas / international marker in voucher or narration text. Missing GSTIN
    alone is not treated as evidence of an international sale.
    """
    columns = ["country", "sales", "quantity", "invoices", "customers"]
    transactions = df[is_valid_sale(df)].copy()
    if transactions.empty:
        return pd.DataFrame(columns=columns)

    country_columns = [
        column for column in transactions.columns
        if "country" in _normalize_geo_text(column).split()
    ]
    location_columns = [
        column for column in transactions.columns
        if any(term in _normalize_geo_text(column).split() for term in ("destination", "address"))
    ]
    export_columns = [
        column for column in transactions.columns
        if _normalize_geo_text(column) in {"voucher type", "transaction type", "narration", "remarks", "notes"}
    ]

    transactions["country"] = transactions.apply(
        lambda row: _international_country_for_row(
            row, country_columns, location_columns, export_columns
        ),
        axis=1,
    )
    international = transactions[transactions["country"].notna()]
    if international.empty:
        return pd.DataFrame(columns=columns)

    aggregations = {
        "sales": ("sales_value", "sum"),
        "invoices": ("invoice_number", "nunique"),
        "customers": ("customer", "nunique"),
    }
    quantity_available = "quantity" in international.columns and international["quantity"].notna().any()
    if quantity_available:
        aggregations["quantity"] = ("quantity", "sum")
    summary = international.groupby("country").agg(**aggregations).reset_index()
    if not quantity_available:
        summary["quantity"] = pd.NA
    return summary[columns].sort_values("sales", ascending=False).reset_index(drop=True)


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
