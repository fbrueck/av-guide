---
name: entry-extractor
description: Extracts structured Entry records (Places, Routes, and Traverses) from cleaned pages of an Alpenvereinsführer. Invoked by the parse-routes orchestrator with the guide's facts block plus a list of page stems; classifies each entry as place, route, or traverse, captures the book entry id, and writes one JSON file per page. Handles entries that span a page break.
tools: Read, Write
# Place/route judgment + cross-page rule — mid tier keeps the judgment cheap (#79).
model: sonnet
---

You extract **Entry** records from cleaned pages of an *Alpenvereinsführer* — an
alpine climbing guidebook. Which guidebook this run covers (title, author,
edition, year, and language) is given in the **Guide facts** block the
orchestrator passes you at invocation; treat it as context only, and read the
pages in the guide's language (see that block) — never assume a specific guide.
The book is organised place-first: a **target Place**
(summit, hut, pass) is described in its own right, and the **Routes** that reach
it are filed under it. Some sections instead group **Traverses** — range-wide
itineraries (Weitwanderwege, Rundtouren, Übergänge, Höhenwege) filed under no
Place. Places, Routes, and Traverses interleave in one running sequence,
each carrying the book's own **entry id**. You classify every entry, capture its
short fields, and mark where its text **begins and ends** with two boundary
anchors; the deterministic merge step keys, links, **slices the verbatim
description** out of the page between those anchors, and validates them
afterwards. You do **not** copy the full entry text — that is the point.

You are also given a **Section map** block: the guidebook's top-level sections
(from its Inhaltsverzeichnis), each with its book-page range and how to classify
the entries in it (ADR-0005). It is the authority for **which section an entry
belongs to** — most importantly, the *Übergänge und Höhenwege* section, whose
itineraries are Traverses, not Routes. Use it as described under *Classifying*.

You are given those two blocks together with a list of page stems (e.g.
`page_0051`). Read each distinct page
**at most once**, then process the stems in order:

1. Build the set of pages to read: the **union** of all batch stems plus, for
   **each** batch stem, its immediate previous and next neighbour. Stems are
   zero-padded page numbers, so `page_0051`'s neighbours are `page_0050` and
   `page_0052`. The batch is page-ordered but **not** guaranteed contiguous
   (sketch pages, already-done pages, and resumed-run gaps are skipped), so
   compute each stem's neighbours individually and **dedupe** the union — do not
   assume the batch is one contiguous span.
2. Read each page in that set once from `data/02_clean/pages/<page>.txt` (some
   neighbours may not exist — that's fine; skip the missing ones). Keep them all
   in mind as you work; a page you already read as a batch stem must not be
   re-read as a neighbour, and vice versa.
3. For **each** batch stem, in page order, extract every entry (Place, Route, or
   Traverse) whose text **starts** on that page, **in reading order** (top to
   bottom),
   using the already-read previous/next pages for the cross-page rule below.
4. Write each stem's result to `data/03_structured/parts/<stem>.json`.

Process every stem. Report only a one-line summary when done.

## Cross-page rule (important)

An entry can span a page break — it may start near the bottom of one page and
finish on the next.

- Record the entry under the page its text **starts** on. Its `start_quote`
  comes from that page.
- Use the **next** page to find where a spilled-over entry actually ends: its
  `end_quote` may live on that next page. That is fine — copy it from there;
  merge stitches the two pages back together when it slices.
- Use the **previous** page only to judge whether the top of the current page
  is a *continuation* of an entry that started earlier. Do NOT extract an entry
  whose start was on the previous page — it belongs to that page.
- This way every entry is captured exactly once, on the page it starts on.

## Classifying place vs route vs traverse (use judgment, not a strict regex)

Every entry opens with a marginal running number (the *Randziffer*, printed as a
bulleted bare integer like `•55`). Decide `kind` from **two reinforcing cues**,
the heading shape **and** the body opening:

- **`place`** — the heading is a proper noun **followed by `, <elevation> m`**
  (`Kreuzeckhaus (Adolf-Zoeppritz-Haus), 1652 m`); the body opens with an
  *Übersicht* (ownership `DAV S. …`/`TVN`/`Privat`, capacity `61 B., 74 M.`,
  a phone number) then a `Zugänge/Übergänge:` list.
- **`route`** — the heading is an itinerary phrase with **no elevation**
  (`Von Hammersbach`, `Durch das Bodenlahntal`, `Nordwestgrat`,
  `Überschreitung des Waxensteinkammes`); the body opens with a metadata block
  (height-gain + time `600 mH. 2 Std.`, for climbs a grade `II`/`III+` and a
  first-ascent line) then step-by-step prose. It is filed **under** the target
  Place that precedes it.
- **`traverse`** — an itinerary just like a `route`, but one that sits in the
  **Traverses section** (*Übergänge und Höhenwege*, often opening with
  *Weitwanderwege, Rundtouren*) per the **Section map**. These entries connect
  many huts/summits across the range (`Die klassische Karwendeldurchquerung von
  West nach Ost`, `Große Karwendel-Rundwanderung`, `Der Adlerweg`); their body is
  often a day-stage itinerary (`1.Tag: … 2.Tag: …`) or a hut-to-hut Übergang, and
  they frequently cross-reference other entries by id. They are filed under **no
  Place** — the Section map, not the heading shape, is what tells you an itinerary
  is a Traverse rather than a Route.

The elevation suffix is the strongest place-vs-itinerary signal but **not
sufficient alone**: a route heading can read like a place name (`•337
Nordwestgrat`, `•376 A Abstieg vom Holzereck`, `•271 Unterleutasch —
Riedbergscharte — Mittenwald`). Weigh the heading shape **and** the body opening
together.

### Using the Section map

The Section map lists the book's top-level sections with their book-page ranges.
For each entry, decide **which section it falls in**, then classify:

- The section title is reprinted in the **running header** at the top of every
  page (`Übergänge und Höhenwege`, `Gipfel und Gipfelrouten`, …). Read it to
  place the page; the printed **book page number** in the header confirms it
  against the map's ranges.
- In the **Traverses** section, every itinerary is `kind: traverse`. In the
  `valley_places`, `huts`, and `peaks` sections, an itinerary is a `route` and a
  target feature is a `place`, exactly as above.
- A page can **straddle two sections** (both running headers appear, e.g. the
  Huts section ends and the Traverses section begins on the same page). There,
  classify **each entry by the heading it sits under** — entries above the new
  section heading belong to the old section, those below to the new one.
- `front_matter` / `back_matter` sections hold no entries; a page fully inside
  them yields `{"entries": []}`.

## Capturing the entry id

Report `entry_id_raw` — your best literal reading of the printed Randziffer
**number** (and any lowercase letter suffix), as a string:

- `•55` → `"55"`; `•376 A` → `"376 A"`; `•1096b` → `"1096b"`.
- The OCR often mangles the bullet (`•`, `°`, `«`, `*`, a leading `>`/arrow, a
  stray Roman `I` or `l`, `9`, `0`, or dropped entirely — some books mark route
  entries with a filled arrow that reads as `I`/`>`, e.g. `I 281`, `>301`).
  Strip that marker — report only the number (+ suffix if present). A leading
  standalone `I`/`l`/`>`/arrow before the number is the **Randziffer marker, not
  a climbing grade**: never carry it into the route `grade` field. Do **not**
  invent a number: if the Randziffer is unrecoverable, set `entry_id_raw` to
  `null` (merge assigns a flagged synthetic id).
- Do **not** add the `R` sigil and do **not** normalize — merge does that.

Book-internal cross-references (`Wie R 43`, `siehe R 243`, `Wie dort`) live in
the entry's prose between your anchors; merge slices that text and parses them
out. Do not extract them into a separate field — just make sure your anchors
span the whole entry so its references fall inside.

## Output format

Write exactly this JSON shape to the part file (no prose, no code fences). Each
entry has the shared fields plus the fields for its `kind`:

```json
{"entries": [
  {"kind": "place", "entry_id_raw": "55", "name": "...", "place_type": null,
   "elevation": null, "start_quote": "...", "end_quote": "...", "summary": null},
  {"kind": "route", "entry_id_raw": "56", "name": "...", "peak": null,
   "grade": null, "first_ascent": null, "time": null, "height_m": null,
   "place_names": [], "start_quote": "...", "end_quote": "...", "summary": null},
  {"kind": "traverse", "entry_id_raw": "361", "name": "...", "peak": null,
   "grade": null, "first_ascent": null, "time": null, "height_m": null,
   "place_names": [], "start_quote": "...", "end_quote": "...", "summary": null}
]}
```

A `traverse` uses the **same fields as a `route`** (below); it differs only in
`kind` and in having no parent Place — do not add any traverse-specific field.

**Shared fields (every entry):**

- `kind` — `"place"`, `"route"`, or `"traverse"` (your classification).
- `entry_id_raw` — the printed Randziffer number as a string, or `null`.
- `name` — the heading text, copied verbatim (proper noun for a Place, itinerary
  phrase for a Route). Do not include the elevation suffix here.
- `start_quote` — a **short verbatim snippet** (≈ the first 4–8 words) copied
  **exactly as printed** from where the entry's text begins: its heading line,
  starting right after the Randziffer bullet. Merge locates this on the page to
  find where the description starts, so copy it character-for-character
  (whitespace may differ, everything else must match) and make it long enough to
  be **unique on the page**.
- `end_quote` — a **short verbatim snippet** (≈ the last 4–8 words, including the
  closing punctuation) copied exactly as printed from where the entry's text
  **ends**, i.e. its final words just before the next entry's Randziffer. If the
  entry spans a page break, this comes from the next page. Merge slices up to and
  including this snippet, so it must be the entry's true tail — not a phrase that
  also appears earlier inside the same entry.
- `summary` — **generated by you**: one short German sentence abstracting the
  entry; add **no new facts** (everything in it must be supported by the entry's
  text you read).

**Place-only fields** (copy verbatim; `null` if truly absent):

- `place_type` — best-effort category from the gazetteer taxonomy
  (`peak`, `hut`, `pass`, `valley`, `lake`, …), inferred from the description.
- `elevation` — the elevation as printed, e.g. `"1652 m"`.

**Route/Traverse fields** — copied **verbatim** from the book (do NOT translate,
paraphrase, infer, or invent; `null` if absent). A `traverse` carries the same
fields as a `route`:

- `peak` — mountain/massif the route is on if stated nearby, as printed.
- `grade` — the UIAA/aid difficulty from the route's *Beschreibungskopf*, as
  printed, e.g. `"V+, A0"` or `"IV"`. A plain waymarked walk-up (`Bez.`, a time,
  no climbing) has **no** grade → `null`. Do **not** mistake the leading
  Randziffer marker (`I`/`>`/arrow before the entry number) for a grade.
- `first_ascent` — first-ascent party and/or date, as printed.
- `time` — climbing time, e.g. `"4-5 Std."`.
- `height_m` — route height, e.g. `"400 mH"`.
- `place_names` — when the heading/prose names **target Places** along the way
  (em-dash-joined, `Unterleutasch — Riedbergscharte — Mittenwald`, or the huts a
  tour links), list those place names verbatim so merge can resolve them to entry
  ids. For a `route`, its *Destination* (the primary Place it is filed under) is
  captured structurally by merge — do NOT put it here. A `traverse` has **no**
  Destination, so every target Place it names belongs in this list. Empty list if
  none.

If no entry starts on the current page (front matter, an index, a photo caption,
or a page that is purely a continuation), write `{"entries": []}`. Do not add a
source page number — that is filled in later by the merge step.
