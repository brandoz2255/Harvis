"use client"

import { useEffect } from "react"
import {
  BookOpen, Search, AudioWaveform,
  Settings, Maximize2, Minimize2,
} from "lucide-react"
import { useNotebookPluginStore, type PluginTab } from "@/stores/notebookPluginStore"
import { useBlockPluginStore } from "@/stores/blockPluginStore"

import NotebookListCompact from "@/components/notebook-plugin/NotebookListCompact"
import SearchCompact       from "@/components/notebook-plugin/SearchCompact"
import SettingsCompact     from "@/components/notebook-plugin/SettingsCompact"
import NotebookWorkspace   from "@/components/notebook-plugin/NotebookWorkspace"
import VoiceContent        from "@/components/block-plugins/VoiceContent"

const TOP_TABS: { id: PluginTab; icon: typeof BookOpen; label: string }[] = [
  { id: "notebooks", icon: BookOpen,      label: "Notebooks" },
  { id: "voices",    icon: AudioWaveform,  label: "Voices" },
  { id: "search",    icon: Search,         label: "Search" },
  { id: "settings",  icon: Settings,       label: "Settings" },
]

const NOTEBOOK_SCOPED_TABS: PluginTab[] = ['sources', 'chat', 'podcasts']

function TabBody({ tab }: { tab: PluginTab }) {
  switch (tab) {
    case "notebooks": return <NotebookListCompact />
    case "voices":    return <VoiceContent />
    case "search":    return <SearchCompact />
    case "settings":  return <SettingsCompact />
    default:          return <NotebookListCompact />
  }
}

export default function NotebookContent() {
  const { activeTab, setActiveTab, selectedNotebookId, viewMode, toggleViewMode } = useNotebookPluginStore()
  const { panelWidth } = useBlockPluginStore()

  const hasSelectedNotebook = !!selectedNotebookId

  useEffect(() => {
    if (!hasSelectedNotebook && NOTEBOOK_SCOPED_TABS.includes(activeTab)) {
      setActiveTab('notebooks')
    }
  }, [hasSelectedNotebook, activeTab, setActiveTab])

  if (hasSelectedNotebook && (activeTab === 'sources' || activeTab === 'chat' || activeTab === 'notebooks' || activeTab === 'podcasts')) {
    return <NotebookWorkspace />
  }

  return (
    <div className="flex flex-col h-full">
      {/* Tab Bar */}
      <div className="flex items-center border-b border-border shrink-0 px-1">
        <div className="flex items-center flex-1 overflow-x-auto">
          {TOP_TABS.map(({ id, icon: Icon, label }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors whitespace-nowrap
                ${activeTab === id
                  ? "text-primary border-b-2 border-primary"
                  : "text-muted-foreground hover:text-foreground"
                }`}
              title={label}
            >
              <Icon className="w-3.5 h-3.5" />
              {panelWidth >= 420 && <span>{label}</span>}
            </button>
          ))}
        </div>

        {hasSelectedNotebook && (
          <button
            onClick={toggleViewMode}
            title={viewMode === 'full' ? 'Half view' : 'Full page'}
            className="p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors shrink-0"
          >
            {viewMode === 'full' ? <Minimize2 className="w-3.5 h-3.5" /> : <Maximize2 className="w-3.5 h-3.5" />}
          </button>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        <TabBody tab={activeTab} />
      </div>
    </div>
  )
}
