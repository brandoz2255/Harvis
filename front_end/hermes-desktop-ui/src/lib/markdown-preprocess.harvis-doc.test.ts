import { describe, expect, it } from 'vitest'

import { preprocessMarkdown } from '@/lib/markdown-preprocess'

const DECK = (title: string) => `---
kind: deck
title: ${title}
outline:
  - Title
  - Costs
---
# ${title}
---
## Costs
- Licences
`

// A reply that holds two documents: the first has closed, the second is still arriving.
describe('preprocessMarkdown with two harvis-doc fences', () => {
  it('keeps the opening fence of a still-streaming second document', () => {
    const text = `First:\n\n\`\`\`\`harvis-doc\n${DECK('Plan A')}\`\`\`\`\n\nAnd the second:\n\n\`\`\`\`harvis-doc\n${DECK('Plan B')}`

    const out = preprocessMarkdown(text)

    expect(out.match(/^`{4}harvis-doc$/gm)).toHaveLength(2)
    expect(out.match(/^`{4}$/gm)).toHaveLength(1)
  })

  it('keeps a three-backtick second fence that has not closed', () => {
    const text = `\`\`\`harvis-doc\n${DECK('Plan A')}\`\`\`\n\nNext:\n\n\`\`\`harvis-doc\n${DECK('Plan B')}`

    expect(preprocessMarkdown(text).match(/^`{3}harvis-doc$/gm)).toHaveLength(2)
  })

  it('still strips stray backtick runs from prose between the fences', () => {
    const text = `\`\`\`\`harvis-doc\n${DECK('Plan A')}\`\`\`\`\n\nstray \`\`\` noise\n\n\`\`\`\`harvis-doc\n${DECK('Plan B')}`

    const out = preprocessMarkdown(text)

    expect(out).not.toContain('stray ``` noise')
    expect(out.match(/^`{4}harvis-doc$/gm)).toHaveLength(2)
  })
})
