"use client"

import type React from "react"

import { useState, useEffect, useRef } from "react"
import { motion, AnimatePresence } from "framer-motion"
import {
  ArrowLeft,
  Plus,
  Settings,
  Play,
  Square,
  Trash2,
  ExternalLink,
  Bot,
  Zap,
  Database,
  Globe,
  Code,
  Workflow,
  Activity,
  CheckCircle,
  XCircle,
  Clock,
  MoreVertical,
  Cpu,
  AlertTriangle,
  Mic,
  Loader,
}
from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Textarea } from "@/components/ui/textarea"
import { CardTitle, CardHeader, CardContent } from "@/components/ui/card"
import Link from "next/link"
import SettingsModal from "@/components/SettingsModal"

interface AIAgent {
  id: string
  name: string
  description: string
  type: "Ollama" | "Gemini" | "Research"
  status: "active" | "inactive" | "error"
  executionCount: number
  hardware: "CPU" | "GPU" | "Unknown"
}

export default function AIAgentsPage() {
  const [agents, setAgents] = useState<AIAgent[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showSettings, setShowSettings] = useState(false)

  // n8n automation states
  const [n8nPrompt, setN8nPrompt] = useState('');
  const [n8nWorkflow, setN8nWorkflow] = useState(null);
  const [n8nError, setN8nError] = useState('');
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef<any>(null);
  const [isProcessing, setIsProcessing] = useState(false); // New state for thinking indicator
  const [statusMessage, setStatusMessage] = useState<string | null>(null); // New state for status messages
  const [statusType, setStatusType] = useState<'success' | 'error' | 'info' | null>(null); // New state for status message type
  const [lastErrorType, setLastErrorType] = useState<'n8n' | 'speech' | null>(null); // New state to track error source

  useEffect(() => {
    const fetchAgents = async () => {
      try {
        const response = await fetch("/api/ollama-models")
        if (!response.ok) {
          throw new Error("Failed to fetch agent data")
        }
        const modelNames = await response.json()

        const fetchedAgents: AIAgent[] = modelNames.map((name: string) => ({
          id: name,
          name: name.split(":")[0], // Extract name before ':'
          description: `An AI agent powered by the ${name} model.`,
          type: name.includes("gemini") ? "Gemini" : "Ollama",
          status: "active" as const,
          executionCount: 0, // Placeholder
          hardware: "Unknown" as const, // Placeholder
        }))

        // Add the Research Assistant agent
        fetchedAgents.push({
          id: "research-assistant",
          name: "Research Assistant",
          description: "Performs research and analysis using web searches.",
          type: "Research",
          status: "active",
          executionCount: 0,
          hardware: "CPU",
        })

        setAgents(fetchedAgents)
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "An unknown error occurred",
        )
      } finally {
        setLoading(false)
      }
    }

    fetchAgents()
  }, [])

  const getStatusColor = (status: AIAgent["status"]) => {
    switch (status) {
      case "active":
        return "border-green-500 text-green-400"
      case "inactive":
        return "border-gray-500 text-gray-400"
      case "error":
        return "border-red-500 text-red-400"
      default:
        return "border-gray-500 text-gray-400"
    }
  }

  const getStatusIcon = (status: AIAgent["status"]) => {
    switch (status) {
      case "active":
        return <CheckCircle className="w-4 h-4" />
      case "inactive":
        return <XCircle className="w-4 h-4" />
      case "error":
        return <AlertTriangle className="w-4 h-4" />
      default:
        return <XCircle className="w-4 h-4" />
    }
  }

  const getTypeIcon = (type: AIAgent["type"]) => {
    switch (type) {
      case "Ollama":
        return <Bot className="w-4 h-4" />
      case "Gemini":
        return <Zap className="w-4 h-4" />
      case "Research":
        return <Globe className="w-4 h-4" />
      default:
        return <Bot className="w-4 h-4" />
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
    <div className="min-h-screen bg-gradient-to-br from-black via-gray-900 to-indigo-900">
      <div className="container mx-auto px-4 py-6">
        {/* Header */}
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
            <Badge
              variant="outline"
              className="border-indigo-500 text-indigo-400"
            >
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

        {/* Stats Overview */}
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
                    {agents.filter((a) => a.status === "active").length}
                  </p>
                </div>
                <Activity className="w-8 h-8 text-green-400" />
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

        {/* n8n Workflow Automation Section */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.3 }}
          className="mb-8"
        >
          <Card className="max-w-full mx-auto bg-gray-900/50 backdrop-blur-sm border-purple-500/30">
            <CardHeader>
              <CardTitle className="text-white flex items-center"><Workflow className="mr-2" /> n8n Workflow Automation</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-col space-y-4">
                <div className="relative">
                  <Textarea
                    placeholder="e.g., Check if google.com is up every hour and send me a message if it’s not."
                    value={n8nPrompt}
                    onChange={handleN8nPromptChange}
                    rows={4}
                    className="bg-gray-800 border-gray-700 text-white placeholder-gray-500"
                    disabled={isProcessing}
                  />
                  <Button
                    variant="ghost"
                    size="icon"
                    className={`absolute bottom-2 right-2 ${isListening ? 'text-red-500' : 'text-gray-400 hover:text-white'}`}
                    onClick={handleVoiceInput}
                    disabled={isProcessing}
                  >
                    <Mic className="h-5 w-5" />
                  </Button>
                </div>
                <Button onClick={handleN8nSubmit} className="bg-purple-600 hover:bg-purple-700 text-white" disabled={isProcessing}>
                  {isProcessing ? (
                    <span className="flex items-center">
                      <Loader className="animate-spin mr-2" size={18} /> Thinking...
                    </span>
                  ) : (
                    "Generate n8n Workflow"
                  )}
                </Button>
              </div>

              {statusMessage && (
                <div className={`mt-4 p-3 rounded-md ${statusType === 'success' ? 'bg-green-900/30 text-green-400 border border-green-600' : statusType === 'error' ? 'bg-red-900/30 text-red-400 border border-red-600' : 'bg-blue-900/30 text-blue-400 border border-blue-600'}`}>
                  <p>{statusMessage}</p>
                  {statusType === 'error' && lastErrorType === 'n8n' && (
                    <Button
                      onClick={handleN8nSubmit}
                      className="mt-2 bg-red-700 hover:bg-red-800 text-white"
                    >
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
                    href={`YOUR_N8N_URL/workflow/${(n8nWorkflow as any).id}`}
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

        {/* Agents Grid */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.2 }}
        >
          {loading ? (
            <div className="text-center text-gray-400">Loading agents...</div>
          ) : error ? (
            <div className="text-center text-red-400">
              Error: {error}. Could not load agent information.
            </div>
          ) : agents.length === 0 ? (
            <div className="text-center text-gray-400">
              No AI agents detected.
            </div>
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
                        {/* Agent Header */}
                        <div className="flex items-start justify-between mb-4">
                          <div className="flex items-center space-x-3">
                            <div className="p-2 bg-indigo-600/20 rounded-lg">
                              {getTypeIcon(agent.type)}
                            </div>
                            <div>
                              <h3 className="text-lg font-semibold text-white">
                                {agent.name}
                              </h3>
                              <p className="text-sm text-gray-400 capitalize">
                                {agent.type} Agent
                              </p>
                            </div>
                          </div>
                          <div className="flex items-center space-x-2">
                            <Badge
                              variant="outline"
                              className={getStatusColor(agent.status)}
                            >
                              {getStatusIcon(agent.status)}
                              <span className="ml-1 capitalize">
                                {agent.status}
                              </span>
                            </Badge>
                          </div>
                        </div>

                        {/* Agent Description */}
                        <p className="text-sm text-gray-300 mb-4">
                          {agent.description}
                        </p>

                        {/* Agent Stats */}
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
                              <p className="text-lg font-semibold text-white">
                                {agent.hardware}
                              </p>
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

      {/* Settings Modal */}
      <SettingsModal
        isOpen={showSettings}
        onClose={() => setShowSettings(false)}
        context="agent"
      />
    </div>
  )
}