"use client"

import React from "react"

import { useState } from "react"
import { cn } from "@/lib/utils"
import {
  Copy,
  Check,
  ThumbsUp,
  ThumbsDown,
  Volume2,
  RefreshCw,
  User,
  Sparkles,
  ExternalLink,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { VoicePlayer } from "@/components/voice-player"
import { AudioWaveform } from "@/components/ui/audio-waveform"
import { ReasoningPanel } from "@/components/reasoning-panel"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

// Utility to separate thinking/reasoning from final answer
// Supports both <think>...</think> and <thinking>...</thinking> formats
function separateThinkingFromContent(content: string): { reasoning: string; finalAnswer: string } {
  let reasoning = ''
  let remainingContent = content

  // Match both <think>...</think> and <thinking>...</thinking> tags (case insensitive)
  const patterns = [
    /<think>([\s\S]*?)<\/think>/gi,
    /<thinking>([\s\S]*?)<\/thinking>/gi,
  ]

  for (const regex of patterns) {
    let matches
    // Extract all thinking blocks
    while ((matches = regex.exec(remainingContent)) !== null) {
      reasoning += matches[1].trim() + '\n\n'
    }
    // Remove tags from content
    remainingContent = remainingContent.replace(regex, '')
  }

  // Clean up
  const finalAnswer = remainingContent
    .replace(/^\s*\n+/, '') // Remove leading newlines
    .trim()

  return {
    reasoning: reasoning.trim(),
    finalAnswer
  }
}

interface ChatMessageProps {
  role: "user" | "assistant"
  content: string
  timestamp?: string
  codeBlocks?: Array<{
    language: string
    code: string
    title?: string
  }>
  searchResults?: Array<{
    title: string
    url: string
    snippet: string
  }>
  searchQuery?: string
  audioUrl?: string
  reasoning?: string
}

// Simple syntax highlighter for code
function highlightCode(code: string, language: string): React.ReactNode[] {
  const lines = code.split('\n')

  const patterns: Record<string, { pattern: RegExp; className: string }[]> = {
    default: [
      // Strings (double and single quotes)
      { pattern: /(["'`])(?:(?!\1)[^\\]|\\.)*\1/g, className: 'text-green-400' },
      // Comments
      { pattern: /(\/\/.*$|\/\*[\s\S]*?\*\/|#.*$)/gm, className: 'text-muted-foreground italic' },
      // Numbers
      { pattern: /\b(\d+\.?\d*)\b/g, className: 'text-orange-400' },
      // Keywords
      { pattern: /\b(const|let|var|function|return|if|else|for|while|class|import|export|from|default|async|await|try|catch|throw|new|this|super|extends|implements|interface|type|public|private|protected|static|readonly|enum|namespace|module|declare|as|is|in|of|typeof|instanceof|void|null|undefined|true|false)\b/g, className: 'text-purple-400' },
      // Function calls
      { pattern: /\b([a-zA-Z_$][\w$]*)\s*(?=\()/g, className: 'text-cyan-400' },
      // JSX tags
      { pattern: /(<\/?[A-Z][a-zA-Z0-9]*|<\/?[a-z][a-zA-Z0-9]*)/g, className: 'text-rose-400' },
      // Operators
      { pattern: /(=>|===|!==|==|!=|<=|>=|&&|\|\||[+\-*/%=<>!&|^~?:])/g, className: 'text-yellow-400' },
      // Properties/attributes
      { pattern: /\b([a-zA-Z_$][\w$]*)\s*(?=:)/g, className: 'text-blue-400' },
      // Types (PascalCase)
      { pattern: /\b([A-Z][a-zA-Z0-9]*)\b/g, className: 'text-teal-400' },
    ]
  }

  const rules = patterns[language] || patterns.default

  return lines.map((line, lineIndex) => {
    if (!line.trim()) {
      return <span key={lineIndex}>{'\n'}</span>
    }

    // Find all matches with their positions
    const matches: Array<{ start: number; end: number; text: string; className: string }> = []

    for (const rule of rules) {
      const regex = new RegExp(rule.pattern.source, rule.pattern.flags)
      let match
      while ((match = regex.exec(line)) !== null) {
        matches.push({
          start: match.index,
          end: match.index + match[0].length,
          text: match[0],
          className: rule.className
        })
      }
    }

    // Sort by position and filter overlapping (keep first match)
    matches.sort((a, b) => a.start - b.start)
    const filteredMatches: typeof matches = []
    let lastEnd = 0
    for (const m of matches) {
      if (m.start >= lastEnd) {
        filteredMatches.push(m)
        lastEnd = m.end
      }
    }

    // Build the highlighted line
    const parts: React.ReactNode[] = []
    let currentIndex = 0

    for (const m of filteredMatches) {
      if (m.start > currentIndex) {
        parts.push(<span key={`${lineIndex}-${currentIndex}`}>{line.slice(currentIndex, m.start)}</span>)
      }
      parts.push(<span key={`${lineIndex}-${m.start}`} className={m.className}>{m.text}</span>)
      currentIndex = m.end
    }

    if (currentIndex < line.length) {
      parts.push(<span key={`${lineIndex}-end`}>{line.slice(currentIndex)}</span>)
    }

    return <span key={lineIndex}>{parts}{lineIndex < lines.length - 1 ? '\n' : ''}</span>
  })
}

export function ChatMessage({
  role,
  content,
  timestamp,
  codeBlocks,
  searchResults,
  searchQuery,
  audioUrl,
  reasoning: propReasoning,
}: ChatMessageProps) {
  const [copied, setCopied] = useState(false)
  const [showVoice, setShowVoice] = useState(false)
  const [feedback, setFeedback] = useState<"up" | "down" | null>(null)

  // Process content to separate reasoning from final answer
  // This handles cases where <think> tags are still in the content
  const { reasoning: extractedReasoning, finalAnswer } = separateThinkingFromContent(content || '')

  // Use extracted reasoning if available, otherwise use prop
  const reasoning = extractedReasoning || propReasoning || ''
  // Use cleaned content (without think tags) for display
  const displayContent = finalAnswer || content || ''

  const handleCopy = async () => {
    await navigator.clipboard.writeText(displayContent)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleCopyCode = async (code: string) => {
    await navigator.clipboard.writeText(code)
  }

  return (
    <div
      className={cn(
        "group flex gap-4 py-6",
        role === "user" ? "justify-end" : "justify-start"
      )}
    >
      {role === "assistant" && (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/20">
          <Sparkles className="h-4 w-4 text-primary" />
        </div>
      )}

      <div
        className={cn(
          "flex max-w-3xl flex-col gap-3",
          role === "user" && "items-end"
        )}
      >
        <div
          className={cn(
            "rounded-2xl px-4 py-3",
            role === "user"
              ? "bg-primary text-primary-foreground"
              : "bg-card text-foreground"
          )}
        >
          {role === "assistant" ? (
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  // Style code blocks
                  code({ node, inline, className, children, ...props }: any) {
                    const match = /language-(\w+)/.exec(className || '')
                    if (!inline && match) {
                      return (
                        <div className="my-2 overflow-hidden rounded-lg border border-border bg-background">
                          <div className="flex items-center justify-between border-b border-border bg-card px-3 py-1">
                            <span className="text-xs text-muted-foreground">{match[1]}</span>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => navigator.clipboard.writeText(String(children))}
                              className="h-6 text-xs"
                            >
                              <Copy className="mr-1 h-3 w-3" />
                              Copy
                            </Button>
                          </div>
                          <pre className="overflow-x-auto p-3 bg-[oklch(0.06_0.005_260)]">
                            <code className="text-xs font-mono" {...props}>
                              {children}
                            </code>
                          </pre>
                        </div>
                      )
                    }
                    return (
                      <code className="rounded bg-muted px-1.5 py-0.5 text-sm font-mono" {...props}>
                        {children}
                      </code>
                    )
                  },
                  // Style links
                  a({ children, href, ...props }: any) {
                    return (
                      <a
                        href={href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-primary hover:underline inline-flex items-center gap-1"
                        {...props}
                      >
                        {children}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )
                  },
                  // Style paragraphs
                  p({ children, ...props }: any) {
                    return (
                      <p className="text-sm leading-relaxed mb-2 last:mb-0" {...props}>
                        {children}
                      </p>
                    )
                  },
                  // Style lists
                  ul({ children, ...props }: any) {
                    return (
                      <ul className="list-disc list-inside space-y-1 mb-2" {...props}>
                        {children}
                      </ul>
                    )
                  },
                  ol({ children, ...props }: any) {
                    return (
                      <ol className="list-decimal list-inside space-y-1 mb-2" {...props}>
                        {children}
                      </ol>
                    )
                  },
                  // Style headings
                  h1({ children, ...props }: any) {
                    return <h1 className="text-xl font-bold mb-2" {...props}>{children}</h1>
                  },
                  h2({ children, ...props }: any) {
                    return <h2 className="text-lg font-bold mb-2" {...props}>{children}</h2>
                  },
                  h3({ children, ...props }: any) {
                    return <h3 className="text-base font-semibold mb-1" {...props}>{children}</h3>
                  },
                  // Style blockquotes
                  blockquote({ children, ...props }: any) {
                    return (
                      <blockquote className="border-l-4 border-primary/30 pl-4 italic text-muted-foreground my-2" {...props}>
                        {children}
                      </blockquote>
                    )
                  },
                  // Style tables
                  table({ children, ...props }: any) {
                    return (
                      <div className="overflow-x-auto my-2">
                        <table className="min-w-full border border-border" {...props}>
                          {children}
                        </table>
                      </div>
                    )
                  },
                  th({ children, ...props }: any) {
                    return <th className="border border-border bg-muted px-3 py-1 text-left text-sm font-semibold" {...props}>{children}</th>
                  },
                  td({ children, ...props }: any) {
                    return <td className="border border-border px-3 py-1 text-sm" {...props}>{children}</td>
                  },
                }}
              >
                {displayContent}
              </ReactMarkdown>
            </div>
          ) : (
            <p className="text-sm leading-relaxed whitespace-pre-wrap">{displayContent}</p>
          )}
        </div>

        {/* Code Blocks */}
        {codeBlocks?.map((block, index) => (
          <div
            key={`code-${index}`}
            className="w-full overflow-hidden rounded-xl border border-border bg-background"
          >
            <div className="flex items-center justify-between border-b border-border bg-card px-4 py-2">
              <div className="flex items-center gap-2">
                <div className="flex h-3 w-3 rounded-full bg-destructive/50" />
                <div className="flex h-3 w-3 rounded-full bg-yellow-500/50" />
                <div className="flex h-3 w-3 rounded-full bg-green-500/50" />
                <span className="ml-2 text-xs text-muted-foreground">
                  {block.title || block.language}
                </span>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => handleCopyCode(block.code)}
                className="h-7 text-xs text-muted-foreground hover:text-foreground"
              >
                <Copy className="mr-1 h-3 w-3" />
                Copy
              </Button>
            </div>
            <pre className="overflow-x-auto p-4 bg-[oklch(0.06_0.005_260)]">
              <code className="text-xs font-mono text-foreground leading-relaxed">
                {highlightCode(block.code, block.language)}
              </code>
            </pre>
          </div>
        ))}

        {/* Search Results */}
        {searchResults && searchResults.length > 0 && (
          <div className="w-full space-y-2">
            {searchQuery && (
              <p className="text-xs text-muted-foreground">
                Search results for: {searchQuery}
              </p>
            )}
            {searchResults.map((result, index) => (
              <a
                key={`search-${index}`}
                href={result.url}
                target="_blank"
                rel="noopener noreferrer"
                className="block rounded-lg border border-border bg-card p-3 transition-colors hover:bg-accent"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1">
                    <h4 className="text-sm font-medium text-foreground line-clamp-1">
                      {result.title}
                    </h4>
                    <p className="mt-1 text-xs text-muted-foreground line-clamp-2">
                      {result.snippet}
                    </p>
                  </div>
                  <ExternalLink className="h-4 w-4 shrink-0 text-muted-foreground" />
                </div>
              </a>
            ))}
          </div>
        )}

        {/* Audio Waveform */}
        {role === "assistant" && audioUrl && (
          <AudioWaveform audioUrl={audioUrl} />
        )}

        {/* Reasoning Content */}
        {role === "assistant" && reasoning && (
          <ReasoningPanel reasoning={reasoning} />
        )}

        {/* Voice Player (Fallback for TTS) */}
        {role === "assistant" && !audioUrl && showVoice && (
          <VoicePlayer
            text={content}
            onClose={() => setShowVoice(false)}
            className="w-full"
          />
        )}

        {/* Actions */}
        {role === "assistant" && (
          <div className="flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
            <Button
              variant="ghost"
              size="icon"
              onClick={handleCopy}
              className="h-8 w-8 text-muted-foreground hover:text-foreground"
            >
              {copied ? (
                <Check className="h-4 w-4 text-green-500" />
              ) : (
                <Copy className="h-4 w-4" />
              )}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setShowVoice(!showVoice)}
              className={cn(
                "h-8 w-8",
                showVoice
                  ? "text-primary"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <Volume2 className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setFeedback(feedback === "up" ? null : "up")}
              className={cn(
                "h-8 w-8",
                feedback === "up"
                  ? "text-green-500"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <ThumbsUp className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setFeedback(feedback === "down" ? null : "down")}
              className={cn(
                "h-8 w-8",
                feedback === "down"
                  ? "text-destructive"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              <ThumbsDown className="h-4 w-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-muted-foreground hover:text-foreground"
            >
              <RefreshCw className="h-4 w-4" />
            </Button>
          </div>
        )}

        {timestamp && (
          <span className="text-xs text-muted-foreground">{timestamp}</span>
        )}
      </div>

      {role === "user" && (
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-secondary">
          <User className="h-4 w-4 text-secondary-foreground" />
        </div>
      )}
    </div>
  )
}
