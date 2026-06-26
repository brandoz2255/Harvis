'use client'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

/** Renders a generated study guide (Markdown). */
export function StudyGuideView({ markdown }: { markdown: string | null | undefined }) {
  if (!markdown || !markdown.trim()) {
    return <div className="text-sm text-muted-foreground py-4">This study guide couldn’t be displayed — try regenerating.</div>
  }
  return (
    <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none py-1">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
    </div>
  )
}
