"use client"

import React, { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Github, LogOut } from 'lucide-react'

interface GitHubUser {
    connected: boolean
    login?: string
    name?: string
    avatar_url?: string
}

export function GitHubStatus() {
    const [status, setStatus] = useState<GitHubUser>({ connected: false })
    const [loading, setLoading] = useState(true)

    const fetchStatus = async () => {
        try {
            const response = await fetch('/api/vibecode/github/status', {
                credentials: 'include'
            })
            if (response.ok) {
                const data = await response.json()
                setStatus(data)
            } else if (response.status === 401) {
                // User not logged into VibeCode - hide the component
                setStatus({ connected: false })
            } else {
                // Other errors - just show as not connected
                setStatus({ connected: false })
            }
        } catch (error) {
            console.error('Failed to fetch GitHub status:', error)
            setStatus({ connected: false })
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchStatus()

        // Check for OAuth callback success
        const params = new URLSearchParams(window.location.search)
        if (params.get('github_connected') === 'true') {
            // Remove query param and refresh status
            window.history.replaceState({}, '', window.location.pathname)
            fetchStatus()
        }
    }, [])

    const handleConnect = () => {
        // Direct redirect to backend login endpoint
        // Pass current path as 'next' parameter so we return here after OAuth
        const next = window.location.pathname
        window.location.href = `/api/vibecode/github/login?next=${encodeURIComponent(next)}`
    }

    const handleDisconnect = async () => {
        try {
            const response = await fetch('/api/vibecode/github/disconnect', {
                method: 'POST',
                credentials: 'include'
            })
            if (response.ok) {
                setStatus({ connected: false })
            }
        } catch (error) {
            console.error('Failed to disconnect GitHub:', error)
        }
    }

    if (loading) {
        return (
            <div className="flex items-center gap-2 text-gray-400 text-sm">
                <Github size={16} className="animate-pulse" />
            </div>
        )
    }

    if (!status.connected) {
        return (
            <Button
                onClick={handleConnect}
                variant="ghost"
                size="sm"
                className="flex items-center gap-2 h-8 px-3 hover:bg-gray-700"
            >
                <Github size={16} />
                <span className="text-sm">Connect GitHub</span>
            </Button>
        )
    }

    return (
        <div className="flex items-center gap-2">
            <div className="relative">
                {status.avatar_url && (
                    <img
                        src={status.avatar_url}
                        alt={status.login || 'GitHub user'}
                        className="w-6 h-6 rounded-full"
                    />
                )}
                {/* Green dot indicator for signed in */}
                <div className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 bg-green-500 rounded-full border-2 border-gray-800"
                     title="Connected to GitHub" />
            </div>
            <span className="text-sm text-gray-300">{status.login}</span>
            <Button
                onClick={handleDisconnect} variant="ghost"
                size="sm"
                className="h-7 px-2 hover:bg-gray-700"
                title="Sign out from GitHub"
            >
                <LogOut size={14} />
            </Button>
        </div>
    )
}
