"use client"

import { useState, useEffect } from "react"
import UnifiedChatInterface from "@/components/UnifiedChatInterface"
import CompactScreenShare from "@/components/CompactScreenShare"
import MiscDisplay from "@/components/MiscDisplay"
import { motion } from "framer-motion"

export default function Home() {
  const [isLoaded, setIsLoaded] = useState(false)
  const [screenAnalysis, setScreenAnalysis] = useState<string>("")

  useEffect(() => {
    setIsLoaded(true)
  }, [])

  const handleScreenAnalysis = (analysis: string) => {
    setScreenAnalysis(analysis)
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-black via-gray-900 to-blue-900">
      <div className="container mx-auto px-4 py-8">
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: isLoaded ? 1 : 0, y: isLoaded ? 0 : -20 }}
          transition={{ duration: 0.8 }}
          className="text-center mb-8"
        >
          <h1 className="text-6xl font-bold bg-gradient-to-r from-blue-400 to-cyan-300 bg-clip-text text-transparent mb-4">
            JARVIS AI
          </h1>
          <p className="text-gray-300 text-lg">Advanced AI Assistant with Intelligent Model Orchestration</p>
        </motion.div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main Chat Interface - Takes up 2/3 of the width */}
          <motion.div
            initial={{ opacity: 0, x: -50 }}
            animate={{ opacity: isLoaded ? 1 : 0, x: isLoaded ? 0 : -50 }}
            transition={{ duration: 0.8, delay: 0.2 }}
            className="lg:col-span-2"
          >
            <UnifiedChatInterface />
          </motion.div>

          {/* Right Column - Screen Share and Misc Display */}
          <motion.div
            initial={{ opacity: 0, x: 50 }}
            animate={{ opacity: isLoaded ? 1 : 0, x: isLoaded ? 0 : 50 }}
            transition={{ duration: 0.8, delay: 0.4 }}
            className="space-y-6"
          >
            <CompactScreenShare onAnalysis={handleScreenAnalysis} />
            <MiscDisplay screenAnalysis={screenAnalysis} />
          </motion.div>
        </div>
      </div>
    </div>
  )
}

