"""
data_loader.py
---------------
Handles getting raw data OUT of an uploaded Excel file and into a plain
pandas DataFrame with sensible headers - nothing else. No cleaning,
no de-duplication, no business logic. That belongs to data_cleaner.py.

Two jobs:
1. Pick the right sheet to read (prefer an already-"Cleaned Data" sheet,
   fall back to "Raw Data" / the first sheet otherwise).
2. Find the real header row inside that sheet - Tally-style exports bury
   the actual column headers under several rows of company letterhead.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from modules.utils import map_columns, validate_mapping, _normalize


# ---------------------------------------------------------------------------
# Sheet selection
# ---------------------------------------------------------------------------

# Preference order for sheet names that already contain cleaned data.
_CLEANED_SHEET_ALIASES = ["cleaned data", "clean data", "cleaned", "clean"]
# Preference order for sheet names that hold the untouched export.
_RAW_SHEET_ALIASES = ["raw data", "raw", "sales register", "data"]
# Sheets that are never real data (summary tabs, dashboards, etc).
_IGNORE_SHEET_ALIASES = ["summary", "dashboard", "insights", "readme", "notes"]


def get_sheet_names(file) -> list[str]:
    """Return all sheet names in the uploaded workbook."""
    xls = pd.ExcelFile(file)
    return xls.sheet_names


def choose_target_sheet(sheet_names: list[str]) -> tuple[str, bool]:
    """
    Decide which sheet to treat as the data source.

    Returns
    -------
    sheet_name     : the chosen sheet.
    prefer_cleaned : True if we picked a sheet that looks pre-cleaned
                      (informational only - data_cleaner.py still decides
                      whether it can actually skip cleaning, based on
                      whether a `row_type` column is present).
    """
    normalized = {name: _normalize(name) for name in sheet_names}

    # 1. Look for an already-cleaned sheet first.
    for name, norm in normalized.items():
        if norm in _CLEANED_SHEET_ALIASES:
            return name, True

    # 2. Fall back to an explicit "raw data" style sheet.
    for name, norm in normalized.items():
        if norm in _RAW_SHEET_ALIASES:
            return name, False

    # 3. Otherwise, take the first sheet that isn't an obvious summary/dashboard tab.
    for name, norm in normalized.items():
        if norm not in _IGNORE_SHEET_ALIASES:
            return name, False

    # 4. Last resort: just take the first sheet in the workbook.
    return sheet_names[0], False


# ---------------------------------------------------------------------------
# Header-row detection
# ---------------------------------------------------------------------------

MAX_SCAN_ROWS = 40          # how many rows to scan looking for the header row
MIN_MATCHED_COLUMNS = 3      # a real header row should map at least this many fields


def find_header_row(file, sheet_name: str, max_scan_rows: int = MAX_SCAN_ROWS) -> Optional[int]:
    """
    Scan the top of a sheet to find which row is the real header row.

    Real headers are identified by how many cells in the row successfully
    map to a canonical field name (see utils.map_columns) - letterhead
    text, addresses, and titles won't match anything.

    Returns the 0-indexed row number, or None if no plausible header row
    was found within max_scan_rows.
    """
    preview = pd.read_excel(
        file, sheet_name=sheet_name, header=None, nrows=max_scan_rows
    )

    best_row_idx = None
    best_score = 0

    for row_idx in range(len(preview)):
        row_values = preview.iloc[row_idx].tolist()
        # Skip rows that are mostly empty - can't be a header row.
        non_empty = [v for v in row_values if pd.notna(v)]
        if len(non_empty) < MIN_MATCHED_COLUMNS:
            continue

        mapping, _ = map_columns(row_values)
        score = len(mapping)

        # A good header row should map date + sales_value at minimum, and
        # more mapped fields beats fewer - keep the best one we see.
        if score > best_score:
            best_score = score
            best_row_idx = row_idx

    if best_score >= MIN_MATCHED_COLUMNS:
        return best_row_idx
    return None


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass
class LoadResult:
    dataframe: pd.DataFrame                  # raw dataframe, canonical-mapped columns not yet renamed
    sheet_name: str
    header_row: int
    column_mapping: dict[str, str]           # {original_header: canonical_field}
    unmatched_columns: list[str]
    is_valid: bool
    missing_required: list[str] = field(default_factory=list)
    likely_precleaned: bool = False          # True if a `row_type` column was found


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def load_sales_data(file, sheet_name: Optional[str] = None) -> LoadResult:
    """
    Load an uploaded Excel file into a raw DataFrame with detected headers.

    Parameters
    ----------
    file       : path or file-like object (e.g. Streamlit's UploadedFile).
    sheet_name : force a specific sheet; if None, auto-detect via
                 choose_target_sheet().

    Notes
    -----
    This function does NOT clean the data (no forward-fill, no row-type
    tagging beyond what may already exist in the sheet, no cancelled/FOC
    handling). See data_cleaner.py for that. It only gets you a DataFrame
    with the right header row and tells you which canonical fields were
    found, so the caller (or the Streamlit UI) can decide what to do next.
    """
    sheet_names = get_sheet_names(file)

    if sheet_name is None:
        sheet_name, _ = choose_target_sheet(sheet_names)

    header_row = find_header_row(file, sheet_name)
    if header_row is None:
        # Could not find a plausible header row at all.
        return LoadResult(
            dataframe=pd.DataFrame(),
            sheet_name=sheet_name,
            header_row=-1,
            column_mapping={},
            unmatched_columns=[],
            is_valid=False,
            missing_required=["date", "sales_value"],
        )

    df = pd.read_excel(file, sheet_name=sheet_name, header=header_row)
    # Drop fully-empty columns/rows that sometimes trail Excel exports.
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="all").reset_index(drop=True)

    mapping, unmatched = map_columns(list(df.columns))
    is_valid, missing_required = validate_mapping(mapping)
    likely_precleaned = "row_type" in mapping.values()

    return LoadResult(
        dataframe=df,
        sheet_name=sheet_name,
        header_row=header_row,
        column_mapping=mapping,
        unmatched_columns=unmatched,
        is_valid=is_valid,
        missing_required=missing_required,
        likely_precleaned=likely_precleaned,
    )