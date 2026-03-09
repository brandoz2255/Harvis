"use client"

import React, { useState, useEffect } from "react"
import mammoth from "mammoth"
import DOMPurify from "dompurify"
import { Loader2, AlertCircle } from "lucide-react"
import { Alert, AlertDescription } from "@/components/ui/alert"

interface DocxPreviewProps {
  downloadUrl: string
  className?: string
}

export function DocxPreview({ downloadUrl, className = "" }: DocxPreviewProps) {
  const [htmlContent, setHtmlContent] = useState<string>("")
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const loadDocument = async () => {
      try {
        setIsLoading(true)
        setError(null)

        // Fetch the document
        const token = localStorage.getItem("token")
        const response = await fetch(downloadUrl, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })

        if (!response.ok) {
          throw new Error(`Failed to load document: ${response.statusText}`)
        }

        // Get the document as array buffer
        const arrayBuffer = await response.arrayBuffer()

        // Convert DOCX to HTML using mammoth
        const result = await mammoth.convertToHtml(
          { arrayBuffer },
          {
            styleMap: [
              "p[style-name='Heading 1'] => h1",
              "p[style-name='Heading 2'] => h2",
              "p[style-name='Heading 3'] => h3",
              "p[style-name='Heading 4'] => h4",
              "p[style-name='Heading 5'] => h5",
              "p[style-name='Heading 6'] => h6",
            ],
          }
        )

        // Sanitize the HTML to prevent XSS
        const sanitizedHtml = DOMPurify.sanitize(result.value, {
          ALLOWED_TAGS: [
            'p', 'br', 'strong', 'b', 'em', 'i', 'u', 'strike', 'del',
            'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
            'ul', 'ol', 'li',
            'table', 'thead', 'tbody', 'tr', 'td', 'th',
            'a', 'img', 'span', 'div', 'blockquote'
          ],
          ALLOWED_ATTR: [
            'href', 'src', 'alt', 'title', 'class', 'style', 'width', 'height'
          ],
        })

        setHtmlContent(sanitizedHtml)

        // Log any conversion warnings
        if (result.messages.length > 0) {
          console.warn('DOCX conversion warnings:', result.messages)
        }
      } catch (err) {
        console.error('Error loading DOCX:', err)
        setError(err instanceof Error ? err.message : 'Failed to load document')
      } finally {
        setIsLoading(false)
      }
    }

    if (downloadUrl) {
      loadDocument()
    }
  }, [downloadUrl])

  if (isLoading) {
    return (
      <div className={`flex items-center justify-center h-[400px] bg-slate-900/50 rounded-lg ${className}`}>
        <div className="text-center">
          <Loader2 className="h-8 w-8 animate-spin text-violet-400 mx-auto mb-2" />
          <p className="text-sm text-muted-foreground">Loading document...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className={`${className}`}>
        <Alert variant="destructive" className="bg-red-500/10 border-red-500/20">
          <AlertCircle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </div>
    )
  }

  return (
    <div 
      className={`docx-preview bg-white text-black rounded-lg overflow-auto max-h-[600px] ${className}`}
      style={{
        padding: '40px',
        boxShadow: '0 0 20px rgba(0,0,0,0.1)',
      }}
    >
      <style jsx global>{`
        .docx-preview {
          font-family: 'Times New Roman', Times, serif;
          line-height: 1.6;
        }
        .docx-preview h1 {
          font-size: 24pt;
          font-weight: bold;
          margin: 24pt 0 12pt 0;
          color: black;
        }
        .docx-preview h2 {
          font-size: 20pt;
          font-weight: bold;
          margin: 20pt 0 10pt 0;
          color: black;
        }
        .docx-preview h3 {
          font-size: 16pt;
          font-weight: bold;
          margin: 16pt 0 8pt 0;
          color: black;
        }
        .docx-preview h4, .docx-preview h5, .docx-preview h6 {
          font-size: 14pt;
          font-weight: bold;
          margin: 14pt 0 7pt 0;
          color: black;
        }
        .docx-preview p {
          margin: 12pt 0;
          color: black;
        }
        .docx-preview ul, .docx-preview ol {
          margin: 12pt 0;
          padding-left: 40pt;
          color: black;
        }
        .docx-preview li {
          margin: 6pt 0;
          color: black;
        }
        .docx-preview table {
          width: 100%;
          border-collapse: collapse;
          margin: 12pt 0;
        }
        .docx-preview td, .docx-preview th {
          border: 1px solid #ccc;
          padding: 8pt;
          color: black;
        }
        .docx-preview th {
          background-color: #f5f5f5;
          font-weight: bold;
        }
        .docx-preview a {
          color: #0563c1;
          text-decoration: underline;
        }
        .docx-preview strong, .docx-preview b {
          font-weight: bold;
        }
        .docx-preview em, .docx-preview i {
          font-style: italic;
        }
        .docx-preview blockquote {
          margin: 12pt 0;
          padding-left: 20pt;
          border-left: 3pt solid #ccc;
          color: #333;
        }
      `}</style>
      <div 
        dangerouslySetInnerHTML={{ __html: htmlContent }}
        className="docx-content"
      />
    </div>
  )
}

export default DocxPreview
