"""
Load extracted statement data from S3 Excel for mapping pipeline.
"""
from __future__ import annotations

import io
import re
from datetime import date
from typing import Any

import pandas as pd

from app.services.storage import get_s3_client
from app.config import get_settings


def parse_year_from_column(col: str) -> str | None:
    """Extract year from column like '2025 (Rm)' or '2024 (Rm)'."""
    m = re.match(r"^(\d{4})", str(col).strip())
    return m.group(1) if m else None


def load_extraction_from_file(file_path: str) -> dict[str, list[dict[str, Any]]]:
    """
    Load extraction Excel from local file path. Same structure as load_extraction_from_s3.
    Used for gold tests and deterministic runs.
    """
    xl = pd.ExcelFile(file_path)
    result: dict[str, list[dict[str, Any]]] = {}
    for sheet in xl.sheet_names:
        if sheet == "Summary":
            continue
        df = pd.read_excel(xl, sheet_name=sheet)
        rows = df.to_dict(orient="records")
        for r in rows:
            for k, v in r.items():
                if pd.isna(v):
                    r[k] = None
                elif isinstance(v, float) and k == "raw_label":
                    r[k] = str(int(v)) if v == int(v) else str(v)
            r["raw_label"] = str(r.get("raw_label") or "").strip()
        result[sheet] = rows
    return result


def load_extraction_from_s3(excel_key: str) -> dict[str, list[dict[str, Any]]]:
    """
    Download Excel from S3 and return {sheet_name: [row_dicts]}.
    Row dict has: page, line_no, raw_label, note, section, and value cols by year.
    """
    import logging
    log = logging.getLogger(__name__)
    client = get_s3_client()
    bucket = get_settings().object_storage_bucket
    try:
        resp = client.get_object(Bucket=bucket, Key=excel_key)
        buf = io.BytesIO(resp["Body"].read())
    except Exception as e:
        try:
            from botocore.exceptions import ClientError
            if isinstance(e, ClientError):
                err_code = e.response.get("Error", {}).get("Code", "")
                if err_code == "NoSuchKey":
                    raise FileNotFoundError(f"Extraction Excel not found in S3: {excel_key}") from e
        except ImportError:
            pass
        log.exception("S3 get_object failed for %s: %s", excel_key, e)
        raise RuntimeError(f"Failed to load extraction from S3: {excel_key}") from e
    xl = pd.ExcelFile(buf)
    result: dict[str, list[dict[str, Any]]] = {}
    for sheet in xl.sheet_names:
        if sheet == "Summary":
            continue
        df = pd.read_excel(xl, sheet_name=sheet)
        rows = df.to_dict(orient="records")
        # Normalize: handle NaN, ensure raw_label is str
        for r in rows:
            for k, v in r.items():
                if pd.isna(v):
                    r[k] = None
                elif isinstance(v, float) and k == "raw_label":
                    r[k] = str(int(v)) if v == int(v) else str(v)
            r["raw_label"] = str(r.get("raw_label") or "").strip()
        result[sheet] = rows
    return result


def extraction_to_flat_rows(
    extraction: dict[str, list[dict[str, Any]]],
    statement_type_from_sheet: dict[str, str],
) -> list[dict[str, Any]]:
    """
    Flatten extraction into rows with: sheet, statement_type, raw_label, year, value, page, note, section.
    """
    flat: list[dict[str, Any]] = []
    for sheet_name, rows in extraction.items():
        stmt_type_hint = statement_type_from_sheet.get(sheet_name, sheet_name.split("_")[0])
        for row in rows:
            raw_label = row.get("raw_label") or ""
            if not raw_label:
                continue
            base = {
                "sheet": sheet_name,
                "statement_type": stmt_type_hint,
                "raw_label": raw_label,
                "page": row.get("page"),
                "line_no": row.get("line_no"),
                "note": row.get("note"),
                "section": row.get("section"),
            }
            for col, val in row.items():
                if str(col).lower() in ("page", "line_no", "raw_label", "note", "section", "sheet", "statement_type"):
                    continue
                year = parse_year_from_column(col)
                if year and val is not None:
                    try:
                        v = float(val)
                    except (TypeError, ValueError):
                        continue
                    flat.append({**base, "year": year, "value": v})
    return flat
