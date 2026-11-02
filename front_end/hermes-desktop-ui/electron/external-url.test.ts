import { describe, expect, it } from 'vitest'

import { classifyExternalUrl } from './external-url'

describe('classifyExternalUrl', () => {
  it('opens only http, https and mailto in the system handler', () => {
    expect(classifyExternalUrl('https://example.com/a')).toEqual({ kind: 'external', url: 'https://example.com/a' })
    expect(classifyExternalUrl(' http://example.com ')).toEqual({ kind: 'external', url: 'http://example.com/' })
    expect(classifyExternalUrl('mailto:a@example.com')).toEqual({ kind: 'external', url: 'mailto:a@example.com' })
  })

  it('marks file: urls so callers can reveal them, never launch them', () => {
    expect(classifyExternalUrl('file:///home/me/run.sh')).toEqual({ kind: 'file', url: 'file:///home/me/run.sh' })
  })

  it.each(['', '   ', 'not a url', 'javascript:alert(1)', 'smb://host/share', 'ms-msdt:/id', 'vscode://x', 'data:text/html,x', null])(
    'refuses %s',
    raw => {
      expect(classifyExternalUrl(raw)).toBeNull()
    }
  )
})
