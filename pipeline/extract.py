"""Stage 1 — deterministic text extraction.

Pulls the embedded OCR text layer out of the PDF with PyMuPDF (no LLM, no
network). Writes one UTF-8 text file per page plus a JSONL manifest of
per-page metadata used by the later stages.

Run:  python -m pipeline.extract
"""
from __future__ import annotations

import json

import fitz  # PyMuPDF

from . import config


def _largest_image_dims(doc: fitz.Document, page: fitz.Page) -> tuple[int, int] | None:
    dims = []
    for img in page.get_images(full=True):
        info = doc.extract_image(img[0])
        dims.append((info["width"], info["height"]))
    return max(dims, key=lambda d: d[0] * d[1]) if dims else None


def extract() -> list[dict]:
    config.RAW_PAGES.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(config.PDF_PATH)
    records: list[dict] = []

    for i, page in enumerate(doc):
        text = page.get_text("text")
        stripped = text.strip()
        images = page.get_images(full=True)
        dims = _largest_image_dims(doc, page)

        stem = config.page_name(i)
        (config.RAW_PAGES / f"{stem}.txt").write_text(text, encoding="utf-8")

        record = {
            "page": i + 1,
            "stem": stem,
            "char_count": len(stripped),
            "rotation": page.rotation,
            "n_images": len(images),
            "largest_image": dims,
            # Low text + a full-page image == a scan of a sketch/diagram/cover.
            "is_sketch": len(stripped) < config.MIN_TEXT_CHARS,
        }
        records.append(record)

    config.MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with config.MANIFEST.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    doc.close()
    return records


def main() -> None:
    records = extract()
    total_chars = sum(r["char_count"] for r in records)
    sketches = sum(r["is_sketch"] for r in records)
    print(f"Extracted {len(records)} pages -> {config.RAW_PAGES}")
    print(f"  text pages: {len(records) - sketches} | image/sketch pages: {sketches}")
    print(f"  total chars: {total_chars:,}  (~{total_chars // 6:,} words)")
    print(f"  manifest: {config.MANIFEST}")


if __name__ == "__main__":
    main()
