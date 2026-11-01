"""CSV parsing + row-level validation (pure pandas, no DB)."""
from __future__ import annotations

import io
import re
import warnings
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from app.constants import REQUIRED_COLUMNS

ALIASES = {
    "material": "material_name", "item": "material_name", "name": "material_name",
    "qty_consumed": "quantity_consumed", "consumption": "quantity_consumed", "quantity": "quantity_consumed",
    "stock": "current_stock", "lead_time": "lead_time_days", "cost": "unit_cost",
    "id": "material_id",
}
MAX_REPORTED_ERRORS = 500


class CsvFormatError(ValueError):
    """The file is not a usable CSV (empty, unreadable, or missing required columns)."""


@dataclass
class ParsedCsv:
    valid: pd.DataFrame            # normalised, validated rows
    errors: list[dict]             # [{row, error}] (capped)
    total_rows: int
    invalid_rows: int
    malformed_lines: int = 0
    extras: dict = field(default_factory=dict)


def _norm_col(c: str) -> str:
    c = re.sub(r"[^a-z0-9]+", "_", str(c).strip().lower()).strip("_")
    return ALIASES.get(c, c)


def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    raise CsvFormatError("Could not decode file; save it as UTF-8 CSV.")


def read_csv_bytes(content: bytes) -> tuple[pd.DataFrame, int]:
    """Read everything as text so we can validate and report row by row."""
    text = _decode(content)
    if not text.strip():
        raise CsvFormatError("The CSV file is empty.")
    first = text.splitlines()[0]
    counts = {d: first.count(d) for d in (",", ";", "\t")}
    delim = max(counts, key=counts.get) if max(counts.values()) > 0 else ","
    bad: list = []
    try:
        df = pd.read_csv(
            io.StringIO(text), sep=delim, dtype=str, keep_default_na=False,
            engine="python", skipinitialspace=True,
            on_bad_lines=lambda line: bad.append(line) or None,
        )
    except Exception as exc:  # noqa: BLE001
        raise CsvFormatError(f"Invalid CSV format: {exc}") from exc
    return df, len(bad)


def _parse_dates(raw: pd.Series) -> pd.Series:
    s = raw.astype(str).str.strip()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        dt = pd.to_datetime(s, errors="coerce", format="ISO8601")
        retry = dt.isna() & s.ne("")
        if retry.any():
            dt.loc[retry] = pd.to_datetime(s[retry], errors="coerce", format="mixed", dayfirst=True)
    try:
        dt = dt.dt.tz_localize(None)
    except (TypeError, AttributeError):
        pass
    return dt


def parse_and_validate(content: bytes, today: date) -> ParsedCsv:
    df, malformed = read_csv_bytes(content)
    df.columns = [_norm_col(c) for c in df.columns]
    df = df.loc[:, ~pd.Index(df.columns).duplicated()]  # keep first of duplicate columns
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise CsvFormatError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"Required columns: {', '.join(REQUIRED_COLUMNS)}."
        )
    df = df.reset_index(drop=True)
    row_no = np.arange(len(df)) + 2  # header is line 1

    name = df["material_name"].astype(str).str.strip()
    dt = _parse_dates(df["date"])
    qty = pd.to_numeric(df["quantity_consumed"].astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")

    err = pd.Series("", index=df.index, dtype=object)
    rules = [
        (name.eq("") | name.str.lower().isin(["nan", "none", "null"]), "Missing material_name"),
        (dt.isna(), "Invalid date format"),
        (dt.dt.normalize() > pd.Timestamp(today), "Date is in the future"),
        (qty.isna() | ~np.isfinite(qty.fillna(np.nan)), "Invalid quantity_consumed (not a number)"),
        (qty <= 0, "quantity_consumed must be greater than 0"),
    ]
    for cond, msg in rules:
        err = err.mask((err == "") & cond.fillna(True), msg)

    ok = err == ""
    errors = [{"row": int(r), "error": e} for r, e in zip(row_no[~ok.to_numpy()], err[~ok]) ][:MAX_REPORTED_ERRORS]
    if malformed:
        errors.append({"row": None, "error": f"{malformed} malformed line(s) skipped (wrong number of fields)"})

    valid = pd.DataFrame(
        {
            "row": row_no[ok.to_numpy()],
            "material_name": name[ok].to_numpy(),
            "date": dt[ok].dt.date.to_numpy(),
            "quantity_consumed": qty[ok].round(4).to_numpy(),
        }
    )
    for col in ("material_id", "unit"):
        valid[col] = df[col].astype(str).str.strip()[ok].to_numpy() if col in df.columns else ""
    for col in ("current_stock", "lead_time_days", "unit_cost"):
        if col in df.columns:
            num = pd.to_numeric(df[col].astype(str).str.replace(",", "", regex=False).str.strip(), errors="coerce")
            valid[col] = num[ok].to_numpy()
        else:
            valid[col] = np.nan
    return ParsedCsv(
        valid=valid,
        errors=errors,
        total_rows=len(df) + malformed,
        invalid_rows=int((~ok).sum()) + malformed,
        malformed_lines=malformed,
    )
