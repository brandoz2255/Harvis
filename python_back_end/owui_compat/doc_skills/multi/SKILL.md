---
description: Make several files in one answer, for example slides, a PDF and a doc on one topic, as one harvis-doc block per file.
---
You were asked for more than one file. Answer with one sentence, then ONE harvis-doc block PER FILE, in the order asked, then at most one sentence. Open each block with four backticks and `harvis-doc`, close it with four backticks. Each block has its own header with its own `kind:` and a different title. Example of a whole answer for slides and a PDF:

Here are the slides and a handout on house cats.

````harvis-doc
---
kind: deck
title: House Cats
outline:
  - Title
  - Why cats sleep so much
---
# House Cats
Living with a cat
---
## Why cats sleep so much
- 12 to 16 hours a day
- Hunters save energy for the chase
````

````harvis-doc
---
kind: pdf
title: House Cats Handout
outline:
  - Summary
  - Daily care
---
# House Cats Handout
## Summary
A cat needs food, water, a clean litter box and play every day.
## Daily care
- [ ] Fresh water
- [ ] Ten minutes of play
````

Both are ready to download.

Rules
- One block for every file asked for, never one block for two files, and never skip one.
- Titles differ, so each file opens in its own panel: "House Cats", "House Cats Handout", "House Cats Notes".
- The outline has one line per part, in order.
- Each file stands alone and is written in full: no "see the slides", no placeholders, no "TBD".

Per kind
- deck: a title slide, then one slide per outline line, separated by a line that is exactly `---`. Each slide starts with `## Title`, then 3-6 short bullets; `Notes:` holds speaker notes.
- pdf: a printed handout. Start with `## Summary`, then short `##` sections, checklists and narrow tables.
- doc: an editable Word document. `##` sections with full paragraphs, lists and tables.
- sheet: only markdown tables, each under a `## Sheet name` heading. Totals are formulas such as `=SUM(B2:B5)`.
