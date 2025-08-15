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

/* ------------------------- Sidebar configuration ------------------------- */

type SectionId =
  | "general"
  | "models"
  | "appearance"
  | "notifications"
  | "security"
  | "voice"
  | "screen"
  | "research"

const sections: { id: SectionId; label: string; icon: React.ElementType }[] = [
  { id: "general", label: "General", icon: User },
  { id: "models", label: "AI Models", icon: BrainCircuit },
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

  // Load API keys when modal opens
  useEffect(() => {
    if (isOpen && activeSection === "models") {
      loadApiKeys()
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

