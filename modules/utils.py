"""
utils.py
--------
Shared utilities used across the Sales Analytics Dashboard.

1. Fuzzy column-name mapping: turns messy, inconsistently-named spreadsheet
   headers (e.g. "Party Name", "Particulars", "Customer Name") into a fixed
   set of canonical field names that the rest of the app relies on.

2. GST state-code lookup: extracts the state from a GSTIN and maps it to a
   human-readable state name for geographic analysis.

Nothing in this module reads a file or touches Streamlit — it is pure logic
so it can be unit-tested and reused by data_loader.py / data_cleaner.py.
"""

from __future__ import annotations

import re
import difflib
from typing import Optional


# ---------------------------------------------------------------------------
# 1. CANONICAL COLUMN MAPPING
# ---------------------------------------------------------------------------
# Canonical field name -> list of known real-world header aliases.
# Aliases are stored lowercase with punctuation/spacing already normalized;
# the matching function normalizes incoming headers the same way before
# comparing, so "GSTIN/UIN", "GST No.", "gstin" all resolve correctly.

CANONICAL_COLUMNS: dict[str, list[str]] = {
    "date": [
        "date", "voucher date", "invoice date", "sales date", "txn date",
        "transaction date",
    ],
    "customer": [
        "particulars", "customer", "customer name", "party", "party name",
        "buyer", "buyer name", "account", "ledger", "ledger name",
    ],
    "consignee_address": [
        "consignee address", "shipping address", "delivery address",
        "address",
    ],
    "voucher_type": [
        "voucher type", "vouchertype", "transaction type", "txn type",
        "type",
    ],
    "invoice_number": [
        "voucher no", "voucher no.", "voucher number", "invoice no",
        "invoice no.", "invoice number", "bill no", "bill no.",
    ],
    "voucher_ref_no": [
        "voucher ref no", "voucher ref. no.", "voucher ref number",
        "reference no", "ref no", "ref no.",
    ],
    "gstin": [
        "gstin/uin", "gstin", "gst no", "gst no.", "gst number", "uin",
    ],
    "pan": [
        "pan no", "pan no.", "pan number", "pan",
    ],
    "narration": [
        "narration", "remarks", "notes", "description",
    ],
    "quantity": [
        "quantity", "qty", "qty.", "units sold",
    ],
    "alt_units": [
        "alt. units", "alt units", "alternate units", "alt unit",
    ],
    "rate": [
        "rate", "unit rate", "price", "unit price",
    ],
    "sales_value": [
        "value", "sales value", "amount", "invoice value", "net value",
        "sale amount", "sales amount",
    ],
    "gross_total": [
        "gross total", "grand total", "total", "invoice total",
    ],
    "row_type": [
        "row type", "rowtype", "record type",
    ],
}

# Fields the app cannot function without.
REQUIRED_FIELDS = {"date", "sales_value"}

# Fields that unlock specific features but are optional.
OPTIONAL_FEATURE_FIELDS = {
    "customer": "Customer-level analysis",
    "gstin": "Geographic analysis",
    "quantity": "Quantity / average-selling-rate analysis",
    "invoice_number": "Invoice-level KPIs",
    "voucher_type": "Cancellation / FOC detection",
    "row_type": "Transaction vs line-item de-duplication",
}


def _normalize(header: object) -> str:
    """Lowercase, strip, and collapse punctuation/whitespace for comparison."""
    if header is None:
        return ""
    text = str(header).lower().strip()
    text = re.sub(r"[./_-]", " ", text)      # treat punctuation as spaces
    text = re.sub(r"\s+", " ", text).strip()  # collapse repeated spaces
    return text


def map_columns(
    actual_columns: list[object],
    fuzzy_cutoff: float = 0.8,
) -> tuple[dict[str, str], list[str]]:
    """
    Map a list of real (messy) spreadsheet headers to canonical field names.

    Parameters
    ----------
    actual_columns : the raw header row from the uploaded sheet, in order.
    fuzzy_cutoff    : similarity threshold (0-1) for the fallback fuzzy match,
                       used only when no exact alias match is found.

    Returns
    -------
    mapping   : {actual_column_name: canonical_field_name} for every column
                that was successfully identified. Columns that don't match
                anything are simply omitted.
    unmatched : list of actual column names that could not be mapped.
    """
    # Build a flat lookup: normalized alias -> canonical field name.
    alias_lookup: dict[str, str] = {}
    for canonical, aliases in CANONICAL_COLUMNS.items():
        for alias in aliases:
            alias_lookup[alias] = canonical

    mapping: dict[str, str] = {}
    unmatched: list[str] = []
    used_canonicals: set[str] = set()

    for col in actual_columns:
        norm = _normalize(col)
        if not norm:
            continue

        # 1. Exact alias match.
        if norm in alias_lookup:
            canonical = alias_lookup[norm]
            if canonical not in used_canonicals:
                mapping[str(col)] = canonical
                used_canonicals.add(canonical)
                continue

        # 2. Fuzzy fallback (handles typos / minor variants not in the alias list).
        close = difflib.get_close_matches(
            norm, alias_lookup.keys(), n=1, cutoff=fuzzy_cutoff
        )
        if close:
            canonical = alias_lookup[close[0]]
            if canonical not in used_canonicals:
                mapping[str(col)] = canonical
                used_canonicals.add(canonical)
                continue

        unmatched.append(str(col))

    return mapping, unmatched


def validate_mapping(mapping: dict[str, str]) -> tuple[bool, list[str]]:
    """
    Check whether a column mapping satisfies the app's minimum requirements.

    Returns
    -------
    is_valid       : False if any REQUIRED_FIELDS are missing.
    missing_fields : list of missing required canonical field names.
    """
    found = set(mapping.values())
    missing = sorted(REQUIRED_FIELDS - found)
    return (len(missing) == 0), missing


def missing_optional_features(mapping: dict[str, str]) -> dict[str, str]:
    """Return {canonical_field: feature_description} for optional fields not found."""
    found = set(mapping.values())
    return {
        field: feature
        for field, feature in OPTIONAL_FEATURE_FIELDS.items()
        if field not in found
    }


# ---------------------------------------------------------------------------
# 2. GST STATE CODES
# ---------------------------------------------------------------------------
# First two digits of a GSTIN identify the state/UT the seller is registered in.

GST_STATE_CODES: dict[str, str] = {
    "01": "Jammu & Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "25": "Daman & Diu",
    "26": "Dadra & Nagar Haveli",
    "27": "Maharashtra",
    "28": "Andhra Pradesh (Old)",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman & Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "97": "Other Territory",
    "99": "Centre Jurisdiction",
}

GSTIN_PATTERN = re.compile(r"^\d{2}[A-Z0-9]{10}[A-Z\d]{3}$")


def extract_state_from_gstin(gstin: object) -> Optional[str]:
    """
    Return the state name for a given GSTIN, or None if the GSTIN is
    missing/malformed. Never raises — callers can treat None as "unknown".
    """
    if gstin is None:
        return None
    text = str(gstin).strip().upper()
    if len(text) < 2 or not text[:2].isdigit():
        return None
    return GST_STATE_CODES.get(text[:2])


def is_valid_gstin_format(gstin: object) -> bool:
    """Loose structural check (15 chars, correct pattern) - not a checksum validator."""
    if gstin is None:
        return False
    text = str(gstin).strip().upper()
    return bool(GSTIN_PATTERN.match(text)) and text[:2] in GST_STATE_CODES