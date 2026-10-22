import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import * as flowModule from '@/lib/harvis-doc-flow'

import { DocMarkdown, WritingCaret } from '../preview-document-views'

import { CardsBlock } from './cards-block'
import { ChartBlock, niceScale } from './chart-block'
import { CsvBlock } from './csv-block'
import { DocBlock } from './doc-block'
import { FlowBlock } from './flow-block'
import { QuadrantBlock } from './quadrant-block'
import { TimelineBlock } from './timeline-block'

const TIMELINE = `title: Go live
Planning | 2026-10-26 | 2026-11-01
Build | 2026-11-02 | 2026-11-15
Freeze | 2026-11-16
*Go live | 2026-11-23
Review | 2026-11-30`

const fence = (kind: string, body: string, closed = true) => `\`\`\`${kind}\n${body}\n${closed ? '```\n' : ''}`

afterEach(cleanup)

describe('blocks', () => {
  it('timeline draws one bar per span, one diamond per milestone, week ticks, and the key milestone in accent', () => {
    const { container } = render(<TimelineBlock code={TIMELINE} />)

    expect(container.querySelectorAll('[data-slot="timeline-bar"] rect')).toHaveLength(2)
    expect(container.querySelectorAll('[data-slot="timeline-milestone"] polygon')).toHaveLength(3)
    expect(container.querySelectorAll('[data-slot="timeline-tick"]').length).toBeGreaterThanOrEqual(5)
    expect(container.querySelector('svg')?.getAttribute('data-scaled')).toBe('true')
    expect(container.querySelector('[data-key] polygon')?.getAttribute('class')).toContain('fill-primary')
    expect(screen.getByText('2026-10-26 to 2026-11-01')).toBeTruthy()
    expect(screen.getByText('Go live', { selector: 'div' })).toBeTruthy()
  })

  it('timeline spaces items evenly, without ticks, when a date does not parse', () => {
    const { container } = render(<TimelineBlock code={'A | Q1\nB | Q2 | Q3\nC | later'} />)

    expect(container.querySelector('svg')?.getAttribute('data-scaled')).toBe('false')
    expect(container.querySelectorAll('[data-slot="timeline-tick"]')).toHaveLength(0)
    expect(container.querySelectorAll('[data-slot="timeline-bar"] rect')).toHaveLength(1)
    expect(screen.getByText('Q2 to Q3')).toBeTruthy()
  })

  it('chart draws a bar per value and a legend for several series', () => {
    const { container } = render(<ChartBlock code={'series: Open, Fixed\nfw01: 3, 5\nweb01: 7, 2'} />)

    expect(container.querySelectorAll('[data-slot="chart-bar"]')).toHaveLength(4)
    expect(container.querySelectorAll('[data-slot="chart-legend"] li')).toHaveLength(2)
    expect(container.querySelector('svg')?.getAttribute('data-type')).toBe('bar')
    expect(screen.getAllByText('7').length).toBeGreaterThan(0)
  })

  it('chart draws a polyline per series for line and a slice per row for pie', () => {
    const line = render(<ChartBlock code={'type: line\nseries: A, B\nJan: 1, 2\nFeb: 2, 3\nMar: 3, 1'} />)

    expect(line.container.querySelectorAll('[data-slot="chart-line"] polyline')).toHaveLength(2)
    line.unmount()

    const pie = render(<ChartBlock code={'type: pie\nseries: Share\nweb: 60\ndb: 30\nmon: 10'} />)

    expect(pie.container.querySelectorAll('[data-slot="chart-slice"]')).toHaveLength(3)
    expect(pie.container.querySelectorAll('path').length).toBe(3)
    expect(screen.getByText(/60%/)).toBeTruthy()
  })

  it('a one-slice pie is a full circle, not a degenerate arc', () => {
    const { container } = render(<ChartBlock code={'type: pie\nonly: 5'} />)

    expect(container.querySelectorAll('circle')).toHaveLength(1)
    expect(container.querySelectorAll('path')).toHaveLength(0)
  })

  it('quadrant renders four cells with axis names', () => {
    const { container } = render(
      <QuadrantBlock
        code={'x: Effort\ny: Impact\nQuick wins: MFA, Patch\nBig bets: SIEM\nFill-ins: Rename\nMoney pits: Rewrite'}
      />
    )

    expect(container.querySelectorAll('[data-slot="quadrant-cell"]')).toHaveLength(4)
    expect(container.querySelectorAll('[data-slot="quadrant-cell"] li')).toHaveLength(5)
    expect(screen.getByText('Effort →')).toBeTruthy()
    expect(screen.getByText('Impact →')).toBeTruthy()
  })

  it('cards are numbered 1..n', () => {
    const { container } = render(
      <CardsBlock code={'fw01 | 10.0.0.1 | Firewall\nweb01 | 10.0.0.10 | Web server\ndb01'} />
    )
    const cards = container.querySelectorAll('[data-slot="doc-card"]')

    expect(cards).toHaveLength(3)
    expect([...cards].map(c => c.querySelector('span')?.textContent)).toEqual(['1', '2', '3'])
    expect(screen.getByText('10.0.0.10')).toBeTruthy()
  })

  it('a leading title: line titles the cards block instead of becoming a card', () => {
    const { container } = render(
      <CardsBlock code={'title: Lab devices\nfw01 | 10.0.0.1 | Firewall\nweb01 | 10.0.0.10'} />
    )

    expect(container.querySelectorAll('[data-slot="doc-card"]')).toHaveLength(2)
    expect(screen.getByText('Lab devices')).toBeTruthy()
    expect(screen.queryByText('title: Lab devices')).toBeNull()
  })

  it('flow draws a box per unique label and an edge per link', () => {
    const { container } = render(<FlowBlock code={'Internet -> fw01 -> web01 -> db01\nweb01 -> mon01'} />)

    expect(container.querySelectorAll('[data-slot="flow-box"]')).toHaveLength(5)
    expect(container.querySelectorAll('[data-slot="flow-edge"]')).toHaveLength(4)
  })

  it('flow draws a cycle edge dashed instead of failing', () => {
    const { container } = render(<FlowBlock code={'A -> B -> A'} />)

    expect(container.querySelectorAll('[data-slot="flow-box"]')).toHaveLength(2)
    expect(container.querySelectorAll('[data-back="true"]')).toHaveLength(1)
  })

  it('csv shows a grid with a collapsible Source holding the raw text', () => {
    const { container } = render(<CsvBlock code={'host,status\nweb01,Done\ndb01,"a, b"'} />)

    expect(container.querySelectorAll('thead th')).toHaveLength(2)
    expect(container.querySelectorAll('tbody tr')).toHaveLength(2)
    expect(container.querySelector('details')?.open).toBe(false)
    expect(container.querySelector('details pre')?.textContent).toContain('web01,Done')
    expect(container.querySelector('[data-tone="green"]')?.textContent).toBe('Done')
    expect(screen.getByText('Source')).toBeTruthy()
  })

  it('DocBlock shows the raw text as code when no line was readable', () => {
    const { container } = render(<DocBlock code={'??? nothing\n:::'} kind="chart" />)

    expect(container.querySelector('[data-slot="doc-block"]')).toBeNull()
    expect(container.querySelector('[data-slot="doc-code"]')?.textContent).toContain('??? nothing')
  })
})

describe('DocMarkdown', () => {
  it('routes block fences to drawings and shows no raw text', () => {
    const text = `Intro\n\n${fence('timeline', TIMELINE)}\n${fence('cards', 'a | 1 | x\nb | 2 | y')}`
    const { container } = render(<DocMarkdown text={text} />)

    expect(container.querySelector('[data-kind="timeline"] svg')).toBeTruthy()
    expect(container.querySelectorAll('[data-slot="doc-card"]')).toHaveLength(2)
    expect(container.textContent).not.toContain('```')
  })

  it('shows a skeleton for an unclosed block fence and replaces it when the fence closes, keeping siblings mounted', () => {
    const lead = 'Before the chart.\n\n'
    const open = `${lead}${fence('chart', 'title: Hosts\nfw01: 3', false)}`
    const { container, rerender } = render(<DocMarkdown active text={open} />)

    const para = container.querySelector('p')

    expect(container.querySelector('[data-slot="doc-block-skeleton"]')).toBeTruthy()
    expect(screen.getByText('Chart: drawing…')).toBeTruthy()
    expect(container.querySelector('svg')).toBeNull()

    rerender(<DocMarkdown active text={`${lead}${fence('chart', 'title: Hosts\nfw01: 3')}`} />)

    expect(container.querySelector('[data-slot="doc-block-skeleton"]')).toBeNull()
    expect(container.querySelector('[data-kind="chart"] svg')).toBeTruthy()
    expect(container.querySelector('p')).toBe(para)
  })

  it('only the last, unclosed fence is a skeleton; earlier closed blocks stay drawn', () => {
    const text = `${fence('cards', 'a | 1')}\n${fence('flow', 'A -> B', false)}`
    const { container } = render(<DocMarkdown active text={text} />)

    expect(container.querySelectorAll('[data-slot="doc-card"]')).toHaveLength(1)
    expect(container.querySelectorAll('[data-slot="doc-block-skeleton"]')).toHaveLength(1)
    expect(screen.getByText('Diagram: drawing…')).toBeTruthy()
  })

  it('draws an unclosed fence from a part that is no longer being written', () => {
    const { container } = render(<DocMarkdown text={fence('cards', 'a | 1', false)} />)

    expect(container.querySelector('[data-slot="doc-block-skeleton"]')).toBeNull()
    expect(container.querySelectorAll('[data-slot="doc-card"]')).toHaveLength(1)
  })

  it('renders a chip for a status cell and plain text otherwise', () => {
    const table = '| Task | Status |\n|---|---|\n| Plan | Done |\n| Build | **In progress** |\n| Ship | Done soon |\n'
    const { container } = render(<DocMarkdown text={table} />)
    const chips = [...container.querySelectorAll('[data-slot="badge"]')]

    expect(chips.map(c => [c.textContent, c.getAttribute('data-tone')])).toEqual([
      ['Done', 'green'],
      ['In progress', 'blue']
    ])
    expect(screen.getByText('Done soon').closest('[data-slot="badge"]')).toBeNull()
  })

  it('renders checklists as read-only checkboxes without bullets', () => {
    const { container } = render(<DocMarkdown text={'- [x] patched\n- [ ] rotated keys\n'} />)
    const boxes = [...container.querySelectorAll('[data-slot="doc-checkbox"]')]

    expect(boxes.map(b => b.getAttribute('aria-checked'))).toEqual(['true', 'false'])
    expect(container.querySelector('ul')?.className).toContain('list-none')
    expect(container.querySelector('input')).toBeNull()
  })

  it('renders display math with KaTeX and labels highlighted code with its language', () => {
    const text = '$$\nx^2 + y^2 = z^2\n$$\n\n```python\nprint(1)\n```\n'
    const { container } = render(<DocMarkdown text={text} />)

    expect(container.querySelector('.katex-display, .katex')).toBeTruthy()
    expect(container.querySelector('[data-slot="doc-code-language"]')?.textContent).toBe('python')
    expect(container.querySelector('[data-slot="doc-code"]')?.textContent).toContain('print(1)')
  })

  it('does not treat currency dollars in prose as math', () => {
    const { container } = render(<DocMarkdown text={'Costs $5 now and $10 later.'} />)

    expect(container.querySelector('.katex')).toBeNull()
    expect(container.textContent).toContain('$5 now and $10')
  })
})

describe('regressions from review', () => {
  it('an all-zero chart still draws finite bars and gridlines', () => {
    const { container } = render(<ChartBlock code={'a: 0\nb: 0'} />)

    expect(container.querySelectorAll('[data-slot="chart-bar"]')).toHaveLength(2)
    expect(container.innerHTML).not.toContain('NaN')
  })

  it('niceScale always has a vertical range', () => {
    const { hi, lo } = niceScale(0, 0)

    expect(hi).toBeGreaterThan(lo)
  })

  it('a parser that throws falls back to the raw text instead of breaking the document', () => {
    const spy = vi.spyOn(flowModule, 'parseFlow').mockImplementation(() => {
      throw new RangeError('boom')
    })

    const { container } = render(<DocBlock code={'a -> b'} kind="flow" />)

    expect(container.querySelector('[data-slot="doc-code"]')?.textContent).toContain('a -> b')
    spy.mockRestore()
  })

  it('a full-width bar keeps its date text clear of the label column', () => {
    const code = 'Project | 2026-10-01 | 2026-12-31\nStart | 2026-10-01\nEnd | 2026-12-31'
    const { container } = render(<TimelineBlock code={code} />)
    const bar = container.querySelector('[data-slot="timeline-bar"]')!
    const date = bar.querySelectorAll('text')[1]
    const x = Number(date.getAttribute('x'))
    const textW = (date.textContent ?? '').length * 5.8
    const left = date.getAttribute('text-anchor') === 'end' ? x - textW : x

    expect(left).toBeGreaterThanOrEqual(166)
  })

  it('does not leak the markdown node prop onto code, table or link elements', () => {
    const { container } = render(<DocMarkdown text={'`x` and [a](https://example.com)\n\n| a |\n| - |\n| b |\n'} />)

    expect(container.querySelector('[node]')).toBeNull()
  })

  it('an open fence inside a blockquote shows the skeleton, not a half-drawn chart', () => {
    const { container } = render(<DocMarkdown active text={'> ```chart\n> a: 1\n'} />)

    expect(container.querySelector('[data-slot="doc-block"]')).toBeNull()
    expect(container.querySelector('[data-slot="doc-block-skeleton"]')).toBeTruthy()
  })
})

describe('WritingCaret', () => {
  it('carries the Harvis name tag above the caret', () => {
    const { container } = render(<WritingCaret />)

    expect(container.querySelector('[data-slot="doc-caret"]')).toBeTruthy()
    expect(container.querySelector('[data-slot="doc-caret-tag"]')?.textContent).toBe('Harvis')
    expect(container.querySelector('[data-slot="doc-caret-tag"]')?.className).toContain('motion-reduce:animate-none')
  })
})
