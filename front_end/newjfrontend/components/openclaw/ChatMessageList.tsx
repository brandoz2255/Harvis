"use client"

import { useMemo } from "react"
import { cn } from "@/lib/utils"
import {
  User,
  Sparkles,
  Loader2,
  Copy,
  Check,
  ChevronDown,
  ChevronUp,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Separator } from "@/components/ui/separator"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { Highlight, themes } from "prism-react-renderer"
import type { NormalizedMessage, ChatMessageContentItem, ChatAttachment } from "@/lib/openclaw/types"

interface ChatMessageListProps {
  messages: NormalizedMessage[]
  streamText: string | null
  streamRunId: string | null
  thinkingLevel: string | null
  isStreaming: boolean
  focusMode: boolean
  showThinking: boolean
  className?: string
  onScrollToBottom?: () => void
}

function MessageContent({
  content,
  showThinking,
}: {
  content: ChatMessageContentItem[]
  showThinking: boolean
}) {
  const textItems = content.filter((c) => c.type === "text")
  const toolItems = content.filter((c) => c.type === "tool_call" || c.type === "tool_result")
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
                return match ? (
                  <div className="relative my-2">
                    <Highlight
                      code={String(children).trim()}
                      language={lang as any}
                      theme={themes.oneDark}
                    >
                      {({ className, style, tokens, getLineProps, getTokenProps }) => (
                        <pre className={cn(className, "rounded-lg p-4 overflow-x-auto text-xs")} style={style}>
                          {tokens.map((line, i) => (
                            <div key={i} {...getLineProps({ line })} />
                          ))}
                        </pre>
                      )}
                    </Highlight>
                  </div>
                ) : (
                  <code className="bg-muted px-1.5 py-0.5 rounded text-xs" {...props}>
                    {children}
                  </code>
                )
              },
              pre({ children }) {
                return <pre className="rounded-lg">{children}</pre>
              },
              table({ children }) {
                return (
                  <div className="overflow-x-auto my-2">
                    <table className="min-w-full divide-y divide-border text-xs">{children}</table>
                  </div>
                )
              },
              th({ children }) {
                return <th className="px-3 py-1.5 bg-muted font-semibold text-left">{children}</th>
              },
              td({ children }) {
                return <td className="px-3 py-1.5 border-t border-border">{children}</td>
              },
            }}
          >
            {mainText}
          </ReactMarkdown>
        </div>
      )}

      {toolItems.length > 0 && (
        <div className="space-y-1">
          {toolItems.map((item, idx) => (
            <div key={idx} className="text-xs font-mono text-muted-foreground bg-muted/50 rounded px-2 py-1">
              {item.type === "tool_call" ? "⚙" : "✓"} {item.name}
            </div>
          ))}
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
      <div className="flex items-start gap-3">
        <div className="w-7 h-7 rounded-full bg-muted flex items-center justify-center shrink-0 mt-1">
          <User className="h-4 w-4 text-muted-foreground" />
        </div>
        <div className="flex-1 min-w-0">
          <MessageContent content={message.content} showThinking={showThinking} />
        </div>
      </div>
    )
  }

  if (isAssistant) {
    const hasThinking = message.content.some((c) => c.type === "text")
    return (
      <div className="flex items-start gap-3">
        <div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-1">
          <Sparkles className="h-4 w-4 text-primary" />
        </div>
        <div className="flex-1 min-w-0">
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
    <div className="flex items-start gap-3">
      <div className="w-7 h-7 rounded-full bg-primary/10 flex items-center justify-center shrink-0 mt-1">
        <Sparkles className="h-4 w-4 text-primary" />
      </div>
      <div className="flex-1 min-w-0">
        {thinkingLevel && (
          <div className="flex items-center gap-1 text-xs text-muted-foreground mb-1">
            <Loader2 className="h-3 w-3 animate-spin" />
            Thinking...
          </div>
        )}
        <div className="prose prose-sm dark:prose-invert max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {text}
          </ReactMarkdown>
        </div>
        <div className="flex items-center gap-1 mt-1">
          <div className="w-2 h-2 rounded-full bg-primary/60 animate-pulse" />
        </div>
      </div>
    </div>
  )
}

function MessageGroup({
  messages,
  role,
  isStreaming,
  showThinking,
}: {
  messages: NormalizedMessage[]
  role: string
  isStreaming: boolean
  showThinking: boolean
}) {
  const isUser = role === "user"

  return (
    <div className="space-y-2">
      {messages.map((msg) => (
        <SingleMessage key={msg.id ?? msg.timestamp} message={msg} showThinking={showThinking} />
      ))}
      {isStreaming && (
        <StreamingMessage text="" thinkingLevel={null} />
      )}
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
          <MessageGroup
            messages={focusedGroup.messages}
            role={focusedGroup.role}
            isStreaming={isStreaming}
            showThinking={showThinking}
          />
        ) : (
          groups.map((group) => (
            <MessageGroup
              key={group.role + group.messages[0]?.id}
              messages={group.messages}
              role={group.role}
              isStreaming={false}
              showThinking={showThinking}
            />
          ))
        )}

        {isStreaming && (
          <StreamingMessage
            text={streamText ?? ""}
            thinkingLevel={thinkingLevel}
          />
        )}

        {!isStreaming && messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center py-20">
            <div className="w-12 h-12 rounded-full bg-primary/10 flex items-center justify-center mb-4">
              <Sparkles className="h-6 w-6 text-primary" />
            </div>
            <h3 className="text-lg font-medium mb-1">Start a conversation</h3>
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
