/**
 * Notebook Components - Open Notebook Integration
 *
 * Components for enhanced notebook features including:
 * - AI Transformations (summarize, key points, questions, etc.)
 * - Podcast Generation from notebook content
 * - Sources management with grid/list views
 * - RAG-powered chat with citations
 * - Tab-based navigation (Sources, Chat, Podcast, Settings)
 */

// Original components
export { default as TransformPanel } from './TransformPanel'
export { default as PodcastGenerator } from './PodcastGenerator'

// Open Notebook UI components
export { default as TopNavigation } from './TopNavigation'
export type { NotebookView } from './TopNavigation'
export { default as SourceCard } from './SourceCard'
export { default as SourcesView } from './SourcesView'
export { default as ChatView } from './ChatView'
export { default as PodcastView } from './PodcastView'
export { default as AddSourceModal } from './AddSourceModal'

