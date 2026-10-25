---
description: Make a spreadsheet (xlsx or csv) as a harvis-doc with one markdown table per sheet, real numbers and formulas for totals. No rich blocks.
---
You were asked to make a spreadsheet. Answer with one sentence, then ONE harvis-doc block, then at most one sentence. Open the block with four backticks and `harvis-doc`, close it with four backticks. No second block. Example of a whole answer:

Here is the budget sheet.

````harvis-doc
---
kind: sheet
title: Road Trip Budget
outline:
  - Budget
---
## Budget
| Item | Cost (USD) |
| --- | --- |
| Fuel | 320 |
| Hotels | 540 |
| Food | 260 |
| Total | =SUM(B2:B4) |
| Budget | 2000 |
| Left | =$B$6-B5 |
````

Totals are formulas, so they update when you change a number.

Rules
- The outline lists the sheet names, in order. Each sheet is a `## Sheet name` heading, then a markdown table: header row first, then data rows.
- Numbers are plain numbers (`1200`, `0.15`, `$40`, `12%`), no units inside number cells.
- A cell that starts with `=` is a formula. Totals and derived columns are formulas (`=SUM(B2:B5)`, `=B2*C2`, `=AVERAGE(D2:D9)`), never a typed total.
- Tables and formulas only: no charts, timelines or other blocks.

Design
- Put units in the headers (`Cost (USD)`, `Weight (kg)`), so the cells stay plain numbers.
- Give each assumption (a rate, a limit, a budget) its own labelled row below the totals, like `Budget | 2000`, and point formulas at that cell (`=$B$6-B5`) instead of retyping the number.
- Keep SUM ranges above the assumption rows, so a total never adds a rate in.
- One table per sheet. Assumptions are rows in that table, not a second table.

Gotchas
- Never write a `<body>` tag.
- ONE sheet unless the user asked for several: a category column beats a sheet per category.
- No bold or other markdown inside cells.
- When the user gives a limit (a $2000 budget), make the rows fit it or add a formula row showing the gap.
- A formula must reference the column that holds the numbers: on a two-column Item | Cost table the costs are column B, so `=SUM(B2:B4)`. Count the columns before you write it.
- A formula gives a number. For a status like Over or OK, write the word in the cell and keep the formula for the amount.
