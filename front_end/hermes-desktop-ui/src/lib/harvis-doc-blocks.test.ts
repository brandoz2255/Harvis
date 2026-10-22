import { describe, expect, it } from 'vitest'

import {
  docBlockKind,
  formatChartValue,
  parseCards,
  parseCardsBlock,
  parseChart,
  parseChartNumber,
  parseQuadrant,
  scanFences,
  statusTone
} from './harvis-doc-blocks'
import { parseCsv, parseFlow } from './harvis-doc-flow'
import { parseDocDate, parseTimeline, timelineRange, weekTicks } from './harvis-doc-timeline'

const utc = (y: number, m: number, d: number) => Date.UTC(y, m - 1, d)

describe('docBlockKind', () => {
  it('names the six blocks and nothing else', () => {
    expect(docBlockKind('timeline')).toBe('timeline')
    expect(docBlockKind(' Chart {x}')).toBe('chart')
    expect(docBlockKind('csv')).toBe('csv')
    expect(docBlockKind('python')).toBeNull()
    expect(docBlockKind(undefined)).toBeNull()
  })
})

describe('scanFences', () => {
  it('reports whether each fence has closed', () => {
    const fences = scanFences('a\n```chart\ntitle: x\n```\n\n```timeline\nA | Oct 1')

    expect(fences.map(f => [f.language, f.line, f.closed])).toEqual([
      ['chart', 2, true],
      ['timeline', 6, false]
    ])
  })

  it('keeps a shorter inner fence inside a longer one', () => {
    expect(scanFences('````md\n```js\nx\n```\n````').map(f => f.closed)).toEqual([true])
    expect(scanFences('```js\nx\n````').map(f => f.closed)).toEqual([true])
    expect(scanFences('````js\nx\n```').map(f => f.closed)).toEqual([false])
  })

  it('does not count a fence indented four spaces, which markdown reads as indented code', () => {
    expect(scanFences('    ```chart\n    a: 1\n')).toEqual([])
    expect(scanFences('   ```chart\n   a: 1\n')[0]).toMatchObject({ closed: false, line: 1 })
    expect(scanFences('```js\n    ```\n')[0].closed).toBe(false)
    expect(scanFences('```js\n   ```\n')[0].closed).toBe(true)
  })

  it('ends a fence opened in a blockquote when the quote ends', () => {
    const fences = scanFences('> ```chart\n> a: 1\n\nafter\n\n```timeline\nA | Oct 1')

    expect(fences.map(f => [f.language, f.closed])).toEqual([
      ['chart', true],
      ['timeline', false]
    ])
    expect(scanFences('> ```chart\n> a: 1\nlazy line')[0].closed).toBe(true)
    expect(scanFences('> > ```chart\n> > a: 1\n> back to one quote')[0].closed).toBe(true)
    expect(scanFences('> > ```chart\n> > a: 1\n')[0].closed).toBe(false)
  })

  it('does not close a plain fence on a quoted fence line', () => {
    expect(scanFences('```js\n> ```\n')[0].closed).toBe(false)
  })

  it('does not take inline triple backticks for a fence', () => {
    expect(scanFences('see ```x``` here\n``` not `a` fence ```')).toEqual([])
  })
})

describe('regressions from review', () => {
  it('scanFences sees a fence opened inside a blockquote as open until its closing fence', () => {
    expect(scanFences('> ```chart\n> a: 1\n')[0]).toMatchObject({ closed: false, language: 'chart' })
    expect(scanFences('> ```chart\n> a: 1\n> ```\n')[0].closed).toBe(true)
  })

  it('parseTimeline skips a line with no date cell so prose does not turn off the scale', () => {
    const tl = parseTimeline('Phase 1 | Oct 26 | Nov 1\nReview\nNote: this is prose\nGo | ', { year: 2026 })

    expect(tl.items.map(i => i.label)).toEqual(['Phase 1'])
    expect(tl.scaled).toBe(true)
  })

  it('parseFlow survives a very long chain and a long cycle without overflowing the stack', () => {
    const n = 30000
    const chain = Array.from({ length: n }, (_, i) => `n${i}`).join(' -> ')
    const flow = parseFlow(chain)

    expect(flow.nodes).toHaveLength(n)
    expect(flow.layers).toBe(n)
    expect(flow.nodes[n - 1].layer).toBe(n - 1)

    const cycle = parseFlow(`${chain} -> n0`)

    expect(cycle.edges.filter(e => e.back)).toHaveLength(1)
    expect(cycle.layers).toBe(n)
  })
})

describe('parseDocDate', () => {
  it('reads the documented spellings', () => {
    expect(parseDocDate('2026-10-26', 2020)).toEqual({ hasYear: true, ms: utc(2026, 10, 26) })
    expect(parseDocDate('Oct 26', 2026)).toEqual({ hasYear: false, ms: utc(2026, 10, 26) })
    expect(parseDocDate('Oct 26 2026', 2020)?.ms).toBe(utc(2026, 10, 26))
    expect(parseDocDate('26 Oct', 2026)?.ms).toBe(utc(2026, 10, 26))
    expect(parseDocDate('November 3rd, 2027', 2020)?.ms).toBe(utc(2027, 11, 3))
    expect(parseDocDate('Sept 9', 2026)?.ms).toBe(utc(2026, 9, 9))
  })

  it('rejects things that are not dates', () => {
    const bad = ['', 'soon', 'Q3', 'Oct 32', 'Feb 30', 'Foo 12', '2026-13-01', 'week 3']

    // The export does not read these, so neither may the panel or the two would draw different timelines.
    bad.push('10/26', '2026/10/26', '10/26/2026', 'Octo 26', '2026-10-26 extra', '1850-01-01', '2300-01-01')

    for (const text of bad) {
      expect(parseDocDate(text, 2026)).toBeNull()
    }
  })
})

describe('parseTimeline', () => {
  const SOURCE = `title: Go live lands four weeks after planning starts
subtitle: Q4 rollout
Planning | Oct 26 | Nov 1
Build and configure | Nov 2 | Nov 15
Config freeze | Nov 16
*Go live | Nov 23
Review | Nov 30`

  it('reads title, spans, milestones and the key marker', () => {
    const tl = parseTimeline(SOURCE, { year: 2026 })

    expect(tl.title).toBe('Go live lands four weeks after planning starts')
    expect(tl.subtitle).toBe('Q4 rollout')
    expect(tl.items.map(i => [i.label, i.span, i.key])).toEqual([
      ['Planning', true, false],
      ['Build and configure', true, false],
      ['Config freeze', false, false],
      ['Go live', false, true],
      ['Review', false, false]
    ])
    expect(tl.items[0].dateText).toBe('Oct 26 to Nov 1')
    expect(tl.items[0].start).toBe(utc(2026, 10, 26))
    expect(tl.items[0].end).toBe(utc(2026, 11, 1))
  })

  it('draws to scale only when every date parses', () => {
    expect(parseTimeline(SOURCE, { year: 2026 }).scaled).toBe(true)
    expect(parseTimeline('A | Oct 1\nB | sometime in spring\nC | Oct 9', { year: 2026 }).scaled).toBe(false)
    expect(parseTimeline('A | Q1 | Q2', { year: 2026 }).scaled).toBe(false)
  })

  it('defaults a missing year to the current one', () => {
    const tl = parseTimeline('A | Oct 1')

    expect(new Date(tl.items[0].start ?? 0).getUTCFullYear()).toBe(new Date().getFullYear())
  })

  it('carries a span across New Year and swaps a reversed span', () => {
    const wrap = parseTimeline('Freeze | Dec 20 | Jan 5', { year: 2026 }).items[0]

    expect(wrap.end).toBe(utc(2027, 1, 5))

    const swapped = parseTimeline('Odd | Nov 10 2026 | Nov 1 2026', { year: 2026 }).items[0]

    expect([swapped.start, swapped.end]).toEqual([utc(2026, 11, 1), utc(2026, 11, 10)])
  })

  it('skips empty labels and never throws on junk', () => {
    const tl = parseTimeline('| Oct 1\n\n   \n|||\n* | Oct 2\nReal | Oct 3', { year: 2026 })

    expect(tl.items.map(i => i.label)).toEqual(['Real'])
    expect(() => parseTimeline('\u0000|\n*|*|*\n' + '|'.repeat(5000))).not.toThrow()
    expect(parseTimeline('').items).toEqual([])
  })

  it('computes a range and thinned week ticks', () => {
    const range = timelineRange(parseTimeline(SOURCE, { year: 2026 }))

    expect(range).toEqual({ max: utc(2026, 11, 30), min: utc(2026, 10, 26) })

    const ticks = weekTicks(range.min, range.max)

    expect(ticks.map(t => t.label)).toEqual(['Oct 26', 'Nov 2', 'Nov 9', 'Nov 16', 'Nov 23', 'Nov 30'])
    expect(weekTicks(utc(2026, 1, 1), utc(2026, 12, 31)).length).toBeLessThanOrEqual(10)
    expect(timelineRange(parseTimeline('A | Oct 1', { year: 2026 })).max).toBeGreaterThan(utc(2026, 10, 1))
  })
})

describe('parseChart', () => {
  it('reads a grouped bar chart', () => {
    const chart = parseChart('title: Open findings by host\ntype: bar\nseries: Open, Fixed\nfw01: 3, 5\nweb01: 7, 2')

    expect(chart).toMatchObject({ title: 'Open findings by host', type: 'bar', series: ['Open', 'Fixed'] })
    expect(chart.rows).toEqual([
      { label: 'fw01', values: [3, 5] },
      { label: 'web01', values: [7, 2] }
    ])
  })

  it('defaults to one unnamed bar series and unknown types to bar', () => {
    const chart = parseChart('type: radar\nA: 1\nB: 2')

    expect(chart.type).toBe('bar')
    expect(chart.series).toEqual([''])
  })

  it('accepts line and pie and invents series names for unnamed extras', () => {
    expect(parseChart('type: line\nA: 1, 2\nB: 3, 4').series).toEqual(['Series 1', 'Series 2'])
    expect(parseChart('type: Pie\nA: 1').type).toBe('pie')
  })

  it('reads $ , % k numbers and remembers the unit', () => {
    expect(parseChartNumber('1.2k')).toBe(1200)
    expect(parseChartNumber('$1,250')).toBe(1250)
    expect(parseChartNumber('45%')).toBe(45)
    expect(parseChartNumber('-3')).toBe(-3)
    expect(parseChartNumber('lots')).toBeNull()
    expect(parseChartNumber('')).toBeNull()

    const chart = parseChart('Q1: $1.2k\nQ2: $3k')

    expect(chart.prefix).toBe('$')
    expect(formatChartValue(1200, chart.prefix, chart.suffix)).toBe('$1,200')
    expect(parseChart('A: 5%').suffix).toBe('%')
  })

  it('drops rows with no number, pads short rows and survives colons in labels', () => {
    const chart = parseChart('series: A, B\nnote without colon\nbad: n/a\n10:30 standup: 4\nfull: 1, 2')

    expect(chart.rows).toEqual([
      { label: '10:30 standup', values: [4, 0] },
      { label: 'full', values: [1, 2] }
    ])
  })
})

describe('chart readings shared with the export', () => {
  it('keeps a thousands comma inside its number', () => {
    expect(parseChart('Revenue: 1,200, 900').rows).toEqual([{ label: 'Revenue', values: [1200, 900] }])

    const cost = parseChart('Cost: $3,500')

    expect(cost.rows).toEqual([{ label: 'Cost', values: [3500] }])
    expect(cost.series).toEqual([''])
    expect(parseChart('A: 3,5,7').rows[0].values).toEqual([3, 5, 7])
    expect(parseChart('A: 1,2000').rows[0].values).toEqual([1, 2000])
  })

  it('reads line* and donut types', () => {
    expect(parseChart('type: Line chart\nA: 1').type).toBe('line')
    expect(parseChart('type: donut\nA: 1').type).toBe('pie')
    expect(parseChart('type: doughnut\nA: 1').type).toBe('pie')
    expect(parseChart('type: pipeline\nA: 1').type).toBe('bar')
  })

  it('drops a non-numeric token instead of turning it into zero', () => {
    expect(parseChart('A: 1, n/a, 3').rows[0].values).toEqual([1, 3])
  })

  it('treats a number too big for a double as not a number', () => {
    expect(parseChartNumber('9'.repeat(400))).toBeNull()
    expect(parseChartNumber('1' + '0'.repeat(303))).toBeNull()
    expect(parseChart(`A: ${'9'.repeat(400)}`).rows).toEqual([])
  })
})

describe('parseQuadrant', () => {
  const SOURCE = `title: Impact vs effort
x: Effort
y: Impact
Quick wins: MFA rollout, Patch web01
Big bets: SIEM migration
Fill-ins: Rename shares
Money pits: Rewrite firewall rules by hand`

  it('reads axes and four cells in order', () => {
    const q = parseQuadrant(SOURCE)

    expect([q.title, q.x, q.y]).toEqual(['Impact vs effort', 'Effort', 'Impact'])
    expect(q.cells).toEqual([
      { items: ['MFA rollout', 'Patch web01'], name: 'Quick wins' },
      { items: ['SIEM migration'], name: 'Big bets' },
      { items: ['Rename shares'], name: 'Fill-ins' },
      { items: ['Rewrite firewall rules by hand'], name: 'Money pits' }
    ])
  })

  it('skips a line with no name instead of shifting the later cells', () => {
    expect(parseQuadrant(': orphan\nA: 1\nB: 2').cells.map(c => c.name)).toEqual(['A', 'B', '', ''])
  })

  it('pads missing cells and ignores a fifth line', () => {
    expect(parseQuadrant('A: 1').cells.map(c => c.name)).toEqual(['A', '', '', ''])
    expect(parseQuadrant('A: 1\nB\nC\nD\nE: 5').cells.map(c => c.name)).toEqual(['A', 'B', 'C', 'D'])
  })
})

describe('parseCards', () => {
  it('splits title, highlight and detail; extra pipes stay in the detail', () => {
    expect(parseCards('fw01 | 10.0.0.1 | Firewall · pfSense\nsolo\n | x\nweb | 10.0.0.10 | a | b')).toEqual([
      { detail: 'Firewall · pfSense', highlight: '10.0.0.1', title: 'fw01' },
      { detail: '', highlight: '', title: 'solo' },
      { detail: 'a | b', highlight: '10.0.0.10', title: 'web' }
    ])
  })
})

describe('parseCardsBlock', () => {
  it('reads a leading title: line as the block title, not a card', () => {
    const block = parseCardsBlock('title: Lab devices\nfw01 | 10.0.0.1 | Firewall\nweb | 10.0.0.10')

    expect(block.title).toBe('Lab devices')
    expect(block.cards.map(c => c.title)).toEqual(['fw01', 'web'])
    expect(parseCards('Title : Lab devices\nsolo').map(c => c.title)).toEqual(['solo'])
  })

  it('keeps a titled-looking card line that has pipes, and a title: line that is not first', () => {
    expect(parseCardsBlock('title: Mail | 10.0.0.2 | Postfix').cards.map(c => c.title)).toEqual(['title: Mail'])
    expect(parseCardsBlock('a | 1\ntitle: Late').cards.map(c => c.title)).toEqual(['a', 'title: Late'])
    expect(parseCardsBlock('a | 1').title).toBe('')
  })

  it('consumes an empty leading title: line as no title, and a later title: line stays a card', () => {
    const block = parseCardsBlock('\n title:\ntitle: Late\nOne | 1')

    expect(block.title).toBe('')
    expect(block.cards.map(c => c.title)).toEqual(['title: Late', 'One'])
  })

  it('has no cards when the body is only a title line', () => {
    expect(parseCardsBlock('title: Lab devices').cards).toEqual([])
  })
})

describe('parseFlow', () => {
  it('layers by longest path and shares boxes by label', () => {
    const flow = parseFlow('Internet -> fw01 -> web01 -> db01\nweb01 -> mon01')
    const layer = Object.fromEntries(flow.nodes.map(n => [n.id, n.layer]))

    expect(layer).toEqual({ Internet: 0, fw01: 1, web01: 2, db01: 3, mon01: 3 })
    expect(flow.layers).toBe(4)
    expect(flow.nodes.filter(n => n.layer === 3).map(n => [n.id, n.row])).toEqual([
      ['db01', 0],
      ['mon01', 1]
    ])
    expect(flow.edges).toHaveLength(4)
  })

  it('uses the longest path when a shortcut exists', () => {
    const flow = parseFlow('A -> B -> C\nA -> C')

    expect(flow.nodes.find(n => n.id === 'C')?.layer).toBe(2)
  })

  it('marks a cycle back edge and still lists it', () => {
    const flow = parseFlow('A -> B -> C -> A')

    expect(flow.edges.filter(e => e.back).map(e => `${e.from}>${e.to}`)).toEqual(['C>A'])
    expect(flow.nodes.map(n => n.layer)).toEqual([0, 1, 2])
  })

  it('layers from sources first when a cycle is reached from a later source', () => {
    const flow = parseFlow('X -> Y\nY -> X\nS -> Y')
    const layer = Object.fromEntries(flow.nodes.map(n => [n.id, n.layer]))

    expect(layer).toEqual({ S: 0, X: 2, Y: 1 })
    expect(flow.edges.filter(e => e.back).map(e => `${e.from}>${e.to}`)).toEqual(['X>Y'])
  })

  it('tolerates other arrows, lone boxes, self loops and garbage', () => {
    expect(parseFlow('A --> B => C → D').nodes.map(n => n.layer)).toEqual([0, 1, 2, 3])
    expect(parseFlow('Lonely').nodes).toEqual([{ id: 'Lonely', layer: 0, row: 0 }])
    expect(parseFlow('A -> A').edges).toEqual([])
    expect(parseFlow('->\n-> ->\n').nodes).toEqual([])
  })
})

describe('parseCsv', () => {
  it('reads header, quoted commas and doubled quotes', () => {
    expect(parseCsv('name,notes\nweb01,"a, b"\ndb01,"say ""hi"""\n')).toEqual({
      header: ['name', 'notes'],
      rows: [
        ['web01', 'a, b'],
        ['db01', 'say "hi"']
      ]
    })
  })

  it('pads ragged rows and skips blank lines', () => {
    expect(parseCsv('a,b,c\n1,2\n\n3,4,5').rows).toEqual([
      ['1', '2', ''],
      ['3', '4', '5']
    ])
  })

  it('splits on commas only, like the export', () => {
    expect(parseCsv('a;b\n1;2')).toEqual({ header: ['a;b'], rows: [['1;2']] })
  })

  it('does not throw on an unterminated quote or empty input', () => {
    expect(() => parseCsv('a,b\n"open,1\n2,3')).not.toThrow()
    expect(parseCsv('')).toEqual({ header: [], rows: [] })
  })
})

describe('statusTone', () => {
  it('maps the status words, ignoring case, bold marks and spacing', () => {
    expect(statusTone('Done')).toBe('green')
    expect(statusTone('**In  progress**')).toBe('blue')
    expect(statusTone('NOT STARTED')).toBe('gray')
    expect(statusTone('At risk')).toBe('red')
    expect(statusTone('medium')).toBe('amber')
    expect(statusTone('Low')).toBe('gray')
  })

  it('leaves everything else as plain text', () => {
    expect(statusTone('Done soon')).toBeNull()
    expect(statusTone('toString')).toBeNull()
    expect(statusTone('')).toBeNull()
  })
})
