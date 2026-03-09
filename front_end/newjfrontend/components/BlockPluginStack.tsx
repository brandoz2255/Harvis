"use client"

import { useState } from "react"
import { motion, AnimatePresence } from "framer-motion"
import {
  BookOpen, Code, Blocks,
} from "lucide-react"
import type { LucideIcon } from "lucide-react"
import {
  useBlockPluginStore,
  BLOCK_PLUGINS,
} from "@/stores/blockPluginStore"

const ICON_MAP: Record<string, LucideIcon> = {
  BookOpen,
  Code,
}

const BUTTON_SIZE = 44
const MAIN_SIZE = 48
const GAP = 10

export default function BlockPluginStack() {
  const { activePluginId, toggle } = useBlockPluginStore()
  const [isExpanded, setIsExpanded] = useState(false)

  const hasActivePlugin = activePluginId !== null

  return (
    <div className="fixed bottom-6 right-6 z-40 hidden lg:block">
      {/* Plugin buttons -- absolutely positioned above the main bubble */}
      <AnimatePresence>
        {isExpanded && BLOCK_PLUGINS.map((plugin, i) => {
          const Icon = ICON_MAP[plugin.iconName] ?? BookOpen
          const isActive = activePluginId === plugin.id
          const offset = (i + 1) * (BUTTON_SIZE + GAP)

          return (
            <motion.div
              key={plugin.id}
              className="group absolute right-0.5"
              style={{ bottom: 0 }}
              initial={{ opacity: 0, scale: 0.4, y: 0 }}
              animate={{ opacity: 1, scale: 1, y: -offset }}
              exit={{ opacity: 0, scale: 0.4, y: 0 }}
              transition={{
                delay: i * 0.035,
                type: "spring",
                stiffness: 380,
                damping: 22,
              }}
            >
              <span
                className="pointer-events-none absolute right-full mr-3 top-1/2 -translate-y-1/2
                           whitespace-nowrap rounded-md bg-popover px-2.5 py-1 text-xs font-medium
                           text-popover-foreground shadow-md border border-border
                           opacity-0 scale-95 group-hover:opacity-100 group-hover:scale-100
                           transition-all duration-150"
              >
                {plugin.label}
              </span>

              <motion.button
                onClick={() => toggle(plugin.id)}
                whileHover={{ scale: 1.12 }}
                whileTap={{ scale: 0.92 }}
                title={plugin.label}
                className={`
                  flex items-center justify-center rounded-full
                  backdrop-blur-md border shadow-lg transition-all duration-200
                  ${isActive
                    ? "bg-primary text-primary-foreground border-primary ring-2 ring-ring/50 shadow-primary/25"
                    : "bg-card/80 text-muted-foreground border-border hover:text-foreground hover:border-ring/40 hover:shadow-xl"
                  }
                `}
                style={{ width: BUTTON_SIZE, height: BUTTON_SIZE }}
              >
                <Icon className="w-[18px] h-[18px]" />
              </motion.button>
            </motion.div>
          )
        })}
      </AnimatePresence>

      {/* Main toggle bubble -- always pinned at bottom-right */}
      <motion.button
        onClick={() => setIsExpanded((v) => !v)}
        whileHover={{ scale: 1.1 }}
        whileTap={{ scale: 0.9 }}
        title={isExpanded ? "Close plugins" : "Plugins"}
        className={`
          relative flex items-center justify-center rounded-full
          backdrop-blur-md border shadow-lg transition-all duration-200
          ${hasActivePlugin
            ? "bg-primary text-primary-foreground border-primary shadow-primary/30"
            : "bg-card/90 text-muted-foreground border-border hover:text-foreground hover:border-ring/40 hover:shadow-xl"
          }
        `}
        style={{ width: MAIN_SIZE, height: MAIN_SIZE }}
      >
        <motion.div
          animate={{ rotate: isExpanded ? 90 : 0 }}
          transition={{ type: "spring", stiffness: 300, damping: 20 }}
        >
          <Blocks className="w-5 h-5" />
        </motion.div>
      </motion.button>
    </div>
  )
}
