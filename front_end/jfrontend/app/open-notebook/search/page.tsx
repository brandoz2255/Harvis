'use client'

import { useState, useRef, useEffect } from 'react'
import { useNotebookStore } from '@/stores/notebookStore'
import { useUser } from '@/lib/auth/UserProvider'
import {
  Search,
  Send,
  Loader2,
  FileText,
  MessageSquare,
  Sparkles,
  RefreshCw,
  Book,
  ExternalLink,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface SearchResult {
  id: string
  content: string
  source_title: string
  source_type: string
  notebook_title?: string
  notebook_id?: string
  score: number
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  sources?: SearchResult[]
  timestamp: Date
}

export default function OpenNotebookSearchPage() {
  const { user, isLoading: authLoading } = useUser()
  const { notebooks, isOpenNotebookAvailable, checkServiceHealth } = useNotebookStore()

  const [query, setQuery] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [selectedNotebook, setSelectedNotebook] = useState<string>('all')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    checkServiceHealth()
  }, [checkServiceHealth])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSearch = async () => {
    if (!query.trim() || isSearching) return

    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: query,
      timestamp: new Date(),
    }

    setMessages(prev => [...prev, userMessage])
    setQuery('')
    setIsSearching(true)

    try {
      // Simulate search API call (replace with actual API)
      // In real implementation, this would call the Open Notebook search API
      await new Promise(resolve => setTimeout(resolve, 1500))

      const assistantMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: `I searched across your sources for "${userMessage.content}". Here's what I found:

Based on my analysis of your documents, I can provide the following insights:

1. **Relevant Information**: Your sources contain information related to this topic in multiple documents.

2. **Key Points**: The main themes that emerge from your sources include...

3. **Recommendations**: Based on this search, you might want to explore the related sources for more detailed information.

Would you like me to dive deeper into any specific aspect of this topic?`,
        sources: [
          {
            id: '1',
            content: 'Sample relevant content from source 1...',
            source_title: 'Research Document',
            source_type: 'pdf',
            notebook_title: 'Research Notes',
            notebook_id: 'notebook-1',
            score: 0.95,
          },
          {
            id: '2',
            content: 'Sample relevant content from source 2...',
            source_title: 'Web Article',
            source_type: 'url',
            notebook_title: 'Web Clippings',
            notebook_id: 'notebook-2',
            score: 0.87,
          },
        ],
        timestamp: new Date(),
      }

      setMessages(prev => [...prev, assistantMessage])
    } catch (error) {
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: 'Sorry, I encountered an error while searching. Please try again.',
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, errorMessage])
    } finally {
      setIsSearching(false)
    }
  }

  if (authLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="w-8 h-8 animate-spin text-primary" />
      </div>
    )
  }

  if (!user) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-4">
        <div className="w-20 h-20 rounded-full bg-primary/20 flex items-center justify-center mb-6">
          <Search className="w-10 h-10 text-primary" />
        </div>
        <h2 className="text-3xl font-bold mb-3">Ask and Search</h2>
        <p className="text-muted-foreground mb-8 max-w-md">
          Search across all your sources and get AI-powered answers with citations.
        </p>
        <Button onClick={() => window.location.href = '/login'}>
          Sign In to Get Started
        </Button>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex-none p-4 border-b border-border">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-primary/20 flex items-center justify-center">
              <Search className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h1 className="text-xl font-bold">Ask and Search</h1>
              <p className="text-sm text-muted-foreground">Search across all your sources</p>
            </div>
          </div>

          {/* Notebook Filter */}
          <select
            value={selectedNotebook}
            onChange={(e) => setSelectedNotebook(e.target.value)}
            className="px-3 py-2 bg-muted border border-border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          >
            <option value="all">All Notebooks</option>
            {notebooks.map(notebook => (
              <option key={notebook.id} value={notebook.id}>{notebook.title}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Messages Area */}
      <div className="flex-1 overflow-auto p-4">
        <div className="max-w-4xl mx-auto">
          {messages.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-center py-12">
              <div className="w-16 h-16 rounded-full bg-primary/10 flex items-center justify-center mb-4">
                <Sparkles className="w-8 h-8 text-primary" />
              </div>
              <h2 className="text-xl font-semibold mb-2">Ask anything</h2>
              <p className="text-muted-foreground max-w-md mb-8">
                Search across all your sources with AI-powered semantic search.
                Get answers with citations from your documents.
              </p>

              {/* Quick Start Suggestions */}
              <div className="flex flex-wrap gap-2 justify-center">
                {[
                  'Summarize my notes',
                  'What are the key themes?',
                  'Find related concepts',
                ].map((suggestion) => (
                  <button
                    key={suggestion}
                    onClick={() => setQuery(suggestion)}
                    className="px-4 py-2 bg-muted hover:bg-muted/80 rounded-lg text-sm transition-colors"
                  >
                    {suggestion}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              {messages.map((message) => (
                <div
                  key={message.id}
                  className={cn(
                    'flex gap-3',
                    message.role === 'user' && 'justify-end'
                  )}
                >
                  {message.role === 'assistant' && (
                    <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center flex-shrink-0">
                      <Sparkles className="w-4 h-4 text-primary" />
                    </div>
                  )}

                  <div
                    className={cn(
                      'max-w-[80%] rounded-xl p-4',
                      message.role === 'user'
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-muted'
                    )}
                  >
                    <div className="whitespace-pre-wrap">{message.content}</div>

                    {/* Sources */}
                    {message.sources && message.sources.length > 0 && (
                      <div className="mt-4 pt-4 border-t border-border/50 space-y-2">
                        <p className="text-xs text-muted-foreground font-medium">Sources</p>
                        {message.sources.map((source) => (
                          <div
                            key={source.id}
                            className="flex items-start gap-2 p-2 bg-background/50 rounded-lg text-sm"
                          >
                            <FileText className="w-4 h-4 text-muted-foreground mt-0.5" />
                            <div className="flex-1 min-w-0">
                              <p className="font-medium truncate">{source.source_title}</p>
                              <p className="text-xs text-muted-foreground truncate">
                                {source.notebook_title} &bull; {source.source_type}
                              </p>
                            </div>
                            <span className="text-xs text-muted-foreground">
                              {Math.round(source.score * 100)}%
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {message.role === 'user' && (
                    <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center flex-shrink-0">
                      <MessageSquare className="w-4 h-4 text-primary-foreground" />
                    </div>
                  )}
                </div>
              ))}

              {isSearching && (
                <div className="flex gap-3">
                  <div className="w-8 h-8 rounded-full bg-primary/20 flex items-center justify-center flex-shrink-0">
                    <Sparkles className="w-4 h-4 text-primary" />
                  </div>
                  <div className="bg-muted rounded-xl p-4">
                    <div className="flex items-center gap-2">
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span className="text-muted-foreground">Searching your sources...</span>
                    </div>
                  </div>
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>
          )}
        </div>
      </div>

      {/* Input Area */}
      <div className="flex-none p-4 border-t border-border">
        <div className="max-w-4xl mx-auto">
          <div className="flex gap-2">
            <div className="flex-1 relative">
              <input
                type="text"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                placeholder="Ask a question or search your sources..."
                className="w-full px-4 py-3 bg-muted border border-border rounded-xl placeholder-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary"
                disabled={isSearching}
              />
            </div>
            <Button
              onClick={handleSearch}
              disabled={!query.trim() || isSearching}
              className="px-4"
            >
              {isSearching ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <Send className="w-5 h-5" />
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
