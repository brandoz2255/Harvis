"use client"

import React, { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Github, GitBranch, Star, Lock, Loader2, Download, Search, RefreshCw, CheckCircle2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'

interface Repository {
    id: number
    name: string
    full_name: string
    description: string | null
    html_url: string
    clone_url: string
    default_branch: string
    private: boolean
    updated_at: string
    language: string | null
    stargazers_count: number
}

interface GitHubRepoListProps {
    sessionId: string
    onRepoCloned?: () => void
}

export function GitHubRepoList({ sessionId, onRepoCloned }: GitHubRepoListProps) {
    const [repos, setRepos] = useState<Repository[]>([])
    const [loading, setLoading] = useState(true)
    const [cloning, setCloning] = useState<number | null>(null)
    const [searchTerm, setSearchTerm] = useState('')
    const [error, setError] = useState<string | null>(null)
    const [success, setSuccess] = useState<number | null>(null)

    const fetchRepos = async () => {
        setLoading(true)
        setError(null)
        try {
            const response = await fetch('/api/vibecode/repo/list', {
                credentials: 'include'
            })
            if (response.ok) {
                const data = await response.json()
                setRepos(data.repos)
            } else if (response.status === 401) {
                setError('GitHub not connected')
            } else {
                setError('Failed to fetch repositories')
            }
        } catch (err) {
            console.error('Failed to fetch repos:', err)
            setError('Network error')
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchRepos()
    }, [])

    const handleClone = async (repo: Repository) => {
        setCloning(repo.id)
        setError(null)
        setSuccess(null)

        try {
            const response = await fetch('/api/vibecode/repo/import', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'include',
                body: JSON.stringify({
                    session_id: sessionId,
                    url: repo.html_url,
                    branch: repo.default_branch,
                    dest: '/workspace',
                }),
            })

            const data = await response.json()

            if (response.ok) {
                setSuccess(repo.id)
                setTimeout(() => setSuccess(null), 3000)
                onRepoCloned?.()
            } else {
                setError(data.detail || 'Failed to clone repository')
            }
        } catch (err) {
            setError('Network error during clone')
        } finally {
            setCloning(null)
        }
    }

    const filteredRepos = repos.filter(repo =>
        repo.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
        repo.description?.toLowerCase().includes(searchTerm.toLowerCase())
    )

    if (loading) {
        return (
            <div className="flex items-center justify-center py-8">
                <Loader2 className="animate-spin text-gray-400" size={24} />
            </div>
        )
    }

    if (error && repos.length === 0) {
        return (
            <div className="p-4 text-center">
                <p className="text-sm text-gray-400 mb-3">{error}</p>
                <Button
                    onClick={fetchRepos}
                    variant="ghost"
                    size="sm"
                    className="text-blue-400 hover:bg-gray-700"
                >
                    <RefreshCw size={14} className="mr-2" />
                    Retry
                </Button>
            </div>
        )
    }

    return (
        <div className="flex flex-col h-full">
            {/* Header with search */}
            <div className="p-3 border-b border-gray-700">
                <div className="flex items-center gap-2 mb-3">
                    <Github size={16} className="text-gray-400" />
                    <span className="text-sm font-medium text-gray-300">Your Repositories</span>
                    <Badge variant="secondary" className="ml-auto text-xs">
                        {repos.length}
                    </Badge>
                </div>
                <div className="relative">
                    <Search size={14} className="absolute left-2 top-2.5 text-gray-500" />
                    <Input
                        type="text"
                        placeholder="Search repos..."
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                        className="pl-8 h-8 bg-gray-700 border-gray-600 text-sm"
                    />
                </div>
            </div>

            {/* Repository list */}
            <div className="flex-1 overflow-y-auto">
                {filteredRepos.length === 0 ? (
                    <div className="p-4 text-center text-sm text-gray-400">
                        {searchTerm ? 'No repositories found' : 'No repositories'}
                    </div>
                ) : (
                    <div className="divide-y divide-gray-700">
                        {filteredRepos.map((repo) => (
                            <div
                                key={repo.id}
                                className="p-3 hover:bg-gray-700/50 transition-colors"
                            >
                                <div className="flex items-start justify-between gap-2 mb-2">
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 mb-1">
                                            <span className="text-sm font-medium text-gray-200 truncate">
                                                {repo.name}
                                            </span>
                                            {repo.private && (
                                                <Lock size={12} className="text-gray-500 flex-shrink-0" />
                                            )}
                                        </div>
                                        {repo.description && (
                                            <p className="text-xs text-gray-400 line-clamp-2 mb-2">
                                                {repo.description}
                                            </p>
                                        )}
                                        <div className="flex items-center gap-3 text-xs text-gray-500">
                                            {repo.language && (
                                                <span className="flex items-center gap-1">
                                                    <span className="w-2 h-2 rounded-full bg-blue-400" />
                                                    {repo.language}
                                                </span>
                                            )}
                                            <span className="flex items-center gap-1">
                                                <Star size={12} />
                                                {repo.stargazers_count}
                                            </span>
                                            <span className="flex items-center gap-1">
                                                <GitBranch size={12} />
                                                {repo.default_branch}
                                            </span>
                                        </div>
                                    </div>
                                    <Button
                                        onClick={() => handleClone(repo)}
                                        disabled={cloning === repo.id || success === repo.id}
                                        size="sm"
                                        variant="ghost"
                                        className="flex-shrink-0 h-8 px-2 hover:bg-gray-600"
                                        title="Clone repository"
                                    >
                                        {cloning === repo.id ? (
                                            <Loader2 size={14} className="animate-spin" />
                                        ) : success === repo.id ? (
                                            <CheckCircle2 size={14} className="text-green-400" />
                                        ) : (
                                            <Download size={14} />
                                        )}
                                    </Button>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>

            {/* Error banner */}
            {error && (
                <div className="p-2 bg-red-900/20 border-t border-red-500/50 text-red-300 text-xs">
                    {error}
                </div>
            )}
        </div>
    )
}
