"use client"

import React, { useState, useEffect, useRef, useMemo } from "react"
import { 
  Search, 
  Save, 
  FileText, 
  Terminal, 
  Play, 
  Square, 
  Sun, 
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  Minimize2,
  Maximize2,
  X,
  Sparkles
} from "lucide-react"
import { safeTrim, toStr } from '@/lib/strings'

export interface Command {
  id: string
  label: string
  description?: string
  icon?: React.ReactNode
  action: () => void
  keywords?: string[]
}

interface CommandPaletteProps {
  isOpen: boolean
  onClose: () => void
  commands: Command[]
}

/**
 * Simple fuzzy search implementation
 * Checks if all characters in the query appear in order in the target string
 */
function fuzzyMatch(query: string, target: string): { matches: boolean; score: number } {
  const lowerQuery = query.toLowerCase()
  const lowerTarget = target.toLowerCase()
  
  if (lowerQuery === '') {
    return { matches: true, score: 0 }
  }
  
  let queryIndex = 0
  let targetIndex = 0
  let score = 0
  let consecutiveMatches = 0
  
  while (queryIndex < lowerQuery.length && targetIndex < lowerTarget.length) {
    if (lowerQuery[queryIndex] === lowerTarget[targetIndex]) {
      queryIndex++
      consecutiveMatches++
      // Bonus points for consecutive matches
      score += consecutiveMatches * 2
      
      // Bonus for matching at word boundaries
      if (targetIndex === 0 || lowerTarget[targetIndex - 1] === ' ') {
        score += 5
      }
    } else {
      consecutiveMatches = 0
    }
    targetIndex++
  }
  
  const matches = queryIndex === lowerQuery.length
  
  // Penalize longer strings
  if (matches) {
    score -= lowerTarget.length
  }
  
  return { matches, score }
}

/**
 * Filter and sort commands based on fuzzy search query
 */
function filterCommands(commands: Command[], query: string): Command[] {
  if (!safeTrim(query)) {
    return commands
  }
  
  const results = commands
    .map(cmd => {
      // Check label match
      const labelMatch = fuzzyMatch(query, cmd.label)
      
      // Check description match
      const descMatch = cmd.description 
        ? fuzzyMatch(query, cmd.description)
        : { matches: false, score: 0 }
      
      // Check keywords match
      let keywordScore = 0
      let keywordMatches = false
      if (cmd.keywords) {
        for (const keyword of cmd.keywords) {
          const match = fuzzyMatch(query, keyword)
          if (match.matches && match.score > keywordScore) {
            keywordScore = match.score
            keywordMatches = true
          }
        }
      }
      
      // Combine scores (prioritize label matches)
      const matches = labelMatch.matches || descMatch.matches || keywordMatches
      const score = Math.max(
        labelMatch.score * 2, // Label matches are worth more
        descMatch.score,
        keywordScore
      )
      
      return { cmd, matches, score }
    })
    .filter(result => result.matches)
    .sort((a, b) => b.score - a.score)
    .map(result => result.cmd)
  
  return results
}

export default function CommandPalette({ isOpen, onClose, commands }: CommandPaletteProps) {
  const [query, setQuery] = useState('')
  const [selectedIndex, setSelectedIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  
  // Filter commands based on query
  const filteredCommands = useMemo(() => {
    return filterCommands(commands, query)
  }, [commands, query])
  
  // Reset state when opened
  useEffect(() => {
    if (isOpen) {
      setQuery('')
      setSelectedIndex(0)
      // Focus input after a brief delay to ensure modal is rendered
      setTimeout(() => {
        inputRef.current?.focus()
      }, 50)
    }
  }, [isOpen])
  
  // Reset selected index when filtered commands change
  useEffect(() => {
    setSelectedIndex(0)
  }, [filteredCommands])
  
  // Scroll selected item into view
  useEffect(() => {
    if (listRef.current) {
      const selectedElement = listRef.current.children[selectedIndex] as HTMLElement
      if (selectedElement) {
        selectedElement.scrollIntoView({
          block: 'nearest',
          behavior: 'smooth'
        })
      }
    }
  }, [selectedIndex])
  
  // Handle keyboard navigation
  const handleKeyDown = (e: React.KeyboardEvent) => {
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        setSelectedIndex(prev => 
          prev < filteredCommands.length - 1 ? prev + 1 : prev
        )
        break
        
      case 'ArrowUp':
        e.preventDefault()
        setSelectedIndex(prev => prev > 0 ? prev - 1 : 0)
        break
        
      case 'Enter':
        e.preventDefault()
        if (filteredCommands[selectedIndex]) {
          executeCommand(filteredCommands[selectedIndex])
        }
        break
        
      case 'Escape':
        e.preventDefault()
        onClose()
        break
    }
  }
  
  // Execute command and close palette
  const executeCommand = (command: Command) => {
    command.action()
    onClose()
  }
  
  // Handle backdrop click
  const handleBackdropClick = (e: React.MouseEvent) => {
    if (e.target === e.currentTarget) {
      onClose()
    }
  }
  
  if (!isOpen) return null
  
  return (
    <div 
      className="fixed inset-0 bg-black/50 flex items-start justify-center z-50 pt-20"
      onClick={handleBackdropClick}
    >
      <div className="bg-gray-800 rounded-lg shadow-2xl w-full max-w-2xl border border-gray-700 overflow-hidden">
        {/* Search Input */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-700">
          <Search className="w-5 h-5 text-gray-400 flex-shrink-0" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Type a command or search..."
            className="flex-1 bg-transparent text-white placeholder-gray-400 outline-none text-base"
          />
          <button
            onClick={onClose}
            className="p-1 hover:bg-gray-700 rounded transition-colors"
            title="Close (Esc)"
          >
            <X className="w-4 h-4 text-gray-400" />
          </button>
        </div>
        
        {/* Command List */}
        <div 
          ref={listRef}
          className="max-h-96 overflow-y-auto"
        >
          {filteredCommands.length === 0 ? (
            <div className="px-4 py-8 text-center text-gray-400">
              <p className="text-sm">No commands found</p>
              {query && (
                <p className="text-xs mt-1">Try a different search term</p>
              )}
            </div>
          ) : (
            filteredCommands.map((command, index) => (
              <button
                key={command.id}
                onClick={() => executeCommand(command)}
                onMouseEnter={() => setSelectedIndex(index)}
                className={`
                  w-full flex items-center gap-3 px-4 py-3 text-left transition-colors
                  ${index === selectedIndex 
                    ? 'bg-blue-600 text-white' 
                    : 'text-gray-300 hover:bg-gray-700'
                  }
                  ${index !== filteredCommands.length - 1 ? 'border-b border-gray-700' : ''}
                `}
              >
                {/* Icon */}
                {command.icon && (
                  <div className="flex-shrink-0 w-5 h-5">
                    {command.icon}
                  </div>
                )}
                
                {/* Label and Description */}
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm">
                    {command.label}
                  </div>
                  {command.description && (
                    <div className={`text-xs mt-0.5 ${
                      index === selectedIndex ? 'text-blue-100' : 'text-gray-400'
                    }`}>
                      {command.description}
                    </div>
                  )}
                </div>
              </button>
            ))
          )}
        </div>
        
        {/* Footer with hints */}
        <div className="px-4 py-2 bg-gray-900 border-t border-gray-700 flex items-center justify-between text-xs text-gray-400">
          <div className="flex items-center gap-4">
            <span>↑↓ Navigate</span>
            <span>↵ Execute</span>
            <span>Esc Close</span>
          </div>
          <div>
            {filteredCommands.length} {filteredCommands.length === 1 ? 'command' : 'commands'}
          </div>
        </div>
      </div>
    </div>
  )
}

/**
 * Hook to create standard IDE commands
 */
export function useIDECommands({
  onSaveFile,
  onNewFile,
  onNewTerminal,
  onStartContainer,
  onStopContainer,
  onToggleTheme,
  onToggleLeftPanel,
  onToggleRightPanel,
  onToggleTerminal,
  onProposeChanges,
  onQuickPropose,
  canSave = false,
  canStartContainer = false,
  canStopContainer = false,
  theme = 'dark'
}: {
  onSaveFile?: () => void
  onNewFile?: () => void
  onNewTerminal?: () => void
  onStartContainer?: () => void
  onStopContainer?: () => void
  onToggleTheme?: () => void
  onToggleLeftPanel?: () => void
  onToggleRightPanel?: () => void
  onToggleTerminal?: () => void
  onProposeChanges?: () => void
  onQuickPropose?: () => void
  canSave?: boolean
  canStartContainer?: boolean
  canStopContainer?: boolean
  theme?: string
}): Command[] {
  return useMemo(() => {
    const commands: Command[] = []
    
    // File commands
    if (onSaveFile && canSave) {
      commands.push({
        id: 'save-file',
        label: 'Save File',
        description: 'Save the current file (Ctrl+S)',
        icon: <Save className="w-5 h-5" />,
        action: onSaveFile,
        keywords: ['save', 'write', 'persist']
      })
    }
    
    if (onNewFile) {
      commands.push({
        id: 'new-file',
        label: 'New File',
        description: 'Create a new file in the workspace',
        icon: <FileText className="w-5 h-5" />,
        action: onNewFile,
        keywords: ['create', 'new', 'file', 'add']
      })
    }

    // AI commands
    if (onProposeChanges) {
      commands.push({
        id: 'propose-changes',
        label: 'AI → Propose Changes',
        description: 'Ask AI to propose code changes for the current file',
        icon: <Sparkles className="w-5 h-5" />,
        action: onProposeChanges,
        keywords: ['ai', 'propose', 'changes', 'modify', 'refactor', 'suggest', 'copilot']
      })
    }

    if (onQuickPropose) {
      commands.push({
        id: 'quick-propose',
        label: 'AI → Quick Propose (Ctrl+Shift+I)',
        description: 'Quickly propose changes with a prompt dialog',
        icon: <Sparkles className="w-5 h-5" />,
        action: onQuickPropose,
        keywords: ['ai', 'quick', 'propose', 'prompt', 'fast', 'shortcut', 'copilot']
      })
    }
    
    // Terminal commands
    if (onNewTerminal) {
      commands.push({
        id: 'new-terminal',
        label: 'New Terminal',
        description: 'Open a new terminal tab',
        icon: <Terminal className="w-5 h-5" />,
        action: onNewTerminal,
        keywords: ['terminal', 'shell', 'bash', 'console']
      })
    }
    
    // Container commands
    if (onStartContainer && canStartContainer) {
      commands.push({
        id: 'start-container',
        label: 'Start Container',
        description: 'Start the session container',
        icon: <Play className="w-5 h-5" />,
        action: onStartContainer,
        keywords: ['start', 'run', 'container', 'docker']
      })
    }
    
    if (onStopContainer && canStopContainer) {
      commands.push({
        id: 'stop-container',
        label: 'Stop Container',
        description: 'Stop the session container',
        icon: <Square className="w-5 h-5" />,
        action: onStopContainer,
        keywords: ['stop', 'halt', 'container', 'docker']
      })
    }
    
    // Theme commands
    if (onToggleTheme) {
      commands.push({
        id: 'toggle-theme',
        label: 'Toggle Theme',
        description: `Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`,
        icon: theme === 'dark' ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />,
        action: onToggleTheme,
        keywords: ['theme', 'dark', 'light', 'appearance']
      })
    }
    
    // Panel commands
    if (onToggleLeftPanel) {
      commands.push({
        id: 'toggle-left-panel',
        label: 'Toggle Left Panel',
        description: 'Show/hide the file explorer (Ctrl+B)',
        icon: <PanelLeftClose className="w-5 h-5" />,
        action: onToggleLeftPanel,
        keywords: ['panel', 'sidebar', 'explorer', 'files', 'left']
      })
    }
    
    if (onToggleRightPanel) {
      commands.push({
        id: 'toggle-right-panel',
        label: 'Toggle Right Panel',
        description: 'Show/hide the AI assistant and execution panel',
        icon: <PanelRightClose className="w-5 h-5" />,
        action: onToggleRightPanel,
        keywords: ['panel', 'sidebar', 'assistant', 'ai', 'right']
      })
    }
    
    if (onToggleTerminal) {
      commands.push({
        id: 'toggle-terminal',
        label: 'Toggle Terminal',
        description: 'Show/hide the terminal panel (Ctrl+J)',
        icon: <Minimize2 className="w-5 h-5" />,
        action: onToggleTerminal,
        keywords: ['terminal', 'console', 'shell', 'bottom']
      })
    }
    
    return commands
  }, [
    onSaveFile,
    onNewFile,
    onNewTerminal,
    onStartContainer,
    onStopContainer,
    onToggleTheme,
    onToggleLeftPanel,
    onToggleRightPanel,
    onToggleTerminal,
    canSave,
    canStartContainer,
    canStopContainer,
    theme
  ])
}
