#!/usr/bin/env node
// Builds the island browser harness (harness.tsx + stubs.tsx) into dist/ as one bundle.
// The stub plugin swaps the account-backend and app-chrome imports for harness doubles;
// everything else — IslandHost, mount.js, the engine, the art store — is the real code.
import { build } from 'esbuild'
import { existsSync, statSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const ui = resolve(here, '..', '..')
const src = resolve(ui, 'src')

const STUBS = new Set([
  '@/lib/harvis-session',
  '@/store/session',
  '@/plugins/hermes-bots/data',
  '@/plugins/hermes-bots/roster-actions',
  '@/themes/context',
  '@/components/ui/codicon',
  '@/api/plugins'
])

const stubPlugin = {
  name: 'harness-stubs',
  setup(build) {
    build.onResolve({ filter: /^@/ }, args => {
      if (STUBS.has(args.path)) {
        return { path: resolve(here, 'stubs.tsx') }
      }

      if (args.path.startsWith('@/')) {
        const base = resolve(src, args.path.slice(2))
        // A file wins over a same-named directory (src/i18n.ts beside src/i18n/), and a bare path
        // that is a directory is never a module.
        const found = ['', '.tsx', '.ts', '.js', '/index.tsx', '/index.ts', '/index.js']
          .map(ext => base + ext)
          .find(path => existsSync(path) && statSync(path).isFile())

        return found ? { path: found } : null
      }

      return null
    })
  }
}

await build({
  bundle: true,
  define: { 'import.meta.env.BASE_URL': '"/"' },
  entryPoints: [resolve(here, 'harness.tsx')],
  format: 'iife',
  jsx: 'automatic',
  loader: { '.js': 'jsx' },
  logLevel: 'warning',
  outfile: resolve(here, 'dist', 'harness.js'),
  plugins: [stubPlugin],
  target: 'es2020'
})

console.log('built scripts/island-browser/dist/harness.js')
