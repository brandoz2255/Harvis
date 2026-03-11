"use client"

import { motion, AnimatePresence } from "framer-motion"
import {
  BookOpen, Code, X, Maximize2, Minimize2,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import {
  useBlockPluginStore,
  BLOCK_PLUGINS,
  type BlockPluginId,
} from "@/stores/blockPluginStore"
import { useNotebookPluginStore } from "@/stores/notebookPluginStore"
import ResizablePanel from "@/components/ResizablePanel"

import NotebookContent from "@/components/block-plugins/NotebookContent"
import VibeCodeContent from "@/components/block-plugins/VibeCodeContent"

const ICON_MAP: Record<string, LucideIcon> = {
  BookOpen,
  Code,
}

function PluginContent({ pluginId, isFullPage }: { pluginId: BlockPluginId; isFullPage: boolean }) {
  switch (pluginId) {
    case "open-notebook": return <NotebookContent />
    case "vibe-code": return <VibeCodeContent fullPage={isFullPage} />
  }
}

/**
 * Hook for external components (like page.tsx) to check if the plugin is in
 * full-page mode — so they can hide the sidebar and chat area.
 */
export function usePluginIsFullPage(): boolean {
  const activePluginId = useBlockPluginStore((s) => s.activePluginId)
  const notebookViewMode = useNotebookPluginStore((s) => s.viewMode)
  const viewModes = useBlockPluginStore((s) => s.viewModes)

  if (!activePluginId) return false
  if (activePluginId === 'open-notebook') return notebookViewMode === 'full'
  return (viewModes[activePluginId] || 'compact') === 'full'
}

export default function BlockPluginPanel() {
  const { activePluginId, close, panelWidth, setPanelWidth, getViewMode, toggleViewMode } = useBlockPluginStore()
  const { viewMode: notebookViewMode } = useNotebookPluginStore()

  const activeDef = BLOCK_PLUGINS.find((p) => p.id === activePluginId)
  const Icon = activeDef ? (ICON_MAP[activeDef.iconName] ?? BookOpen) : BookOpen
  const isOpen = !!(activePluginId && activeDef)

  const isFullPage = activePluginId === 'open-notebook'
    ? notebookViewMode === 'full'
    : (activePluginId ? getViewMode(activePluginId) === 'full' : false)

  const supportsFullPage = activeDef?.supportsFullPage ?? false

  if (!isOpen || !activeDef || !activePluginId) {
    return null
  }

  const handleToggleFullPage = () => {
    if (activePluginId === 'open-notebook') {
      useNotebookPluginStore.getState().toggleViewMode()
    } else if (activePluginId) {
      toggleViewMode(activePluginId)
    }
  }

  const panelContent = (
    <div className={`flex flex-col h-full bg-card ${isFullPage ? '' : 'border-l border-border'}`}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
        <div className="flex items-center gap-2">
          <Icon className="w-4 h-4 text-primary" />
          <span className="text-sm font-semibold text-foreground">{activeDef.label}</span>
          {isFullPage && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium">Full Page</span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {supportsFullPage && (
            <button
              onClick={handleToggleFullPage}
              className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
              title={isFullPage ? "Compact view" : "Full page view"}
            >
              {isFullPage ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
            </button>
          )}
          <button
            onClick={close}
            className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        <PluginContent pluginId={activePluginId} isFullPage={isFullPage} />
      </div>
    </div>
  )

  // ── Full page mode: simple flex child that fills ALL available space ─────
  // The parent page.tsx hides the sidebar and chat when this is active,
  // so this div naturally takes the full width and height.
  if (isFullPage) {
    return (
      <div className="flex-1 h-full min-w-0 overflow-hidden">
        {panelContent}
      </div>
    )
  }

  // ── Compact mode: resizable side panel ──────────────────────────────────
  return (
    <motion.div
      className="hidden lg:block shrink-0 h-full overflow-hidden"
      initial={false}
      animate={{ width: panelWidth }}
      transition={{ type: "spring", damping: 28, stiffness: 300 }}
    >
      <AnimatePresence mode="wait">
        <motion.div
          key={activePluginId}
          className="h-full"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
        >
          <ResizablePanel
            width={panelWidth}
            onResize={setPanelWidth}
            minWidth={320}
            maxWidth={800}
            handlePosition="left"
            className="h-full"
          >
            {panelContent}
          </ResizablePanel>
        </motion.div>
      </AnimatePresence>
    </motion.div>
  )
}

