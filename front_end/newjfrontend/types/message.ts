export interface SearchResult {
  title: string
  url: string
  snippet: string
  source?: string
}

export interface VideoResult {
  title: string
  url: string
  thumbnail: string
  channel?: string
  duration?: string
  views?: string
  description?: string
  published?: string
  videoId?: string          // YouTube video ID for embedding
  transcript?: string       // Transcript text from the video
  hasTranscript?: boolean   // Flag indicating transcript availability
}

export interface ImageAttachment {
  id: string
  type: 'image'
  data: string // base64
  mimeType: string
  name?: string
  width?: number
  height?: number
}

export interface FileAttachment {
  id: string
  type: 'file'
  data: string // base64
  mimeType: string
  name: string
  size: number
}

export type Attachment = ImageAttachment | FileAttachment

export interface MCPPlugin {
  id: string
  name: string
  host: string
  port: number
  enabled: boolean
  tools?: string[]
}

export interface Message {
  id?: string
  tempId?: string
  role: "user" | "assistant"
  content: string
  timestamp: Date
  model?: string
  status?: "pending" | "sent" | "failed" | "streaming"
  audioUrl?: string
  reasoning?: string
  searchResults?: SearchResult[]
  searchQuery?: string
  videos?: VideoResult[]  // YouTube videos from research
  inputType?: 'text' | 'voice' | 'screen' | 'image' | 'file'
  codeBlocks?: Array<{
    language: string
    code: string
    title?: string
  }>
  attachments?: Attachment[]
  imageUrl?: string // For displaying image in message
  imageUrls?: string[] // Multiple image URLs from backend
  autoResearched?: boolean // Perplexity-style auto-research indicator
  metadata?: {
    images?: string[]
    image_count?: number
    [key: string]: any
  }
}

export interface MessageObject {
  id: string
  role: 'user' | 'assistant'
  content: string
  audioUrl?: string
  reasoning?: string
  searchResults?: SearchResult[]
  timestamp: Date
  inputType?: 'text' | 'voice' | 'screen' | 'image' | 'file'
  attachments?: Attachment[]
  imageUrl?: string
}

// Vision Language model detection
export const VL_MODEL_PATTERNS = [
  'vision', 'vl', 'llava', 'bakllava', 'moondream',
  'minicpm-v', 'qwen2-vl', 'qwen-vl', 'cogvlm', 'internvl',
  'phi-3-vision', 'deepseek-vl', 'yi-vl', 'gemma-2-vision'
]

export function isVisionModel(modelName: string): boolean {
  if (!modelName) return false
  const lowerName = modelName.toLowerCase()
  return VL_MODEL_PATTERNS.some(pattern => lowerName.includes(pattern))
}
