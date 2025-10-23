"use client"

import React, { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { 
  Sparkles, 
  ArrowRight, 
  X, 
  Monitor, 
  Zap,
  CheckCircle,
  Star
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import Link from "next/link"

interface IDEMigrationPromptProps {
  onStayLegacy: (dontShowAgain: boolean) => void
  onUpgrade: (dontShowAgain: boolean) => void
  className?: string
}

export default function IDEMigrationPrompt({
  onStayLegacy,
  onUpgrade,
  className = ""
}: IDEMigrationPromptProps) {
  const [isVisible, setIsVisible] = useState(true)
  const [dontShowAgain, setDontShowAgain] = useState(false)

  const handleStayLegacy = () => {
    if (dontShowAgain) {
      localStorage.setItem('ide-migration-seen', 'true')
      console.log('✅ User chose to stay on legacy and not show prompt again')
    } else {
      console.log('✅ User chose to stay on legacy (will show prompt again)')
    }
    onStayLegacy(dontShowAgain)
  }

  const handleUpgrade = () => {
    if (dontShowAgain) {
      localStorage.setItem('ide-migration-seen', 'true')
      console.log('✅ User chose to upgrade and not show prompt again')
    } else {
      console.log('✅ User chose to upgrade (will show prompt again)')
    }
    onUpgrade(dontShowAgain)
  }

  const handleDismiss = () => {
    localStorage.setItem('ide-migration-seen', 'true')
    setHasSeenPrompt(true)
    setIsVisible(false)
  }

  if (!isVisible) return null

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className={`fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 ${className}`}
      >
        <motion.div
          initial={{ scale: 0.9, opacity: 0, y: 20 }}
          animate={{ scale: 1, opacity: 1, y: 0 }}
          exit={{ scale: 0.9, opacity: 0, y: 20 }}
          className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl max-w-4xl w-full mx-4 overflow-hidden"
        >
          {/* Header */}
          <div className="bg-gradient-to-r from-purple-600 to-blue-600 p-6 text-white">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-white/20 rounded-lg">
                  <Sparkles className="w-6 h-6" />
                </div>
                <div>
                  <h2 className="text-2xl font-bold">New IDE Available!</h2>
                  <p className="text-purple-100">Experience the next generation of VibeCode</p>
                </div>
              </div>
              <Button
                onClick={handleDismiss}
                variant="ghost"
                size="sm"
                className="text-white hover:bg-white/20"
              >
                <X className="w-5 h-5" />
              </Button>
            </div>
          </div>

          {/* Content */}
          <div className="p-6">
            <div className="grid md:grid-cols-2 gap-6">
              {/* New IDE Features */}
              <div className="space-y-4">
                <div className="flex items-center gap-2 mb-4">
                  <Star className="w-5 h-5 text-yellow-400" />
                  <h3 className="text-lg font-semibold text-white">New Cursor-Style IDE</h3>
                </div>
                
                <div className="space-y-3">
                  <div className="flex items-start gap-3">
                    <CheckCircle className="w-5 h-5 text-green-400 mt-0.5 flex-shrink-0" />
                    <div>
                      <p className="font-medium text-white">Integrated AI Chat</p>
                      <p className="text-sm text-gray-400">AI assistant built into the sidebar</p>
                    </div>
                  </div>
                  
                  <div className="flex items-start gap-3">
                    <CheckCircle className="w-5 h-5 text-green-400 mt-0.5 flex-shrink-0" />
                    <div>
                      <p className="font-medium text-white">Session Tabs</p>
                      <p className="text-sm text-gray-400">Switch between projects like browser tabs</p>
                    </div>
                  </div>
                  
                  <div className="flex items-start gap-3">
                    <CheckCircle className="w-5 h-5 text-green-400 mt-0.5 flex-shrink-0" />
                    <div>
                      <p className="font-medium text-white">Auto-Start Containers</p>
                      <p className="text-sm text-gray-400">Containers start automatically</p>
                    </div>
                  </div>
                  
                  <div className="flex items-start gap-3">
                    <CheckCircle className="w-5 h-5 text-green-400 mt-0.5 flex-shrink-0" />
                    <div>
                      <p className="font-medium text-white">Cursor Shortcuts</p>
                      <p className="text-sm text-gray-400">Cmd+K for AI, Cmd+Shift+E for files</p>
                    </div>
                  </div>
                </div>
              </div>

              {/* Legacy Version */}
              <div className="space-y-4">
                <div className="flex items-center gap-2 mb-4">
                  <Monitor className="w-5 h-5 text-gray-400" />
                  <h3 className="text-lg font-semibold text-white">Legacy Version</h3>
                </div>
                
                <div className="space-y-3">
                  <div className="flex items-start gap-3">
                    <div className="w-5 h-5 rounded-full bg-gray-600 mt-0.5 flex-shrink-0" />
                    <div>
                      <p className="font-medium text-white">Familiar Interface</p>
                      <p className="text-sm text-gray-400">Keep using the current layout</p>
                    </div>
                  </div>
                  
                  <div className="flex items-start gap-3">
                    <div className="w-5 h-5 rounded-full bg-gray-600 mt-0.5 flex-shrink-0" />
                    <div>
                      <p className="font-medium text-white">Modal Sessions</p>
                      <p className="text-sm text-gray-400">Session manager as popup</p>
                    </div>
                  </div>
                  
                  <div className="flex items-start gap-3">
                    <div className="w-5 h-5 rounded-full bg-gray-600 mt-0.5 flex-shrink-0" />
                    <div>
                      <p className="font-medium text-white">Manual Container Start</p>
                      <p className="text-sm text-gray-400">Start containers manually</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Don't Show Again Checkbox */}
            <div className="flex items-center gap-2 mt-6 pt-4 border-t border-gray-700">
              <input
                type="checkbox"
                id="dontShowAgain"
                checked={dontShowAgain}
                onChange={(e) => setDontShowAgain(e.target.checked)}
                className="w-4 h-4 rounded border-gray-600 bg-gray-800 text-purple-600 focus:ring-purple-500 focus:ring-2"
              />
              <label htmlFor="dontShowAgain" className="text-sm text-gray-300 cursor-pointer">
                Don't show this prompt again
              </label>
            </div>

            {/* Action Buttons */}
            <div className="flex items-center justify-between mt-6">
              <div className="flex items-center gap-2 text-sm text-gray-400">
                <Zap className="w-4 h-4" />
                <span>You can always switch between versions</span>
              </div>
              
              <div className="flex items-center gap-3">
                <Button
                  onClick={handleStayLegacy}
                  variant="outline"
                  className="border-gray-600 text-gray-300 hover:bg-gray-800"
                >
                  Stay in Legacy
                </Button>
                <Link href="/ide">
                  <Button
                    onClick={handleUpgrade}
                    className="bg-gradient-to-r from-purple-600 to-blue-600 hover:from-purple-700 hover:to-blue-700 text-white"
                  >
                    <ArrowRight className="w-4 h-4 mr-2" />
                    Try New IDE
                  </Button>
                </Link>
              </div>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}
