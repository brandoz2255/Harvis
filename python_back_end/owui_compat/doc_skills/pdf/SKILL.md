---
description: Write a finished handout, checklist or report as a harvis-doc that prints to a paged PDF, with ## sections, tables, checklists, math and charts, timelines, cards, quadrants or flows.
---
You were asked to make a PDF. Answer with one sentence, then ONE harvis-doc block, then at most one sentence. Open the block with four backticks and `harvis-doc` (four, so code fences inside survive), close it with four backticks. No second block. Example of a whole answer:

Here is the handout as a PDF.

````harvis-doc
---
kind: pdf
title: Move-In Checklist
outline:
  - Before the move
  - First week
---
# Move-In Checklist
## Before the move
- [ ] Book the elevator
- [ ] Pack a box of essentials
## First week
| Day | Task |
| --- | --- |
| Mon | Set up internet |
| Tue | Meet the neighbors |
````

It is ready to download.

Rules
- The outline has one line per section, in order; each line becomes one `## ` section (`###` inside it).
- The app prints it to paged PDF, so write a finished handout: full paragraphs, short tables, no filler.
- No placeholders, no "TBD", no lorem ipsum.

Rich blocks: use one only where it makes a point clearer than text. Three backticks, one item per line.
```timeline
Planning | Oct 26 | Nov 1
*Go live | Nov 23
```
(span: Label | start | end; milestone: Label | when; `*` marks the key one)
```chart
title: Open findings by host
type: bar
series: Open, Fixed
web01: 7, 2
```
(type: bar, line or pie)
```quadrant
x: Effort
y: Impact
Quick wins: MFA
Big bets: SIEM
Fill-ins: Rename shares
Money pits: Manual rules
```
(four lines, in order: top-left, top-right, bottom-left, bottom-right)
```cards
fw01 | 10.0.0.1 | Firewall
```
```flow
Internet -> fw01 -> web01
```
```csv
Host,Open
web01,7
```
Also available
- Status table cells show as colored chips: Done, In progress, Blocked, At risk, Not started, High, Medium, Low.
- Checklists: `- [ ] item` and `- [x] item`.
- Math: `$$E = mc^2$$`.
- Code: a fence with a language, for example ```bash.

Gotchas
- Never write a `<body>` tag.
- Keep tables narrow (2-4 columns) so they fit the page.
- Put a chart, timeline or diagram inside a `##` section, never before the first one.
