# `sample` — committed parse-routes test fixture

A tiny, self-contained guide that **ships with the repo** (its `data/` is
un-ignored in `.gitignore`, unlike every real guide). It exists so tests and
experiments have real, representative pages to run against without needing the
full, gitignored guide data.

## Why it's committable

The pages are a verbatim slice of the *Alpenvereinsführer Karwendel*
(Klier/Walter, 16. Auflage), publicly shared by Rother/DAV with no usage
restriction.

## The slice

Pages **145–150** of the source — the **Großkarspitzen** place group — kept at
their **real source stem numbers** (`page_0145`..`page_0150`), not renumbered.

- **Valid range.** It starts on a Place heading (`1950 Großkarspitzen`, top of
  page 0145) — the book is place-first, so a page that opens with a Place is a
  clean segmentation boundary — and ends right before the next place group
  (`2070 Bäralpikopf`, page 0151). So the six pages form a complete, extractable
  unit: clean → extract → merge → export runs end-to-end on it.
- All six are non-sketch, prose-dense pages with route Randziffern
  (`I 1971`, `I 2011`, `I 2021`, …) and entries that span page breaks (pages
  0147 and 0150 open mid-description) — real material for exercising the
  cross-page extractor and the within-paragraph reflow.

## Contents

```
config.yml                                # id: sample, real bibliographic facts
data/parse-routes/
  01_raw/
    manifest.jsonl                        # the 6 real manifest records, verbatim
    pages/page_0145..0150.txt             # raw OCR input (Stage 1 output)
```

Only the raw input ships. The pipeline reads `01_raw/`; run it with
`--guide sample` to produce the later stages locally (`02_clean` via the
`ocr-cleaner`, then `03_structured`). No PDF ships, so never run
`pipeline.extract` for this guide — `01_raw` is committed directly.

## Used for

- **The local Ollama bake-off (#150).** Run a candidate Ollama model on
  `01_raw/pages/` and score its output against the reference clean produced by
  running the current `ocr-cleaner` over the same pages: does it reproduce the
  German OCR repair and the reflow-vs-structure behaviour (prose joined into
  flowing paragraphs, every Randziffer / heading / grade line kept on its own
  line)?
- A general, real-data fixture for parse-routes tests.
