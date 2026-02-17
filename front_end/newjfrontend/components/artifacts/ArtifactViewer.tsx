"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import dynamic from "next/dynamic"
import { cn } from "@/lib/utils"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import {
  Download,
  Trash2,
  Share2,
  Copy,
  ExternalLink,
  MessageSquare,
  FileText,
  FileSpreadsheet,
  FileType,
  Presentation,
  Globe,
  Code,
  Box,
  Loader2,
  AlertCircle,
  Check,
} from "lucide-react"
import { toast } from "sonner"
import { formatDistanceToNow } from "date-fns"

// Dynamically import preview components to avoid SSR issues
const PdfPreview = dynamic(() => import("./PdfPreview").then(mod => ({ default: mod.PdfPreview })), { ssr: false })
const DocxPreview = dynamic(() => import("./DocxPreview").then(mod => ({ default: mod.DocxPreview })), { ssr: false })
const XlsxPreview = dynamic(() => import("./XlsxPreview").then(mod => ({ default: mod.XlsxPreview })), { ssr: false })
const PptxPreview = dynamic(() => import("./PptxPreview").then(mod => ({ default: mod.PptxPreview })), { ssr: false })
const SandpackPreview = dynamic(() => import("./SandpackPreview").then(mod => ({ default: mod.SandpackPreview })), { ssr: false })

// Artifact type icons mapping
const ARTIFACT_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  spreadsheet: FileSpreadsheet,
  document: FileText,
  pdf: FileText,
  presentation: Presentation,
  website: Globe,
  app: Globe,
  code: Code,
}

// Artifact type colors
const TYPE_COLORS: Record<string, string> = {
  spreadsheet: "bg-green-500/10 text-green-500",
  document: "bg-blue-500/10 text-blue-500",
  pdf: "bg-red-500/10 text-red-500",
  presentation: "bg-orange-500/10 text-orange-500",
  website: "bg-purple-500/10 text-purple-500",
  app: "bg-indigo-500/10 text-indigo-500",
  code: "bg-cyan-500/10 text-cyan-500",
}

interface ArtifactViewerProps {
  artifact: {
    id: string
    artifact_type?: string
    type?: string
    title: string
    description?: string
    status: string
    file_size?: number
    fileSize?: number
    session_id?: string
    created_at?: string
    updated_at?: string
  } | null
  isOpen: boolean
  onClose: () => void
  chatSessions?: { id: string; title: string }[]
  onArtifactDeleted?: () => void
}

interface ArtifactDetails {
  id: string
  artifact_type: string
  title: string
  description?: string
  status: string
  file_size?: number
  mime_type?: string
  file_path?: string
  content?: any
  session_id?: string
  message_id?: number
  created_at: string
  updated_at: string
  framework?: string
  preview_url?: string
}

export function ArtifactViewer({
  artifact,
  isOpen,
  onClose,
  chatSessions = [],
  onArtifactDeleted,
}: ArtifactViewerProps) {
  const router = useRouter()
  const [details, setDetails] = useState<ArtifactDetails | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [isDownloading, setIsDownloading] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  const artifactType = artifact?.artifact_type || artifact?.type || ''
  const Icon = artifactType ? ARTIFACT_ICONS[artifactType] || Box : Box
  const typeColor = artifactType ? TYPE_COLORS[artifactType] || "bg-slate-500/10 text-slate-500" : ""

  // Fetch artifact details when opened
  useEffect(() => {
    if (isOpen && artifact) {
      fetchArtifactDetails()
    } else {
      setDetails(null)
    }
  }, [isOpen, artifact?.id])

  const fetchArtifactDetails = async () => {
    if (!artifact) return
    
    setIsLoading(true)
    try {
      const token = localStorage.getItem('token')
      const res = await fetch(`/api/artifacts/${artifact.id}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      
      if (res.ok) {
        const data = await res.json()
        setDetails(data)
      } else {
        toast.error("Failed to load artifact details")
      }
    } catch (error) {
      console.error('Failed to fetch artifact details:', error)
      toast.error("Failed to load artifact details")
    } finally {
      setIsLoading(false)
    }
  }

  const handleDownload = async () => {
    if (!artifact) return
    
    setIsDownloading(true)
    try {
      const token = localStorage.getItem('token')
      const res = await fetch(`/api/artifacts/${artifact.id}/download`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      
      if (!res.ok) {
        throw new Error('Download failed')
      }

      // Get filename from Content-Disposition header
      const contentDisposition = res.headers.get('content-disposition')
      let filename = artifact.title
      if (contentDisposition) {
        const match = contentDisposition.match(/filename="?([^"]+)"?/)
        if (match) {
          filename = match[1]
        }
      }

      // Get file blob
      const blob = await res.blob()
      
      // Create object URL
      const url = window.URL.createObjectURL(blob)
      
      // Create temporary link element for Save As dialog
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      
      // Trigger Save As dialog
      link.click()
      
      // Cleanup
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)
      
      toast.success("Download started")
    } catch (error) {
      console.error('Download error:', error)
      toast.error("Failed to download artifact")
    } finally {
      setIsDownloading(false)
    }
  }

  const handleDelete = async () => {
    if (!artifact) return
    
    setIsDeleting(true)
    try {
      const token = localStorage.getItem('token')
      const res = await fetch(`/api/artifacts/${artifact.id}`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      })
      
      if (res.ok) {
        toast.success("Artifact deleted")
        onClose()
        onArtifactDeleted?.()
      } else {
        throw new Error('Delete failed')
      }
    } catch (error) {
      console.error('Delete error:', error)
      toast.error("Failed to delete artifact")
    } finally {
      setIsDeleting(false)
      setShowDeleteConfirm(false)
    }
  }

  const handleCopyLink = () => {
    const link = `${window.location.origin}/api/artifacts/${artifact?.id}/download`
    navigator.clipboard.writeText(link)
    toast.success("Link copied to clipboard")
  }

  const handleShare = async () => {
    const shareData = {
      title: artifact?.title || 'Artifact',
      text: `Check out this ${artifactType} artifact: ${artifact?.title}`,
      url: `${window.location.origin}/api/artifacts/${artifact?.id}/download`,
    }

    if (navigator.share) {
      try {
        await navigator.share(shareData)
      } catch (error) {
        // User cancelled or share failed
        handleCopyLink()
      }
    } else {
      handleCopyLink()
    }
  }

  const navigateToChat = () => {
    if (details?.session_id) {
      router.push(`/chat/${details.session_id}`)
      onClose()
    }
  }

  const getChatTitle = () => {
    if (!details?.session_id) return null
    const session = chatSessions.find(s => s.id === details.session_id)
    return session?.title || `Chat ${details.session_id.slice(0, 8)}...`
  }

  const formatFileSize = (bytes?: number) => {
    if (!bytes) return ''
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  // Get download URL for preview components
  const getDownloadUrl = () => {
    if (!artifact) return ''
    return `/api/artifacts/${artifact.id}/download`
  }

  // Render content based on artifact type
  const renderPreview = () => {
    if (!artifact) return null

    const type = artifactType
    const downloadUrl = getDownloadUrl()

    // Document types - use download URL with preview components
    if (type === 'pdf') {
      return <PdfPreview downloadUrl={downloadUrl} />
    }

    if (type === 'document') {
      return <DocxPreview downloadUrl={downloadUrl} />
    }

    if (type === 'spreadsheet') {
      return <XlsxPreview downloadUrl={downloadUrl} />
    }

    if (type === 'presentation') {
      return <PptxPreview downloadUrl={downloadUrl} />
    }

    // Code/Website/App types - use SandpackPreview with content from details
    if (type === 'website' || type === 'app' || type === 'code') {
      if (!details?.content) {
        return (
          <div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
            <Code className="h-12 w-12 mb-4 opacity-50" />
            <p>Loading code preview...</p>
          </div>
        )
      }

      return (
        <SandpackPreview
          files={details.content.files || {}}
          entryFile={details.content.entryFile || 'index.js'}
          framework={details.framework || 'react'}
          dependencies={details.content.dependencies || {}}
        />
      )
    }

    return (
      <div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
        <Icon className="h-12 w-12 mb-4 opacity-50" />
        <p>Preview not available for this artifact type</p>
        <Button 
          variant="outline" 
          size="sm" 
          className="mt-4"
          onClick={handleDownload}
          disabled={isDownloading}
        >
          {isDownloading ? (
            <Loader2 className="h-4 w-4 mr-2 animate-spin" />
          ) : (
            <Download className="h-4 w-4 mr-2" />
          )}
          Download to view
        </Button>
      </div>
    )
  }

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-hidden flex flex-col">
        <DialogHeader className="flex flex-row items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={cn("flex h-10 w-10 items-center justify-center rounded-lg", typeColor)}>
              <Icon className="h-5 w-5" />
            </div>
            <div>
              <DialogTitle className="text-xl">{artifact?.title}</DialogTitle>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span className="capitalize">{artifactType}</span>
                {details?.file_size && (
                  <>
                    <span>•</span>
                    <span>{formatFileSize(details.file_size)}</span>
                  </>
                )}
              </div>
            </div>
          </div>
        </DialogHeader>

        {isLoading ? (
          <div className="flex items-center justify-center h-64">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="flex-1 overflow-auto space-y-4">
            {/* Actions Bar */}
            <div className="flex items-center gap-2 pb-4 border-b">
              <Button
                variant="default"
                onClick={handleDownload}
                disabled={isDownloading || artifact?.status !== 'ready'}
              >
                {isDownloading ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <Download className="h-4 w-4 mr-2" />
                )}
                Download
              </Button>
              
              <Button variant="outline" onClick={handleCopyLink}>
                <Copy className="h-4 w-4 mr-2" />
                Copy Link
              </Button>
              
              <Button variant="outline" onClick={handleShare}>
                <Share2 className="h-4 w-4 mr-2" />
                Share
              </Button>

              {details?.session_id && (
                <Button variant="outline" onClick={navigateToChat}>
                  <MessageSquare className="h-4 w-4 mr-2" />
                  Open Chat
                </Button>
              )}

              <div className="flex-1" />

              <Button 
                variant="outline" 
                onClick={() => setShowDeleteConfirm(true)}
                className="text-destructive hover:bg-destructive/10"
              >
                <Trash2 className="h-4 w-4 mr-2" />
                Delete
              </Button>
            </div>

            {/* Status */}
            <div className="flex items-center gap-2">
              <Badge 
                variant={artifact?.status === 'ready' ? 'default' : 'secondary'}
                className={cn(
                  artifact?.status === 'ready' && "bg-green-500/10 text-green-500 hover:bg-green-500/20"
                )}
              >
                {artifact?.status === 'ready' ? (
                  <Check className="h-3 w-3 mr-1" />
                ) : artifact?.status === 'failed' ? (
                  <AlertCircle className="h-3 w-3 mr-1" />
                ) : (
                  <Loader2 className="h-3 w-3 mr-1 animate-spin" />
                )}
                {artifact?.status?.charAt(0).toUpperCase()}{artifact?.status?.slice(1)}
              </Badge>
            </div>

            {/* Description */}
            {details?.description && (
              <p className="text-muted-foreground">{details.description}</p>
            )}

            {/* Chat Session Info */}
            {details?.session_id && (
              <div className="rounded-lg border bg-muted/50 p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <MessageSquare className="h-4 w-4 text-muted-foreground" />
                    <span className="font-medium">From Chat Session</span>
                  </div>
                  <Button 
                    variant="ghost" 
                    size="sm"
                    onClick={navigateToChat}
                  >
                    Open Chat
                    <ExternalLink className="h-3 w-3 ml-1" />
                  </Button>
                </div>
                <p className="text-sm text-muted-foreground mt-1">
                  {getChatTitle()}
                </p>
              </div>
            )}

            <Separator />

            {/* Preview */}
            <div>
              <h4 className="font-medium mb-2">Preview</h4>
              {renderPreview()}
            </div>

            {/* Metadata */}
            <div className="text-sm text-muted-foreground space-y-1 pt-4 border-t">
              <div className="flex justify-between">
                <span>Created</span>
                <span>{details?.created_at && formatDistanceToNow(new Date(details.created_at), { addSuffix: true })}</span>
              </div>
              <div className="flex justify-between">
                <span>Updated</span>
                <span>{details?.updated_at && formatDistanceToNow(new Date(details.updated_at), { addSuffix: true })}</span>
              </div>
              {details?.mime_type && (
                <div className="flex justify-between">
                  <span>MIME Type</span>
                  <span>{details.mime_type}</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Delete Confirmation */}
        {showDeleteConfirm && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50">
            <div className="bg-background rounded-lg shadow-lg p-6 max-w-sm mx-4">
              <h3 className="text-lg font-semibold mb-2">Delete Artifact?</h3>
              <p className="text-sm text-muted-foreground mb-4">
                This will permanently delete "{artifact?.title}". This action cannot be undone.
              </p>
              <div className="flex justify-end gap-2">
                <Button 
                  variant="outline" 
                  onClick={() => setShowDeleteConfirm(false)}
                  disabled={isDeleting}
                >
                  Cancel
                </Button>
                <Button 
                  variant="destructive" 
                  onClick={handleDelete}
                  disabled={isDeleting}
                >
                  {isDeleting ? (
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <Trash2 className="h-4 w-4 mr-2" />
                  )}
                  Delete
                </Button>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
