"use client"

import React, { useEffect } from "react"

import { useState } from "react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useUser } from "@/lib/auth/UserProvider"
import {
  User,
  Mail,
  Key,
  Bell,
  Shield,
  Sparkles,
  ArrowLeft,
  Moon,
  Volume2,
  Mic,
  Globe,
  Trash2,
  Download,
  LogOut,
  ChevronRight,
  Check,
  Cloud,
  Eye,
  EyeOff,
  Save,
  AlertCircle,
  Zap,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Separator } from "@/components/ui/separator"
import { Alert, AlertDescription } from "@/components/ui/alert"

export default function ProfilePage() {
  const router = useRouter()
  const { user, logout, isLoading } = useUser()

  useEffect(() => {
    if (!isLoading && !user) {
      router.push("/login")
    }
  }, [user, isLoading, router])

  const [profile, setProfile] = useState({
    name: "",
    email: "",
  })

  // Update profile state when user data is loaded
  useEffect(() => {
    if (user) {
      setProfile({
        name: user.name || "",
        email: user.email || "",
      })
    }
  }, [user])

  const [settings, setSettings] = useState({
    darkMode: true,
    soundEffects: true,
    voiceInput: true,
    notifications: true,
    emailUpdates: false,
  })

  // API Keys State
  const [apiKeys, setApiKeys] = useState<{[key: string]: {apiKey: string; apiUrl: string; isActive: boolean}}>({
    moonshot: { apiKey: "", apiUrl: "", isActive: false }
  })
  const [showApiKey, setShowApiKey] = useState<{[key: string]: boolean}>({
    moonshot: false
  })
  const [apiKeyLoading, setApiKeyLoading] = useState(false)
  const [apiKeyMessage, setApiKeyMessage] = useState<{type: "success" | "error"; text: string} | null>(null)

  // Load API keys on mount
  useEffect(() => {
    if (user) {
      loadApiKeys()
    }
  }, [user])

  const loadApiKeys = async () => {
    try {
      const token = localStorage.getItem('token')
      const response = await fetch('/api/user/api-keys', {
        headers: {
          'Authorization': `Bearer ${token}`
        }
      })
      
      if (response.ok) {
        const data = await response.json()
        const keysMap: {[key: string]: {apiKey: string; apiUrl: string; isActive: boolean}} = {
          moonshot: { apiKey: "", apiUrl: "", isActive: false }
        }
        
        data.forEach((key: any) => {
          keysMap[key.provider_name] = {
            apiKey: "••••••••••••••••", // Don't show actual key
            apiUrl: key.api_url || "",
            isActive: key.is_active
          }
        })
        
        setApiKeys(keysMap)
      }
    } catch (error) {
      console.error('Error loading API keys:', error)
    }
  }

  const saveApiKey = async (provider: string) => {
    setApiKeyLoading(true)
    setApiKeyMessage(null)
    
    // DEBUG: Log what we're about to send
    const keyToSend = apiKeys[provider].apiKey
    console.log(`[DEBUG] Saving ${provider} API key:`, {
      length: keyToSend?.length || 0,
      preview: keyToSend ? `${keyToSend.substring(0, 8)}...${keyToSend.substring(keyToSend.length - 4)}` : 'EMPTY'
    })
    
    try {
      const token = localStorage.getItem('token')
      const response = await fetch('/api/user/api-keys', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          provider_name: provider,
          api_key: apiKeys[provider].apiKey,
          api_url: apiKeys[provider].apiUrl || undefined,
          is_active: true
        })
      })
      
      if (response.ok) {
        setApiKeyMessage({ type: "success", text: `${provider} API key saved successfully!` })
        // Reload to get updated status
        loadApiKeys()
        // Clear the input
        setApiKeys(prev => ({
          ...prev,
          [provider]: { ...prev[provider], apiKey: "" }
        }))
      } else {
        const error = await response.json()
        setApiKeyMessage({ type: "error", text: error.detail || 'Failed to save API key' })
      }
    } catch (error) {
      setApiKeyMessage({ type: "error", text: 'Network error while saving API key' })
    } finally {
      setApiKeyLoading(false)
    }
  }

  const deleteApiKey = async (provider: string) => {
    if (!confirm(`Are you sure you want to remove your ${provider} API key?`)) return
    
    try {
      const token = localStorage.getItem('token')
      const response = await fetch(`/api/user/api-keys/${provider}`, {
        method: 'DELETE',
        headers: {
          'Authorization': `Bearer ${token}`
        }
      })
      
      if (response.ok) {
        setApiKeyMessage({ type: "success", text: `${provider} API key removed` })
        setApiKeys(prev => ({
          ...prev,
          [provider]: { apiKey: "", apiUrl: "", isActive: false }
        }))
      }
    } catch (error) {
      setApiKeyMessage({ type: "error", text: 'Failed to remove API key' })
    }
  }

  const toggleSetting = (key: keyof typeof settings) => {
    setSettings((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  const handleLogout = () => {
    logout()
    router.push("/login")
  }

  if (isLoading || !user) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <Sparkles className="h-10 w-10 animate-pulse text-primary" />
          <p className="text-muted-foreground">Loading profile...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur-sm">
        <div className="mx-auto flex h-16 max-w-4xl items-center gap-4 px-4">
          <Link href="/">
            <Button variant="ghost" size="icon" className="shrink-0">
              <ArrowLeft className="h-5 w-5" />
            </Button>
          </Link>
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary">
              <Sparkles className="h-4 w-4 text-primary-foreground" />
            </div>
            <span className="text-lg font-semibold">Harvis</span>
          </div>
          <span className="text-muted-foreground">/</span>
          <span className="text-foreground">Profile</span>
        </div>
      </header>

      {/* Main Content */}
      <main className="mx-auto max-w-4xl px-4 py-8">
        <div className="space-y-8">
          {/* Profile Card */}
          <Card className="border-border bg-card">
            <CardHeader>
              <CardTitle className="text-foreground">Profile</CardTitle>
              <CardDescription>Manage your account information</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="flex items-center gap-6">
                <Avatar className="h-20 w-20 ring-4 ring-primary/20">
                  <AvatarFallback className="bg-primary/20 text-primary text-2xl font-semibold">
                    {profile.name ? profile.name.split(" ").map((n) => n[0]).join("") : "U"}
                  </AvatarFallback>
                </Avatar>
                <div className="space-y-1">
                  <h2 className="text-xl font-semibold text-foreground">{profile.name}</h2>
                  <p className="text-muted-foreground">{profile.email}</p>
                  <div className="flex items-center gap-2">
                    <span className="inline-flex items-center gap-1 rounded-full bg-primary/20 px-2.5 py-0.5 text-xs font-medium text-primary">
                      Local User
                    </span>
                  </div>
                </div>
              </div>

              <Separator className="bg-border" />

              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">Full Name</label>
                  <div className="relative">
                    <User className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      value={profile.name}
                      onChange={(e) => setProfile((p) => ({ ...p, name: e.target.value }))}
                      className="pl-9 bg-input border-border"
                    />
                  </div>
                </div>
                <div className="space-y-2">
                  <label className="text-sm font-medium text-foreground">Email</label>
                  <div className="relative">
                    <Mail className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      value={profile.email}
                      disabled
                      className="pl-9 bg-input border-border opacity-70"
                    />
                  </div>
                </div>
              </div>

              <Button className="bg-primary text-primary-foreground hover:bg-primary/90">
                <Check className="mr-2 h-4 w-4" />
                Save Changes
              </Button>
            </CardContent>
          </Card>


          {/* Preferences Card */}
          <Card className="border-border bg-card">
            <CardHeader>
              <CardTitle className="text-foreground">Preferences</CardTitle>
              <CardDescription>Customize your Harvis experience</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <SettingRow
                icon={<Moon className="h-5 w-5" />}
                title="Dark Mode"
                description="Always use dark theme"
                checked={settings.darkMode}
                onToggle={() => toggleSetting("darkMode")}
              />
              <SettingRow
                icon={<Volume2 className="h-5 w-5" />}
                title="Sound Effects"
                description="Play sounds for messages and notifications"
                checked={settings.soundEffects}
                onToggle={() => toggleSetting("soundEffects")}
              />
              <SettingRow
                icon={<Mic className="h-5 w-5" />}
                title="Voice Input"
                description="Enable voice commands and dictation"
                checked={settings.voiceInput}
                onToggle={() => toggleSetting("voiceInput")}
              />
              <SettingRow
                icon={<Bell className="h-5 w-5" />}
                title="Push Notifications"
                description="Receive notifications for new messages"
                checked={settings.notifications}
                onToggle={() => toggleSetting("notifications")}
              />
              <SettingRow
                icon={<Mail className="h-5 w-5" />}
                title="Email Updates"
                description="Receive product updates and tips via email"
                checked={settings.emailUpdates}
                onToggle={() => toggleSetting("emailUpdates")}
              />
            </CardContent>
          </Card>

          {/* API Keys Card */}
          <Card className="border-border bg-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-foreground">
                <Zap className="h-5 w-5 text-yellow-500" />
                API Keys
              </CardTitle>
              <CardDescription>Configure external AI provider API keys</CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {apiKeyMessage && (
                <Alert className={apiKeyMessage.type === "success" ? "bg-green-500/10 border-green-500/20" : "bg-red-500/10 border-red-500/20"}>
                  <AlertCircle className={`h-4 w-4 ${apiKeyMessage.type === "success" ? "text-green-500" : "text-red-500"}`} />
                  <AlertDescription className={apiKeyMessage.type === "success" ? "text-green-400" : "text-red-400"}>
                    {apiKeyMessage.text}
                  </AlertDescription>
                </Alert>
              )}

              {/* Moonshot API Key Section */}
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-purple-500/10 text-purple-500">
                      <Cloud className="h-5 w-5" />
                    </div>
                    <div>
                      <p className="font-medium text-foreground">Moonshot AI (Kimi)</p>
                      <p className="text-sm text-muted-foreground">
                        Access Kimi K2.5 and other Moonshot models
                      </p>
                    </div>
                  </div>
                  {apiKeys.moonshot.isActive && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-green-500/10 px-2.5 py-0.5 text-xs font-medium text-green-400">
                      <Check className="h-3 w-3" />
                      Active
                    </span>
                  )}
                </div>

                <div className="space-y-3 rounded-lg border border-border bg-input/30 p-4">
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-foreground">API Key</label>
                    <div className="relative">
                      <Key className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                      <Input
                        type={showApiKey.moonshot ? "text" : "password"}
                        placeholder={apiKeys.moonshot.isActive ? "••••••••••••••••" : "Enter your Moonshot API key"}
                        value={apiKeys.moonshot.apiKey}
                        onChange={(e) => setApiKeys(prev => ({
                          ...prev,
                          moonshot: { ...prev.moonshot, apiKey: e.target.value }
                        }))}
                        className="pl-9 pr-10 bg-input border-border"
                      />
                      <button
                        type="button"
                        onClick={() => setShowApiKey(prev => ({ ...prev, moonshot: !prev.moonshot }))}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                      >
                        {showApiKey.moonshot ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </button>
                    </div>
                  </div>

                  <div className="space-y-2">
                    <label className="text-sm font-medium text-foreground">API URL (Optional)</label>
                    <div className="relative">
                      <Globe className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                      <Input
                        placeholder="https://api.moonshot.cn/v1"
                        value={apiKeys.moonshot.apiUrl}
                        onChange={(e) => setApiKeys(prev => ({
                          ...prev,
                          moonshot: { ...prev.moonshot, apiUrl: e.target.value }
                        }))}
                        className="pl-9 bg-input border-border"
                      />
                    </div>
                    <p className="text-xs text-muted-foreground">
                      Leave empty to use the default Moonshot API endpoint
                    </p>
                  </div>

                  <div className="flex gap-2">
                    <Button
                      onClick={() => saveApiKey('moonshot')}
                      disabled={apiKeyLoading || !apiKeys.moonshot.apiKey}
                      className="bg-primary text-primary-foreground hover:bg-primary/90"
                    >
                      <Save className="mr-2 h-4 w-4" />
                      {apiKeyLoading ? 'Saving...' : 'Save Key'}
                    </Button>
                    {apiKeys.moonshot.isActive && (
                      <Button
                        variant="outline"
                        onClick={() => deleteApiKey('moonshot')}
                        className="border-destructive text-destructive hover:bg-destructive/10"
                      >
                        <Trash2 className="mr-2 h-4 w-4" />
                        Remove
                      </Button>
                    )}
                  </div>
                </div>

                <p className="text-xs text-muted-foreground">
                  Your API key is encrypted and stored securely. Get your API key from{' '}
                  <a
                    href="https://platform.moonshot.cn/"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                  >
                    Moonshot Platform
                  </a>
                </p>
              </div>
            </CardContent>
          </Card>

          {/* Security Card */}
          <Card className="border-border bg-card">
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-foreground">
                <Shield className="h-5 w-5 text-primary" />
                Security
              </CardTitle>
              <CardDescription>Keep your account secure</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <ActionRow
                icon={<Key className="h-5 w-5" />}
                title="Change Password"
                description="Update your password regularly for security"
              />
              <ActionRow
                icon={<Shield className="h-5 w-5" />}
                title="Two-Factor Authentication"
                description="Add an extra layer of security"
                badge="Recommended"
              />
              <ActionRow
                icon={<Globe className="h-5 w-5" />}
                title="Active Sessions"
                description="Manage devices where you're logged in"
              />
            </CardContent>
          </Card>

          {/* Data & Privacy Card */}
          <Card className="border-border bg-card">
            <CardHeader>
              <CardTitle className="text-foreground">Data & Privacy</CardTitle>
              <CardDescription>Control your data and privacy settings</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <ActionRow
                icon={<Download className="h-5 w-5" />}
                title="Export Data"
                description="Download a copy of your chat history and data"
              />
              <ActionRow
                icon={<Trash2 className="h-5 w-5 text-destructive" />}
                title="Delete All Chats"
                description="Permanently delete your chat history"
                destructive
              />
              <ActionRow
                icon={<LogOut className="h-5 w-5 text-destructive" />}
                title="Log Out"
                description="Sign out of your account"
                destructive
                onClick={handleLogout}
              />
            </CardContent>
          </Card>
        </div>
      </main>
    </div>
  )
}

function SettingRow({
  icon,
  title,
  description,
  checked,
  onToggle,
}: {
  icon: React.ReactNode
  title: string
  description: string
  checked: boolean
  onToggle: () => void
}) {
  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-border bg-input/50 p-4">
      <div className="flex items-center gap-4">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
          {icon}
        </div>
        <div>
          <p className="font-medium text-foreground">{title}</p>
          <p className="text-sm text-muted-foreground">{description}</p>
        </div>
      </div>
      <Switch checked={checked} onCheckedChange={onToggle} />
    </div>
  )
}

function ActionRow({
  icon,
  title,
  description,
  badge,
  destructive,
  onClick,
}: {
  icon: React.ReactNode
  title: string
  description: string
  badge?: string
  destructive?: boolean
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center justify-between gap-4 rounded-lg border border-border bg-input/50 p-4 text-left transition-colors hover:bg-sidebar-accent"
    >
      <div className="flex items-center gap-4">
        <div
          className={`flex h-10 w-10 items-center justify-center rounded-lg ${destructive ? "bg-destructive/10 text-destructive" : "bg-primary/10 text-primary"
            }`}
        >
          {icon}
        </div>
        <div>
          <div className="flex items-center gap-2">
            <p className={`font-medium ${destructive ? "text-destructive" : "text-foreground"}`}>{title}</p>
            {badge && (
              <span className="rounded-full bg-primary/20 px-2 py-0.5 text-[10px] font-medium text-primary">
                {badge}
              </span>
            )}
          </div>
          <p className="text-sm text-muted-foreground">{description}</p>
        </div>
      </div>
      <ChevronRight className="h-5 w-5 text-muted-foreground" />
    </button>
  )
}
