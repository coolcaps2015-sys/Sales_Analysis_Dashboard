"""
data_cleaner.py
----------------
Turns a raw-header LoadResult (from data_loader.py) into one canonical,
analysis-ready DataFrame - regardless of whether the source sheet was
already cleaned or is a raw Tally export.

Two entry paths, one output shape:

  likely_precleaned=True   -> _clean_precleaned()  (light pass: rename,
                               cast types, derive cancelled/FOC flags)
  likely_precleaned=False  -> _clean_raw()          (full pipeline: tag
                               Transaction vs Line Item, forward-fill,
                               drop footer/total rows, derive flags)

Either way, every downstream module only ever needs to know about these
canonical columns:

    date, customer, voucher_type, invoice_number, gstin, quantity,
    sales_value, row_type, is_cancelled, is_foc, financial_year, half_year

Nothing here excludes rows from the final DataFrame - cancelled/FOC/footer
rows are flagged, not dropped, so the Cancellation and FOC analysis pages
can still see them. Downstream KPI code is responsible for filtering to
`is_valid_sale` (see helper at the bottom) when computing revenue.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from modules.data_loader import LoadResult
from modules.utils import is_valid_gstin_format


CANONICAL_ORDER = [
    "date", "customer", "voucher_type", "invoice_number", "gstin",
    "quantity", "sales_value", "row_type", "is_cancelled", "is_foc",
    "financial_year", "half_year",
]


@dataclass
class DataQualityReport:
    total_rows: int = 0
    valid_transactions: int = 0
    cancelled_transactions: int = 0
    foc_transactions: int = 0
    footer_rows_excluded: int = 0
    duplicate_rows: int = 0
    missing_dates: int = 0
    missing_customers: int = 0
    missing_gstin: int = 0
    missing_values: int = 0
    missing_quantities: int = 0
    invalid_gstins: int = 0
    financial_years: list[str] = field(default_factory=list)


@dataclass
class CleanResult:
    dataframe: pd.DataFrame
    quality: DataQualityReport
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _financial_year_label(dt: pd.Timestamp) -> Optional[str]:
    """April 2025 -> 'FY 2025-26'. March 2026 -> 'FY 2025-26'."""
    if pd.isna(dt):
        return None
    fy_start = dt.year if dt.month >= 4 else dt.year - 1
    return f"FY {fy_start}-{str(fy_start + 1)[-2:]}"


def _half_year_label(dt: pd.Timestamp) -> Optional[str]:
    """April-Sept -> H1, Oct-March -> H2 (financial-year halves)."""
    if pd.isna(dt):
        return None
    return "H1" if dt.month in range(4, 10) else "H2"


def _looks_like_footer(customer_val: object) -> bool:
    """Rows like 'Grand Total' / 'Closing Balance' aren't real transactions."""
    if pd.isna(customer_val):
        return False
    text = str(customer_val).strip().lower()
    return any(kw in text for kw in ("grand total", "closing balance", "total"))


def _drop_blank_key_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    Drop rows where BOTH date and customer are blank - these are almost
    always a trailing grand-total/footer row (no text label, just a lone
    number) or a genuinely empty spacer row. Real transaction and line-item
    rows always carry at least a customer/particulars value, so this never
    removes legitimate data.
    """
    if "date" not in df.columns or "customer" not in df.columns:
        return df
    blank_mask = df["date"].isna() & df["customer"].isna()
    return df.loc[~blank_mask].copy()


def _rename_to_canonical(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """Rename mapped columns to canonical names; leave unmapped columns as-is."""
    return df.rename(columns=mapping)


def _finalize_common(df: pd.DataFrame) -> pd.DataFrame:
    """Steps shared by both pipelines once row_type/dates/flags exist."""
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    if "quantity" in df.columns:
        df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce")
    df["sales_value"] = pd.to_numeric(df["sales_value"], errors="coerce")

    df["financial_year"] = df["date"].apply(_financial_year_label)
    df["half_year"] = df["date"].apply(_half_year_label)

    # Ensure every canonical column exists even if the source lacked it,
    # so downstream code never has to defensively check `in df.columns`.
    for col in CANONICAL_ORDER:
        if col not in df.columns:
            df[col] = np.nan

    ordered = CANONICAL_ORDER + [c for c in df.columns if c not in CANONICAL_ORDER]
    return df[ordered]


# ---------------------------------------------------------------------------
# Path A: sheet is already cleaned (has a `row_type` column)
# ---------------------------------------------------------------------------

def _clean_precleaned(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    df = _rename_to_canonical(df, mapping)

    # Row Type may already say "Footer/Total (excluded from analysis)" -
    # normalize to just drop those rows outright, they're not data.
    if "row_type" in df.columns:
        is_footer = df["row_type"].astype(str).str.contains(
            "footer|total", case=False, na=False
        )
        df = df.loc[~is_footer].copy()
        df["row_type"] = df["row_type"].replace(
            {"Transaction": "Transaction", "Line Item": "Line Item"}
        )

    df["is_cancelled"] = df.get("customer", pd.Series(dtype=object)).astype(str).str.contains(
        "cancel", case=False, na=False
    )
    df["is_foc"] = df.get("voucher_type", pd.Series(dtype=object)).astype(str).str.contains(
        "foc|sample", case=False, na=False
    )

    return _finalize_common(df)


# ---------------------------------------------------------------------------
# Path B: raw Tally-style export, needs full cleaning
# ---------------------------------------------------------------------------

def _clean_raw(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    df = _rename_to_canonical(df, mapping)
    df = _drop_blank_key_rows(df)

    # 1. Drop obvious footer/total rows before anything else - they'd
    #    otherwise get treated as a "Transaction" and inflate sales.
    if "customer" in df.columns:
        footer_mask = df["customer"].apply(_looks_like_footer) & df["date"].isna()
        df = df.loc[~footer_mask].copy()

    # 2. Tag Transaction vs Line Item: a real Tally transaction row always
    #    carries a Date; its line-item rows (below it) leave Date blank.
    df["row_type"] = np.where(df["date"].notna(), "Transaction", "Line Item")

    # 3. Group consecutive rows into one voucher block per Transaction row,
    #    then forward-fill the header-level fields into that block's line
    #    items (Date, Voucher Type, Invoice No., GSTIN, PAN, Narration).
    group_id = (df["row_type"] == "Transaction").cumsum()
    ffill_cols = [
        c for c in ["date", "voucher_type", "invoice_number", "gstin", "customer"]
        if c in df.columns
    ]
    # Only forward-fill customer/date within the SAME voucher group - a
    # line item's "customer" should inherit the transaction's customer,
    # but we must not bleed across groups.
    for col in ffill_cols:
        df[col] = df.groupby(group_id)[col].transform(lambda s: s.ffill())

    # 4. Flag cancelled / FOC based on the now-filled header fields.
    df["is_cancelled"] = df["customer"].astype(str).str.contains(
        "cancel", case=False, na=False
    )
    df["is_foc"] = df.get("voucher_type", pd.Series(dtype=object)).astype(str).str.contains(
        "foc|sample", case=False, na=False
    )

    return _finalize_common(df)


# ---------------------------------------------------------------------------
# Path C: Tally "Day Book" double-entry export (Debit/Credit columns
# instead of a single Value column - no dedicated GSTIN or Quantity column
# either, since item-level detail is squeezed into unlabeled columns that
# shift position depending on row type and aren't reliably recoverable).
# ---------------------------------------------------------------------------

def _clean_daybook(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    df = _rename_to_canonical(df, mapping)
    df = _drop_blank_key_rows(df)

    # A transaction row is any row carrying a voucher/invoice number - the
    # customer's total invoice amount sits in Debit on that exact row.
    # Every other row (tax lines, "Sales Local @X%" lines, item detail,
    # rounding adjustments) is a Line Item and never counted toward revenue.
    df["row_type"] = np.where(df["invoice_number"].notna(), "Transaction", "Line Item")
    df["sales_value"] = np.where(df["row_type"] == "Transaction", df.get("debit"), np.nan)

    # Forward-fill date/customer within each voucher block, same grouping
    # approach as the raw pipeline.
    group_id = (df["row_type"] == "Transaction").cumsum()
    for col in ["date", "customer"]:
        if col in df.columns:
            df[col] = df.groupby(group_id)[col].transform(lambda s: s.ffill())

    # This format has no dedicated Voucher Type column populated with real
    # values (Tally's export shifts item amounts into that column position
    # instead), so cancelled/FOC detection relies on the Particulars text.
    df["is_cancelled"] = df["customer"].astype(str).str.contains("cancel", case=False, na=False)
    df["is_foc"] = df["customer"].astype(str).str.contains("foc|sample", case=False, na=False)

    return _finalize_common(df)

def _build_quality_report(df: pd.DataFrame) -> DataQualityReport:
    txn = df[df["row_type"] == "Transaction"]
    valid_txn = txn[~txn["is_cancelled"] & ~txn["is_foc"]]

    gstin_present = df["gstin"].notna() & (df["gstin"].astype(str).str.strip() != "")
    invalid_gstin = gstin_present & ~df["gstin"].apply(is_valid_gstin_format)

    dup_mask = df.duplicated(
        subset=[c for c in ["date", "invoice_number", "sales_value"] if c in df.columns],
        keep=False,
    )

    fy_list = sorted(
        [fy for fy in df["financial_year"].dropna().unique().tolist()]
    )

    return DataQualityReport(
        total_rows=len(df),
        valid_transactions=len(valid_txn),
        cancelled_transactions=int(txn["is_cancelled"].sum()),
        foc_transactions=int(txn["is_foc"].sum()),
        footer_rows_excluded=0,  # already dropped before this point; see warnings
        duplicate_rows=int(dup_mask.sum()),
        missing_dates=int(df["date"].isna().sum()),
        missing_customers=int(df["customer"].isna().sum()) if "customer" in df.columns else 0,
        missing_gstin=int((~gstin_present).sum()),
        missing_values=int(df["sales_value"].isna().sum()),
        missing_quantities=int(df["quantity"].isna().sum()) if "quantity" in df.columns else 0,
        invalid_gstins=int(invalid_gstin.sum()),
        financial_years=fy_list,
    )


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def clean_data(load_result: LoadResult) -> CleanResult:
    """
    Run the appropriate cleaning pipeline based on what data_loader.py found.
    """
    warnings: list[str] = []

    if not load_result.is_valid:
        return CleanResult(
            dataframe=pd.DataFrame(columns=CANONICAL_ORDER),
            quality=DataQualityReport(),
            warnings=[f"Missing required fields: {', '.join(load_result.missing_required)}"],
        )

    raw_df = load_result.dataframe.copy()
    mapped_fields = set(load_result.column_mapping.values())
    is_daybook_format = "sales_value" not in mapped_fields and "debit" in mapped_fields and "credit" in mapped_fields

    if is_daybook_format:
        df = _clean_daybook(raw_df, load_result.column_mapping)
        warnings.append(
            "This file uses a Debit/Credit ledger format (Tally Day Book export) rather than a "
            "single Sales Value column. Sales value was derived from the Debit amount on each "
            "transaction row. Quantity and GSTIN were not available in this format, so quantity/ASP "
            "and geographic analysis are unavailable for this file."
        )
    elif load_result.likely_precleaned:
        df = _clean_precleaned(raw_df, load_result.column_mapping)
    else:
        df = _clean_raw(raw_df, load_result.column_mapping)
        warnings.append(
            "Sheet did not include a Row Type column - Transaction/Line Item "
            "tagging and forward-fill were performed automatically."
        )

    if "customer" not in load_result.column_mapping.values():
        warnings.append("No customer column detected - customer-level analysis will be unavailable.")
    if "gstin" not in load_result.column_mapping.values():
        warnings.append("No GSTIN column detected - geographic analysis will be unavailable.")
    if "quantity" not in load_result.column_mapping.values():
        warnings.append("No quantity column detected - quantity/ASP analysis will be unavailable.")

    quality = _build_quality_report(df)

    return CleanResult(dataframe=df, quality=quality, warnings=warnings)


def is_valid_sale(df: pd.DataFrame) -> pd.Series:
    """
    Boolean mask for rows that should count toward normal revenue KPIs:
    Transaction-level, not cancelled, not FOC.
    Use this everywhere a KPI/chart sums sales_value or counts invoices.
    """
    return (
        (df["row_type"] == "Transaction")
        & (~df["is_cancelled"].fillna(False))
        & (~df["is_foc"].fillna(False))
    )