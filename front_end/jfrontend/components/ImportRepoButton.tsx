"use client"

import React, { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { Github, Loader2 } from 'lucide-react'

interface ImportRepoButtonProps {
    sessionId: string
    onSuccess?: () => void
}

export function ImportRepoButton({ sessionId, onSuccess }: ImportRepoButtonProps) {
    const [open, setOpen] = useState(false)
    const [url, setUrl] = useState('')
    const [branch, setBranch] = useState('main')
    const [folder, setFolder] = useState('')
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [success, setSuccess] = useState(false)

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault()
        setError(null)
        setSuccess(false)
        setLoading(true)

        try {
            const response = await fetch('/api/vibecode/repo/import', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                credentials: 'include',
                body: JSON.stringify({
                    session_id: sessionId,
                    url: url.trim(),
                    branch: branch.trim() || 'main',
                    dest: '/workspace',
                    subdir: folder.trim() || undefined,
                }),
            })

            const data = await response.json()

            if (response.ok) {
                setSuccess(true)
                setTimeout(() => {
                    setOpen(false)
                    setUrl('')
                    setBranch('main')
                    setFolder('')
                    setSuccess(false)
                    onSuccess?.()
                }, 1500)
            } else {
                setError(data.detail || 'Failed to import repository')
            }
        } catch (err) {
            setError('Network error. Please try again.')
        } finally {
            setLoading(false)
        }
    }

    return (
        <>
            <Button
                onClick={() => setOpen(true)}
                variant="ghost"
                size="sm"
                className="p-1 h-auto hover:bg-gray-700"
                title="Import from GitHub"
            >
                <Github size={14} className="text-gray-400" />
            </Button>

            <Dialog open={open} onOpenChange={setOpen}>
                <DialogContent className="bg-gray-800 border-gray-700 text-gray-200">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2">
                            <Github size={20} />
                            Import from GitHub
                        </DialogTitle>
                        <DialogDescription className="text-gray-400">
                            Clone a repository into your workspace
                        </DialogDescription>
                    </DialogHeader>

                    <form onSubmit={handleSubmit} className="space-y-4">
                        <div>
                            <label htmlFor="repo-url" className="text-sm font-medium text-gray-300 block mb-1">
                                Repository URL
                            </label>
                            <Input
                                id="repo-url"
                                type="text"
                                placeholder="https://github.com/owner/repo"
                                value={url}
                                onChange={(e) => setUrl(e.target.value)}
                                required
                                className="bg-gray-700 border-gray-600 text-gray-200 placeholder:text-gray-500"
                                disabled={loading}
                            />
                        </div>

                        <div>
                            <label htmlFor="branch" className="text-sm font-medium text-gray-300 block mb-1">
                                Branch
                            </label>
                            <Input
                                id="branch"
                                type="text"
                                placeholder="main"
                                value={branch}
                                onChange={(e) => setBranch(e.target.value)}
                                className="bg-gray-700 border-gray-600 text-gray-200 placeholder:text-gray-500"
                                disabled={loading}
                            />
                        </div>

                        <div>
                            <label htmlFor="folder" className="text-sm font-medium text-gray-300 block mb-1">
                                Folder Name (optional)
                            </label>
                            <Input
                                id="folder"
                                type="text"
                                placeholder="my-project"
                                value={folder}
                                onChange={(e) => setFolder(e.target.value)}
                                className="bg-gray-700 border-gray-600 text-gray-200 placeholder:text-gray-500"
                                disabled={loading}
                            />
                            <p className="text-xs text-gray-500 mt-1">
                                Leave empty to use repository name
                            </p>
                        </div>

                        {error && (
                            <div className="p-3 rounded bg-red-900/20 border border-red-500/50 text-red-300 text-sm">
                                {error}
                            </div>
                        )}

                        {success && (
                            <div className="p-3 rounded bg-green-900/20 border border-green-500/50 text-green-300 text-sm">
                                ✓ Repository imported successfully!
                            </div>
                        )}

                        <div className="flex gap-2 justify-end">
                            <Button
                                type="button"
                                variant="ghost"
                                onClick={() => setOpen(false)}
                                disabled={loading}
                                className="hover:bg-gray-700"
                            >
                                Cancel
                            </Button>
                            <Button
                                type="submit"
                                disabled={loading || !url.trim()}
                                className="bg-blue-600 hover:bg-blue-700"
                            >
                                {loading ? (
                                    <>
                                        <Loader2 size={16} className="animate-spin mr-2" />
                                        Importing...
                                    </>
                                ) : (
                                    'Import'
                                )}
                            </Button>
                        </div>
                    </form>
                </DialogContent>
            </Dialog>
        </>
    )
}
