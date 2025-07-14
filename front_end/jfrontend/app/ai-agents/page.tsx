"use client"

import type React from "react"

import { useState } from "react"
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
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import Link from "next/link"
import Aurora from "@/components/Aurora"
import SettingsModal from "@/components/SettingsModal"

interface AIAgent {
  id: string
  name: string
  description: string
  type: "n8n" | "zapier" | "make" | "custom" | "webhook"
  status: "active" | "inactive" | "error" | "deploying"
  endpoint: string
  model: string
  capabilities: string[]
  createdAt: Date
  lastActivity: Date
  deploymentUrl?: string
  apiKey?: string
  webhookUrl?: string
  executionCount: number
  successRate: number
}

interface DeploymentTemplate {
  id: string
  name: string
  description: string
  type: "n8n" | "zapier" | "make" | "custom"
  icon: React.ComponentType<any>
  capabilities: string[]
  setupSteps: string[]
}

export default function AIAgentsPage() {
  const [agents, setAgents] = useState<AIAgent[]>([
    {
      id: "1",
      name: "Customer Support Bot",
      description: "Handles customer inquiries and support tickets",
      type: "n8n",
      status: "active",
      endpoint: "https://n8n.example.com/webhook/customer-support",
      model: "mistral",
      capabilities: ["chat", "ticket-management", "knowledge-base"],
      createdAt: new Date(Date.now() - 86400000 * 5),
      lastActivity: new Date(Date.now() - 3600000),
      deploymentUrl: "https://n8n.example.com/workflow/123",
      executionCount: 1247,
      successRate: 94.2,
    },
    {
      id: "2",
      name: "Data Processing Agent",
      description: "Processes and analyzes incoming data streams",
      type: "make",
      status: "active",
      endpoint: "https://hook.integromat.com/abc123",
      model: "llama3",
      capabilities: ["data-analysis", "reporting", "automation"],
      createdAt: new Date(Date.now() - 86400000 * 12),
      lastActivity: new Date(Date.now() - 1800000),
      deploymentUrl: "https://make.com/scenario/456",
      executionCount: 892,
      successRate: 98.1,
    },
  ])

  const [showCreateModal, setShowCreateModal] = useState(false)
  const [selectedTemplate, setSelectedTemplate] = useState<DeploymentTemplate | null>(null)
  const [newAgent, setNewAgent] = useState({
    name: "",
    description: "",
    model: "mistral",
    capabilities: [] as string[],
    type: "n8n" as const,
  })

  const [showSettings, setShowSettings] = useState(false)

  const deploymentTemplates: DeploymentTemplate[] = [
    {
      id: "n8n-chat",
      name: "n8n Chat Bot",
      description: "Deploy a conversational AI agent to n8n workflows",
      type: "n8n",
      icon: Workflow,
      capabilities: ["chat", "webhook", "automation"],
      setupSteps: [
        "Create n8n workflow",
        "Add webhook trigger",
        "Configure AI model",
        "Set up response formatting",
        "Deploy and test",
      ],
    },
    {
      id: "zapier-automation",
      name: "Zapier Automation",
      description: "Integrate AI decision-making into Zapier workflows",
      type: "zapier",
      icon: Zap,
      capabilities: ["automation", "decision-making", "data-processing"],
      setupSteps: [
        "Create Zapier webhook",
        "Configure trigger conditions",
        "Set up AI processing",
        "Define output actions",
        "Activate automation",
      ],
    },
    {
      id: "make-processor",
      name: "Make.com Processor",
      description: "Deploy AI data processing to Make.com scenarios",
      type: "make",
      icon: Database,
      capabilities: ["data-processing", "analysis", "reporting"],
      setupSteps: [
        "Create Make scenario",
        "Add HTTP webhook",
        "Configure AI endpoint",
        "Set up data transformation",
        "Schedule and deploy",
      ],
    },
    {
      id: "custom-api",
      name: "Custom API Agent",
      description: "Deploy to any service via REST API",
      type: "custom",
      icon: Code,
      capabilities: ["api", "custom-integration", "flexible"],
      setupSteps: [
        "Define API endpoint",
        "Configure authentication",
        "Set up request/response format",
        "Test integration",
        "Deploy agent",
      ],
    },
  ]

  const availableModels = [
    { value: "mistral", label: "Mistral" },
    { value: "llama3", label: "Llama 3" },
    { value: "codellama", label: "Code Llama" },
    { value: "gemma", label: "Gemma" },
    { value: "phi3", label: "Phi-3" },
  ]

  const availableCapabilities = [
    "chat",
    "automation",
    "data-processing",
    "analysis",
    "reporting",
    "webhook",
    "api",
    "decision-making",
    "knowledge-base",
    "ticket-management",
    "custom-integration",
  ]

  const createAgent = async () => {
    if (!newAgent.name || !selectedTemplate) return

    const agent: AIAgent = {
      id: Date.now().toString(),
      name: newAgent.name,
      description: newAgent.description,
      type: selectedTemplate.type,
      status: "deploying",
      endpoint: "",
      model: newAgent.model,
      capabilities: newAgent.capabilities,
      createdAt: new Date(),
      lastActivity: new Date(),
      executionCount: 0,
      successRate: 0,
    }

    setAgents((prev) => [...prev, agent])
    setShowCreateModal(false)
    setSelectedTemplate(null)
    setNewAgent({
      name: "",
      description: "",
      model: "mistral",
      capabilities: [],
      type: "n8n",
    })

    // Simulate deployment
    setTimeout(() => {
      setAgents((prev) =>
        prev.map((a) =>
          a.id === agent.id
            ? {
                ...a,
                status: "active" as const,
                endpoint: `https://${selectedTemplate.type}.example.com/webhook/${agent.id}`,
                deploymentUrl: `https://${selectedTemplate.type}.example.com/workflow/${agent.id}`,
              }
            : a,
        ),
      )
    }, 3000)
  }

  const deleteAgent = async (agentId: string) => {
    setAgents((prev) => prev.filter((a) => a.id !== agentId))
  }

  const toggleAgentStatus = async (agentId: string) => {
    setAgents((prev) =>
      prev.map((agent) =>
        agent.id === agentId
          ? {
              ...agent,
              status: agent.status === "active" ? ("inactive" as const) : ("active" as const),
            }
          : agent,
      ),
    )
  }

  const getStatusColor = (status: AIAgent["status"]) => {
    switch (status) {
      case "active":
        return "border-green-500 text-green-400"
      case "inactive":
        return "border-gray-500 text-gray-400"
      case "error":
        return "border-red-500 text-red-400"
      case "deploying":
        return "border-yellow-500 text-yellow-400"
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
        return <XCircle className="w-4 h-4" />
      case "deploying":
        return <Clock className="w-4 h-4 animate-spin" />
      default:
        return <XCircle className="w-4 h-4" />
    }
  }

  const getTypeIcon = (type: AIAgent["type"]) => {
    switch (type) {
      case "n8n":
        return <Workflow className="w-4 h-4" />
      case "zapier":
        return <Zap className="w-4 h-4" />
      case "make":
        return <Database className="w-4 h-4" />
      case "custom":
        return <Code className="w-4 h-4" />
      case "webhook":
        return <Globe className="w-4 h-4" />
      default:
        return <Bot className="w-4 h-4" />
    }
  }

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
        {/* Header */}
        <motion.div
          initial={{ opacity: 0, y: -20 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center justify-between mb-8"
        >
          <div className="flex items-center space-x-4">
            <Link href="/">
              <Button variant="outline" size="sm" className="bg-gray-800 border-gray-600 text-gray-300">
                <ArrowLeft className="w-4 h-4 mr-2" />
                Dashboard
              </Button>
            </Link>
            <div className="flex items-center space-x-2">
              <Bot className="w-6 h-6 text-indigo-400" />
              <h1 className="text-3xl font-bold text-white">AI Agents</h1>
            </div>
            <Badge variant="outline" className="border-indigo-500 text-indigo-400">
              {agents.length} Deployed
            </Badge>
          </div>
          <div className="flex items-center space-x-2">
            <Button onClick={() => setShowCreateModal(true)} className="bg-indigo-600 hover:bg-indigo-700 text-white">
              <Plus className="w-4 h-4 mr-2" />
              Deploy Agent
            </Button>
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
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }}>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
            <Card className="bg-gray-900/50 backdrop-blur-sm border-indigo-500/30 p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-400">Total Agents</p>
                  <p className="text-2xl font-bold text-white">{agents.length}</p>
                </div>
                <Bot className="w-8 h-8 text-indigo-400" />
              </div>
            </Card>

            <Card className="bg-gray-900/50 backdrop-blur-sm border-green-500/30 p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-400">Active Agents</p>
                  <p className="text-2xl font-bold text-white">{agents.filter((a) => a.status === "active").length}</p>
                </div>
                <Activity className="w-8 h-8 text-green-400" />
              </div>
            </Card>

            <Card className="bg-gray-900/50 backdrop-blur-sm border-blue-500/30 p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-400">Total Executions</p>
                  <p className="text-2xl font-bold text-white">
                    {agents.reduce((sum, agent) => sum + agent.executionCount, 0).toLocaleString()}
                  </p>
                </div>
                <Zap className="w-8 h-8 text-blue-400" />
              </div>
            </Card>

            <Card className="bg-gray-900/50 backdrop-blur-sm border-purple-500/30 p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-400">Avg Success Rate</p>
                  <p className="text-2xl font-bold text-white">
                    {agents.length > 0
                      ? (agents.reduce((sum, agent) => sum + agent.successRate, 0) / agents.length).toFixed(1)
                      : "0"}
                    %
                  </p>
                </div>
                <CheckCircle className="w-8 h-8 text-purple-400" />
              </div>
            </Card>
          </div>
        </motion.div>

        {/* Agents Grid */}
        <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }}>
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
                          <div className="p-2 bg-indigo-600/20 rounded-lg">{getTypeIcon(agent.type)}</div>
                          <div>
                            <h3 className="text-lg font-semibold text-white">{agent.name}</h3>
                            <p className="text-sm text-gray-400 capitalize">{agent.type} Agent</p>
                          </div>
                        </div>
                        <div className="flex items-center space-x-2">
                          <Badge variant="outline" className={getStatusColor(agent.status)}>
                            {getStatusIcon(agent.status)}
                            <span className="ml-1 capitalize">{agent.status}</span>
                          </Badge>
                          <Button variant="ghost" size="sm" className="text-gray-400 hover:text-white h-8 w-8 p-0">
                            <MoreVertical className="w-4 h-4" />
                          </Button>
                        </div>
                      </div>

                      {/* Agent Description */}
                      <p className="text-sm text-gray-300 mb-4">{agent.description}</p>

                      {/* Agent Stats */}
                      <div className="grid grid-cols-2 gap-4 mb-4">
                        <div className="bg-gray-800/50 rounded-lg p-3">
                          <p className="text-xs text-gray-400">Executions</p>
                          <p className="text-lg font-semibold text-white">{agent.executionCount.toLocaleString()}</p>
                        </div>
                        <div className="bg-gray-800/50 rounded-lg p-3">
                          <p className="text-xs text-gray-400">Success Rate</p>
                          <p className="text-lg font-semibold text-white">{agent.successRate}%</p>
                        </div>
                      </div>

                      {/* Capabilities */}
                      <div className="mb-4">
                        <p className="text-xs text-gray-400 mb-2">Capabilities</p>
                        <div className="flex flex-wrap gap-1">
                          {agent.capabilities.slice(0, 3).map((capability) => (
                            <Badge key={capability} variant="outline" className="text-xs border-gray-600 text-gray-300">
                              {capability}
                            </Badge>
                          ))}
                          {agent.capabilities.length > 3 && (
                            <Badge variant="outline" className="text-xs border-gray-600 text-gray-300">
                              +{agent.capabilities.length - 3}
                            </Badge>
                          )}
                        </div>
                      </div>

                      {/* Agent Actions */}
                      <div className="flex space-x-2">
                        <Button
                          onClick={() => toggleAgentStatus(agent.id)}
                          disabled={agent.status === "deploying"}
                          size="sm"
                          className={`flex-1 ${
                            agent.status === "active"
                              ? "bg-red-600 hover:bg-red-700"
                              : "bg-green-600 hover:bg-green-700"
                          } text-white`}
                        >
                          {agent.status === "active" ? (
                            <>
                              <Square className="w-3 h-3 mr-1" />
                              Stop
                            </>
                          ) : (
                            <>
                              <Play className="w-3 h-3 mr-1" />
                              Start
                            </>
                          )}
                        </Button>
                        {agent.deploymentUrl && (
                          <Button
                            onClick={() => window.open(agent.deploymentUrl, "_blank")}
                            size="sm"
                            variant="outline"
                            className="bg-gray-800 border-gray-600 text-gray-300"
                          >
                            <ExternalLink className="w-3 h-3" />
                          </Button>
                        )}
                        <Button
                          onClick={() => deleteAgent(agent.id)}
                          size="sm"
                          variant="outline"
                          className="bg-gray-800 border-gray-600 text-gray-300 hover:text-red-400 hover:border-red-400"
                        >
                          <Trash2 className="w-3 h-3" />
                        </Button>
                      </div>

                      {/* Last Activity */}
                      <div className="mt-4 pt-4 border-t border-gray-700">
                        <p className="text-xs text-gray-400">Last activity: {agent.lastActivity.toLocaleString()}</p>
                      </div>
                    </div>
                  </Card>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        </motion.div>

        {/* Create Agent Modal */}
        <AnimatePresence>
          {showCreateModal && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
              onClick={() => setShowCreateModal(false)}
            >
              <motion.div
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.9, opacity: 0 }}
                className="bg-gray-900 rounded-lg border border-indigo-500/30 max-w-4xl w-full max-h-[90vh] overflow-hidden"
                onClick={(e) => e.stopPropagation()}
              >
                <div className="p-6 border-b border-indigo-500/30">
                  <h2 className="text-2xl font-bold text-white">Deploy New AI Agent</h2>
                  <p className="text-gray-400">Choose a deployment template and configure your agent</p>
                </div>

                <div className="p-6 overflow-y-auto max-h-[calc(90vh-200px)]">
                  {!selectedTemplate ? (
                    <div>
                      <h3 className="text-lg font-semibold text-white mb-4">Select Deployment Template</h3>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {deploymentTemplates.map((template) => (
                          <Card
                            key={template.id}
                            className="bg-gray-800/50 border-gray-600 cursor-pointer hover:border-indigo-500/50 transition-colors"
                            onClick={() => setSelectedTemplate(template)}
                          >
                            <div className="p-4">
                              <div className="flex items-center space-x-3 mb-3">
                                <div className="p-2 bg-indigo-600/20 rounded-lg">
                                  <template.icon className="w-5 h-5 text-indigo-400" />
                                </div>
                                <div>
                                  <h4 className="text-lg font-semibold text-white">{template.name}</h4>
                                  <p className="text-sm text-gray-400 capitalize">{template.type}</p>
                                </div>
                              </div>
                              <p className="text-sm text-gray-300 mb-3">{template.description}</p>
                              <div className="flex flex-wrap gap-1">
                                {template.capabilities.map((capability) => (
                                  <Badge
                                    key={capability}
                                    variant="outline"
                                    className="text-xs border-gray-600 text-gray-300"
                                  >
                                    {capability}
                                  </Badge>
                                ))}
                              </div>
                            </div>
                          </Card>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div>
                      <div className="flex items-center justify-between mb-6">
                        <div className="flex items-center space-x-3">
                          <div className="p-2 bg-indigo-600/20 rounded-lg">
                            <selectedTemplate.icon className="w-5 h-5 text-indigo-400" />
                          </div>
                          <div>
                            <h3 className="text-lg font-semibold text-white">{selectedTemplate.name}</h3>
                            <p className="text-sm text-gray-400">{selectedTemplate.description}</p>
                          </div>
                        </div>
                        <Button
                          onClick={() => setSelectedTemplate(null)}
                          variant="outline"
                          size="sm"
                          className="bg-gray-800 border-gray-600 text-gray-300"
                        >
                          Back
                        </Button>
                      </div>

                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                        {/* Configuration Form */}
                        <div className="space-y-4">
                          <div>
                            <label className="block text-sm font-medium text-gray-300 mb-2">Agent Name</label>
                            <Input
                              value={newAgent.name}
                              onChange={(e) => setNewAgent((prev) => ({ ...prev, name: e.target.value }))}
                              placeholder="Enter agent name"
                              className="bg-gray-800 border-gray-600 text-white"
                            />
                          </div>

                          <div>
                            <label className="block text-sm font-medium text-gray-300 mb-2">Description</label>
                            <Textarea
                              value={newAgent.description}
                              onChange={(e) => setNewAgent((prev) => ({ ...prev, description: e.target.value }))}
                              placeholder="Describe what this agent does"
                              className="bg-gray-800 border border-gray-600 text-white"
                              rows={3}
                            />
                          </div>

                          <div>
                            <label className="block text-sm font-medium text-gray-300 mb-2">AI Model</label>
                            <select
                              value={newAgent.model}
                              onChange={(e) => setNewAgent((prev) => ({ ...prev, model: e.target.value }))}
                              className="w-full bg-gray-800 border border-gray-600 text-white rounded px-3 py-2 focus:border-indigo-500 focus:outline-none"
                            >
                              {availableModels.map((model) => (
                                <option key={model.value} value={model.value}>
                                  {model.label}
                                </option>
                              ))}
                            </select>
                          </div>

                          <div>
                            <label className="block text-sm font-medium text-gray-300 mb-2">Capabilities</label>
                            <div className="grid grid-cols-2 gap-2">
                              {availableCapabilities.map((capability) => (
                                <label key={capability} className="flex items-center space-x-2">
                                  <input
                                    type="checkbox"
                                    checked={newAgent.capabilities.includes(capability)}
                                    onChange={(e) => {
                                      if (e.target.checked) {
                                        setNewAgent((prev) => ({
                                          ...prev,
                                          capabilities: [...prev.capabilities, capability],
                                        }))
                                      } else {
                                        setNewAgent((prev) => ({
                                          ...prev,
                                          capabilities: prev.capabilities.filter((c) => c !== capability),
                                        }))
                                      }
                                    }}
                                    className="rounded border-gray-600 bg-gray-800 text-indigo-600"
                                  />
                                  <span className="text-sm text-gray-300">{capability}</span>
                                </label>
                              ))}
                            </div>
                          </div>
                        </div>

                        {/* Setup Steps */}
                        <div>
                          <h4 className="text-lg font-semibold text-white mb-4">Setup Steps</h4>
                          <div className="space-y-3">
                            {selectedTemplate.setupSteps.map((step, index) => (
                              <div key={index} className="flex items-center space-x-3">
                                <div className="w-6 h-6 bg-indigo-600 rounded-full flex items-center justify-center text-white text-sm font-medium">
                                  {index + 1}
                                </div>
                                <p className="text-sm text-gray-300">{step}</p>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                <div className="p-6 border-t border-indigo-500/30 flex justify-end space-x-3">
                  <Button
                    onClick={() => setShowCreateModal(false)}
                    variant="outline"
                    className="bg-gray-800 border-gray-600 text-gray-300"
                  >
                    Cancel
                  </Button>
                  {selectedTemplate && (
                    <Button
                      onClick={createAgent}
                      disabled={!newAgent.name}
                      className="bg-indigo-600 hover:bg-indigo-700 text-white"
                    >
                      Deploy Agent
                    </Button>
                  )}
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Settings Modal */}
      <SettingsModal isOpen={showSettings} onClose={() => setShowSettings(false)} context="agent" />
      </div>
    </div>
  )
}
