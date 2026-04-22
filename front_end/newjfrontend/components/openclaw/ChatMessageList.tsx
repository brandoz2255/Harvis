"use client"

import { useMemo, useState } from "react"
import { cn } from "@/lib/utils"
import {
  Loader2,
  Copy,
  Check,
  ExternalLink,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Highlight, themes } from "prism-react-renderer"
import { HarvisMascot } from "@/components/mascots/HarvisMascot"
import type { NormalizedMessage, ChatMessageContentItem } from "@/lib/openclaw/types"

interface ChatMessageListProps {
  messages: NormalizedMessage[]
  streamText: string | null
  streamRunId: string | null
  thinkingLevel: string | null
  isStreaming: boolean
  isThinking: boolean
  focusMode: boolean
  showThinking: boolean
  className?: string
  onScrollToBottom?: () => void
}

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
          <span className="text-xs font-medium text-violet-300/80">{language || "text"}</span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          onClick={handleCopy}
          className="h-6 text-xs text-violet-300/70 hover:text-violet-200 hover:bg-violet-500/20"
        >
          {copied ? <Check className="mr-1 h-3 w-3 text-green-400" /> : <Copy className="mr-1 h-3 w-3" />}
          {copied ? "Copied!" : "Copy"}
        </Button>
      </div>
      <Highlight theme={themes.nightOwl} code={code} language={normalizedLang || "text"}>
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

function MessageContent({
  content,
  showThinking,
}: {
  content: ChatMessageContentItem[]
  showThinking: boolean
}) {
  const textItems = content.filter((c) => c.type === "text")
  const mainText = textItems.map((t) => t.text ?? "").join("")

  return (
    <div className="space-y-3">
      {mainText && (
        <div className="prose prose-sm dark:prose-invert max-w-none">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              code({ className, children, ...props }) {
                const match = /language-(\w+)/.exec(className || "")
                const lang = match ? match[1] : ""
                const code = String(children).replace(/\n$/, "")
                if (match) {
                  return <CodeBlock code={code} language={lang} />
                }
                // Multi-line unlabeled code blocks (e.g. shell output, ls -la, etc.)
                if (code.includes("\n")) {
                  return <CodeBlock code={code} language="text" />
                }
                return (
                  <code className="rounded-md bg-violet-500/20 px-1.5 py-0.5 text-sm font-mono text-violet-300" {...props}>
                    {children}
                  </code>
                )
              },
              pre({ children }) {
                return <>{children}</>
              },
              p({ children }) {
                return <p className="text-sm leading-relaxed mb-2 last:mb-0">{children}</p>
              },
              h1({ children }) {
                return <h1 className="text-xl font-bold mb-2">{children}</h1>
              },
              h2({ children }) {
                return <h2 className="text-lg font-bold mb-2">{children}</h2>
              },
              h3({ children }) {
                return <h3 className="text-base font-semibold mb-1">{children}</h3>
              },
              table({ children }) {
                return (
                  <div className="overflow-x-auto my-2">
                    <table className="min-w-full border border-border text-sm">{children}</table>
                  </div>
                )
              },
              th({ children }) {
                return <th className="border border-border bg-muted px-3 py-1.5 text-left font-semibold">{children}</th>
              },
              td({ children }) {
                return <td className="border border-border px-3 py-1.5">{children}</td>
              },
              a({ href, children }) {
                return (
                  <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline inline-flex items-center gap-1">
                    {children}
                    <ExternalLink className="h-3 w-3" />
                  </a>
                )
              },
              ul({ children }) {
                return <ul className="list-disc list-outside space-y-1 mb-2 pl-5">{children}</ul>
              },
              ol({ children }) {
                return <ol className="list-decimal list-outside space-y-1 mb-2 pl-5">{children}</ol>
              },
              li({ children }) {
                return <li className="text-sm">{children}</li>
              },
              blockquote({ children }) {
                return (
                  <blockquote className="border-l-4 border-primary/30 pl-4 italic text-muted-foreground my-2">
                    {children}
                  </blockquote>
                )
              },
            }}
          >
            {mainText}
          </ReactMarkdown>
        </div>
      )}
    </div>
  )
}

function SingleMessage({
  message,
  showThinking,
}: {
  message: NormalizedMessage
  showThinking: boolean
}) {
  const isUser = message.role === "user"
  const isAssistant = message.role === "assistant"

  if (isUser) {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl bg-muted px-4 py-3">
          <MessageContent content={message.content} showThinking={showThinking} />
        </div>
      </div>
    )
  }

     if (isAssistant) {
      return (
        <div className="flex items-start gap-3 pl-10">
          <div className="w-8 h-8 shrink-0 mt-0.5">
            <HarvisMascot state="idle" size={32} />
          </div>
          <div className="max-w-[80%] rounded-2xl bg-card border border-border px-4 py-3">
            <MessageContent content={message.content} showThinking={showThinking} />
          </div>
        </div>
      )
    }

  return null
}

function StreamingMessage({
  text,
  thinkingLevel,
}: {
  text: string
  thinkingLevel: string | null
}) {
  return (
    <div className="flex items-start gap-3 pl-10">
      <div className="w-8 h-8 shrink-0 mt-0.5">
        <HarvisMascot state="talking" size={32} />
      </div>
      <div className="max-w-[80%] rounded-2xl bg-card border border-border px-4 py-3">
        {thinkingLevel && (
          <div className="flex items-center gap-1 text-xs text-muted-foreground mb-2">
            <Loader2 className="h-3 w-3 animate-spin" />
            Thinking...
          </div>
        )}
        <div className="prose prose-sm dark:prose-invert max-w-none">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              code({ className, children, ...props }) {
                const match = /language-(\w+)/.exec(className || "")
                const lang = match ? match[1] : ""
                const code = String(children).replace(/\n$/, "")
                if (match) return <CodeBlock code={code} language={lang} />
                if (code.includes("\n")) return <CodeBlock code={code} language="text" />
                return (
                  <code className="rounded-md bg-violet-500/20 px-1.5 py-0.5 text-sm font-mono text-violet-300" {...props}>
                    {children}
                  </code>
                )
              },
              pre({ children }) { return <>{children}</> },
              p({ children }) { return <p className="text-sm leading-relaxed mb-2 last:mb-0">{children}</p> },
            }}
          >
            {text}
          </ReactMarkdown>
        </div>
        <div className="flex items-center gap-1.5 mt-2">
          <div className="w-1.5 h-1.5 rounded-full bg-primary/70 animate-bounce" style={{ animationDelay: "0ms" }} />
          <div className="w-1.5 h-1.5 rounded-full bg-primary/70 animate-bounce" style={{ animationDelay: "150ms" }} />
          <div className="w-1.5 h-1.5 rounded-full bg-primary/70 animate-bounce" style={{ animationDelay: "300ms" }} />
        </div>
      </div>
    </div>
  )
}

export function ChatMessageList({
  messages,
  streamText,
  streamRunId,
  thinkingLevel,
  isStreaming,
  focusMode,
  showThinking,
  isThinking,
  className,
}: ChatMessageListProps) {
  const groups = useMemo(() => {
    if (messages.length === 0 && !isStreaming) return []

    const result: Array<{
      kind: "group"
      role: string
      messages: NormalizedMessage[]
    }> = []

    for (const msg of messages) {
      const lastGroup = result[result.length - 1]
      if (lastGroup && lastGroup.role === msg.role) {
        lastGroup.messages.push(msg)
      } else {
        result.push({ kind: "group", role: msg.role, messages: [msg] })
      }
    }

    return result
  }, [messages, isStreaming])

  const focusedGroup = focusMode ? groups[groups.length - 1] : null

  return (
    <ScrollArea className={cn("flex-1", className)}>
      <div className="p-4 space-y-6">
        {focusMode && focusedGroup ? (
          <div className="space-y-6">
            {focusedGroup.messages.map((msg) => (
              <SingleMessage key={msg.id ?? msg.timestamp} message={msg} showThinking={showThinking} />
            ))}
          </div>
        ) : (
          groups.map((group) => (
            <div key={group.role + group.messages[0]?.id} className="space-y-4">
              {group.messages.map((msg) => (
                <SingleMessage key={msg.id ?? msg.timestamp} message={msg} showThinking={showThinking} />
              ))}
            </div>
          ))
        )}

        {isStreaming && (
          <StreamingMessage
            text={streamText ?? ""}
            thinkingLevel={thinkingLevel}
          />
        )}

        {isThinking && !isStreaming && (
          <div className="flex items-center gap-3 pl-10">
            <div className="w-8 h-8 shrink-0">
              <HarvisMascot state="talking" size={32} />
            </div>
            <div className="w-fit rounded-2xl bg-card border border-border px-4 py-3">
              <div className="flex items-center gap-1.5">
                <div className="w-2 h-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: "0ms" }} />
                <div className="w-2 h-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: "150ms" }} />
                <div className="w-2 h-2 rounded-full bg-primary animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            </div>
          </div>
        )}

        {!isStreaming && messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center py-20 bg-background/80 backdrop-blur-sm">
            <HarvisMascot size={100} interactive state="idle" />
            <h3 className="text-lg font-medium mt-4 mb-1">Start a conversation</h3>
            <p className="text-sm text-muted-foreground">
              Send a message to begin chatting with OpenClaw
            </p>
          </div>
        )}

        <div className="h-4" />
      </div>
    </ScrollArea>
  )
}
