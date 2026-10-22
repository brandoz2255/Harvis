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
  - Why a garden
  - Rollout plan
---
# Community Garden Launch
From empty lot to first harvest
---
## Why a garden
- Fresh food within walking distance
  - Twelve neighbors already signed up
- A reason to meet outside
Notes: Open with the empty lot photo.
---
## Rollout plan
```timeline
Build beds | Mar 1 | Mar 15
*First planting | Apr 2
```
````

Those are the slides; tell me which to expand.

Rules
- The outline has one line per slide, in order; each line becomes one slide.
- Slides are separated by a line that is exactly `---`.
- Slide 1 is the title slide: `# Title`, then one subtitle line, no bullets.
- Every other slide starts with `## Title`, then 3-6 short bullets (indent two spaces for a sub-bullet).
- 6-12 slides unless the user gave a number: then exactly that many.
- `Notes:` at the end of a slide holds speaker notes.
- Real content only: no placeholders, no "TBD", no lorem ipsum.

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
- Slide 1 is a title slide with a subtitle; every slide has a title.
- If the user asked for N slides, the outline and the slides both number N.
