"use client"

import { useAIOrchestrator } from "./AIOrchestrator"
import { useEffect, useState } from "react"

export default function OllamaDebugger() {
  const { ollamaModels, ollamaConnected, ollamaError, refreshOllamaModels } = useAIOrchestrator()
  const [testResult, setTestResult] = useState<any>(null)
  
  const testDirectConnection = async () => {
    try {
      const response = await fetch('/api/test-ollama')
      const data = await response.json()
      setTestResult(data)
      console.log("🧪 Test result:", data)
    } catch (error) {
      setTestResult({ error: error instanceof Error ? error.message : "Failed" })
    }
  }
  
  useEffect(() => {
    console.log("🔍 OllamaDebugger - Current state:", {
      ollamaModels,
      ollamaConnected,
      ollamaError
    })
  }, [ollamaModels, ollamaConnected, ollamaError])
  
  return (
    <div className="fixed bottom-4 right-4 bg-gray-800 text-white p-4 rounded-lg max-w-md text-xs">
      <h3 className="font-bold mb-2">🔍 Ollama Debug Info</h3>
      
      <div className="mb-2">
        <strong>Connected:</strong> {ollamaConnected ? "✅ YES" : "❌ NO"}
      </div>
      
      <div className="mb-2">
        <strong>Models Count:</strong> {ollamaModels.length}
      </div>
      
      <div className="mb-2">
        <strong>Models:</strong> {ollamaModels.length > 0 ? ollamaModels.join(", ") : "None"}
      </div>
      
      <div className="mb-2">
        <strong>Error:</strong> {ollamaError || "None"}
      </div>
      
      <div className="flex gap-2 mb-2">
        <button 
          onClick={refreshOllamaModels}
          className="bg-blue-600 px-2 py-1 rounded text-xs"
        >
          Refresh
        </button>
        <button 
          onClick={testDirectConnection}
          className="bg-green-600 px-2 py-1 rounded text-xs"
        >
          Test Direct
        </button>
      </div>
      
      {testResult && (
        <div className="mt-2 p-2 bg-gray-700 rounded">
          <strong>Test Result:</strong>
          <pre className="text-xs mt-1 overflow-auto max-h-32">
            {JSON.stringify(testResult, null, 2)}
          </pre>
        </div>
      )}
    </div>
  )
}