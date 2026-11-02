import { describe, expect, it } from 'vitest'

import { auditEntry, buildCsp, CSP_DEFAULT } from './csp'

const directive = (csp: string, name: string) => csp.split('; ').find(d => d.startsWith(`${name} `))

describe('buildCsp', () => {
  it('is closed by default: nothing can connect, embed or move the base', () => {
    expect(directive(CSP_DEFAULT, 'default-src')).toBe("default-src 'none'")
    expect(directive(CSP_DEFAULT, 'connect-src')).toBe("connect-src 'none'")
    expect(directive(CSP_DEFAULT, 'frame-src')).toBe("frame-src 'none'")
    expect(directive(CSP_DEFAULT, 'base-uri')).toBe("base-uri 'none'")
    expect(directive(CSP_DEFAULT, 'form-action')).toBe("form-action 'none'")
    expect(CSP_DEFAULT).not.toMatch(/https?:|wss?:|\*/)
  })

  it('opens exactly the declared domains and nothing else', () => {
    const csp = buildCsp({
      baseUriDomains: ['https://base.example'],
      connectDomains: ['https://api.example.com', 'wss://live.example.com:8443'],
      frameDomains: ['https://embed.example'],
      resourceDomains: ['https://cdn.example.com', 'https://*.fonts.example']
    })

    expect(directive(csp, 'connect-src')).toBe('connect-src https://api.example.com wss://live.example.com:8443')
    expect(directive(csp, 'frame-src')).toBe('frame-src https://embed.example')
    expect(directive(csp, 'base-uri')).toBe('base-uri https://base.example')
    expect(directive(csp, 'script-src')).toBe("script-src 'self' 'unsafe-inline' https://cdn.example.com https://*.fonts.example")
    expect(directive(csp, 'img-src')).toContain('https://cdn.example.com')
  })

  it('drops anything that is not a plain https/wss origin, so a string can never break out of the meta tag', () => {
    const csp = buildCsp({
      connectDomains: [
        'http://plain.example',
        'https://ok.example',
        "https://a.example'; script-src *",
        'https://b.example; img-src *',
        'https://c.example "x',
        '*',
        'https://',
        42 as unknown as string
      ]
    })

    expect(directive(csp, 'connect-src')).toBe('connect-src https://ok.example')
    expect(csp).not.toMatch(/script-src \*/)
    expect(csp).not.toContain('"')
  })

  it('tolerates a null or malformed declaration', () => {
    expect(buildCsp(null)).toBe(CSP_DEFAULT)
    expect(buildCsp({ connectDomains: 'https://x.example' as unknown as string[] })).toBe(CSP_DEFAULT)
  })
})

describe('auditEntry', () => {
  it('records who, which bytes and which policy', () => {
    const entry = auditEntry('clockface', 'a'.repeat(64), CSP_DEFAULT)

    expect(entry).toMatchObject({ csp: CSP_DEFAULT, hash: 'a'.repeat(64), mod: 'clockface' })
    expect(Number.isNaN(Date.parse(entry.at))).toBe(false)
  })
})
