"use client"

import { useRef } from "react"

import { useState, useEffect } from "react"
import UnifiedChatInterface from "@/components/UnifiedChatInterface"
import CompactScreenShare from "@/components/CompactScreenShare"
import MiscDisplay from "@/components/MiscDisplay"
import { motion } from "framer-motion"
import { Button } from "@/components/ui/button"
import { Swords, Shield } from "lucide-react"
import Link from "next/link"

export default function Home() {
  const [isLoaded, setIsLoaded] = useState(false)
  const [screenAnalysis, setScreenAnalysis] = useState<string>("")

  // Reference to the chat interface to add messages
  const chatInterfaceRef = useRef<any>(null)

  useEffect(() => {
    setIsLoaded(true)
  }, [])

  const handleScreenAnalysis = (analysis: string) => {
    setScreenAnalysis(analysis)
  }

  const handleAnalyzeAndRespond = (response: string) => {
    // Add the AI response to the chat interface
    if (chatInterfaceRef.current) {
      chatInterfaceRef.current.addAIMessage(response, "Screen Analysis")
    }
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
          <p className="text-gray-300 text-lg mb-6">Advanced AI Assistant with Intelligent Model Orchestration</p>

          {/* Navigation Buttons */}
          <div className="flex justify-center space-x-4 mb-8">
            <Link href="/versus-mode">
              <Button className="bg-gradient-to-r from-red-600 to-blue-600 hover:from-red-700 hover:to-blue-700 text-white px-6 py-3 text-lg">
                <Swords className="w-5 h-5 mr-2" />
                Versus Mode
              </Button>
            </Link>
            <Button
              variant="outline"
              className="border-cyan-500 text-cyan-400 hover:bg-cyan-500/10 px-6 py-3 text-lg bg-transparent"
            >
              <Shield className="w-5 h-5 mr-2" />
              Defense Mode
            </Button>
          </div>
        </motion.div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Main Chat Interface - Takes up 2/3 of the width */}
          <motion.div
            initial={{ opacity: 0, x: -50 }}
            animate={{ opacity: isLoaded ? 1 : 0, x: isLoaded ? 0 : -50 }}
            transition={{ duration: 0.8, delay: 0.2 }}
            className="lg:col-span-2"
          >
            <UnifiedChatInterface ref={chatInterfaceRef} />
          </motion.div>

          {/* Right Column - Screen Share and Misc Display */}
          <motion.div
            initial={{ opacity: 0, x: 50 }}
            animate={{ opacity: isLoaded ? 1 : 0, x: isLoaded ? 0 : 50 }}
            transition={{ duration: 0.8, delay: 0.4 }}
            className="space-y-6"
          >
            <CompactScreenShare onAnalysis={handleScreenAnalysis} onAnalyzeAndRespond={handleAnalyzeAndRespond} />
            <MiscDisplay screenAnalysis={screenAnalysis} />
          </motion.div>
        </div>
      </div>
    </div>
  )
}

//bllah blah blah blah


