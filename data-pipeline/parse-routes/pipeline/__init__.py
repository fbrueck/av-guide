"""parse-routes pipeline (deterministic tools).

Claude Code is the orchestrator: the `/parse-routes <guide>` command drives the
run, executing these deterministic tools via Bash and delegating per-page LLM
work to subagents (`ocr-cleaner`, `entry-extractor`).

Deterministic tools in this package:
  * extract    — pull the embedded OCR text layer out of the PDF (PyMuPDF)
  * plan       — list/batch the pages that still need cleaning or structuring
  * ids        — normalize book entry ids to the canonical key (`R43`)
  * references — parse inline cross-refs (`Wie R 43`) from Entry prose
  * merge      — key Entries by id, link destination/places, validate → routes.jsonl
  * export     — project Entries onto the route-map contract → routes.json
"""
