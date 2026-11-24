import { describe, expect, it } from 'vitest'

import { pathFromInlineCode } from './inline-code-path'

describe('pathFromInlineCode', () => {
  it.each([
    ['src/app/main.tsx', 'src/app/main.tsx'],
    ['/home/user/report.md', '/home/user/report.md'],
    ['~/notes/todo.md', '~/notes/todo.md'],
    ['./scripts/run.sh', './scripts/run.sh'],
    ['main.py', 'main.py'],
    ['src/lib/media.ts:76', 'src/lib/media.ts'],
    ['src/lib/media.ts:76:3', 'src/lib/media.ts'],
    ['/api/v1/files/3f2a-91/content', '/api/v1/files/3f2a-91/content']
  ])('reads %s as a file', (text, path) => {
    expect(pathFromInlineCode(text)).toBe(path)
  })

  it.each([
    'npm test',
    'v1.2',
    'e.g',
    'useState',
    '/api/chat',
    '/hermes-api/api/fs/read-text',
    'https://example.com/a.md',
    'src/**/*.ts',
    '@/lib/media.ts',
    'src/components/',
    '/etc/hosts',
    '$HOME/notes.md'
  ])('leaves %s as plain code', text => {
    expect(pathFromInlineCode(text)).toBeNull()
  })
})
