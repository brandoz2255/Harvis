/* -------------------------------------------------------------------------- */
/* components/SettingsModal.tsx – dark-themed modal (screenshot accurate)     */
/* -------------------------------------------------------------------------- */

"use client"

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogClose,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui/select"
import clsx from "clsx"
import { FC, Fragment, useState, useEffect } from "react"
import {
  User,
  BrainCircuit,
  Palette,
  Bell,
  Shield,
  Mic,
  Monitor,
  Globe,
  Download,
  Upload,
  Undo2,
  Key,
  Eye,
  EyeOff,
  Plus,
  Trash2,
  CheckCircle,
  XCircle,
} from "lucide-react"

/* -------------------------------- Props ---------------------------------- */

interface SettingsModalProps {
  isOpen: boolean
  onClose: () => void
  context?: "dashboard" | "agent" | "global"
}

interface ApiKey {
  id: number
  provider_name: string
  api_url?: string
  is_active: boolean
  has_key: boolean
  created_at: string
  updated_at: string
}

interface Provider {
  name: string
  label: string
  description: string
  requiresUrl: boolean
  defaultUrl?: string
  icon: React.ElementType
}

interface OllamaSettings {
  cloud_url: string
  local_url: string
  api_key: string
  preferred_endpoint: 'cloud' | 'local' | 'auto'
}

interface ConnectionTest {
  status: 'success' | 'error'
  model_count?: number
  models?: string[]
  message?: string
}

/* ------------------------- Sidebar configuration ------------------------- */

type SectionId =
  | "general"
  | "models"
  | "ollama"
  | "appearance"
  | "notifications"
  | "security"
  | "voice"
  | "screen"
  | "research"

const sections: { id: SectionId; label: string; icon: React.ElementType }[] = [
  { id: "general", label: "General", icon: User },
  { id: "models", label: "AI Models", icon: BrainCircuit },
  { id: "ollama", label: "Ollama Settings", icon: Globe },
  { id: "appearance", label: "Appearance", icon: Palette },
  { id: "notifications", label: "Notifications", icon: Bell },
  { id: "security", label: "Security", icon: Shield },
  { id: "voice", label: "Voice", icon: Mic },
  { id: "screen", label: "Screen", icon: Monitor },
  { id: "research", label: "Research", icon: Globe },
]

const AI_PROVIDERS: Provider[] = [
  {
    name: "ollama",
    label: "Ollama",
    description: "Local AI models with Ollama",
    requiresUrl: true,
    defaultUrl: "http://localhost:11434",
    icon: BrainCircuit,
  },
  {
    name: "gemini",
    label: "Google Gemini",
    description: "Google's Gemini AI models",
    requiresUrl: false,
    icon: Globe,
  },
  {
    name: "openai",
    label: "OpenAI",
    description: "GPT models from OpenAI",
    requiresUrl: false,
    icon: BrainCircuit,
  },
  {
    name: "anthropic",
    label: "Anthropic",
    description: "Claude models from Anthropic",
    requiresUrl: false,
    icon: User,
  },
  {
    name: "huggingface",
    label: "Hugging Face",
    description: "Models from Hugging Face Hub",
    requiresUrl: true,
    defaultUrl: "https://api-inference.huggingface.co",
    icon: BrainCircuit,
  },
]

/* -------------------------------- Styles --------------------------------- */
/* Tailwind colors used:
   - Dark navy panels:      #0F172A  (slate-900)
   - Slightly lighter bg:   #111827  (slate-800)
   - Border lines:          #1E293B  (slate-700)
   - Text main:             slate-100
   - Muted text:            slate-400
   - Accent blue (active):  #2563EB  (blue-600)
*/

const WRAP_BG   = "bg-[#0F172A] text-slate-100"
const PANEL_BG  = "bg-[#111827]"
const BORDER    = "border border-[#1E293B]"
const SIDEBAR_BG= "bg-[#111827]"

/* ------------------------------ Component --------------------------------- */

const SettingsModal: FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  context = "dashboard",
}) => {
  /* ------------------------- Example state -------------------------- */
  const [activeSection, setActiveSection] = useState<SectionId>("general")

  const [name, setName]       = useState("User")
  const [email, setEmail]     = useState("user@example.com")
  const [timezone, setTZ]     = useState("UTC")
  const [language, setLang]   = useState("en")

  // API Keys state
  const [apiKeys, setApiKeys] = useState<ApiKey[]>([])
  const [loading, setLoading] = useState(false)
  const [showApiKey, setShowApiKey] = useState<{ [provider: string]: boolean }>({})
  const [newApiKey, setNewApiKey] = useState<{ [provider: string]: string }>({})
  const [newApiUrl, setNewApiUrl] = useState<{ [provider: string]: string }>({})
  const [saving, setSaving] = useState<{ [provider: string]: boolean }>({})

  // Ollama settings state
  const [ollamaSettings, setOllamaSettings] = useState<OllamaSettings>({
    cloud_url: '',
    local_url: '',
    api_key: '',
    preferred_endpoint: 'auto'
  })
  const [ollamaLoading, setOllamaLoading] = useState(false)
  const [ollamaSaving, setOllamaSaving] = useState(false)
  const [connectionTest, setConnectionTest] = useState<{cloud: ConnectionTest | null, local: ConnectionTest | null}>({
    cloud: null,
    local: null
  })
  const [testing, setTesting] = useState(false)
  // Load API keys when modal opens
  useEffect(() => {
    if (isOpen && activeSection === "models") {
      loadApiKeys()
    }
  }, [isOpen, activeSection])

  // Load Ollama settings when modal opens
  useEffect(() => {
    if (isOpen && activeSection === "ollama") {
      loadOllamaSettings()
    }
  }, [isOpen, activeSection])
  const loadApiKeys = async () => {
    setLoading(true)
    try {
      const token = localStorage.getItem('token')
      if (!token) return

      const response = await fetch('/api/user-api-keys', {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        setApiKeys(data.api_keys || [])
        
        // Initialize default URLs for providers that require them
        const defaultUrls: { [key: string]: string } = {}
        AI_PROVIDERS.forEach(provider => {
          if (provider.requiresUrl && provider.defaultUrl) {
            defaultUrls[provider.name] = provider.defaultUrl
          }
        })
        setNewApiUrl(defaultUrls)
      }
    } catch (error) {
      console.error('Error loading API keys:', error)
    } finally {
      setLoading(false)
    }
  }

  const saveApiKey = async (provider: string) => {
    const apiKey = newApiKey[provider]
    if (!apiKey?.trim()) return

    setSaving(prev => ({ ...prev, [provider]: true }))
    try {
      const token = localStorage.getItem('token')
      if (!token) return

      const providerConfig = AI_PROVIDERS.find(p => p.name === provider)
      const payload: any = {
        provider_name: provider,
        api_key: apiKey,
      }

      if (providerConfig?.requiresUrl) {
        payload.api_url = newApiUrl[provider] || providerConfig.defaultUrl
      }

      const response = await fetch('/api/user-api-keys', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      })

      if (response.ok) {
        const data = await response.json()
        // Update the API keys list
        setApiKeys(prev => {
          const existing = prev.find(k => k.provider_name === provider)
          if (existing) {
            return prev.map(k => k.provider_name === provider ? data.api_key : k)
          } else {
            return [...prev, data.api_key]
          }
        })
        
        // Clear the input
        setNewApiKey(prev => ({ ...prev, [provider]: '' }))
        setShowApiKey(prev => ({ ...prev, [provider]: false }))
      }
    } catch (error) {
      console.error('Error saving API key:', error)
    } finally {
      setSaving(prev => ({ ...prev, [provider]: false }))
    }
  }

  const deleteApiKey = async (provider: string) => {
    if (!confirm(`Are you sure you want to delete the ${provider} API key?`)) return

    try {
      const token = localStorage.getItem('token')
      if (!token) return

      const response = await fetch(`/api/user-api-keys?provider=${provider}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      })

      if (response.ok) {
        setApiKeys(prev => prev.filter(k => k.provider_name !== provider))
      }
    } catch (error) {
      console.error('Error deleting API key:', error)
    }
  }

  const toggleApiKeyStatus = async (provider: string, isActive: boolean) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) return

      const response = await fetch('/api/user-api-keys', {
        method: 'PATCH',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          provider_name: provider,
          is_active: isActive,
        }),
      })

      if (response.ok) {
        const data = await response.json()
        setApiKeys(prev => prev.map(k => 
          k.provider_name === provider ? data.api_key : k
        ))
      }
    } catch (error) {
      console.error('Error updating API key status:', error)
    }
  }

  // Ollama settings functions
  const loadOllamaSettings = async () => {
    setOllamaLoading(true)
    try {
      const token = localStorage.getItem('token')
      if (!token) return

      const response = await fetch('/api/user/ollama-settings', {
        headers: {
          'Authorization': `Bearer ${token}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        setOllamaSettings(data)
      }
    } catch (error) {
      console.error('Error loading Ollama settings:', error)
    } finally {
      setOllamaLoading(false)
    }
  }

  const saveOllamaSettings = async () => {
    setOllamaSaving(true)
    try {
      const token = localStorage.getItem('token')
      if (!token) return

      const response = await fetch('/api/user/ollama-settings', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(ollamaSettings),
      })

      if (response.ok) {
        const data = await response.json()
        console.log('Ollama settings saved:', data)
      }
    } catch (error) {
      console.error('Error saving Ollama settings:', error)
    } finally {
      setOllamaSaving(false)
    }
  }

  const testOllamaConnection = async () => {
    setTesting(true)
    setConnectionTest({ cloud: null, local: null })
    
    try {
      const token = localStorage.getItem('token')
      if (!token) return

      const response = await fetch('/api/user/ollama-test-connection', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(ollamaSettings),
      })

      if (response.ok) {
        const data = await response.json()
        setConnectionTest(data)
      }
    } catch (error) {
      console.error('Error testing Ollama connection:', error)
    } finally {
      setTesting(false)
    }
  }
  const resetDefaults = () => {
    setName("User")
    setEmail("user@example.com")
    setTZ("UTC")
    setLang("en")
  }

  const save = () => {
    // TODO: API / localStorage
    onClose()
  }

  /* --------------------- Section renderer -------------------------- */
  const renderSection = () => {
    if (activeSection === "models") {
      return (
        <Fragment>
          <h3 className="text-xl font-semibold mb-6">AI Models & API Keys</h3>
          <p className="text-slate-400 mb-6">
            Manage your API keys for different AI providers. Keys are encrypted and stored securely.
          </p>

          {loading ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
            </div>
          ) : (
            <div className="space-y-6">
              {AI_PROVIDERS.map(provider => {
                const existingKey = apiKeys.find(k => k.provider_name === provider.name)
                const Icon = provider.icon
                
                return (
                  <div
                    key={provider.name}
                    className={`${PANEL_BG} ${BORDER} rounded-lg p-6`}
                  >
                    <div className="flex items-start justify-between mb-4">
                      <div className="flex items-center space-x-3">
                        <div className="p-2 bg-blue-600/20 rounded-lg">
                          <Icon className="w-5 h-5 text-blue-400" />
                        </div>
                        <div>
                          <h4 className="font-semibold text-lg">{provider.label}</h4>
                          <p className="text-sm text-slate-400">{provider.description}</p>
                        </div>
                      </div>
                      
                      {existingKey && (
                        <div className="flex items-center space-x-2">
                          <button
                            onClick={() => toggleApiKeyStatus(provider.name, !existingKey.is_active)}
                            className={`p-1 rounded ${
                              existingKey.is_active 
                                ? 'text-green-400 hover:text-green-300' 
                                : 'text-gray-400 hover:text-gray-300'
                            }`}
                            title={existingKey.is_active ? 'Disable' : 'Enable'}
                          >
                            {existingKey.is_active ? <CheckCircle className="w-5 h-5" /> : <XCircle className="w-5 h-5" />}
                          </button>
                          <button
                            onClick={() => deleteApiKey(provider.name)}
                            className="p-1 text-red-400 hover:text-red-300"
                            title="Delete API Key"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </div>
                      )}
                    </div>

                    {existingKey ? (
                      <div className="space-y-3">
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-slate-300">
                            Status: {existingKey.is_active ? (
                              <span className="text-green-400">Active</span>
                            ) : (
                              <span className="text-gray-400">Inactive</span>
                            )}
                          </span>
                          <span className="text-slate-400">
                            Added: {new Date(existingKey.created_at).toLocaleDateString()}
                          </span>
                        </div>
                        
                        {provider.requiresUrl && existingKey.api_url && (
                          <div className="text-sm">
                            <span className="text-slate-400">URL: </span>
                            <span className="text-slate-300">{existingKey.api_url}</span>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="space-y-4">
                        {provider.requiresUrl && (
                          <div className="space-y-2">
                            <label className="text-sm font-medium">API URL</label>
                            <Input
                              value={newApiUrl[provider.name] || ''}
                              onChange={e => setNewApiUrl(prev => ({ ...prev, [provider.name]: e.target.value }))}
                              placeholder={provider.defaultUrl}
                              className={`${PANEL_BG} ${BORDER} placeholder:text-slate-500`}
                            />
                          </div>
                        )}
                        
                        <div className="space-y-2">
                          <label className="text-sm font-medium">API Key</label>
                          <div className="relative">
                            <Input
                              type={showApiKey[provider.name] ? "text" : "password"}
                              value={newApiKey[provider.name] || ''}
                              onChange={e => setNewApiKey(prev => ({ ...prev, [provider.name]: e.target.value }))}
                              placeholder="Enter your API key..."
                              className={`${PANEL_BG} ${BORDER} placeholder:text-slate-500 pr-20`}
                            />
                            <div className="absolute right-2 top-1/2 -translate-y-1/2 flex space-x-1">
                              <button
                                type="button"
                                onClick={() => setShowApiKey(prev => ({ ...prev, [provider.name]: !prev[provider.name] }))}
                                className="p-1 text-slate-400 hover:text-slate-300"
                                title={showApiKey[provider.name] ? "Hide" : "Show"}
                              >
                                {showApiKey[provider.name] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                              </button>
                              <Button
                                size="sm"
                                onClick={() => saveApiKey(provider.name)}
                                disabled={!newApiKey[provider.name]?.trim() || saving[provider.name]}
                                className="h-6 px-2 bg-blue-600 hover:bg-blue-700"
                              >
                                {saving[provider.name] ? (
                                  <div className="animate-spin rounded-full h-3 w-3 border-b border-white"></div>
                                ) : (
                                  <Plus className="w-3 h-3" />
                                )}
                              </Button>
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </Fragment>
      )
    }

    if (activeSection === "ollama") {
      return (
        <Fragment>
          <h3 className="text-xl font-semibold mb-6">Ollama Configuration</h3>
          <p className="text-slate-400 mb-6">
            Configure your Ollama endpoints for local and cloud AI models. No .env file needed!
          </p>

          {ollamaLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
            </div>
          ) : (
            <div className="space-y-6">
              {/* Cloud URL */}
              <div className="space-y-2">
                <label className="text-sm font-medium">Cloud Ollama URL</label>
                <Input
                  value={ollamaSettings.cloud_url}
                  onChange={e => setOllamaSettings(prev => ({ ...prev, cloud_url: e.target.value }))}
                  placeholder="https://your-ollama-cloud.com/ollama"
                  className={`${PANEL_BG} ${BORDER} placeholder:text-slate-500`}
                />
                <p className="text-xs text-slate-500">URL for cloud-hosted Ollama instance</p>
              </div>

              {/* Local URL */}
              <div className="space-y-2">
                <label className="text-sm font-medium">Local Ollama URL</label>
                <Input
                  value={ollamaSettings.local_url}
                  onChange={e => setOllamaSettings(prev => ({ ...prev, local_url: e.target.value }))}
                  placeholder="http://ollama:11434"
                  className={`${PANEL_BG} ${BORDER} placeholder:text-slate-500`}
                />
                <p className="text-xs text-slate-500">URL for local Ollama instance</p>
              </div>

              {/* API Key */}
              <div className="space-y-2">
                <label className="text-sm font-medium">API Key (for cloud)</label>
                <div className="relative">
                  <Input
                    type={showApiKey['ollama'] ? "text" : "password"}
                    value={ollamaSettings.api_key}
                    onChange={e => setOllamaSettings(prev => ({ ...prev, api_key: e.target.value }))}
                    placeholder="sk-your-api-key"
                    className={`${PANEL_BG} ${BORDER} placeholder:text-slate-500 pr-10`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowApiKey(prev => ({ ...prev, ollama: !prev.ollama }))}
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-slate-400 hover:text-slate-300"
                  >
                    {showApiKey['ollama'] ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                <p className="text-xs text-slate-500">API key for cloud Ollama authentication</p>
              </div>

              {/* Preferred Endpoint */}
              <div className="space-y-2">
                <label className="text-sm font-medium">Preferred Endpoint</label>
                <Select 
                  value={ollamaSettings.preferred_endpoint} 
                  onValueChange={value => setOllamaSettings(prev => ({ ...prev, preferred_endpoint: value as 'cloud' | 'local' | 'auto' }))}
                >
                  <SelectTrigger className={`${PANEL_BG} ${BORDER} text-left`}>
                    <SelectValue placeholder="Select preferred endpoint" />
                  </SelectTrigger>
                  <SelectContent className={WRAP_BG}>
                    <SelectItem value="auto">Auto (try cloud first, fallback to local)</SelectItem>
                    <SelectItem value="cloud">Cloud only</SelectItem>
                    <SelectItem value="local">Local only</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-slate-500">How to choose between cloud and local endpoints</p>
              </div>

              {/* Action buttons */}
              <div className="flex space-x-4 pt-4">
                <Button
                  onClick={saveOllamaSettings}
                  disabled={ollamaSaving}
                  className="bg-blue-600 hover:bg-blue-700"
                >
                  {ollamaSaving ? (
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white mr-2"></div>
                  ) : null}
                  Save Settings
                </Button>
                
                <Button
                  onClick={testOllamaConnection}
                  disabled={testing}
                  variant="outline"
                  className={`${BORDER} bg-[#0F172A] text-slate-300 hover:bg-[#1E293B]`}
                >
                  {testing ? (
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500 mr-2"></div>
                  ) : null}
                  Test Connection
                </Button>
              </div>

              {/* Connection test results */}
              {(connectionTest.cloud || connectionTest.local) && (
                <div className="space-y-4 pt-4 border-t border-slate-700">
                  <h4 className="font-medium">Connection Test Results</h4>
                  
                  {connectionTest.cloud && (
                    <div className={`${PANEL_BG} ${BORDER} rounded-lg p-4`}>
                      <div className="flex items-center space-x-2 mb-2">
                        <Globe className="w-4 h-4" />
                        <span className="font-medium">Cloud Endpoint</span>
                        <span className={`text-sm px-2 py-1 rounded ${
                          connectionTest.cloud.status === 'success' 
                            ? 'bg-green-600/20 text-green-400' 
                            : 'bg-red-600/20 text-red-400'
                        }`}>
                          {connectionTest.cloud.status}
                        </span>
                      </div>
                      {connectionTest.cloud.status === 'success' ? (
                        <div>
                          <p className="text-sm text-slate-300">
                            Found {connectionTest.cloud.model_count} models
                          </p>
                          {connectionTest.cloud.models && connectionTest.cloud.models.length > 0 && (
                            <p className="text-xs text-slate-500 mt-1">
                              Available: {connectionTest.cloud.models.join(', ')}
                            </p>
                          )}
                        </div>
                      ) : (
                        <p className="text-sm text-red-400">{connectionTest.cloud.message}</p>
                      )}
                    </div>
                  )}

                  {connectionTest.local && (
                    <div className={`${PANEL_BG} ${BORDER} rounded-lg p-4`}>
                      <div className="flex items-center space-x-2 mb-2">
                        <Monitor className="w-4 h-4" />
                        <span className="font-medium">Local Endpoint</span>
                        <span className={`text-sm px-2 py-1 rounded ${
                          connectionTest.local.status === 'success' 
                            ? 'bg-green-600/20 text-green-400' 
                            : 'bg-red-600/20 text-red-400'
                        }`}>
                          {connectionTest.local.status}
                        </span>
                      </div>
                      {connectionTest.local.status === 'success' ? (
                        <div>
                          <p className="text-sm text-slate-300">
                            Found {connectionTest.local.model_count} models
                          </p>
                          {connectionTest.local.models && connectionTest.local.models.length > 0 && (
                            <p className="text-xs text-slate-500 mt-1">
                              Available: {connectionTest.local.models.join(', ')}
                            </p>
                          )}
                        </div>
                      ) : (
                        <p className="text-sm text-red-400">{connectionTest.local.message}</p>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </Fragment>
      )
    }
    if (activeSection !== "general")
      return (
        <div className="flex items-center justify-center h-full text-slate-400">
          <p className="text-sm">
            {sections.find(s => s.id === activeSection)?.label} settings coming soon…
          </p>
        </div>
      )

    return (
      <Fragment>
        <h3 className="text-xl font-semibold mb-6">User Profile</h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Name */}
          <div className="flex flex-col space-y-2">
            <label htmlFor="name" className="text-sm font-medium">
              Name
            </label>
            <Input
              id="name"
              value={name}
              onChange={e => setName(e.target.value)}
              className={`${PANEL_BG} ${BORDER} placeholder:text-slate-500`}
            />
          </div>

          {/* Email */}
          <div className="flex flex-col space-y-2">
            <label htmlFor="email" className="text-sm font-medium">
              Email
            </label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              className={`${PANEL_BG} ${BORDER} placeholder:text-slate-500`}
            />
          </div>

          {/* Timezone */}
          <div className="flex flex-col space-y-2">
            <label className="text-sm font-medium">Timezone</label>
            <Select value={timezone} onValueChange={setTZ}>
              <SelectTrigger className={`${PANEL_BG} ${BORDER} text-left`}>
                <SelectValue placeholder="Select timezone" />
              </SelectTrigger>
              <SelectContent className={WRAP_BG}>
                <SelectItem value="UTC">UTC</SelectItem>
                <SelectItem value="EST">EST (GMT-5)</SelectItem>
                <SelectItem value="PST">PST (GMT-8)</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {/* Language */}
          <div className="flex flex-col space-y-2">
            <label className="text-sm font-medium">Language</label>
            <Select value={language} onValueChange={setLang}>
              <SelectTrigger className={`${PANEL_BG} ${BORDER} text-left`}>
                <SelectValue placeholder="Select language" />
              </SelectTrigger>
              <SelectContent className={WRAP_BG}>
                <SelectItem value="en">English</SelectItem>
                <SelectItem value="es">Spanish</SelectItem>
                <SelectItem value="fr">French</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </Fragment>
    )
  }

  /* ------------------------------- UI -------------------------------- */

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent
        className={clsx(
          WRAP_BG,
          BORDER,
          "w-full max-w-5xl p-0 overflow-hidden"
        )}
      >
        {/* Header */}
        <DialogHeader className="px-6 pt-6">
          <DialogTitle className="text-2xl">Settings</DialogTitle>
          <DialogDescription className="text-slate-400">
            Dashboard Configuration
          </DialogDescription>
        </DialogHeader>

        <div className="flex h-[540px] divide-x divide-[#1E293B]">
          {/* Sidebar */}
          <aside className={`${SIDEBAR_BG} w-56 border-r border-[#1E293B]`}>
            <nav className="flex flex-col p-4 space-y-1">
              {sections.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => setActiveSection(id)}
                  className={clsx(
                    "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors",
                    activeSection === id
                      ? "bg-[#2563EB] text-white"
                      : "text-slate-300 hover:bg-[#1E293B]"
                  )}
                >
                  <Icon className="w-4 h-4" />
                  <span>{label}</span>
                </button>
              ))}
            </nav>
          </aside>

          {/* Content */}
          <section className="flex-1 p-8 overflow-y-auto">{renderSection()}</section>
        </div>

        {/* Footer */}
        <div
          className={`flex items-center justify-between ${SIDEBAR_BG} border-t border-[#1E293B] px-6 py-4`}
        >
          <div className="space-x-2">
            <Button
              variant="outline"
              size="sm"
              className={`${BORDER} bg-[#0F172A] text-slate-300 hover:bg-[#1E293B]`}
            >
              <Download className="w-4 h-4 mr-1.5" />
              Export
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={`${BORDER} bg-[#0F172A] text-slate-300 hover:bg-[#1E293B]`}
            >
              <Upload className="w-4 h-4 mr-1.5" />
              Import
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={resetDefaults}
              className={`${BORDER} text-red-400 hover:bg-red-400/10`}
            >
              <Undo2 className="w-4 h-4 mr-1.5" />
              Reset
            </Button>
          </div>

          <div className="space-x-2">
            <DialogClose asChild>
              <Button
                variant="outline"
                className={`${BORDER} bg-[#0F172A] text-slate-300 hover:bg-[#1E293B]`}
                size="sm"
              >
                Cancel
              </Button>
            </DialogClose>
            <Button
              onClick={save}
              size="sm"
              className="bg-[#2563EB] hover:bg-[#1D4ED8] text-white"
            >
              Save Changes
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default SettingsModal

