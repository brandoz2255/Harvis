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
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Separator } from "@/components/ui/separator"

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
