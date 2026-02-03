"use client"

import { useState, useEffect, useCallback } from "react"
import { useRouter } from "next/navigation"
import {
    ArrowLeft,
    Database,
    RefreshCw,
    Trash2,
    Play,
    Loader2,
    CheckCircle,
    XCircle,
    AlertCircle,
    FileText,
    Github,
    MessageSquare,
    Plus,
    X,
    BookOpen,
    FolderOpen,
    Container,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Checkbox } from "@/components/ui/checkbox"
import {
    startRagUpdate,
    getRagJobStatus,
    getRagSourceStats,
    rebuildRagSource,
    clearRagSource,
    getRagHealth,
    type RagJob,
    type SourceStats,
} from "@/lib/rag"

// Source configuration
const SOURCE_CONFIG = {
    nextjs_docs: {
        label: "Next.js Documentation",
        description: "Official Next.js docs from nextjs.org",
        icon: FileText,
        color: "text-blue-400",
        group: "development",
    },
    stack_overflow: {
        label: "Stack Overflow",
        description: "Q&A from Stack Overflow",
        icon: MessageSquare,
        color: "text-orange-400",
        group: "development",
    },
    github: {
        label: "GitHub Repositories",
        description: "Code and docs from GitHub repos",
        icon: Github,
        color: "text-purple-400",
        group: "development",
    },
    python_docs: {
        label: "Python Documentation",
        description: "Docs for any Python library",
        icon: BookOpen,
        color: "text-yellow-400",
        group: "development",
    },
    docker_docs: {
        label: "Docker Documentation",
        description: "Docker Engine, Compose, Swarm, Registry, and best practices",
        icon: Container,
        color: "text-blue-500",
        group: "containerization",
    },
    kubernetes_docs: {
        label: "Kubernetes Documentation",
        description: "K8s concepts, tasks, networking, storage, security, and API reference",
        icon: Container,
        color: "text-blue-600",
        group: "containerization",
    },
    local_docs: {
        label: "Local Engineering Docs",
        description: "Your project's /docs folder (best practices, guidelines)",
        icon: FolderOpen,
        color: "text-green-400",
        group: "local",
    },
}

type SourceKey = keyof typeof SOURCE_CONFIG

export default function SettingsPage() {
    const router = useRouter()

    // Source selection state
    const [selectedSources, setSelectedSources] = useState<Set<SourceKey>>(new Set())
    const [keywords, setKeywords] = useState<string[]>([])
    const [newKeyword, setNewKeyword] = useState("")
    const [extraUrls, setExtraUrls] = useState<string[]>([])
    const [newUrl, setNewUrl] = useState("")

    // Python libraries state
    const [pythonLibraries, setPythonLibraries] = useState<string[]>([])
    const [newPythonLib, setNewPythonLib] = useState("")

    // Docker topics state
    const [dockerTopics, setDockerTopics] = useState<string[]>([])
    const [newDockerTopic, setNewDockerTopic] = useState("")

    // Kubernetes topics state
    const [kubernetesTopics, setKubernetesTopics] = useState<string[]>([])
    const [newKubernetesTopic, setNewKubernetesTopic] = useState("")

    // Job state
    const [currentJob, setCurrentJob] = useState<RagJob | null>(null)
    const [isStarting, setIsStarting] = useState(false)

    // Stats state
    const [sourceStats, setSourceStats] = useState<SourceStats | null>(null)
    const [isLoadingStats, setIsLoadingStats] = useState(true)

    // Health state
    const [healthStatus, setHealthStatus] = useState<string>("unknown")

    // Action states for individual sources
    const [rebuildingSource, setRebuildingSource] = useState<string | null>(null)
    const [clearingSource, setClearingSource] = useState<string | null>(null)

    // Load source stats
    const loadStats = useCallback(async () => {
        try {
            const stats = await getRagSourceStats()
            setSourceStats(stats)
        } catch (error) {
            console.error("Failed to load source stats:", error)
        } finally {
            setIsLoadingStats(false)
        }
    }, [])

    // Check health
    const checkHealth = useCallback(async () => {
        try {
            const health = await getRagHealth()
            setHealthStatus(health.status)
        } catch {
            setHealthStatus("unavailable")
        }
    }, [])

    // Poll job status
    useEffect(() => {
        if (!currentJob || currentJob.status === "COMPLETED" || currentJob.status === "FAILED") {
            return
        }

        const interval = setInterval(async () => {
            try {
                const job = await getRagJobStatus(currentJob.id)
                setCurrentJob(job)

                if (job.status === "COMPLETED" || job.status === "FAILED") {
                    // Refresh stats after job completes
                    loadStats()
                }
            } catch (error) {
                console.error("Failed to poll job status:", error)
            }
        }, 2000)

        return () => clearInterval(interval)
    }, [currentJob, loadStats])

    // Initial load
    useEffect(() => {
        loadStats()
        checkHealth()
    }, [loadStats, checkHealth])

    // Source toggle
    const toggleSource = (source: SourceKey) => {
        setSelectedSources(prev => {
            const next = new Set(prev)
            if (next.has(source)) {
                next.delete(source)
            } else {
                next.add(source)
            }
            return next
        })
    }

    // Add keyword
    const addKeyword = () => {
        const keyword = newKeyword.trim()
        if (keyword && !keywords.includes(keyword)) {
            setKeywords(prev => [...prev, keyword])
            setNewKeyword("")
        }
    }

    // Remove keyword
    const removeKeyword = (keyword: string) => {
        setKeywords(prev => prev.filter(k => k !== keyword))
    }

    // Add URL
    const addUrl = () => {
        const url = newUrl.trim()
        if (url && !extraUrls.includes(url)) {
            setExtraUrls(prev => [...prev, url])
            setNewUrl("")
        }
    }

    // Remove URL
    const removeUrl = (url: string) => {
        setExtraUrls(prev => prev.filter(u => u !== url))
    }

    // Add Python library
    const addPythonLib = () => {
        const lib = newPythonLib.trim().toLowerCase()
        if (lib && !pythonLibraries.includes(lib)) {
            setPythonLibraries(prev => [...prev, lib])
            setNewPythonLib("")
        }
    }

    // Remove Python library
    const removePythonLib = (lib: string) => {
        setPythonLibraries(prev => prev.filter(l => l !== lib))
    }

    // Add Docker topic
    const addDockerTopic = () => {
        const topic = newDockerTopic.trim().toLowerCase()
        if (topic && !dockerTopics.includes(topic)) {
            setDockerTopics(prev => [...prev, topic])
            setNewDockerTopic("")
        }
    }

    // Remove Docker topic
    const removeDockerTopic = (topic: string) => {
        setDockerTopics(prev => prev.filter(t => t !== topic))
    }

    // Add Kubernetes topic
    const addKubernetesTopic = () => {
        const topic = newKubernetesTopic.trim().toLowerCase()
        if (topic && !kubernetesTopics.includes(topic)) {
            setKubernetesTopics(prev => [...prev, topic])
            setNewKubernetesTopic("")
        }
    }

    // Remove Kubernetes topic
    const removeKubernetesTopic = (topic: string) => {
        setKubernetesTopics(prev => prev.filter(t => t !== topic))
    }

    // Start update
    const handleStartUpdate = async () => {
        if (selectedSources.size === 0) return

        setIsStarting(true)
        try {
            const response = await startRagUpdate({
                sources: Array.from(selectedSources),
                keywords: keywords.length > 0 ? keywords : undefined,
                extra_urls: extraUrls.length > 0 ? extraUrls : undefined,
                python_libraries: pythonLibraries.length > 0 ? pythonLibraries : undefined,
                docker_topics: dockerTopics.length > 0 ? dockerTopics : undefined,
                kubernetes_topics: kubernetesTopics.length > 0 ? kubernetesTopics : undefined,
            })

            // Get initial job status
            const job = await getRagJobStatus(response.job_id)
            setCurrentJob(job)
        } catch (error) {
            console.error("Failed to start update:", error)
        } finally {
            setIsStarting(false)
        }
    }

    // Rebuild source
    const handleRebuildSource = async (source: string) => {
        setRebuildingSource(source)
        try {
            const response = await rebuildRagSource(source)
            const job = await getRagJobStatus(response.job_id)
            setCurrentJob(job)
        } catch (error) {
            console.error("Failed to rebuild source:", error)
        } finally {
            setRebuildingSource(null)
        }
    }

    // Clear source
    const handleClearSource = async (source: string) => {
        setClearingSource(source)
        try {
            await clearRagSource(source)
            loadStats()
        } catch (error) {
            console.error("Failed to clear source:", error)
        } finally {
            setClearingSource(null)
        }
    }

    return (
        <div className="min-h-screen bg-background">
            {/* Header */}
            <header className="sticky top-0 z-10 border-b border-border bg-background/95 backdrop-blur">
                <div className="mx-auto max-w-4xl flex h-14 items-center gap-4 px-4">
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => router.push("/")}
                    >
                        <ArrowLeft className="h-5 w-5" />
                    </Button>
                    <h1 className="text-lg font-semibold">RAG Corpus Settings</h1>
                    <div className="ml-auto flex items-center gap-2">
                        <div className={`flex items-center gap-2 rounded-full px-3 py-1 text-xs ${healthStatus === "healthy" ? "bg-green-500/20 text-green-400" :
                            healthStatus === "degraded" ? "bg-yellow-500/20 text-yellow-400" :
                                "bg-red-500/20 text-red-400"
                            }`}>
                            {healthStatus === "healthy" ? <CheckCircle className="h-3 w-3" /> :
                                healthStatus === "degraded" ? <AlertCircle className="h-3 w-3" /> :
                                    <XCircle className="h-3 w-3" />}
                            {healthStatus}
                        </div>
                    </div>
                </div>
            </header>

            <main className="mx-auto max-w-4xl px-4 py-8 space-y-10">
                {/* Update Section */}
                <section className="space-y-6">
                    <div className="flex items-center justify-between">
                        <h2 className="text-2xl font-semibold">Update Local Corpus</h2>
                        {sourceStats && (
                            <span className="text-sm text-muted-foreground">
                                {sourceStats.total_documents} documents indexed
                            </span>
                        )}
                    </div>

                    {/* Source Selection - Grouped by Category */}
                    <div className="space-y-8">
                        {/* Containerization Group */}
                        <div className="space-y-4">
                            <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-2">
                                <Container className="h-4 w-4" />
                                Containerization
                            </h3>
                            <div className="grid gap-4 sm:grid-cols-2">
                                {(Object.keys(SOURCE_CONFIG) as SourceKey[])
                                    .filter((source) => SOURCE_CONFIG[source].group === "containerization")
                                    .map((source) => {
                                        const config = SOURCE_CONFIG[source]
                                        const Icon = config.icon
                                        const isSelected = selectedSources.has(source)
                                        const docCount = sourceStats?.indexed_stats[source] || 0

                                        return (
                                            <button
                                                key={source}
                                                onClick={() => toggleSource(source)}
                                                className={`relative flex flex-col gap-3 rounded-xl border-2 p-5 text-left transition-all hover:scale-[1.02] ${isSelected
                                                    ? "border-primary bg-primary/10 shadow-lg shadow-primary/20"
                                                    : "border-border bg-card hover:border-primary/50"
                                                    }`}
                                            >
                                                <div className="flex items-center justify-between">
                                                    <div className={`p-2 rounded-lg bg-background/50 ${isSelected ? "ring-2 ring-primary/50" : ""}`}>
                                                        <Icon className={`h-5 w-5 ${config.color}`} />
                                                    </div>
                                                    <Checkbox checked={isSelected} className="pointer-events-none" />
                                                </div>
                                                <div>
                                                    <h3 className="font-semibold">{config.label}</h3>
                                                    <p className="text-xs text-muted-foreground mt-1">{config.description}</p>
                                                </div>
                                                <div className="text-xs text-muted-foreground mt-auto pt-2 border-t border-border/50">
                                                    {docCount} documents
                                                </div>
                                            </button>
                                        )
                                    })}
                            </div>
                        </div>

                        {/* Development Group */}
                        <div className="space-y-4">
                            <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
                                Development
                            </h3>
                            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                                {(Object.keys(SOURCE_CONFIG) as SourceKey[])
                                    .filter((source) => SOURCE_CONFIG[source].group === "development")
                                    .map((source) => {
                                        const config = SOURCE_CONFIG[source]
                                        const Icon = config.icon
                                        const isSelected = selectedSources.has(source)
                                        const docCount = sourceStats?.indexed_stats[source] || 0

                                        return (
                                            <button
                                                key={source}
                                                onClick={() => toggleSource(source)}
                                                className={`relative flex flex-col gap-3 rounded-xl border-2 p-5 text-left transition-all hover:scale-[1.02] ${isSelected
                                                    ? "border-primary bg-primary/10 shadow-lg shadow-primary/20"
                                                    : "border-border bg-card hover:border-primary/50"
                                                    }`}
                                            >
                                                <div className="flex items-center justify-between">
                                                    <div className={`p-2 rounded-lg bg-background/50 ${isSelected ? "ring-2 ring-primary/50" : ""}`}>
                                                        <Icon className={`h-5 w-5 ${config.color}`} />
                                                    </div>
                                                    <Checkbox checked={isSelected} className="pointer-events-none" />
                                                </div>
                                                <div>
                                                    <h3 className="font-semibold">{config.label}</h3>
                                                    <p className="text-xs text-muted-foreground mt-1">{config.description}</p>
                                                </div>
                                                <div className="text-xs text-muted-foreground mt-auto pt-2 border-t border-border/50">
                                                    {docCount} documents
                                                </div>
                                            </button>
                                        )
                                    })}
                            </div>
                        </div>

                        {/* Local Group */}
                        <div className="space-y-4">
                            <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wide">
                                Local
                            </h3>
                            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                                {(Object.keys(SOURCE_CONFIG) as SourceKey[])
                                    .filter((source) => SOURCE_CONFIG[source].group === "local")
                                    .map((source) => {
                                        const config = SOURCE_CONFIG[source]
                                        const Icon = config.icon
                                        const isSelected = selectedSources.has(source)
                                        const docCount = sourceStats?.indexed_stats[source] || 0

                                        return (
                                            <button
                                                key={source}
                                                onClick={() => toggleSource(source)}
                                                className={`relative flex flex-col gap-3 rounded-xl border-2 p-5 text-left transition-all hover:scale-[1.02] ${isSelected
                                                    ? "border-primary bg-primary/10 shadow-lg shadow-primary/20"
                                                    : "border-border bg-card hover:border-primary/50"
                                                    }`}
                                            >
                                                <div className="flex items-center justify-between">
                                                    <div className={`p-2 rounded-lg bg-background/50 ${isSelected ? "ring-2 ring-primary/50" : ""}`}>
                                                        <Icon className={`h-5 w-5 ${config.color}`} />
                                                    </div>
                                                    <Checkbox checked={isSelected} className="pointer-events-none" />
                                                </div>
                                                <div>
                                                    <h3 className="font-semibold">{config.label}</h3>
                                                    <p className="text-xs text-muted-foreground mt-1">{config.description}</p>
                                                </div>
                                                <div className="text-xs text-muted-foreground mt-auto pt-2 border-t border-border/50">
                                                    {docCount} documents
                                                </div>
                                            </button>
                                        )
                                    })}
                            </div>
                        </div>
                    </div>

                    {/* Python Libraries Input (shown when python_docs is selected) */}
                    {selectedSources.has("python_docs") && (
                        <div className="space-y-3 p-4 rounded-lg border border-yellow-500/30 bg-yellow-500/5">
                            <label className="text-sm font-medium flex items-center gap-2">
                                <BookOpen className="h-4 w-4 text-yellow-400" />
                                Python Libraries to Index
                            </label>
                            <p className="text-xs text-muted-foreground">
                                Enter library names (e.g., requests, pandas, fastapi) to fetch their documentation
                            </p>
                            <div className="flex gap-2">
                                <Input
                                    placeholder="Enter library name..."
                                    value={newPythonLib}
                                    onChange={(e) => setNewPythonLib(e.target.value)}
                                    onKeyDown={(e) => e.key === "Enter" && addPythonLib()}
                                    className="flex-1"
                                />
                                <Button onClick={addPythonLib} variant="secondary" size="icon">
                                    <Plus className="h-4 w-4" />
                                </Button>
                            </div>
                            {pythonLibraries.length > 0 && (
                                <div className="flex flex-wrap gap-2">
                                    {pythonLibraries.map((lib) => (
                                        <span
                                            key={lib}
                                            className="flex items-center gap-1 rounded-full bg-yellow-500/20 px-3 py-1 text-sm font-mono"
                                        >
                                            {lib}
                                            <button onClick={() => removePythonLib(lib)} className="hover:text-red-400">
                                                <X className="h-3 w-3" />
                                            </button>
                                        </span>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Docker Topics Input (shown when docker_docs is selected) */}
                    {selectedSources.has("docker_docs") && (
                        <div className="space-y-3 p-4 rounded-lg border border-blue-500/30 bg-blue-500/5">
                            <label className="text-sm font-medium flex items-center gap-2">
                                <Container className="h-4 w-4 text-blue-400" />
                                Docker Topics to Index
                            </label>
                            <p className="text-xs text-muted-foreground">
                                Enter topics like: engine, compose, swarm, registry, hub, buildx, networking, storage, security. Leave empty to fetch all Docker docs.
                            </p>
                            <div className="flex gap-2">
                                <Input
                                    placeholder="Enter Docker topic (e.g., engine, compose)..."
                                    value={newDockerTopic}
                                    onChange={(e) => setNewDockerTopic(e.target.value)}
                                    onKeyDown={(e) => e.key === "Enter" && addDockerTopic()}
                                    className="flex-1"
                                />
                                <Button onClick={addDockerTopic} variant="secondary" size="icon">
                                    <Plus className="h-4 w-4" />
                                </Button>
                            </div>
                            {dockerTopics.length > 0 && (
                                <div className="flex flex-wrap gap-2">
                                    {dockerTopics.map((topic) => (
                                        <span
                                            key={topic}
                                            className="flex items-center gap-1 rounded-full bg-blue-500/20 px-3 py-1 text-sm font-mono"
                                        >
                                            {topic}
                                            <button onClick={() => removeDockerTopic(topic)} className="hover:text-red-400">
                                                <X className="h-3 w-3" />
                                            </button>
                                        </span>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Kubernetes Topics Input (shown when kubernetes_docs is selected) */}
                    {selectedSources.has("kubernetes_docs") && (
                        <div className="space-y-3 p-4 rounded-lg border border-blue-600/30 bg-blue-600/5">
                            <label className="text-sm font-medium flex items-center gap-2">
                                <Container className="h-4 w-4 text-blue-600" />
                                Kubernetes Topics to Index
                            </label>
                            <p className="text-xs text-muted-foreground">
                                Enter topics like: concepts, tasks, reference, tutorials, networking, storage, security, scheduling, workloads. Leave empty to fetch all K8s docs.
                            </p>
                            <div className="flex gap-2">
                                <Input
                                    placeholder="Enter K8s topic (e.g., concepts, networking)..."
                                    value={newKubernetesTopic}
                                    onChange={(e) => setNewKubernetesTopic(e.target.value)}
                                    onKeyDown={(e) => e.key === "Enter" && addKubernetesTopic()}
                                    className="flex-1"
                                />
                                <Button onClick={addKubernetesTopic} variant="secondary" size="icon">
                                    <Plus className="h-4 w-4" />
                                </Button>
                            </div>
                            {kubernetesTopics.length > 0 && (
                                <div className="flex flex-wrap gap-2">
                                    {kubernetesTopics.map((topic) => (
                                        <span
                                            key={topic}
                                            className="flex items-center gap-1 rounded-full bg-blue-600/20 px-3 py-1 text-sm font-mono"
                                        >
                                            {topic}
                                            <button onClick={() => removeKubernetesTopic(topic)} className="hover:text-red-400">
                                                <X className="h-3 w-3" />
                                            </button>
                                        </span>
                                    ))}
                                </div>
                            )}
                        </div>
                    )}

                    {/* Keyword Filters */}
                    <div className="space-y-3">
                        <label className="text-sm font-medium">Keyword Filters (optional)</label>
                        <div className="flex gap-2">
                            <Input
                                placeholder="Add keyword to filter content..."
                                value={newKeyword}
                                onChange={(e) => setNewKeyword(e.target.value)}
                                onKeyDown={(e) => e.key === "Enter" && addKeyword()}
                                className="flex-1"
                            />
                            <Button onClick={addKeyword} variant="secondary" size="icon">
                                <Plus className="h-4 w-4" />
                            </Button>
                        </div>
                        {keywords.length > 0 && (
                            <div className="flex flex-wrap gap-2">
                                {keywords.map((keyword) => (
                                    <span
                                        key={keyword}
                                        className="flex items-center gap-1 rounded-full bg-primary/20 px-3 py-1 text-sm"
                                    >
                                        {keyword}
                                        <button onClick={() => removeKeyword(keyword)}>
                                            <X className="h-3 w-3" />
                                        </button>
                                    </span>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Extra URLs */}
                    <div className="space-y-3">
                        <label className="text-sm font-medium">Specific URLs (optional)</label>
                        <div className="flex gap-2">
                            <Input
                                placeholder="Add specific URL to fetch..."
                                value={newUrl}
                                onChange={(e) => setNewUrl(e.target.value)}
                                onKeyDown={(e) => e.key === "Enter" && addUrl()}
                                className="flex-1"
                            />
                            <Button onClick={addUrl} variant="secondary" size="icon">
                                <Plus className="h-4 w-4" />
                            </Button>
                        </div>
                        {extraUrls.length > 0 && (
                            <div className="space-y-1">
                                {extraUrls.map((url) => (
                                    <div
                                        key={url}
                                        className="flex items-center gap-2 rounded bg-muted px-3 py-1.5 text-sm"
                                    >
                                        <span className="flex-1 truncate">{url}</span>
                                        <button onClick={() => removeUrl(url)}>
                                            <X className="h-3 w-3" />
                                        </button>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    {/* Start Button */}
                    <Button
                        onClick={handleStartUpdate}
                        disabled={selectedSources.size === 0 || isStarting || currentJob?.status === "RUNNING"}
                        className="w-full h-12 text-base"
                        size="lg"
                    >
                        {isStarting ? (
                            <>
                                <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                                Starting...
                            </>
                        ) : currentJob?.status === "RUNNING" ? (
                            <>
                                <Loader2 className="mr-2 h-5 w-5 animate-spin" />
                                Running...
                            </>
                        ) : (
                            <>
                                <Play className="mr-2 h-5 w-5" />
                                Start Update
                            </>
                        )}
                    </Button>

                    {/* Job Progress */}
                    {currentJob && (
                        <div className={`rounded-xl border-2 p-5 ${currentJob.status === "COMPLETED" ? "border-green-500/50 bg-green-500/10" :
                            currentJob.status === "FAILED" ? "border-red-500/50 bg-red-500/10" :
                                "border-primary/50 bg-primary/10"
                            }`}>
                            <div className="flex items-center justify-between mb-3">
                                <span className="font-semibold text-lg">
                                    {currentJob.status === "COMPLETED" ? "Update Complete" :
                                        currentJob.status === "FAILED" ? "Update Failed" :
                                            "Updating..."}
                                </span>
                                <span className={`rounded-full px-3 py-1 text-xs font-medium ${currentJob.status === "COMPLETED" ? "bg-green-500/20 text-green-400" :
                                    currentJob.status === "FAILED" ? "bg-red-500/20 text-red-400" :
                                        "bg-primary/20 text-primary"
                                    }`}>
                                    {currentJob.status}
                                </span>
                            </div>

                            {currentJob.progress && (
                                <div className="space-y-3 text-sm text-muted-foreground">
                                    <div className="flex justify-between">
                                        <span>Phase:</span>
                                        <span className="font-medium text-foreground">{currentJob.progress.current_phase}</span>
                                    </div>
                                    {currentJob.progress.current_source && (
                                        <div className="flex justify-between">
                                            <span>Source:</span>
                                            <span className="font-medium text-foreground">{currentJob.progress.current_source}</span>
                                        </div>
                                    )}
                                    <div className="flex justify-between">
                                        <span>Progress:</span>
                                        <span className="font-medium text-foreground">
                                            {currentJob.progress.processed} / {currentJob.progress.total_docs} documents
                                        </span>
                                    </div>
                                    {currentJob.progress.total_docs > 0 && (
                                        <div className="h-3 rounded-full bg-background/50 overflow-hidden">
                                            <div
                                                className="h-full bg-primary transition-all duration-300"
                                                style={{
                                                    width: `${(currentJob.progress.processed / currentJob.progress.total_docs) * 100}%`
                                                }}
                                            />
                                        </div>
                                    )}
                                </div>
                            )}

                            {currentJob.error && (
                                <div className="mt-3 text-sm text-red-400 p-3 bg-red-500/10 rounded-lg">
                                    Error: {currentJob.error}
                                </div>
                            )}
                        </div>
                    )}
                </section>

                {/* Manage Sources Section */}
                <section className="space-y-6">
                    <div className="flex items-center justify-between">
                        <h2 className="text-2xl font-semibold">Manage Indexed Sources</h2>
                        <Button
                            variant="ghost"
                            size="sm"
                            onClick={loadStats}
                            disabled={isLoadingStats}
                        >
                            <RefreshCw className={`h-4 w-4 ${isLoadingStats ? "animate-spin" : ""}`} />
                        </Button>
                    </div>

                    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                        {(Object.keys(SOURCE_CONFIG) as SourceKey[]).map((source) => {
                            const config = SOURCE_CONFIG[source]
                            const Icon = config.icon
                            const docCount = sourceStats?.indexed_stats[source] || 0
                            const isRebuilding = rebuildingSource === source
                            const isClearing = clearingSource === source

                            return (
                                <div
                                    key={source}
                                    className="flex flex-col gap-4 rounded-xl border border-border bg-card p-5"
                                >
                                    <div className="flex items-center gap-3">
                                        <div className={`p-2 rounded-lg bg-background/50`}>
                                            <Icon className={`h-5 w-5 ${config.color}`} />
                                        </div>
                                        <span className="font-semibold">{config.label}</span>
                                    </div>

                                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                                        <Database className="h-4 w-4" />
                                        {docCount} documents
                                    </div>

                                    <div className="flex gap-2 mt-auto">
                                        <Button
                                            variant="secondary"
                                            size="sm"
                                            className="flex-1"
                                            onClick={() => handleRebuildSource(source)}
                                            disabled={isRebuilding || isClearing}
                                        >
                                            {isRebuilding ? (
                                                <Loader2 className="h-3 w-3 animate-spin" />
                                            ) : (
                                                <RefreshCw className="h-3 w-3" />
                                            )}
                                            <span className="ml-1">Rebuild</span>
                                        </Button>
                                        <Button
                                            variant="destructive"
                                            size="sm"
                                            className="flex-1"
                                            onClick={() => handleClearSource(source)}
                                            disabled={isRebuilding || isClearing || docCount === 0}
                                        >
                                            {isClearing ? (
                                                <Loader2 className="h-3 w-3 animate-spin" />
                                            ) : (
                                                <Trash2 className="h-3 w-3" />
                                            )}
                                            <span className="ml-1">Clear</span>
                                        </Button>
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                </section>
            </main>
        </div>
    )
}

