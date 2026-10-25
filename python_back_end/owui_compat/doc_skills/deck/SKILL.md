---
description: Make a slide deck (pptx) as a harvis-doc with a title slide, bullet slides, and at most one chart, timeline, cards, quadrant, flow or table per slide.
---
You were asked to make a deck. Answer with one sentence, then ONE harvis-doc block, then at most one sentence. Open the block with four backticks and `harvis-doc`, close it with four backticks. No second block. Example of a whole answer:

I put together a short launch deck.

````harvis-doc
---
kind: deck
title: Community Garden Launch
outline:
  - Title
  - Neighbors want it
  - Beds ready by April
  - Next steps
---
# Community Garden Launch
From empty lot to first harvest
---
## Neighbors want it
- 12 households signed up
- Fresh food nearby
Notes: Open with the empty lot photo.
---
## Beds ready by April
```timeline
Build beds | Mar 1 | Mar 15
*First planting | Apr 2
```
---
## Next steps
- Order beds Feb 28
````

Tell me which slides to expand.

Rules
- The outline has one line per slide, in order; each line becomes one slide.
- Slides are separated by a line that is exactly `---`.
- Every other slide starts with `## Title`, then 3-6 short bullets (indent two spaces for a sub-bullet).
- 6-12 slides unless the user gave a number: then exactly that many.
- `Notes:` at the end of a slide holds speaker notes.
- Real content only: no placeholders, no "TBD", no lorem ipsum.

Design
- Titles state the takeaway ("Rollout takes six weeks"), not a topic.
- At most 25 words per slide; detail goes in `Notes:`.
- Never two bullet-only slides in a row: use cards, a chart, a timeline, a quadrant or a table between.
- Two `###` headings with text: columns. Up to three `**42%**` figures with captions: big numbers.
- End with a next-steps slide.
- Optional look: a `theme:` header line, one of harvis, paper, slate, ember, forest, mono. Leave it out for the default.

Rich blocks: at most ONE per slide, and then it is the whole slide body (no bullets). Three backticks, one item per line.
```cards
fw01 | 10.0.0.1 | Firewall
web01 | 10.0.0.10 | Web server
```
```timeline
Planning | Oct 26 | Nov 1
*Go live | Nov 23
```
(span: Label | start | end; milestone: Label | when; `*` marks the key one)
```quadrant
x: Effort
y: Impact
Quick wins: MFA
Big bets: SIEM
Fill-ins: Rename shares
Money pits: Manual rules
```
(four lines, in order: top-left, top-right, bottom-left, bottom-right)
```chart
type: bar
series: Open, Fixed
web01: 7, 2
```
(type: bar, line or pie)
```flow
Internet -> fw01 -> web01
```
A table also works as a slide body:
| Step | Owner |
| --- | --- |
| Order beds | Sam |

Gotchas
- Never write a `<body>` tag.
- Slide 1 is a title slide (`# Title`, one subtitle line, no bullets); every slide has a title.
- If the user asked for N slides, the outline and the slides both number N.
