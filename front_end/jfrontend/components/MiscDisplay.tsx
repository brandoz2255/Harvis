"use client"

import { useState, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import { ImageIcon, Code, Brain, FileText, X } from "lucide-react"
import { Card } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"

interface MiscItem {
  id: string
  type: "image" | "code" | "thought" | "document"
  title: string
  content: string
  timestamp: Date
}

interface MiscDisplayProps {
  screenAnalysis?: string
}

export default function MiscDisplay({ screenAnalysis }: MiscDisplayProps) {
  const [items, setItems] = useState<MiscItem[]>([])
  const [selectedItem, setSelectedItem] = useState<MiscItem | null>(null)

  useEffect(() => {
    if (screenAnalysis) {
      const newItem: MiscItem = {
        id: Date.now().toString(),
        type: "thought",
        title: "Screen Analysis",
        content: screenAnalysis,
        timestamp: new Date(),
      }
      setItems((prev) => [newItem, ...prev.slice(0, 9)]) // Keep last 10 items
    }
  }, [screenAnalysis])

  // Simulate AI generating various content types
  useEffect(() => {
    const interval = setInterval(() => {
      const types: MiscItem["type"][] = ["code", "thought", "document"]
      const randomType = types[Math.floor(Math.random() * types.length)]

      const sampleContent = {
        code: `// AI-generated optimization
function optimizePerformance() {
  const cache = new Map();
  return (key, computation) => {
    if (cache.has(key)) return cache.get(key);
    const result = computation();
    cache.set(key, result);
    return result;
  };
}`,
        thought:
          "Analyzing user interaction patterns to improve response accuracy. Detected preference for technical explanations.",
        document:
          "Generated summary: The current conversation indicates a focus on AI orchestration and performance optimization. Key topics include model selection, hardware detection, and user interface improvements.",
        image: "A placeholder for a generated image."
      }

      const titles = {
        code: "Performance Optimization",
        thought: "AI Reasoning Process",
        document: "Conversation Summary",
        image: "Generated Image"
      }

      if (Math.random() > 0.7) {
        // 30% chance every 10 seconds
        const newItem: MiscItem = {
          id: Date.now().toString(),
          type: randomType,
          title: titles[randomType],
          content: sampleContent[randomType],
          timestamp: new Date(),
        }
        setItems((prev) => [newItem, ...prev.slice(0, 9)])
      }
    }, 10000)

    return () => clearInterval(interval)
  }, [])

  const getIcon = (type: MiscItem["type"]) => {
    switch (type) {
      case "image":
        return <ImageIcon className="w-4 h-4" />
      case "code":
        return <Code className="w-4 h-4" />
      case "thought":
        return <Brain className="w-4 h-4" />
      case "document":
        return <FileText className="w-4 h-4" />
    }
  }

  const getTypeColor = (type: MiscItem["type"]) => {
    switch (type) {
      case "image":
        return "border-purple-500 text-purple-400"
      case "code":
        return "border-green-500 text-green-400"
      case "thought":
        return "border-yellow-500 text-yellow-400"
      case "document":
        return "border-blue-500 text-blue-400"
    }
  }

  return (
    <Card className="bg-gray-900/50 backdrop-blur-sm border-blue-500/30">
      <div className="p-3 border-b border-blue-500/30">
        <h3 className="text-lg font-semibold text-blue-300">AI Insights</h3>
      </div>

      <div className="p-3 max-h-96 overflow-y-auto">
        <AnimatePresence>
          {items.map((item) => (
            <motion.div
              key={item.id}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="mb-3 last:mb-0"
            >
              <div
                className="bg-gray-800/50 rounded-lg p-3 cursor-pointer hover:bg-gray-800/70 transition-colors"
                onClick={() => setSelectedItem(item)}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center space-x-2">
                    <Badge variant="outline" className={`text-xs ${getTypeColor(item.type)}`}>
                      {getIcon(item.type)}
                      <span className="ml-1 capitalize">{item.type}</span>
                    </Badge>
                    <span className="text-sm font-medium text-gray-300">{item.title}</span>
                  </div>
                  <span className="text-xs text-gray-500">{item.timestamp.toLocaleTimeString()}</span>
                </div>
                <p className="text-xs text-gray-400 line-clamp-2">{item.content}</p>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {items.length === 0 && (
          <div className="text-center text-gray-500 py-8">
            <Brain className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p className="text-sm">AI insights will appear here</p>
          </div>
        )}
      </div>

      {/* Modal for detailed view */}
      <AnimatePresence>
        {selectedItem && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
            onClick={() => setSelectedItem(null)}
          >
            <motion.div
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="bg-gray-900 rounded-lg border border-blue-500/30 max-w-2xl w-full max-h-[80vh] overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="p-4 border-b border-blue-500/30 flex justify-between items-center">
                <div className="flex items-center space-x-2">
                  <Badge variant="outline" className={`${getTypeColor(selectedItem.type)}`}>
                    {getIcon(selectedItem.type)}
                    <span className="ml-1 capitalize">{selectedItem.type}</span>
                  </Badge>
                  <h3 className="text-lg font-semibold text-white">{selectedItem.title}</h3>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setSelectedItem(null)}
                  className="text-gray-400 hover:text-white"
                >
                  <X className="w-4 h-4" />
                </Button>
              </div>
              <div className="p-4 overflow-y-auto max-h-96">
                {selectedItem.type === "code" ? (
                  <pre className="bg-gray-800 rounded p-3 text-sm text-green-400 overflow-x-auto">
                    <code>{selectedItem.content}</code>
                  </pre>
                ) : (
                  <p className="text-gray-300 whitespace-pre-wrap">{selectedItem.content}</p>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </Card>
  )
}
