---
description: Write a report, memo, guide, runbook or tracker as a harvis-doc document with ## sections, tables, checklists, code, math and charts, timelines, cards, quadrants or flows.
---
You were asked to make a document. Answer with one sentence, then ONE harvis-doc block, then at most one sentence. Open the block with four backticks and `harvis-doc` (four, so code fences inside survive), close it with four backticks. No second block. Example of a whole answer:

Here is the memo.

````harvis-doc
---
kind: doc
title: Bike Share Pilot Memo
outline:
  - Summary
  - Follow-up
---
# Bike Share Pilot Memo
## Summary
On **Monday** the pilot opened with 20 bikes at two campus stops.
## Follow-up
| Task | Status |
| --- | --- |
| Add a third stop | In progress |
| Order helmets | Done |
````

Let me know if the tone should change.

Rules
- The outline has one line per section, in order; each line becomes one `## ` section (`###` inside it).
- Write full paragraphs with real content. Markdown: lists, tables, **bold**, links.
- No placeholders, no "TBD", no lorem ipsum.

Design
- Start with a Summary section: two to four sentences that give the conclusion, so a reader can stop there.
- Then short sections, each with a real heading that says what it covers ("Costs are under budget"), never "Section 2" or "Details".
- Keep a section to a few sentences or one table. Use a chart only when the numbers back a point.
- Optional look: a `theme:` header line, one of harvis, paper, slate, ember, forest, mono. Leave it out for the default.

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
- Code: a fence with a language, such as ```bash.

Gotchas
- Never write a `<body>` tag.
- A tracker is a table with a Status column using the words above, not prose.
- Put a chart, timeline or diagram inside a `##` section, never before the first one.
