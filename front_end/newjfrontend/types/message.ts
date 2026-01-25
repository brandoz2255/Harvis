export interface SearchResult {
  title: string
  url: string
  snippet: string
  source?: string
}

export interface Message {
  id?: string
  tempId?: string
  role: "user" | "assistant"
  content: string
  timestamp: Date
  model?: string
  status?: "pending" | "sent" | "failed"
  audioUrl?: string
  reasoning?: string
  searchResults?: SearchResult[]
  searchQuery?: string
  inputType?: 'text' | 'voice' | 'screen'
  codeBlocks?: Array<{
    language: string
    code: string
    title?: string
  }>
}

export interface MessageObject {
  id: string
  role: 'user' | 'assistant'
  content: string
  audioUrl?: string
  reasoning?: string
  searchResults?: SearchResult[]
  timestamp: Date
  inputType?: 'text' | 'voice' | 'screen'
}
