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
import { Highlight, themes } from "prism-react-renderer"

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

// Language mapping for prism-react-renderer
const languageMap: Record<string, string> = {
  js: 'javascript',
  ts: 'typescript',
  jsx: 'jsx',
  tsx: 'tsx',
  py: 'python',
  rb: 'ruby',
  yml: 'yaml',
  sh: 'bash',
  shell: 'bash',
  zsh: 'bash',
  dockerfile: 'docker',
  md: 'markdown',
}

// Code block component with prism-react-renderer
function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false)
  const normalizedLang = languageMap[language.toLowerCase()] || language.toLowerCase()

  const handleCopy = async () => {
    await navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-violet-500/20 bg-gradient-to-br from-slate-900 via-slate-900 to-violet-950/30">
      <div className="flex items-center justify-between border-b border-violet-500/20 bg-slate-800/50 px-4 py-2">
        <div className="flex items-center gap-2">
          <div className="flex gap-1.5">
            <div className="h-3 w-3 rounded-full bg-red-500/80" />
            <div className="h-3 w-3 rounded-full bg-yellow-500/80" />
            <div className="h-3 w-3 rounded-full bg-green-500/80" />
          </div>
          <span className="text-xs font-medium text-violet-300/80">{language}</span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleCopy}
          className="h-6 text-xs text-violet-300/70 hover:text-violet-200 hover:bg-violet-500/20"
        >
          {copied ? <Check className="mr-1 h-3 w-3 text-green-400" /> : <Copy className="mr-1 h-3 w-3" />}
          {copied ? 'Copied!' : 'Copy'}
        </Button>
      </div>
      <Highlight theme={themes.nightOwl} code={code} language={normalizedLang}>
        {({ className, style, tokens, getLineProps, getTokenProps }) => (
          <pre className="overflow-x-auto p-4" style={{ ...style, background: '#0d1117', margin: 0 }}>
            <code className="text-sm font-mono leading-relaxed">
              {tokens.map((line, i) => (
                <div key={i} {...getLineProps({ line })} className="table-row">
                  <span className="table-cell pr-4 text-right text-xs text-slate-600 select-none">
                    {i + 1}
                  </span>
                  <span className="table-cell">
                    {line.map((token, key) => (
                      <span key={key} {...getTokenProps({ token })} />
                    ))}
                  </span>
                </div>
              ))}
            </code>
          </pre>
        )}
      </Highlight>
    </div>
  )
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
                  // Style code blocks with syntax highlighting using prism-react-renderer
                  code({ node, inline, className, children, ...props }: any) {
                    const match = /language-(\w+)/.exec(className || '')
                    const codeString = String(children).replace(/\n$/, '')

                    if (!inline && match) {
                      const language = match[1]
                      return <CodeBlock code={codeString} language={language} />
                    }

                    // Check if it's a multi-line code block without language specified
                    if (!inline && codeString.includes('\n')) {
                      return <CodeBlock code={codeString} language="text" />
                    }

                    return (
                      <code className="rounded-md bg-violet-500/20 px-1.5 py-0.5 text-sm font-mono text-violet-300" {...props}>
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
          <div key={`code-${index}`} className="w-full">
            {block.title && (
              <div className="text-xs text-muted-foreground mb-1">{block.title}</div>
            )}
            <CodeBlock code={block.code} language={block.language} />
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
