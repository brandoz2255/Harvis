
"use client"

import { useState, useEffect, useCallback } from "react"

interface ModelCapabilities {
  name: string
  tasks: string[]
  speed: number // 1-10 scale
  accuracy: number // 1-10 scale
  memoryUsage: number // MB
  gpuRequired: boolean
}

interface HardwareInfo {
  gpu: boolean
  gpuMemory?: number
  cpuCores: number
  totalMemory: number
  webgl: boolean
}

export class AIOrchestrator {
  private models: ModelCapabilities[] = [
    {
      name: "gemini-1.5-flash",
      tasks: ["general", "conversation", "creative", "multilingual", "code", "reasoning", "lightweight", "quick-response"],
      speed: 9,
      accuracy: 8,
      memoryUsage: 1024,
      gpuRequired: false,
    },
    {
      name: "mistral",
      tasks: ["general", "conversation", "reasoning"],
      speed: 8,
      accuracy: 7,
      memoryUsage: 2048,
      gpuRequired: false,
    },
    {
      name: "llama3",
      tasks: ["general", "conversation", "complex-reasoning"],
      speed: 6,
      accuracy: 9,
      memoryUsage: 4096,
      gpuRequired: true,
    },
    {
      name: "codellama",
      tasks: ["code", "programming", "debugging"],
      speed: 7,
      accuracy: 9,
      memoryUsage: 3072,
      gpuRequired: false,
    },
    {
      name: "gemma",
      tasks: ["general", "creative", "writing"],
      speed: 9,
      accuracy: 6,
      memoryUsage: 1536,
      gpuRequired: false,
    },
    {
      name: "phi3",
      tasks: ["lightweight", "mobile", "quick-response"],
      speed: 10,
      accuracy: 6,
      memoryUsage: 512,
      gpuRequired: false,
    },
    {
      name: "qwen",
      tasks: ["multilingual", "translation", "general"],
      speed: 7,
      accuracy: 8,
      memoryUsage: 2560,
      gpuRequired: false,
    },
    {
      name: "deepseek-coder",
      tasks: ["code", "programming", "technical"],
      speed: 6,
      accuracy: 10,
      memoryUsage: 3584,
      gpuRequired: true,
    },
  ]

  private hardware: HardwareInfo | null = null

  async detectHardware(): Promise<HardwareInfo> {
    const hardware: HardwareInfo = {
      gpu: false,
      cpuCores: navigator.hardwareConcurrency || 4,
      totalMemory: (navigator as any).deviceMemory ? (navigator as any).deviceMemory * 1024 : 8192,
      webgl: false,
    }

    try {
      const canvas = document.createElement("canvas")
      const gl = canvas.getContext("webgl") || canvas.getContext("experimental-webgl")
      if (gl) {
        hardware.webgl = true
        hardware.gpu = true

        const debugInfo = (gl as any).getExtension("WEBGL_debug_renderer_info");
        if (debugInfo) {
          const renderer = (gl as any).getParameter(debugInfo.UNMASKED_RENDERER_WEBGL);
          console.log("GPU Renderer:", renderer)
        }
      }
    } catch (e) {
      console.log("WebGL not supported")
    }

    if (hardware.gpu) {
      hardware.gpuMemory = hardware.totalMemory > 16384 ? 8192 : 4096
    }

    this.hardware = hardware
    return hardware
  }

  async fetchOllamaModels(): Promise<{ models: string[], connected: boolean, error?: string }> {
    try {
      console.log("🦙 Fetching Ollama models...")
      const response = await fetch("/api/ollama-models")
      console.log("🦙 Response status:", response.status, response.statusText)
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }
      
      const data = await response.json()
      console.log("🦙 API Response data:", data)
      console.log("🦙 data type:", typeof data)
      console.log("🦙 data is array:", Array.isArray(data))
      
      // Backend returns array of model names directly: ["model1", "model2"]
      if (Array.isArray(data) && data.length > 0) {
        console.log("🦙 Found models array:", data)
        return {
          models: data,
          connected: true
        }
      } else if (Array.isArray(data) && data.length === 0) {
        console.log("🦙 Empty models array - Ollama connected but no models")
        return {
          models: [],
          connected: true,
          error: 'No models found on Ollama server'
        }
      } else {
        console.log("🦙 Unexpected response format:", data)
        return {
          models: [],
          connected: false,
          error: 'Unexpected response format from server'
        }
      }
    } catch (error) {
      console.error("🦙 Could not fetch Ollama models:", error)
      return {
        models: [],
        connected: false,
        error: error instanceof Error ? error.message : 'Network error'
      }
    }
  }

  selectOptimalModel(task: string, priority: "speed" | "accuracy" | "balanced" = "balanced"): string {
    if (!this.hardware) {
      return "mistral"
    }

    const suitableModels = this.models.filter((model) =>
      model.tasks.some((t) => t.includes(task.toLowerCase()) || task.toLowerCase().includes(t)),
    )

    if (suitableModels.length === 0) {
      const generalModels = this.models.filter((model) => model.tasks.includes("general"))
      return this.selectBestModel(generalModels, priority)
    }

    return this.selectBestModel(suitableModels, priority)
  }

  private selectBestModel(models: ModelCapabilities[], priority: "speed" | "accuracy" | "balanced"): string {
    if (!this.hardware) return models[0]?.name || "mistral"

    const compatibleModels = models.filter((model) => {
      if (model.gpuRequired && !this.hardware!.gpu) return false
      if (model.memoryUsage > this.hardware!.totalMemory) return false
      return true
    })

    if (compatibleModels.length === 0) {
      return models.sort((a, b) => a.memoryUsage - b.memoryUsage)[0]?.name || "mistral"
    }

    const scoredModels = compatibleModels.map((model) => {
      let score = 0
      switch (priority) {
        case "speed":
          score = model.speed * 0.7 + model.accuracy * 0.3
          break
        case "accuracy":
          score = model.accuracy * 0.7 + model.speed * 0.3
          break
        case "balanced":
          score = (model.speed + model.accuracy) / 2
          break
      }
      return { model, score }
    })

    scoredModels.sort((a, b) => b.score - a.score)
    return scoredModels[0]?.model.name || "mistral"
  }

  getModelInfo(modelName: string): ModelCapabilities | null {
    return this.models.find((m) => m.name === modelName) || null
  }

  getAllModels(): ModelCapabilities[] {
    return [...this.models]
  }

  async analyzeAndRespond(imageData: string): Promise<{ commentary: string; llm_response: string }> {
    try {
      const response = await fetch("/api/analyze-and-respond", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ image: imageData }),
      })

      if (!response.ok) {
        throw new Error(`Backend responded with ${response.status}`)
      }

      return await response.json()
    } catch (error) {
      console.error("Analyze and respond API error:", error)
      return {
        commentary: "Failed to analyze screen",
        llm_response: "Could not get a response from the assistant.",
      }
    }
  }
}

export function useAIOrchestrator() {
  const [orchestrator] = useState(() => new AIOrchestrator())
  const [hardware, setHardware] = useState<HardwareInfo | null>(null)
  const [isDetecting, setIsDetecting] = useState(true)
  const [models, setModels] = useState<string[]>([])
  const [ollamaModels, setOllamaModels] = useState<string[]>([])
  const [ollamaConnected, setOllamaConnected] = useState(false)
  const [ollamaError, setOllamaError] = useState<string | null>(null)
  const [lastFetch, setLastFetch] = useState<Date | null>(null)

  const refreshOllamaModels = useCallback(async () => {
    console.log("🔄 refreshOllamaModels called")
    const result = await orchestrator.fetchOllamaModels()
    console.log("🔄 fetchOllamaModels result:", result)
    console.log("🔄 result.models type:", typeof result.models)
    console.log("🔄 result.models length:", result.models?.length)
    console.log("🔄 result.connected:", result.connected)
    
    setOllamaModels(result.models)
    setOllamaConnected(result.connected)
    setOllamaError(result.error || null)
    setLastFetch(new Date())
    console.log("🔄 State set - about to log current state")
    
    // Log state after a brief delay to see if React updated it
    setTimeout(() => {
      console.log("🔄 State after update - models:", result.models, "connected:", result.connected)
    }, 100)
    
    // Update combined models list
    const builtInModels = orchestrator.getAllModels().map((m) => m.name)
    const allModels = [...builtInModels, ...result.models]
    setModels(Array.from(new Set(allModels)))
    console.log("🔄 Combined models updated:", allModels)
    
    return result
  }, [orchestrator])

  useEffect(() => {
    const initialize = async () => {
      try {
        const hw = await orchestrator.detectHardware()
        setHardware(hw)
        await refreshOllamaModels()
      } catch (error) {
        console.error("Initialization failed:", error)
      } finally {
        setIsDetecting(false)
      }
    }

    initialize()
    
    // Set up periodic refresh every 30 seconds
    const interval = setInterval(refreshOllamaModels, 30000)
    
    return () => clearInterval(interval)
  }, [orchestrator, refreshOllamaModels])

  return { 
    orchestrator, 
    hardware, 
    isDetecting, 
    models, 
    ollamaModels, 
    ollamaConnected, 
    ollamaError, 
    lastFetch,
    refreshOllamaModels 
  }
}
