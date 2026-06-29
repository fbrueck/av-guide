"""AV-guide digitalization pipeline (deterministic tools).

Claude Code is the orchestrator: the `/digitalize` command drives the run,
executing these deterministic tools via Bash and delegating per-page LLM work
to subagents (`ocr-cleaner`, `route-extractor`).

Deterministic tools in this package:
  * extract — pull the embedded OCR text layer out of the PDF (PyMuPDF)
  * plan    — list/batch the pages that still need cleaning or structuring
  * merge   — combine per-page route JSON into the final routes.jsonl
"""
