#!/usr/bin/env node
// Island browser adversarial tests: drives the harness (harness.tsx, REAL IslandHost +
// mount.js + per-account IndexedDB art) in headless Chromium. No external network: a local
// server serves the bundle and, read-only, the user's own imported game-art folder for the
// BYO-art seeding. Fails closed: any failed assertion exits non-zero.
//
// Run: node scripts/island-browser/run.mjs
import { chromium } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { createServer } from 'node:http'
import { mkdirSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { homedir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const ART_DIR = process.env.ISLAND_STARDEW_ASSETS ?? join(homedir(), '.local', 'share', 'harvis', 'stardew-assets')
const SHOTS = join(here, 'shots')
mkdirSync(SHOTS, { recursive: true })

execFileSync(process.execPath, [join(here, 'build.mjs')], { stdio: 'inherit' })

// The art paths the island accepts (mirrors src/island/engine/stardew/art-files.js rules).
const ART_PATH = /^(LooseSprites|Maps|TileSheets)\/[A-Za-z0-9_ .-]+\.(png|tbin)$/
const artFiles = (() => {
  const out = []
  const walk = dir => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name)
      if (statSync(path).isDirectory()) walk(path)
      else out.push(path.slice(ART_DIR.length + 1))
    }
  }
  try {
    walk(ART_DIR)
  } catch {
    console.error(`FATAL: cannot read the imported game-art folder at ${ART_DIR}`)
    process.exit(2)
  }
  return out.filter(p => ART_PATH.test(p))
})()

if (!artFiles.includes('Maps/Town.tbin')) {
  console.error(`FATAL: ${ART_DIR} has no Maps/Town.tbin — run scripts/island/import-stardew.mjs first`)
  process.exit(2)
}

const MIME = { '.html': 'text/html', '.js': 'text/javascript', '.png': 'image/png' }
const server = createServer((req, res) => {
  const url = new URL(req.url ?? '/', 'http://x')
  try {
    if (url.pathname === '/art-manifest') {
      res.end(JSON.stringify(artFiles))
    } else if (url.pathname.startsWith('/art/')) {
      const rel = decodeURIComponent(url.pathname.slice(5))
      if (!ART_PATH.test(rel)) throw new Error('bad path')
      const body = readFileSync(join(ART_DIR, rel))
      res.setHeader('content-type', MIME[rel.slice(-4)] ?? 'application/octet-stream')
      res.end(body)
    } else if (url.pathname === '/other') {
      res.setHeader('content-type', 'text/html')
      res.end('<!doctype html><title>other</title><p>elsewhere</p>')
    } else {
      const file = url.pathname === '/' ? 'index.html' : url.pathname.slice(1)
      const path = file === 'index.html' ? join(here, 'index.html') : join(here, 'dist', file)
      res.setHeader('content-type', MIME[path.slice(path.lastIndexOf('.'))] ?? 'text/plain')
      res.end(readFileSync(path))
    }
  } catch {
    res.statusCode = 404
    res.end('nope')
  }
})

await new Promise(r => server.listen(0, '127.0.0.1', r))
const base = `http://127.0.0.1:${server.address().port}`

const failures = []
const check = (name, cond, detail = '') => {
  console.log(`${cond ? 'PASS' : 'FAIL'} ${name}${cond || !detail ? '' : ` — ${detail}`}`)
  if (!cond) failures.push(name)
}

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { height: 700, width: 1100 } })
page.on('pageerror', err => check(`page error: ${err.message}`, false))

const state = () => page.evaluate(() => window.__harness.state())
const waitFor = (fn, timeout = 15_000) => page.waitForFunction(fn, null, { timeout })
const ticksAdvancing = async (ms = 400) => {
  const a = (await state()).ticks
  await page.waitForTimeout(ms)
  const b = (await state()).ticks
  return b - a
}

try {
  await page.goto(base)
  await page.evaluate(() => {
    window.__bots = {
      alice: [{ display_name: 'Researcher', name: 'researcher' }],
      bob: [{ display_name: 'Builder', name: 'builder' }]
    }
    window.__botChats = []
  })

  // -- A: signed out, nothing renders -------------------------------------------------
  check('A1 signed-out: no island mounted', !(await state()).mounted)
  check('A2 signed-out: no iframes on the page', (await state()).iframes === 0)

  // -- B: alice signs in; her own bots and her own art arrive --------------------------
  await page.evaluate(async () => {
    const paths = await (await fetch('/art-manifest')).json()
    const files = {}
    for (const p of paths) files[p] = await (await fetch(`/art/${encodeURIComponent(p)}`)).arrayBuffer()
    await window.__harness.seedArt('alice', files)
  })
  await page.evaluate(() => window.__harness.signIn('alice'))
  await waitFor(() => window.__harness.state().mounted)
  await waitFor(() => window.__harness.state().residents.some(r => r.includes('Researcher')))
  await waitFor(() => window.__harness.state().artCustom)

  const b = await state()
  check('B1 island mounted in-page', b.islandRoots === 1)
  check('B2 no iframe anywhere', b.iframes === 0)
  check('B3 no island window globals', b.globals.length === 0, b.globals.join(','))
  check('B4 nothing listens to window messages', b.messageListeners === 0)
  check('B5 residents are the account bots', b.residents.some(r => r.includes('Researcher')), b.residents.join('|'))
  check('B6 BYO art restored from this account store', b.artCustom && b.byoCanvas)
  check('B7 sim is ticking', (await ticksAdvancing()) > 0)
  await page.screenshot({ path: join(SHOTS, 'b-alice-faded.png') })

  // -- C: spoofed postMessage storms change nothing ------------------------------------
  await page.evaluate(() => {
    const evil = { agents: [{ id: 'evil-bot', name: 'EVIL' }] }
    for (const origin of [location.origin, 'null', 'https://evil.example']) {
      window.dispatchEvent(new MessageEvent('message', { data: { session: evil, type: 'island:session' }, origin }))
      window.dispatchEvent(new MessageEvent('message', { data: { files: { 'Maps/Town.tbin': new ArrayBuffer(8) }, type: 'island:stardew' }, origin }))
      window.dispatchEvent(new MessageEvent('message', { data: { message: 'x', state: 'error', type: 'island:stardew-status' }, origin }))
      window.dispatchEvent(new MessageEvent('message', { data: { agentId: 'researcher', type: 'island:select' }, origin }))
    }
  })
  await page.waitForTimeout(300)
  const c = await state()
  check('C1 spoofed session did not add residents', !c.residents.some(r => r.includes('EVIL')), c.residents.join('|'))
  check('C2 spoofed art/status/select did not break the island', c.artCustom && c.islandRoots === 1)
  check('C3 no bot chat opened by spoofed select', await page.evaluate(() => window.__botChats.length) === 0)

  // -- D: Explore gives the island keys; the faded background never gets them ----------
  await page.getByRole('button', { name: 'Explore' }).click()
  await waitFor(() => window.__harness.state().exploring)
  await waitFor(() => window.__harness.state().artCustom) // the remount re-restores first
  const cover = await page.evaluate(() => {
    const c = document.querySelector('.hi-byo')?.getBoundingClientRect()
    return c ? Math.round(c.width) >= innerWidth && Math.round(c.height) >= innerHeight : false
  })
  check('D0 Explore shows the custom art fullscreen', cover)
  await page.screenshot({ path: join(SHOTS, 'd-alice-explore.png') })
  await page.keyboard.press('p')
  check('D1 "p" in Explore pauses the island', (await ticksAdvancing(500)) === 0)
  await page.keyboard.press('p')
  check('D2 "p" again resumes it', (await ticksAdvancing(500)) > 0)
  await page.getByRole('button', { name: 'Back to bots' }).click()
  await waitFor(() => !window.__harness.state().exploring)
  await page.keyboard.press('p')
  check('D3 "p" over chat never reaches the island', (await ticksAdvancing(500)) > 0)
  // Explore remounts (portal): art must be restored again from the account store.
  await page.getByRole('button', { name: 'Explore' }).click()
  await waitFor(() => window.__harness.state().artCustom)
  check('D4 art survives the Explore remount', true)
  await page.getByRole('button', { name: 'Back to bots' }).click()
  await waitFor(() => !window.__harness.state().exploring)
  await waitFor(() => window.__harness.state().artCustom) // the remount re-restores first

  // -- E: account switch disposes alice's island; bob gets only his own ----------------
  const keydownWithAlice = (await state()).keydownListeners
  await page.evaluate(() => window.__harness.signIn('bob'))
  await waitFor(() => window.__harness.state().residents.some(r => r.includes('Builder')))
  await page.waitForTimeout(400)
  const e = await state()
  check('E1 bob sees his own bot', e.residents.some(r => r.includes('Builder')), e.residents.join('|'))
  check('E2 alice bot is gone', !e.residents.some(r => r.includes('Researcher')), e.residents.join('|'))
  check('E3 alice art is not restored for bob', !e.artCustom && !e.byoCanvas)
  check('E4 exactly one island still', e.islandRoots === 1)
  check('E5 alice island keybind disposed', e.keydownListeners < keydownWithAlice, `${e.keydownListeners} !< ${keydownWithAlice}`)
  check('E6 bob has no stored art; alice keeps hers', await page.evaluate(async () =>
    (await window.__harness.readArt('bob')) === 0 && (await window.__harness.readArt('alice')) > 0))
  check('E7 bob sim ticking', (await ticksAdvancing()) > 0)
  await page.screenshot({ path: join(SHOTS, 'e-bob.png') })
  // Alice has BYO art (no resident list), so selection is exercised on bob's built-in island:
  // a click must reach the roster as exactly bob's bot, and never one of alice's.
  await page.getByRole('button', { name: 'Explore' }).click()
  await waitFor(() => window.__harness.state().exploring)
  await page.locator('.hi-agent', { hasText: 'Builder' }).click()
  await waitFor(() => window.__botChats.length > 0)
  const chats = await page.evaluate(() => window.__botChats)
  check('E8 selecting a resident opens exactly that account bot', chats.length === 1 && chats[0] === 'builder', chats.join(','))
  await page.getByRole('button', { name: 'Back to bots' }).click()
  await waitFor(() => !window.__harness.state().exploring)
  await page.evaluate(() => { window.__botChats.length = 0 })

  // -- F: back to alice restores her island exactly ------------------------------------
  await page.evaluate(() => window.__harness.signIn('alice'))
  await waitFor(() => window.__harness.state().artCustom)
  await waitFor(() => window.__harness.state().residents.some(r => r.includes('Researcher')))
  check('F1 alice gets her bots and art back', true)
  await page.screenshot({ path: join(SHOTS, 'f-alice-back.png') })

  // -- G: rapid switching settles on the last account only ------------------------------
  await page.evaluate(() => {
    window.__harness.signIn('bob')
    window.__harness.signIn('alice')
    window.__harness.signIn('bob')
  })
  await waitFor(() => window.__harness.state().residents.some(r => r.includes('Builder')))
  await page.waitForTimeout(500)
  const g = await state()
  check('G1 rapid switches settle on bob', g.residents.some(r => r.includes('Builder')) && !g.residents.some(r => r.includes('Researcher')), g.residents.join('|'))
  check('G2 still exactly one island, built-in art', g.islandRoots === 1 && !g.artCustom)

  // -- H: sign-out tears everything down ------------------------------------------------
  await page.evaluate(() => window.__harness.signIn('alice'))
  await waitFor(() => window.__harness.state().artCustom)
  await page.evaluate(() => window.__harness.signOut())
  await page.waitForTimeout(300)
  const h = await state()
  check('H1 sign-out unmounts the island', !h.mounted && h.islandRoots === 0)
  check('H2 no rAF loops survive', h.rafOutstanding === 0, String(h.rafOutstanding))
  check('H3 no island keybind survives', h.keydownListeners === 0, String(h.keydownListeners))

  // -- I: real navigation away and back starts clean ------------------------------------
  await page.goto(`${base}/other`)
  await page.goBack()
  await page.evaluate(() => { // a fresh document: the rosters come from the backend again
    window.__bots = {
      alice: [{ display_name: 'Researcher', name: 'researcher' }],
      bob: [{ display_name: 'Builder', name: 'builder' }]
    }
    window.__botChats = []
    window.__harness.signIn('alice')
  })
  await waitFor(() => window.__harness.state().artCustom)
  await waitFor(() => window.__harness.state().residents.some(r => r.includes('Researcher')))
  check('I1 after navigation the island works again', true)

  // -- J: island styles stay inside the island ------------------------------------------
  const radius = await page.evaluate(() => getComputedStyle(document.getElementById('sentinel')).borderRadius)
  check('J1 chrome button untouched by island css', radius === '0px', radius)
} finally {
  await browser.close()
  server.close()
}

if (failures.length) {
  console.error(`\n${failures.length} FAILURE(S): ${failures.join(', ')}`)
  process.exit(1)
}

console.log('\nAll island browser checks passed.')
