// Drift test for the landing site. Run from the repo root:
//   node --test front_end/landing/landing.test.mjs
// terms.html must carry the text of python_back_end/plugins/people/legal.py, and every local
// link must resolve. The two screenshots are captured separately and are allowed to be missing.
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const legalPath = resolve(here, '../../python_back_end/plugins/people/legal.py')
const PAGES = ['index.html', 'terms.html']
const SCREENSHOTS = new Set(['assets/harvis-app.png', 'assets/island.png'])

const read = (path) => readFileSync(path, 'utf8')
const legal = read(legalPath)

const literals = (chunk) => [...chunk.matchAll(/"((?:[^"\\]|\\.)*)"/g)].map((m) => JSON.parse(`"${m[1]}"`))

// A section is `"heading": "...", "body": "..."` or a parenthesised run of adjacent literals.
function sections(name, nextName) {
  const start = legal.indexOf(`${name} = (`)
  const end = nextName ? legal.indexOf(`${nextName} = (`) : legal.indexOf('router = ')
  assert.ok(start >= 0 && end > start, `${name} not found in legal.py`)

  return [...legal.slice(start, end).matchAll(/"heading":\s*("(?:[^"\\]|\\.)*"),\s*"body":\s*([\s\S]*?)\n\s*\},/g)].map(
    (m) => ({ heading: literals(m[1])[0], body: literals(m[2]).join('') })
  )
}

const text = (html) =>
  html
    .replace(/<script[\s\S]*?<\/script>/g, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&#39;|&apos;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim()

const version = legal.match(/^LEGAL_VERSION\s*=\s*"([^"]+)"/m)?.[1]
const terms = sections('TERMS', 'ACCEPTABLE_USE')
const acceptableUse = sections('ACCEPTABLE_USE', null)

test('legal.py parses into the sections the page mirrors', () => {
  assert.match(version ?? '', /^\d{4}-\d{2}-\d{2}$/)
  assert.ok(terms.length > 0, 'no TERMS parsed')
  assert.ok(acceptableUse.length > 0, 'no ACCEPTABLE_USE parsed')

  for (const s of [...terms, ...acceptableUse]) {
    assert.ok(s.heading && s.body, `empty section: ${JSON.stringify(s)}`)
  }
})

test('terms.html shows the legal version', () => {
  assert.ok(text(read(join(here, 'terms.html'))).includes(`Version ${version}`))
})

test('terms.html carries every heading and body from legal.py, in order', () => {
  const page = text(read(join(here, 'terms.html')))
  let from = 0

  for (const s of [...terms, ...acceptableUse]) {
    const heading = page.indexOf(s.heading, from)
    assert.ok(heading >= 0, `heading missing or out of order: ${s.heading}`)
    const body = page.indexOf(text(s.body), heading)
    assert.ok(body >= 0, `body of "${s.heading}" differs from legal.py`)
    from = body
  }
})

for (const page of PAGES) {
  test(`${page}: local links and sources resolve`, () => {
    const html = read(join(here, page))
    const refs = [...html.matchAll(/\b(?:href|src)="([^"]*)"/g)].map((m) => m[1])
    assert.ok(refs.length > 0)

    for (const ref of refs) {
      if (/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(ref)) {
        continue
      }

      const [file, fragment] = ref.split('#')
      const target = file || page

      if (SCREENSHOTS.has(target)) {
        continue
      }

      const path = join(here, target)
      assert.ok(existsSync(path), `${page}: ${ref} does not exist`)

      if (fragment && target.endsWith('.html')) {
        assert.ok(read(path).includes(`id="${fragment}"`), `${page}: ${ref} has no matching id`)
      }
    }
  })

  test(`${page}: no external scripts and no retired names`, () => {
    const html = read(join(here, page))
    assert.doesNotMatch(html, /<script[^>]+src="(?:https?:)?\/\//i)
    assert.doesNotMatch(html, /openclaw|opencode|next\.js/i)
  })
}

test('style.css url() references resolve', () => {
  const css = read(join(here, 'style.css'))

  for (const m of css.matchAll(/url\(['"]?([^'")]+)['"]?\)/g)) {
    assert.ok(existsSync(join(here, m[1])), `style.css: ${m[1]} does not exist`)
  }
})

test('index.html references exactly the two screenshots, each in a figure with alt, width and height', () => {
  const html = read(join(here, 'index.html'))
  const images = [...html.matchAll(/<img\b[^>]*>/g)].map((m) => m[0])
  const srcs = images.map((tag) => tag.match(/\bsrc="([^"]*)"/)?.[1]).sort()
  assert.deepEqual(srcs, [...SCREENSHOTS].sort())

  for (const tag of images) {
    assert.match(tag, /\balt="[^"]{12,}"/)
    assert.match(tag, /\bwidth="\d+"/)
    assert.match(tag, /\bheight="\d+"/)
  }

  assert.equal((html.match(/<figure\b/g) ?? []).length, images.length)
})
