"""Stage 1 — deterministic text extraction.

Pulls the embedded OCR text layer out of the PDF with PyMuPDF (no LLM, no
network). Writes one UTF-8 text file per page plus a JSONL manifest of
per-page metadata used by the later stages.

Run:  python -m pipeline.extract --guide <id>
"""

from __future__ import annotations

import argparse
import json

import fitz  # PyMuPDF

from .config import GuideConfig, load_guide, page_name
from .records import PageMeta


def _largest_image_dims(doc: fitz.Document, page: fitz.Page) -> tuple[int, int] | None:
    dims: list[tuple[int, int]] = []
    for img in page.get_images(full=True):
        info = doc.extract_image(img[0])
        dims.append((info["width"], info["height"]))
    return max(dims, key=lambda d: d[0] * d[1]) if dims else None


def extract(cfg: GuideConfig) -> list[PageMeta]:
    cfg.raw_pages.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(cfg.pdf)
    records: list[PageMeta] = []

    for i, page in enumerate(doc):
        text = page.get_text("text")
        stripped = text.strip()
        images = page.get_images(full=True)
        dims = _largest_image_dims(doc, page)

        stem = page_name(i)
        (cfg.raw_pages / f"{stem}.txt").write_text(text, encoding="utf-8")

        records.append(
            PageMeta(
                page=i + 1,
                stem=stem,
                char_count=len(stripped),
                rotation=page.rotation,
                n_images=len(images),
                largest_image=dims,
                # Low text + a full-page image == a scan of a sketch/diagram/cover.
                is_sketch=len(stripped) < cfg.min_text_chars,
            )
        )

    cfg.manifest.parent.mkdir(parents=True, exist_ok=True)
    with cfg.manifest.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r.to_dict(), ensure_ascii=False) + "\n")

    doc.close()
    return records


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Read the OCR text layer out of a guide's PDF."
    )
    ap.add_argument("--guide", required=True, help="Guide id (guides/<id>/config.yml).")
    args = ap.parse_args()
    cfg = load_guide(args.guide)

    records = extract(cfg)
    total_chars = sum(r.char_count for r in records)
    sketches = sum(r.is_sketch for r in records)
    print(f"Extracted {len(records)} pages -> {cfg.raw_pages}")
    print(f"  text pages: {len(records) - sketches} | image/sketch pages: {sketches}")
    print(f"  total chars: {total_chars:,}  (~{total_chars // 6:,} words)")
    print(f"  manifest: {cfg.manifest}")


if __name__ == "__main__":
    main()
