'use client';

import { useState, useRef, useEffect } from "react"
import { motion, AnimatePresence } from "framer-motion"
import {
  Cpu,
  Zap,
  Target,
  Monitor,
  Globe,
  Search,
  BookOpen,
  ArrowLeft,
  MicOff,
  Mic,
  Loader2,
  Check,
  XCircle,
  AlertTriangle,
  Bot,
  BrainCircuit,
  MessageSquare,
  ExternalLink,
  Swords,
  Shield,
  Settings,
  Workflow
} from "lucide-react"
        
import { Button } from "@/components/ui/button"
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { useAIOrchestrator } from "@/components/AIOrchestrator"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import SettingsModal from "@/components/SettingsModal"
import Link from "next/link"
import Aurora from "@/components/Aurora"

interface Agent {
  id: string
  name: string
  description: string
  type: "Ollama" | "Gemini" | "Research"
  status: "active" | "inactive" | "error"
  executionCount: number
  hardware: string
}

interface WorkflowType {
  id: string
  name: string
  description: string
}

interface N8nAutomationResponse {
  workflow: WorkflowType;
}

export default function AIAgents() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [isLoadingAgents, setIsLoadingAgents] = useState(true)
  const [agentsError, setAgentsError] = useState<string | null>(null)
  const [showSettings, setShowSettings] = useState(false)
  const [n8nPrompt, setN8nPrompt] = useState("")
  const [n8nWorkflow, setN8nWorkflow] = useState<WorkflowType | null>(null)
  const [n8nStatus, setN8nStatus] = useState<"idle" | "loading" | "success" | "error">("idle")
  const [n8nMessage, setN8nMessage] = useState<string | null>(null)
  const [n8nMessageType, setN8nMessageType] = useState<"info" | "success" | "error" | null>(null)
  const n8nVoiceInputRef = useRef<any>(null)
  const [isN8nVoiceRecording, setIsN8nVoiceRecording] = useState(false)
  const [isN8nVoiceProcessing, setIsN8nVoiceProcessing] = useState(false)
  useEffect(() => {
    const fetchAgents = async () => {
      try {
        const response = await fetch("http://backend:8000/api/ollama-models", { credentials: 'include' })
        if (!response.ok) throw new Error("Failed to fetch agent data")
        const data = await response.json()
        const fetchedAgents: Agent[] = data.models?.map((model: any) => ({
          id: model.name,
          name: model.name.split(":")[0],
          description: `An AI agent powered by the ${model.name} model.`,
          type: model.name.includes("gemini") ? "Gemini" : "Ollama",
          status: "active",
          executionCount: Math.floor(Math.random() * 100),
          hardware: "GPU",
        })) || []
        fetchedAgents.push({
          id: "research-assistant",
          name: "Research Assistant",
          description: "Performs research and analysis using web searches.",
          type: "Research",
          status: "active",
          executionCount: Math.floor(Math.random() * 50),
          hardware: "CPU",
        })
        setAgents(fetchedAgents)
      } catch (error: any) {
        setAgentsError(error.message || "An unknown error occurred")
      } finally {
        setIsLoadingAgents(false)
      }
    }
    fetchAgents()
  }, [])

  const getAgentStatusColor = (status: Agent["status"]) => {
    switch (status) {
      case "active":
        return "border-green-500 text-green-400"
      case "inactive":
      default:
        return "border-gray-500 text-gray-400"
      case "error":
        return "border-red-500 text-red-400"
    }
  }

  const getAgentStatusIcon = (status: Agent["status"]) => {
    switch (status) {
      case "active":
        return <Check className="w-4 h-4" />
      case "inactive":
      default:
        return <XCircle className="w-4 h-4" />
      case "error":
        return <AlertTriangle className="w-4 h-4" />
    }
  }

  const getAgentTypeIcon = (type: Agent["type"]) => {
    switch (type) {
      case "Ollama":
      default:
        return <Bot className="w-4 h-4" />
      case "Gemini":
        return <BrainCircuit className="w-4 h-4" />
      case "Research":
        return <Globe className="w-4 h-4" />
    }
  }

  const handleN8nAutomation = async () => {
    setN8nWorkflow(null)
    setN8nMessage(null)
    setN8nMessageType(null)
    setN8nStatus("loading")

    try {
      const response = await fetch("/api/n8n-automation", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ prompt: n8nPrompt }),
        credentials: 'include',
      })

      if (!response.ok) {
        const errorData = await response.json()
        const errorMessage = errorData.error || "Failed to create workflow"
        setN8nMessage(errorMessage)
        setN8nMessageType("error")
        setN8nStatus("error")
        console.error("n8n workflow creation error:", errorData)
        throw new Error(errorMessage)
      }

      const data: N8nAutomationResponse = await response.json()
      setN8nWorkflow(data.workflow)
      setN8nMessage("Workflow created successfully!")
      setN8nMessageType("success")
      setN8nStatus("success")
    } catch (error: any) {
      if (n8nStatus !== "error") { // Only update if not already in an error state from speech recognition
        setN8nMessage(error.message)
        setN8nMessageType("error")
        setN8nStatus("error")
        console.error("n8n workflow submission error:", error)
      }
    } finally {
      setIsN8nVoiceProcessing(false)
    }
  }

  const startN8nVoiceRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mediaRecorder = new MediaRecorder(stream)
      n8nVoiceInputRef.current = mediaRecorder
      const audioChunks: Blob[] = []

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          audioChunks.push(event.data)
        }
      }

      mediaRecorder.onstop = async () => {
        const audioBlob = new Blob(audioChunks, { type: "audio/wav" })
        await sendN8nAudioToBackend(audioBlob)
        stream.getTracks().forEach((track) => track.stop())
      }

      mediaRecorder.start()
      setIsN8nVoiceRecording(true)
      setN8nStatus("loading")
      setN8nMessage("Listening...")
      setN8nMessageType("info")
    } catch (error) {
      console.error("Error accessing microphone:", error)
      alert("Unable to access microphone. Please check permissions.")
      setN8nStatus("idle")
      setN8nMessage(null)
      setN8nMessageType(null)
    }
  }

  const stopN8nVoiceRecording = () => {
    if (n8nVoiceInputRef.current && isN8nVoiceRecording) {
      n8nVoiceInputRef.current.stop()
      setIsN8nVoiceRecording(false)
      setIsN8nVoiceProcessing(true)
      setN8nStatus("loading")
      setN8nMessage("Processing audio...")
      setN8nMessageType("info")
    }
  }

  const sendN8nAudioToBackend = async (audioBlob: Blob) => {
    try {
      const formData = new FormData()
      formData.append("file", audioBlob, "n8n_prompt.wav")

      const response = await fetch("/api/voice-transcribe", {
        method: "POST",
        body: formData,
        credentials: 'include',
      })

      if (!response.ok) throw new Error("Network response was not ok")

      const data = await response.json()
      if (data.transcription) {
        setN8nPrompt(data.transcription)
        // Automatically trigger automation after transcription
        // handleN8nAutomation(); // This will be called by the button click after transcription is set
      }
    } catch (error) {
      console.error("Voice processing failed:", error)
      setN8nMessage("Speech recognition error.")
      setN8nMessageType("error")
      setN8nStatus("error")
    } finally {
      setIsN8nVoiceProcessing(false)
    }
  }

  const toggleN8nVoiceRecording = () => {
    if (isN8nVoiceRecording) {
      stopN8nVoiceRecording()
    } else {
      startN8nVoiceRecording()
    }
  }

  const handleN8nPromptChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setN8nPrompt(e.target.value);
  };

  const handleN8nSubmit = async () => {
    setN8nError('');
    setN8nWorkflow(null);
    setStatusMessage(null);
    setStatusType(null);
    setIsProcessing(true);

    try {
      const response = await fetch('/api/n8n-automation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: n8nPrompt }),
      });

      if (!response.ok) {
        const errorData = await response.json();
        const errorMessage = errorData.error || 'Failed to create workflow';
        setN8nError(errorMessage);
        setStatusMessage(`Error: ${errorMessage}`);
        setStatusType('error');
        setLastErrorType('n8n'); // Set error type to n8n
        console.error("n8n workflow creation error:", errorData);
        throw new Error(errorMessage);
      }

      const data = await response.json();
      setN8nWorkflow(data.workflow);
      setStatusMessage("Workflow created successfully!");
      setStatusType('success');
      setLastErrorType(null); // Clear error type on success
    } catch (err: any) {
      if (!n8nError) { // Only set if not already set by response.ok check
        setN8nError(err.message);
        setStatusMessage(`Error: ${err.message}`);
        setStatusType('error');
        console.error("n8n workflow submission error:", err);
      }
    } finally {
      setIsProcessing(false);
    }
  };

  const handleVoiceInput = () => {
    if (isListening) {
      recognitionRef.current?.stop();
      setIsListening(false);
      setIsProcessing(false);
      setStatusMessage("Voice input stopped.");
      setStatusType('info');
      return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      const msg = 'Speech recognition is not supported in this browser.';
      setN8nError(msg);
      setStatusMessage(`Error: ${msg}`);
      setStatusType('error');
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';
    recognitionRef.current = recognition;

    setN8nError('');
    setN8nWorkflow(null);
    setStatusMessage("Listening...");
    setStatusType('info');
    setIsProcessing(true);

    recognition.onstart = () => {
      setIsListening(true);
      setStatusMessage("Listening...");
      setStatusType('info');
    };

    recognition.onend = () => {
      setIsListening(false);
      setIsProcessing(false);
    };

    recognition.onerror = (event: any) => {
      setIsListening(false);
      setIsProcessing(false);
      let errorMessage = `Speech recognition error: ${event.error}`;
      if (event.error === 'not-allowed') {
        errorMessage = 'Microphone access denied. Please enable microphone permissions.';
      } else if (event.error === 'no-speech') {
        errorMessage = 'No speech detected. Please try again.';
      } else if (event.error === 'aborted') {
        errorMessage = 'Speech recognition aborted.';
      }
      setN8nError(errorMessage);
      setStatusMessage(`Error: ${errorMessage}`);
      setStatusType('error');
      setLastErrorType('speech'); // Set error type to speech
      console.error("Speech recognition error:", event);
    };

    recognition.onresult = (event: any) => {
      const speechResult = event.results[0][0].transcript;
      setN8nPrompt(speechResult);
      setStatusMessage("Speech recognized successfully.");
      setStatusType('success');
      setIsProcessing(false);
    };

    recognition.start();
  };

  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* Aurora Background */}
      <div className="fixed inset-0 -z-10 pointer-events-none select-none">
        <Aurora
          className="w-full h-full"
          colorStops={['#4F46E5', '#06B6D4', '#8B5CF6']}
          blend={0.4}
          amplitude={1.0}
          speed={0.6}
        />
        <div className="absolute inset-0 bg-black/20 pointer-events-none [mask-image:radial-gradient(ellipse_at_center,white,transparent_80%)]" />
      </div>

      {/* Content */}
      <div className="relative z-10 min-h-screen bg-black/40 backdrop-blur-sm">
        <div className="container mx-auto px-4 py-6">
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center justify-between mb-8"
        >
          <div className="flex items-center space-x-4">
            <Link href="/">
              <Button
                variant="outline"
                size="sm"
                className="bg-gray-800 border-gray-600 text-gray-300"
              >
                <ArrowLeft className="w-4 h-4 mr-2" />
                Dashboard
              </Button>
            </Link>
            <div className="flex items-center space-x-2">
              <Bot className="w-6 h-6 text-indigo-400" />
              <h1 className="text-3xl font-bold text-white">AI Agents</h1>
            </div>
            <Badge variant="outline" className="border-purple-500 text-purple-400">
              {agents.length} Detected
            </Badge>
          </div>
          <div className="flex items-center space-x-2">
            <Button
              onClick={() => setShowSettings(true)}
              variant="outline"
              size="sm"
              className="bg-gray-800 border-gray-600 text-gray-300"
            >
              <Settings className="w-4 h-4 mr-2" />
              Settings
            </Button>
          </div>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
        >
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
            <Card className="bg-gray-900/50 backdrop-blur-sm border-indigo-500/30 p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-400">Total Agents</p>
                  <p className="text-2xl font-bold text-white">
                    {agents.length}
                  </p>
                </div>
                <Bot className="w-8 h-8 text-indigo-400" />
              </div>
            </Card>

            <Card className="bg-gray-900/50 backdrop-blur-sm border-green-500/30 p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-400">Active Agents</p>
                  <p className="text-2xl font-bold text-white">
                    {agents.filter((agent) => agent.status === "active").length}
                  </p>
                </div>
                <Check className="w-8 h-8 text-green-400" />
              </div>
            </Card>

            <Card className="bg-gray-900/50 backdrop-blur-sm border-blue-500/30 p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-400">Total Executions</p>
                  <p className="text-2xl font-bold text-white">
                    {agents
                      .reduce((sum, agent) => sum + agent.executionCount, 0)
                      .toLocaleString()}
                  </p>
                </div>
                <Zap className="w-8 h-8 text-blue-400" />
              </div>
            </Card>
          </div>
        </motion.div>
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="mb-8"
        >
          <Card className="max-w-full mx-auto bg-gray-900/50 backdrop-blur-sm border-purple-500/30">
            <CardHeader>
              <CardTitle className="text-white flex items-center">
                <Workflow className="mr-2" /> n8n Workflow Automation
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col space-y-4">
                <div className="relative">
                  <Textarea
                    placeholder="e.g., Check if google.com is up every hour and send me a message if it's not."
                    value={n8nPrompt}
                    onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setN8nPrompt(e.target.value)}
                    rows={4}
                    className="bg-gray-800 border-gray-700 text-white placeholder-gray-500"
                    disabled={n8nStatus === "loading"}
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    className={`absolute bottom-2 right-2 ${isN8nVoiceRecording ? "text-red-500" : "text-gray-400 hover:text-white"}`}
                    onClick={() => {
                      if (isN8nVoiceRecording) {
                        stopN8nVoiceRecording();
                        return;
                      }
                      const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
                      if (!SpeechRecognition) {
                        setN8nMessage("Speech recognition is not supported in this browser.");
                        setN8nMessageType("error");
                        setN8nStatus("error");
                        return;
                      }
                      startN8nVoiceRecording();
                    }}
                    disabled={n8nStatus === "loading"}
                  >
                    {isN8nVoiceRecording ? <MicOff className="h-5 w-5" /> : <Mic className="h-5 w-5" />}
                  </Button>
                </div>
                <Button
                  onClick={handleN8nAutomation}
                  className="bg-purple-600 hover:bg-purple-700 text-white"
                  disabled={n8nStatus === "loading"}
                >
                  {n8nStatus === "loading" ? (
                    <span className="flex items-center">
                      <Loader2 className="animate-spin mr-2" size={18} /> Thinking...
                    </span>
                  ) : (
                    "Generate n8n Workflow"
                  )}
                </Button>
              </div>
              {n8nMessage && (
                <div
                  className={`mt-4 p-3 rounded-md ${n8nMessageType === "success"
                    ? "bg-green-900/30 text-green-400 border border-green-600"
                    : n8nMessageType === "error"
                      ? "bg-red-900/30 text-red-400 border border-red-600"
                      : "bg-blue-900/30 text-blue-400 border border-blue-600"
                    }`}
                >
                  <p>{n8nMessage}</p>
                  {n8nMessageType === "error" && n8nStatus === "error" && (
                    <Button onClick={handleN8nAutomation} className="mt-2 bg-red-700 hover:bg-red-800 text-white">
                      Retry
                    </Button>
                  )}
                </div>
              )}
              {n8nWorkflow && (
                <div className="mt-4 p-4 bg-gray-800 rounded-md">
                  <h3 className="text-lg font-semibold text-white mb-2">Workflow Created!</h3>
                  <pre className="bg-gray-700 p-3 rounded-md overflow-auto text-gray-200 text-sm max-h-60">
                    {JSON.stringify(n8nWorkflow, null, 2)}
                  </pre>
                  <a
                    href={`YOUR_N8N_URL/workflow/${n8nWorkflow.id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-400 hover:underline mt-2 block"
                  >
                    View in n8n
                  </a>
                </div>
              )}
            </CardContent>
          </Card>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
        >
          {isLoadingAgents ? (
            <div className="text-center text-gray-400">Loading agents...</div>
          ) : agentsError ? (
            <div className="text-center text-red-400">
              Error: {agentsError}. Could not load agent information.
            </div>
          ) : agents.length === 0 ? (
            <div className="text-center text-gray-400">No AI agents detected.</div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
              <AnimatePresence>
                {agents.map((agent) => (
                  <motion.div
                    key={agent.id}
                    initial={{ opacity: 0, scale: 0.9 }}
                    animate={{ opacity: 1, scale: 1 }}
                    exit={{ opacity: 0, scale: 0.9 }}
                    transition={{ duration: 0.3 }}
                  >
                    <Card className="bg-gray-900/50 backdrop-blur-sm border-indigo-500/30 h-full">
                      <div className="p-6">
                        <div className="flex items-start justify-between mb-4">
                          <div className="flex items-center space-x-3">
                            <div className="p-2 bg-indigo-600/20 rounded-lg">
                              {getAgentTypeIcon(agent.type)}
                            </div>
                            <div>
                              <h3 className="text-lg font-semibold text-white">{agent.name}</h3>
                              <p className="text-sm text-gray-400 capitalize">{agent.type} Agent</p>
                            </div>
                          </div>
                          <div className="flex items-center space-x-2">
                            <Badge variant="outline" className={getAgentStatusColor(agent.status)}>
                              {getAgentStatusIcon(agent.status)}
                              <span className="ml-1 capitalize">{agent.status}</span>
                            </Badge>
                          </div>
                        </div>
                        <p className="text-sm text-gray-300 mb-4">{agent.description}</p>
                        <div className="grid grid-cols-2 gap-4 mb-4">
                          <div className="bg-gray-800/50 rounded-lg p-3">
                            <p className="text-xs text-gray-400">Executions</p>
                            <p className="text-lg font-semibold text-white">
                              {agent.executionCount.toLocaleString()}
                            </p>
                          </div>
                          <div className="bg-gray-800/50 rounded-lg p-3">
                            <p className="text-xs text-gray-400">Hardware</p>
                            <div className="flex items-center">
                              <p className="text-lg font-semibold text-white">{agent.hardware}</p>
                              {agent.hardware === "Unknown" && (
                                <AlertTriangle className="w-4 h-4 ml-2 text-yellow-400" />
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </Card>
                  </motion.div>
                ))}
              </AnimatePresence>
            </div>
          )}
        </motion.div>
        </div>
      </div>
      <SettingsModal
        isOpen={showSettings}
        onClose={() => setShowSettings(false)}
        context="agent"
      />
    </div>
  )
}