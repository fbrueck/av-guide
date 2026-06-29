"""Shared paths and constants for the AV-guide digitalization pipeline."""
from __future__ import annotations

from pathlib import Path

# Repo root = parent of the `pipeline/` package.
ROOT = Path(__file__).resolve().parent.parent

PDF_PATH = ROOT / "Wetterstein_Beulke_4_Auflage_1996.pdf"

DATA = ROOT / "data"
RAW_DIR = DATA / "01_raw"          # deterministic pymupdf extraction
CLEAN_DIR = DATA / "02_clean"      # LLM-cleaned OCR text
STRUCT_DIR = DATA / "03_structured"  # parsed route records

RAW_PAGES = RAW_DIR / "pages"
CLEAN_PAGES = CLEAN_DIR / "pages"
STRUCT_PARTS = STRUCT_DIR / "parts"   # one <stem>.json per structured page (resumability unit)
ROUTES_DIR = STRUCT_DIR / "routes"    # one JSON file per route (final artifact)
ROUTES_JSONL = STRUCT_DIR / "routes.jsonl"  # combined index of all routes

MANIFEST = RAW_DIR / "manifest.jsonl"  # one JSON record per page (metadata)

# Pages with fewer than this many characters of OCR text are treated as
# image/sketch pages (covers, Anstiegsskizzen) and passed through unchanged.
MIN_TEXT_CHARS = 200


def page_name(index: int) -> str:
    """Zero-padded, 1-based page file stem, e.g. page_0001."""
    return f"page_{index + 1:04d}"
