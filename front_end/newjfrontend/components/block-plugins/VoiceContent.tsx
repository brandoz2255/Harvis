"use client"

import { useState } from "react"
import { AudioWaveform, Globe } from "lucide-react"
import VoiceLibrary from "@/components/voice/VoiceLibrary"
import VoiceBrowser from "@/components/voice/VoiceBrowser"

type VoiceTab = "library" | "browser"

export default function VoiceContent() {
  const [tab, setTab] = useState<VoiceTab>("library")

  return (
    <div className="flex flex-col h-full">
      {/* Tab bar */}
      <div className="flex items-center border-b border-border shrink-0 px-1">
        <button
          onClick={() => setTab("library")}
          className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors
            ${tab === "library"
              ? "text-primary border-b-2 border-primary"
              : "text-muted-foreground hover:text-foreground"
            }`}
        >
          <AudioWaveform className="w-3.5 h-3.5" />
          <span>Library</span>
        </button>
        <button
          onClick={() => setTab("browser")}
          className={`flex items-center gap-1.5 px-3 py-2 text-xs font-medium transition-colors
            ${tab === "browser"
              ? "text-primary border-b-2 border-primary"
              : "text-muted-foreground hover:text-foreground"
            }`}
        >
          <Globe className="w-3.5 h-3.5" />
          <span>Browse</span>
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {tab === "library" ? (
          <VoiceLibrary
            compact
            showCloneButton
            showPresets
            showRvcVoices
          />
        ) : (
          <VoiceBrowser embedded />
        )}
      </div>
    </div>
  )
}
