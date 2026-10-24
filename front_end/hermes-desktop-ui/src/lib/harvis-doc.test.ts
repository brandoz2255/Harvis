import { describe, expect, it } from 'vitest'

import {
  arrivedParts,
  columnLetter,
  expectedParts,
  exportFormats,
  isHarvisDocLanguage,
  openHarvisDocFence,
  parseHarvisDoc,
  parseSheetTable,
  sheetCellDisplay
} from './harvis-doc'

const DECK = `---
kind: deck
title: Q3 Security Review
outline:
  - Title
  - Threat landscape
  - Next steps
---
# Q3 Security Review
Notes: open warmly
---
## Threat landscape
- Phishing is up 40%
- MFA covers 92% of staff
---
## Next steps
1. Roll out passkeys
2. Retire legacy VPN
`

const DOC = `---
kind: doc
title: Onboarding Guide
outline: [Welcome, Accounts, Support]
---
# Onboarding Guide

Some intro text.

## Welcome
Hello and **welcome**.

## Accounts
You will get a laptop.

### Passwords
Use the manager.

## Support
Ask in #help.
`

const SHEET = `---
kind: sheet
title: Budget
outline:
  - Income
  - Expenses
---
## Income
| Month | Amount |
|---|---|
| Jan | 1200 |
| Feb | 1350 |
## Expenses
| Month | Amount |
| --- | --- |
| Jan | =B2*0.5 |
`

/** Every prefix, stepping through the text, so truncation lands inside every construct. */
function prefixes(text: string, step = 1): string[] {
  const out: string[] = []

  for (let i = 0; i <= text.length; i += step) {
    out.push(text.slice(0, i))
  }

  return out
}

describe('parseHarvisDoc', () => {
  it('reads a whole deck', () => {
    const doc = parseHarvisDoc(DECK)

    expect(doc.kind).toBe('deck')
    expect(doc.title).toBe('Q3 Security Review')
    expect(doc.outline).toEqual(['Title', 'Threat landscape', 'Next steps'])
    expect(doc.headerComplete).toBe(true)
    expect(doc.sections.map(s => s.title)).toEqual(['Q3 Security Review', 'Threat landscape', 'Next steps'])
    expect(doc.sections[1].body).toContain('Phishing is up 40%')
  })

  it('reads a document with an inline outline and keeps ### inside its section', () => {
    const doc = parseHarvisDoc(DOC)

    expect(doc.outline).toEqual(['Welcome', 'Accounts', 'Support'])
    expect(doc.sections.map(s => s.title)).toEqual(['', 'Welcome', 'Accounts', 'Support'])
    expect(doc.sections[2].body).toContain('### Passwords')
  })

  it('reads sheets and their tables', () => {
    const doc = parseHarvisDoc(SHEET)

    expect(doc.sheets.map(s => s.name)).toEqual(['Income', 'Expenses'])
    expect(doc.sheets[0].rows).toEqual([
      ['Month', 'Amount'],
      ['Jan', '1200'],
      ['Feb', '1350']
    ])
    expect(doc.sheets[1].rows[1]).toEqual(['Jan', '=B2*0.5'])
  })

  it('takes the title from the first H1 when the front matter has none', () => {
    const doc = parseHarvisDoc('# Plain Notes\n\n## One\ntext')

    expect(doc.headerComplete).toBe(true)
    expect(doc.title).toBe('Plain Notes')
  })

  it('treats empty source as an unfinished header with nothing known', () => {
    expect(parseHarvisDoc('')).toMatchObject({ headerComplete: false, sections: [], title: '' })
    expect(parseHarvisDoc('--')).toMatchObject({ headerComplete: false, title: '' })
  })

  it('does not leak a half-typed title, kind or outline label', () => {
    expect(parseHarvisDoc('---\nkind: deck\ntitle: Q3 Sec').title).toBe('')
    expect(parseHarvisDoc('---\nkind: deck\ntitle: Q3 Sec\n').title).toBe('Q3 Sec')
    expect(parseHarvisDoc('---\nkind: deck\ntitle: T\noutline:\n  - Intro\n  - Thre').outline).toEqual(['Intro'])
  })

  it('reads the theme header, lowercased, unquoted and without a trailing comment', () => {
    expect(parseHarvisDoc('---\nkind: deck\ntitle: T\ntheme: Paper\n---\n# T').theme).toBe('paper')
    expect(parseHarvisDoc('---\nkind: deck\ntheme: "slate"\n---\n# T').theme).toBe('slate')
    expect(parseHarvisDoc('---\nkind: deck\ntheme: ember   # harvis | paper | slate\n---\n# T').theme).toBe('ember')
  })

  it('has no theme when the header does not name one, and keeps an unknown name for the exporter to default', () => {
    expect(parseHarvisDoc('---\nkind: deck\ntitle: T\n---\n# T').theme).toBe('')
    expect(parseHarvisDoc('# Plain').theme).toBe('')
    expect(parseHarvisDoc('---\nkind: doc\ntheme: neon\n---\n## A\nx').theme).toBe('neon')
  })

  it('reads the theme before the header closes, but not a half-typed name', () => {
    expect(parseHarvisDoc('---\nkind: deck\ntheme: paper\n').theme).toBe('paper')
    expect(parseHarvisDoc('---\nkind: deck\ntheme: pap').theme).toBe('')
  })

  it('reads an inline outline without its closing bracket yet', () => {
    expect(parseHarvisDoc('---\ntitle: T\noutline: [A, B\n').outline).toEqual(['A', 'B'])
    expect(parseHarvisDoc('---\ntitle: T\noutline: [A, B]\n').outline).toEqual(['A', 'B'])
  })

  it('does not show a lone # or -- at the end of the body as content', () => {
    const header = '---\nkind: doc\ntitle: T\noutline: [A, B]\n---\n'

    expect(parseHarvisDoc(`${header}## A\ntext\n##`).sections[0].body).toBe('text')
    expect(parseHarvisDoc(`${header}## A\ntext\n--`).sections[0].body).toBe('text')
  })

  it('normalises kind aliases and defaults unknown kinds to doc', () => {
    expect(parseHarvisDoc('---\nkind: slides\n---\n# x').kind).toBe('deck')
    expect(parseHarvisDoc('---\nkind: spreadsheet\n---\n').kind).toBe('sheet')
    expect(parseHarvisDoc('---\nkind: mystery\n---\n').kind).toBe('doc')
  })

  it('ignores a trailing # comment on the kind line, as the backend does', () => {
    expect(parseHarvisDoc('---\nkind: deck            # deck | doc | sheet | pdf\n---\n# x').kind).toBe('deck')
  })

  it('does not start a section at a ## inside a code fence', () => {
    const doc = parseHarvisDoc('---\nkind: doc\n---\n## Code\n```bash\n## a comment\necho hi\n```\n## After\nok')

    expect(doc.sections.map(s => s.title)).toEqual(['Code', 'After'])
    expect(doc.sections[0].body).toContain('## a comment')
  })

  it('starts a new slide at a heading when the deck forgot the --- lines', () => {
    const doc = parseHarvisDoc(
      '---\nkind: deck\ntitle: T\n---\n# T\nsub\n## One\n- a\n```timeline\n## not a slide | Oct 1\n```\n## Two\n- b'
    )

    expect(doc.sections.map(s => s.title)).toEqual(['T', 'One', 'Two'])
    expect(doc.sections[1].body).toContain('## not a slide')
  })

  it('accepts CRLF line endings', () => {
    const doc = parseHarvisDoc(DECK.replace(/\n/g, '\r\n'))

    expect(doc.sections.map(s => s.title)).toEqual(['Q3 Security Review', 'Threat landscape', 'Next steps'])
  })

  for (const [name, text] of [
    ['deck', DECK],
    ['doc', DOC],
    ['sheet', SHEET]
  ] as const) {
    it(`never throws on any truncated ${name}, and parts only grow`, () => {
      let previous = 0

      for (const prefix of prefixes(text)) {
        const doc = parseHarvisDoc(prefix)
        const arrived = arrivedParts(doc)

        expect(arrived).toBeGreaterThanOrEqual(0)
        expect(expectedParts(doc)).toBeGreaterThanOrEqual(arrived)
        // A part may be re-split while it is being typed, but a part that has
        // been counted must never disappear again.
        expect(arrived).toBeGreaterThanOrEqual(previous)
        previous = arrived
      }
    })

    it(`reads the same thing twice for a settled ${name}`, () => {
      expect(parseHarvisDoc(text)).toEqual(parseHarvisDoc(text))
      expect(arrivedParts(parseHarvisDoc(text))).toBe(arrivedParts(parseHarvisDoc(`${text}\n`)))
    })
  }
})

describe('expectedParts', () => {
  it('uses the outline length until more parts than outlined arrive', () => {
    const doc = parseHarvisDoc(DECK)

    expect(expectedParts(doc)).toBe(3)
    expect(expectedParts({ ...doc, outline: ['Only'] })).toBe(3)
  })

  it('counts deck slides that have no heading', () => {
    const doc = parseHarvisDoc('---\nkind: deck\ntitle: T\noutline: [A, B, C]\n---\n- bullet\n---\n- another\n')

    expect(arrivedParts(doc)).toBe(2)
    expect(expectedParts(doc)).toBe(3)
  })
})

describe('parseSheetTable', () => {
  it('drops the divider row and unescapes pipes', () => {
    expect(parseSheetTable('| A | B |\n|:--|--:|\n| a\\|b | 2 |')).toEqual([
      ['A', 'B'],
      ['a|b', '2']
    ])
  })
})

describe('parseSheetTable single-hyphen divider', () => {
  it('drops a `| - | - |` divider row like the export does', () => {
    expect(parseSheetTable('| A | B |\n| - | - |\n| 1 | 2 |')).toEqual([
      ['A', 'B'],
      ['1', '2']
    ])
  })
})

describe('openHarvisDocFence', () => {
  it('returns the body of a fence that is still open', () => {
    expect(openHarvisDocFence('Intro\n\n````harvis-doc\n---\nkind: deck')).toBe('---\nkind: deck')
  })

  it('returns null once the fence closed, or for other languages', () => {
    expect(openHarvisDocFence('````harvis-doc\n---\n---\n# x\n````\nAfter')).toBeNull()
    expect(openHarvisDocFence('```ts\nconst a = 1')).toBeNull()
    expect(openHarvisDocFence('no fence at all')).toBeNull()
  })

  it('is not closed by a shorter inner fence', () => {
    const text = '````harvis-doc\n---\ntitle: T\n---\n# x\n```py\nprint(1)\n```\nmore'

    expect(openHarvisDocFence(text)).toContain('more')
  })

  it('finds the last fence when a finished one comes first', () => {
    const text = '````harvis-doc\nA\n````\n\n````harvis-doc\nB'

    expect(openHarvisDocFence(text)).toBe('B')
  })
})

describe('isHarvisDocLanguage', () => {
  it('matches harvis-doc and harvisdoc in any case', () => {
    expect(isHarvisDocLanguage('harvis-doc')).toBe(true)
    expect(isHarvisDocLanguage('HarvisDoc')).toBe(true)
    expect(isHarvisDocLanguage('harvis')).toBe(false)
    expect(isHarvisDocLanguage(undefined)).toBe(false)
  })
})

describe('exportFormats', () => {
  it('lists the formats per kind with the primary first', () => {
    expect(exportFormats('deck').map(f => f.ext)).toEqual(['pptx', 'pdf'])
    expect(exportFormats('doc').map(f => f.ext)).toEqual(['docx', 'pdf', 'md'])
    expect(exportFormats('pdf').map(f => f.ext)).toEqual(['pdf', 'docx'])
    expect(exportFormats('sheet').map(f => f.ext)).toEqual(['xlsx', 'csv'])
  })
})

describe('columnLetter', () => {
  it('counts like a spreadsheet', () => {
    expect([0, 1, 25, 26, 27, 51, 52, 701, 702].map(columnLetter)).toEqual([
      'A',
      'B',
      'Z',
      'AA',
      'AB',
      'AZ',
      'BA',
      'ZZ',
      'AAA'
    ])
  })
})

describe('small-model habits', () => {
  it('drops a copied <body> placeholder line and bold markers around whole cells', () => {
    const deck = parseHarvisDoc('---\nkind: deck\ntitle: T\n---\n<body>\n# First\n- a\n---\n## Second\n</body>\n')

    expect(deck.sections.map(s => s.title)).toEqual(['First', 'Second'])

    const sheet = parseHarvisDoc(
      '---\nkind: sheet\ntitle: B\n---\n## S\n| Item | Cost |\n| --- | --- |\n| **Total** | **=SUM(B2:B3)** |\n'
    )

    expect(sheet.sheets[0].rows[1]).toEqual(['**Total**', '**=SUM(B2:B3)**'])
    expect(sheetCellDisplay('**=SUM(B2:B3)**')).toEqual({ bold: true, text: '=SUM(B2:B3)' })
    expect(sheetCellDisplay('Rent')).toEqual({ bold: false, text: 'Rent' })
  })
})
