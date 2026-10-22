import { isFileEditTool } from '@/lib/tool-render-class'
import type { ChatMessage } from '@/lib/chat-messages'

export interface SessionChangedFile {
  /** Absolute path, resolved against the sandbox folder when the tool gave a relative one. */
  path: string
  /** Shorter text for display: relative to the sandbox folder when the file is inside it. */
  label: string
}

// Harvis workspace runs edit with str_replace and apply_patch (workspace/orchestration/tools.py) besides the
// edit tools the transcript already draws as diffs.
const isChangeTool = (name: string) => isFileEditTool(name) || name === 'str_replace' || name === 'apply_patch'

const PATH_ARG_KEYS = ['path', 'file_path', 'filepath', 'file', 'filename', 'target_file']
const PATCH_FILE_RE = /^\*\*\*\s+(?:Add|Update|Delete|Move to)\s+File:\s*(.+?)\s*$/gim

const isAbsolute = (path: string) => path.startsWith('/') || /^[a-z]:[\\/]/i.test(path)

function joinPath(cwd: string, path: string): string {
  const parts: string[] = []

  for (const part of `${cwd.replace(/[\\/]+$/, '')}/${path}`.split(/[\\/]+/)) {
    if (part === '..') {
      parts.pop()
    } else if (part && part !== '.') {
      parts.push(part)
    }
  }

  return `${cwd.startsWith('/') ? '/' : ''}${parts.join('/')}`
}

function toolFailed(part: { isError?: boolean; result?: unknown }): boolean {
  if (part.isError) {
    return true
  }

  let result = part.result

  if (typeof result === 'string') {
    try {
      result = JSON.parse(result)
    } catch {
      return false
    }
  }

  if (result && typeof result === 'object') {
    const record = result as Record<string, unknown>

    return Boolean(record.error) || record.success === false
  }

  return false
}

function argsRecord(args: unknown): Record<string, unknown> {
  if (typeof args === 'string') {
    try {
      const parsed = JSON.parse(args)

      return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : {}
    } catch {
      return {}
    }
  }

  return args && typeof args === 'object' ? (args as Record<string, unknown>) : {}
}

function pathsFromArgs(args: Record<string, unknown>): string[] {
  const found: string[] = []

  for (const key of PATH_ARG_KEYS) {
    const value = args[key]

    if (typeof value === 'string' && value.trim()) {
      found.push(value.trim())

      break
    }
  }

  // A V4A-style `patch` body names every file it touches on its own lines.
  if (typeof args.patch === 'string') {
    for (const match of args.patch.matchAll(PATCH_FILE_RE)) {
      found.push(match[1])
    }
  }

  return found
}

/**
 * Files this conversation has written or edited, newest first.
 *
 * Read from the finished write/edit/patch tool calls in the transcript rather
 * than from git: a Harvis sandbox folder is not necessarily a git repository.
 * Harvis stores only the text of each turn, so a reopened chat has no tool
 * calls and the list starts empty again. A call that errored changed nothing
 * and is skipped.
 */
export function sessionChangedFiles(messages: readonly ChatMessage[], cwd: string): SessionChangedFile[] {
  const root = cwd.trim()
  const seen = new Set<string>()
  const files: SessionChangedFile[] = []

  for (let m = messages.length - 1; m >= 0; m -= 1) {
    const parts = messages[m].parts

    for (let p = parts.length - 1; p >= 0; p -= 1) {
      const part = parts[p]

      if (part.type !== 'tool-call' || !isChangeTool(part.toolName) || part.result === undefined) {
        continue
      }

      if (toolFailed(part)) {
        continue
      }

      for (const raw of pathsFromArgs(argsRecord(part.args)).reverse()) {
        const path = isAbsolute(raw) || raw.startsWith('~') || !root ? raw : joinPath(root, raw)

        if (seen.has(path)) {
          continue
        }

        seen.add(path)

        const prefix = root ? `${root.replace(/[\\/]+$/, '')}/` : ''

        files.push({ label: prefix && path.startsWith(prefix) ? path.slice(prefix.length) : path, path })
      }
    }
  }

  return files
}
