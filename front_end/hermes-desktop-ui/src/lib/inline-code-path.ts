import { isHarvisFileRoute, isServerRoute } from '@/lib/harvis-files'

// Bare names (`main.py`) only count with an extension people actually open,
// so `v1.2` and `e.g` stay plain code.
const FILE_EXTENSIONS = new Set(
  (
    'c cfg conf cpp css csv docx gif go h hpp htm html ini ipynb java jpeg jpg js json jsx log lua md mjs pdf png ' +
    'pptx py rb rs sh sql svg toml ts tsx txt webp xlsx xml yaml yml'
  ).split(' ')
)

const URL_SCHEME_RE = /^[a-z][a-z\d+.-]*:\/\//i
// Globs, shell syntax and placeholders are not one file.
const NOT_A_PATH_RE = /[\s*?<>|"'`{}$]|^@/

/**
 * The file an inline code span names, for opening it in the side panel, or
 * null when the span is not a path. Editor-style `:line[:col]` suffixes are
 * dropped because the preview opens the whole file.
 */
export function pathFromInlineCode(text: string): string | null {
  const raw = text.trim()

  if (!raw || raw.length > 260 || NOT_A_PATH_RE.test(raw)) {
    return null
  }

  if (URL_SCHEME_RE.test(raw) && !/^file:\/\//i.test(raw)) {
    return null
  }

  const path = raw.replace(/:\d+(?::\d+)?$/, '')

  if (isHarvisFileRoute(path)) {
    return path
  }

  if (isServerRoute(path) || path.endsWith('/')) {
    return null
  }

  const name = path.split(/[\\/]/).pop() || ''
  const ext = /\.([a-z\d]{1,6})$/i.exec(name)?.[1]?.toLowerCase()

  if (!ext || !FILE_EXTENSIONS.has(ext)) {
    return null
  }

  return path
}
