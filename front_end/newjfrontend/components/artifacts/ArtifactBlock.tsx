"use client"

import React, { useState, useEffect, useCallback } from "react"
import {
  FileSpreadsheet,
  FileText,
  FileType,
  Presentation,
  Code,
  Globe,
  Download,
  Copy,
  Check,
  Eye,
  EyeOff,
  Loader2,
  AlertCircle,
  RefreshCw,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import type { Artifact, ArtifactContent } from "@/types/message"

// Lazy load preview components to reduce initial bundle
const SandpackPreview = React.lazy(() => import("./SandpackPreview"))
const DocxPreview = React.lazy(() => import("./DocxPreview"))

// Artifact type icons mapping
const ARTIFACT_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  spreadsheet: FileSpreadsheet,
  document: FileText,
  pdf: FileType,
  presentation: Presentation,
  website: Globe,
  app: Globe,
  code: Code,
}

// Type colors for badges
const TYPE_COLORS: Record<string, string> = {
  spreadsheet: "bg-green-500/20 text-green-400",
  document: "bg-blue-500/20 text-blue-400",
  pdf: "bg-red-500/20 text-red-400",
  presentation: "bg-orange-500/20 text-orange-400",
  website: "bg-purple-500/20 text-purple-400",
  app: "bg-purple-500/20 text-purple-400",
  code: "bg-cyan-500/20 text-cyan-400",
}

interface ArtifactBlockProps {
  artifact: Artifact
  className?: string
}

export function ArtifactBlock({ artifact: initialArtifact, className = "" }: ArtifactBlockProps) {
  const [artifact, setArtifact] = useState(initialArtifact)
  const [showPreview, setShowPreview] = useState(false)
  const [showEditor, setShowEditor] = useState(false)
  const [showCode, setShowCode] = useState(false)
  const [copied, setCopied] = useState(false)
  const [isPolling, setIsPolling] = useState(artifact.status === "generating" || artifact.status === "pending")
  const [previewContent, setPreviewContent] = useState<ArtifactContent | null>(artifact.content || null)

  const Icon = ARTIFACT_ICONS[artifact.type] || Code
  const isCodeType = ["website", "app", "code"].includes(artifact.type)
  const isDocumentType = ["document", "spreadsheet", "pdf", "presentation"].includes(artifact.type)
  const canPreview = isCodeType || artifact.type === "document" // Only DOCX for now
  const typeColor = TYPE_COLORS[artifact.type] || "bg-slate-500/20 text-slate-400"

  // Poll for status updates when artifact is generating
  useEffect(() => {
    if (!isPolling) return

    const pollStatus = async () => {
      try {
        const token = localStorage.getItem("token")
        const res = await fetch(`/api/artifacts/${artifact.id}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        })

        if (res.ok) {
          const data = await res.json()
          setArtifact((prev) => ({
            ...prev,
            status: data.status,
            downloadUrl: data.download_url || data.downloadUrl,
            previewUrl: data.preview_url || data.previewUrl,
            errorMessage: data.error_message || data.errorMessage,
          }))

          if (data.status === "ready" || data.status === "failed") {
            setIsPolling(false)
          }
        }
      } catch (e) {
        console.error("Error polling artifact status:", e)
      }
    }

    const interval = setInterval(pollStatus, 2000)
    return () => clearInterval(interval)
  }, [artifact.id, isPolling])

  // Fetch preview content for code artifacts
  const fetchPreviewContent = useCallback(async () => {
    if (!isCodeType || !artifact.previewUrl || previewContent?.files) return

    try {
      const token = localStorage.getItem("token")
      const res = await fetch(artifact.previewUrl, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })

      if (res.ok) {
        const data = await res.json()
        setPreviewContent({
          files: data.content?.files,
          entryFile: data.content?.entry_file || data.content?.entryFile || "App.tsx",
          framework: data.framework,
          dependencies: data.dependencies || data.content?.dependencies,
        })
      }
    } catch (e) {
      console.error("Error fetching preview content:", e)
    }
  }, [isCodeType, artifact.previewUrl, previewContent])

  // Fetch content when showing preview
  useEffect(() => {
    if (showPreview && isCodeType && artifact.status === "ready") {
      fetchPreviewContent()
    }
  }, [showPreview, isCodeType, artifact.status, fetchPreviewContent])

  const handleDownload = async () => {
    const downloadUrl = artifact.downloadUrl || `/api/artifacts/${artifact.id}/download`

    try {
      const token = localStorage.getItem("token")
      const response = await fetch(downloadUrl, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })

      if (response.ok) {
        const blob = await response.blob()
        const url = URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = artifact.title || "artifact"
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
      }
    } catch (e) {
      console.error("Error downloading artifact:", e)
    }
  }

  const handleCopy = async () => {
    if (!previewContent?.files) return

    const entryFile = previewContent.entryFile || "App.tsx"
    const mainFile = previewContent.files[entryFile] || previewContent.files[`/${entryFile}`]

    if (mainFile) {
      await navigator.clipboard.writeText(mainFile)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const handleCopyCode = async () => {
    if (!artifact.code) return

    await navigator.clipboard.writeText(artifact.code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleRefresh = () => {
    setIsPolling(true)
  }

  return (
    <div
      className={`rounded-xl border border-violet-500/20 bg-gradient-to-br from-slate-900 via-slate-900 to-violet-950/30 overflow-hidden ${className}`}
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-violet-500/20 bg-slate-800/50 px-4 py-3">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-violet-500/20">
            <Icon className="h-4 w-4 text-violet-400" />
          </div>
          <div>
            <h4 className="text-sm font-medium text-foreground">{artifact.title}</h4>
            <div className="flex items-center gap-2 mt-0.5">
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full uppercase font-medium ${typeColor}`}>
                {artifact.type}
              </span>
              {artifact.description && (
                <span className="text-xs text-muted-foreground truncate max-w-[200px]">{artifact.description}</span>
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1">
          {/* Status indicators - only show when generating/pending */}
          {(artifact.status === "generating" || artifact.status === "pending") && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-amber-500/10 text-amber-400 text-xs">
              <Loader2 className="h-3 w-3 animate-spin" />
              <span>{artifact.status === "generating" ? "Generating..." : "Pending..."}</span>
            </div>
          )}

          {artifact.status === "failed" && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-red-500/10 text-red-400 text-xs">
              <AlertCircle className="h-3 w-3" />
              <span>Failed</span>
              <Button variant="ghost" size="sm" onClick={handleRefresh} className="h-6 w-6 p-0 ml-1">
                <RefreshCw className="h-3 w-3" />
              </Button>
            </div>
          )}

          {/* Only show action buttons when status is ready */}
          {artifact.status === "ready" && (
            <>
              {/* Preview button for code types and documents that support preview */}
              {canPreview && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowPreview(!showPreview)}
                  className="h-8 text-xs text-violet-300/70 hover:text-violet-200 hover:bg-violet-500/10"
                >
                  {showPreview ? (
                    <>
                      <EyeOff className="mr-1.5 h-3 w-3" /> Hide Preview
                    </>
                  ) : (
                    <>
                      <Eye className="mr-1.5 h-3 w-3" /> Preview
                    </>
                  )}
                </Button>
              )}

              {/* Copy button for code types only */}
              {isCodeType && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={handleCopy}
                  disabled={!previewContent?.files}
                  className="h-8 text-xs text-violet-300/70 hover:text-violet-200 hover:bg-violet-500/10"
                >
                  {copied ? (
                    <>
                      <Check className="mr-1.5 h-3 w-3 text-green-400" /> Copied!
                    </>
                  ) : (
                    <>
                      <Copy className="mr-1.5 h-3 w-3" /> Copy
                    </>
                  )}
                </Button>
              )}

              {/* View Code button for document types */}
              {!isCodeType && artifact.code && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setShowCode(!showCode)}
                  className="h-8 text-xs text-violet-300/70 hover:text-violet-200 hover:bg-violet-500/10"
                >
                  {showCode ? (
                    <>
                      <EyeOff className="mr-1.5 h-3 w-3" /> Hide Code
                    </>
                  ) : (
                    <>
                      <Code className="mr-1.5 h-3 w-3" /> View Code
                    </>
                  )}
                </Button>
              )}

              {/* Download button - always available when ready */}
              <Button
                variant="ghost"
                size="sm"
                onClick={handleDownload}
                className="h-8 text-xs text-violet-300/70 hover:text-violet-200 hover:bg-violet-500/10"
              >
                <Download className="mr-1.5 h-3 w-3" /> Download
              </Button>
            </>
          )}
        </div>
      </div>

      {/* Content/Preview Area - only show when ready */}
      {artifact.status === "ready" && (
        <div className="p-4">
          {isCodeType ? (
            showPreview && previewContent?.files ? (
              <React.Suspense
                fallback={
                  <div className="flex items-center justify-center h-[400px] bg-slate-900/50 rounded-lg">
                    <Loader2 className="h-6 w-6 animate-spin text-violet-400" />
                  </div>
                }
              >
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-muted-foreground">
                      {previewContent.framework || "React"} Preview
                    </span>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setShowEditor(!showEditor)}
                      className="h-6 text-xs text-violet-300/70"
                    >
                      {showEditor ? "Hide Code" : "Show Code"}
                    </Button>
                  </div>
                  <SandpackPreview
                    files={previewContent.files}
                    entryFile={previewContent.entryFile}
                    dependencies={previewContent.dependencies}
                    showEditor={showEditor}
                  />
                </div>
              </React.Suspense>
            ) : previewContent?.files ? (
              <div className="relative">
                <pre className="overflow-x-auto p-4 bg-[#011627] rounded-lg text-sm font-mono max-h-[400px] overflow-y-auto">
                  <code className="text-gray-300">
                    {previewContent.files[previewContent.entryFile || "App.tsx"] ||
                      previewContent.files[`/${previewContent.entryFile || "App.tsx"}`] ||
                      Object.values(previewContent.files)[0] ||
                      "No code available"}
                  </code>
                </pre>
                <div className="absolute top-2 right-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleCopy}
                    className="h-7 text-xs bg-slate-800/80 text-violet-300/70 hover:text-violet-200"
                  >
                    {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex items-center justify-center h-[200px] bg-slate-900/50 rounded-lg">
                <div className="text-center">
                  <Loader2 className="h-6 w-6 animate-spin text-violet-400 mx-auto mb-2" />
                  <p className="text-sm text-muted-foreground">Loading content...</p>
                </div>
              </div>
            )
          ) : (
            /* Document types */
            <div className="text-center">
              {showPreview && artifact.type === "document" ? (
                /* DOCX Preview */
                <React.Suspense
                  fallback={
                    <div className="flex items-center justify-center h-[400px] bg-slate-900/50 rounded-lg">
                      <Loader2 className="h-6 w-6 animate-spin text-violet-400" />
                    </div>
                  }
                >
                  <DocxPreview 
                    downloadUrl={artifact.downloadUrl || `/api/artifacts/${artifact.id}/download`} 
                  />
                </React.Suspense>
              ) : showCode && artifact.code ? (
                /* Code View */
                <div className="text-left">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-muted-foreground">Generation Code</span>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={handleCopyCode}
                      className="h-6 text-xs text-violet-300/70 hover:text-violet-200"
                    >
                      {copied ? (
                        <>
                          <Check className="mr-1.5 h-3 w-3 text-green-400" /> Copied!
                        </>
                      ) : (
                        <>
                          <Copy className="mr-1.5 h-3 w-3" /> Copy Code
                        </>
                      )}
                    </Button>
                  </div>
                  <pre className="overflow-x-auto p-4 bg-[#011627] rounded-lg text-sm font-mono max-h-[400px] overflow-y-auto text-left">
                    <code className="text-gray-300">{artifact.code}</code>
                  </pre>
                </div>
              ) : (
                /* Default download view */
                <div className="py-8">
                  <Icon className="h-12 w-12 mx-auto text-muted-foreground mb-3" />
                  <p className="text-sm text-muted-foreground mb-4">
                    Your {artifact.type} is ready
                  </p>
                  <div className="flex items-center justify-center gap-2">
                    {canPreview && (
                      <Button 
                        onClick={() => setShowPreview(true)} 
                        variant="outline"
                        className="border-violet-500/30 text-violet-300 hover:bg-violet-500/10"
                      >
                        <Eye className="mr-2 h-4 w-4" />
                        Preview
                      </Button>
                    )}
                    <Button onClick={handleDownload} className="bg-violet-600 hover:bg-violet-700 text-white">
                      <Download className="mr-2 h-4 w-4" />
                      Download
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Error message */}
      {artifact.status === "failed" && artifact.errorMessage && (
        <div className="p-4 text-sm text-red-400 bg-red-500/5">{artifact.errorMessage}</div>
      )}

      {/* Generating placeholder */}
      {(artifact.status === "generating" || artifact.status === "pending") && (
        <div className="p-8 text-center">
          <Loader2 className="h-8 w-8 animate-spin text-violet-400 mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">
            {artifact.status === "generating"
              ? `Generating your ${artifact.type}...`
              : "Waiting to start..."}
          </p>
        </div>
      )}
    </div>
  )
}

export default ArtifactBlock
