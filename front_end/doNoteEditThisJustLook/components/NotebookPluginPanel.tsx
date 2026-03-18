'use client'

import { motion, AnimatePresence } from 'framer-motion'
import {
  BookOpen, FileText, MessageSquare, Search,
  Mic, Settings, X,
} from 'lucide-react'
import { useNotebookPluginStore, PluginTab } from '@/stores/notebookPluginStore'
import ResizablePanel from '@/components/ResizablePanel'

// Lazy-loaded tab content components
import NotebookListCompact from '@/components/notebook-plugin/NotebookListCompact'
import SourcesCompact from '@/components/notebook-plugin/SourcesCompact'
import ChatCompact from '@/components/notebook-plugin/ChatCompact'
import SearchCompact from '@/components/notebook-plugin/SearchCompact'
import PodcastsCompact from '@/components/notebook-plugin/PodcastsCompact'
import SettingsCompact from '@/components/notebook-plugin/SettingsCompact'

const TABS: { id: PluginTab; icon: typeof BookOpen; label: string }[] = [
  { id: 'notebooks', icon: BookOpen, label: 'Notebooks' },
  { id: 'sources', icon: FileText, label: 'Sources' },
  { id: 'chat', icon: MessageSquare, label: 'Chat' },
  { id: 'search', icon: Search, label: 'Search' },
  { id: 'podcasts', icon: Mic, label: 'Podcasts' },
  { id: 'settings', icon: Settings, label: 'Settings' },
]

function TabContent({ tab }: { tab: PluginTab }) {
  switch (tab) {
    case 'notebooks': return <NotebookListCompact />
    case 'sources': return <SourcesCompact />
    case 'chat': return <ChatCompact />
    case 'search': return <SearchCompact />
    case 'podcasts': return <PodcastsCompact />
    case 'settings': return <SettingsCompact />
  }
}

export default function NotebookPluginPanel() {
  const { isOpen, close, activeTab, setActiveTab, panelWidth, setPanelWidth } =
    useNotebookPluginStore()

  return (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          className="fixed top-0 right-0 h-screen z-30 hidden lg:block"
          initial={{ x: '100%' }}
          animate={{ x: 0 }}
          exit={{ x: '100%' }}
          transition={{ type: 'spring', damping: 25, stiffness: 300 }}
        >
          <ResizablePanel
            width={panelWidth}
            onResize={setPanelWidth}
            minWidth={320}
            maxWidth={700}
            handlePosition="left"
            className="h-full"
          >
            <div className="flex flex-col h-full bg-card border-l border-border">
              {/* Header */}
              <div className="flex items-center justify-between px-4 py-3 border-b border-border shrink-0">
                <div className="flex items-center gap-2">
                  <BookOpen className="w-4 h-4 text-primary" />
                  <span className="text-sm font-semibold text-foreground">Open Notebook</span>
                </div>
                <button
                  onClick={close}
                  className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Tab Bar */}
              <div className="flex items-center border-b border-border shrink-0 px-1">
                {TABS.map(({ id, icon: Icon, label }) => (
                  <button
                    key={id}
                    onClick={() => setActiveTab(id)}
                    className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors
                      ${activeTab === id
                        ? 'text-primary border-b-2 border-primary'
                        : 'text-muted-foreground hover:text-foreground'
                      }`}
                    title={label}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    {panelWidth >= 420 && <span>{label}</span>}
                  </button>
                ))}
              </div>

              {/* Content Area */}
              <div className="flex-1 overflow-y-auto overflow-x-hidden">
                <TabContent tab={activeTab} />
              </div>
            </div>
          </ResizablePanel>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
