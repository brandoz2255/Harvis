import React from 'react'
import {
  File, FileText, Code, Image, Music, Video,
  Folder, FolderOpen, FileJson, FileCode, FileType,
  Database, Settings, Package, Terminal
} from 'lucide-react'

const EXT_ICON_MAP: Record<string, React.ComponentType<{ size?: number; className?: string }>> = {
  // Code
  py: Code, js: FileCode, ts: FileCode, tsx: FileCode, jsx: FileCode,
  java: Code, cpp: Code, c: Code, go: Code, rs: Code, rb: Code, php: Code,
  // Web
  html: FileCode, css: FileCode, vue: FileCode, svelte: FileCode,
  // Data
  json: FileJson, yaml: FileText, yml: FileText, toml: FileText, xml: FileText,
  sql: Database,
  // Config
  env: Settings, ini: Settings, conf: Settings, cfg: Settings,
  // Docs
  md: FileText, txt: FileText, rst: FileText, log: FileText,
  // Media
  png: Image, jpg: Image, jpeg: Image, gif: Image, svg: Image, webp: Image,
  mp3: Music, wav: Music, ogg: Music, flac: Music,
  mp4: Video, webm: Video, mov: Video, avi: Video,
  // Build
  lock: Package, dockerfile: Terminal,
  sh: Terminal, bash: Terminal, zsh: Terminal,
}

interface FileIconProps {
  fileName: string
  size?: number
  className?: string
}

export function FileIcon({ fileName, size = 16, className = '' }: FileIconProps) {
  const ext = fileName.split('.').pop()?.toLowerCase() || ''
  const name = fileName.toLowerCase()

  // Special filenames
  if (name === 'dockerfile' || name === 'makefile') {
    return <Terminal size={size} className={`text-blue-400 ${className}`} />
  }
  if (name === 'package.json') {
    return <Package size={size} className={`text-green-400 ${className}`} />
  }

  const IconComponent = EXT_ICON_MAP[ext] || File
  const colorMap: Record<string, string> = {
    py: 'text-yellow-400', js: 'text-yellow-300', ts: 'text-blue-400',
    tsx: 'text-blue-400', jsx: 'text-yellow-300', java: 'text-orange-400',
    go: 'text-cyan-400', rs: 'text-orange-500', html: 'text-orange-400',
    css: 'text-blue-300', json: 'text-yellow-300', md: 'text-gray-400',
    sql: 'text-blue-400', sh: 'text-green-400',
  }
  const color = colorMap[ext] || 'text-gray-400'

  return <IconComponent size={size} className={`${color} ${className}`} />
}

interface FolderIconProps {
  size?: number
  className?: string
  isOpen?: boolean
}

export function FolderIcon({ size = 16, className = '', isOpen = false }: FolderIconProps) {
  const Icon = isOpen ? FolderOpen : Folder
  return <Icon size={size} className={`text-yellow-500 ${className}`} />
}
