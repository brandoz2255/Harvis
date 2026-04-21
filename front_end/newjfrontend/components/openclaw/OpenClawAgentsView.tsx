"use client"

import { useState, useEffect, useCallback } from "react"
import { cn } from "@/lib/utils"
import {
  Cpu,
  FileCode,
  Settings2,
  Zap,
  Loader2,
  Check,
  AlertCircle,
  Search,
  Globe,
  Database,
  FolderOpen,
  Code,
  Save,
  RefreshCw,
} from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import { Separator } from "@/components/ui/separator"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useOpenClawConnection } from "@/hooks/useOpenClawConnection"
import { useAgentsStore } from "@/stores/openclawAgentsStore"
import type { AgentFileEntry, ToolCatalogEntry, ToolCatalogGroup, SkillStatusEntry } from "@/lib/openclaw/types"

interface OpenClawAgentsViewProps {
  className?: string
}

function getToolIcon(name: string) {
  const icons: Record<string, React.ComponentType<{ className?: string }>> = {
    run_code: FileCode,
    local_rag: Database,
    repo_read: FolderOpen,
    repo_write: Code,
    web_fetch: Globe,
    create_docx: FileCode,
    create_pdf: FileCode,
  }
  return icons[name] ?? Settings2
}

// ─── Agent Files Tab ───────────────────────────────────────────────────────

function AgentFilesTab({ agentId }: { agentId: string }) {
  const { client, isConnected } = useOpenClawConnection()
  const { agentFiles, setAgentFiles, setLoading: setFilesLoading, setError } = useAgentsStore()
  const [searchQuery, setSearchQuery] = useState("")
  const [editingFile, setEditingFile] = useState<string | null>(null)
  const [editContent, setEditContent] = useState("")
  const loading = useAgentsStore((s) => s.loading)

  useEffect(() => {
    if (isConnected && client) {
      loadFiles()
    }
  }, [isConnected, client, agentId])

  const loadFiles = useCallback(async () => {
    if (!client) return
    setFilesLoading(true)
    try {
      const result = await client.listAgentFiles(agentId)
      if (result.type === "res" && result.ok) {
        const payload = result.payload as { agentId: string; workspace: string; files: AgentFileEntry[] }
        if (payload?.files) {
          setAgentFiles({ agentId: payload.agentId, workspace: payload.workspace, files: payload.files })
        }
      }
    } catch (e) {
      console.error("[Agents] Failed to load files:", e)
      setError("Failed to load agent files")
    } finally {
      setFilesLoading(false)
    }
  }, [client, agentId])

  const handleEdit = useCallback((file: AgentFileEntry) => {
    setEditingFile(file.name)
    setEditContent(file.content ?? "")
  }, [])

  const handleSave = useCallback(async () => {
    if (!client || !client.connected || !editingFile) return
    try {
      const file = agentFiles.find((f) => f.name === editingFile)
      if (!file) return

      // Use agents.files.set RPC
      await client.request("agents.files.set", {
        agentId,
        path: file.path,
        content: editContent,
      })
      setEditingFile(null)
    } catch (e) {
      console.error("[Agents] Failed to save:", e)
    }
  }, [client, agentId, editingFile, editContent, agentFiles])

  const filteredFiles = agentFiles.filter((f) =>
    f.name.toLowerCase().includes(searchQuery.toLowerCase()),
  )

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            placeholder="Search files..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="h-8 pl-8 text-sm"
          />
        </div>
        <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={loadFiles}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : filteredFiles.length === 0 ? (
        <div className="text-center text-sm text-muted-foreground py-8">No files found</div>
      ) : (
        <div className="space-y-1">
          {filteredFiles.map((file) => (
            <div key={file.path} className="flex items-center justify-between px-3 py-2 rounded-lg hover:bg-muted/50 border border-transparent hover:border-border transition-colors">
              <div className="flex items-center gap-2 min-w-0">
                <FileCode className="h-4 w-4 text-muted-foreground shrink-0" />
                <span className="text-sm font-mono truncate">{file.name}</span>
                {file.missing && <Badge variant="destructive" className="text-xs">missing</Badge>}
                {file.size && <Badge variant="secondary" className="text-xs">{(file.size / 1024).toFixed(1)}KB</Badge>}
              </div>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 text-xs"
                onClick={() => handleEdit(file)}
              >
                Edit
              </Button>
            </div>
          ))}
        </div>
      )}

      {/* Edit dialog */}
      {editingFile && (
        <div className="fixed inset-0 bg-background/80 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-card border rounded-lg w-full max-w-2xl max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between p-4 border-b">
              <h3 className="font-medium font-mono">{editingFile}</h3>
              <Button variant="ghost" size="sm" onClick={() => setEditingFile(null)}>
                <span className="text-lg leading-none">✕</span>
              </Button>
            </div>
            <ScrollArea className="flex-1">
              <textarea
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                className="w-full min-h-[400px] p-4 font-mono text-sm bg-muted/30 resize-none focus:outline-none"
              />
            </ScrollArea>
            <div className="p-4 border-t flex justify-end gap-2">
              <Button variant="outline" onClick={() => setEditingFile(null)}>
                Cancel
              </Button>
              <Button onClick={handleSave}>
                <Save className="h-3.5 w-3.5 mr-1" />
                Save
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Tools Tab ─────────────────────────────────────────────────────────────

function AgentToolsTab() {
  const { toolsCatalog } = useAgentsStore()

  if (!toolsCatalog) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {toolsCatalog.groups.map((group) => (
        <div key={group.id}>
          <h4 className="text-sm font-medium flex items-center gap-2 mb-2">
            {group.source === "core" ? <Zap className="h-3.5 w-3.5 text-primary" /> : <Settings2 className="h-3.5 w-3.5 text-muted-foreground" />}
            {group.label}
            <Badge variant="secondary" className="text-xs">{group.tools.length}</Badge>
          </h4>
          <div className="space-y-1">
            {group.tools.map((tool) => (
              <div key={tool.id} className="flex items-start gap-3 px-3 py-2 rounded-lg hover:bg-muted/50 border border-transparent hover:border-border transition-colors">
                {tool.optional ? (
                  <AlertCircle className="h-4 w-4 text-muted-foreground shrink-0 mt-0.5" />
                ) : (
                  <Check className="h-4 w-4 text-green-500 shrink-0 mt-0.5" />
                )}
                <div className="min-w-0">
                  <div className="text-sm font-medium">{tool.label}</div>
                  <div className="text-xs text-muted-foreground">{tool.description}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

// ─── Skills Tab ────────────────────────────────────────────────────────────

function AgentSkillsTab() {
  const { skills, loading, setError } = useAgentsStore()
  const { client, isConnected } = useOpenClawConnection()

  useEffect(() => {
    if (isConnected && client) {
      loadSkills()
    }
  }, [isConnected, client])

  const loadSkills = useCallback(async () => {
    if (!client) return
    try {
      const result = await client.getSkillStatus()
      if (result.type === "res" && result.ok) {
        const payload = result.payload as { workspaceDir: string; skills: SkillStatusEntry[] }
        if (payload?.skills) {
          useAgentsStore.getState().setSkills({
            workspaceDir: payload.workspaceDir,
            managedSkillsDir: "",
            skills: payload.skills,
          })
        }
      }
    } catch (e) {
      console.error("[Agents] Failed to load skills:", e)
    }
  }, [client])

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">{skills.length} skills</span>
        </div>
        <Button variant="ghost" size="sm" className="h-8 w-8 p-0" onClick={loadSkills}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : skills.length === 0 ? (
        <div className="text-center text-sm text-muted-foreground py-8">No skills found</div>
      ) : (
        <div className="space-y-2">
          {skills.map((skill) => (
            <div key={skill.name} className="flex items-center justify-between px-3 py-2 rounded-lg hover:bg-muted/50 border border-transparent hover:border-border transition-colors">
              <div className="flex items-center gap-3 min-w-0">
                <span className="text-lg">{skill.emoji ?? "📦"}</span>
                <div className="min-w-0">
                  <div className="text-sm font-medium">{skill.name}</div>
                  <div className="text-xs text-muted-foreground truncate">{skill.description}</div>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {skill.disabled && <Badge variant="secondary" className="text-xs">Disabled</Badge>}
                {!skill.eligible && !skill.disabled && <Badge variant="destructive" className="text-xs">Missing deps</Badge>}
                {skill.eligible && !skill.disabled && <Badge variant="secondary" className="text-xs">Active</Badge>}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Main Agents View ──────────────────────────────────────────────────────

export function OpenClawAgentsView({ className }: OpenClawAgentsViewProps) {
  const { client, isConnected } = useOpenClawConnection()
  const { agents, selectedAgentId, setSelectedAgent, setAgents, setLoading, setError, loading } = useAgentsStore()
  const [activeTab, setActiveTab] = useState("files")

  // Load agents on mount
  useEffect(() => {
    if (isConnected && client) {
      loadAgents()
    }
  }, [isConnected, client])

  const loadAgents = useCallback(async () => {
    if (!client) return
    setLoading(true)
    try {
      const result = await client.listAgents()
      if (result.type === "res" && result.ok) {
        const payload = result.payload as { defaultId: string; mainKey: string; scope: string; agents: any[] }
        if (payload?.agents) {
          setAgents({
            defaultId: payload.defaultId,
            mainKey: payload.mainKey,
            scope: payload.scope,
            agents: payload.agents,
          })
        }
      }
    } catch (e) {
      console.error("[Agents] Failed to load:", e)
      setError("Failed to load agents")
    } finally {
      setLoading(false)
    }
  }, [client])

  // Load tools catalog when agents are loaded
  useEffect(() => {
    if (isConnected && client && agents.length > 0) {
      client.getToolsCatalog()
    }
  }, [isConnected, client, agents.length])

  const selectedAgent = agents.find((a) => a.id === selectedAgentId)

  return (
    <div className={cn("flex h-full", className)}>
      {/* Agent list */}
      <div className="w-64 border-r flex flex-col">
        <div className="p-3 border-b">
          <h2 className="font-medium flex items-center gap-2">
            <Cpu className="h-4 w-4 text-primary" />
            Agents
          </h2>
        </div>

        <ScrollArea className="flex-1">
          <div className="p-2 space-y-1">
            {loading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            ) : agents.length === 0 ? (
              <div className="text-center text-sm text-muted-foreground py-8">No agents found</div>
            ) : (
              agents.map((agent) => (
                <button
                  key={agent.id}
                  className={cn(
                    "w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors",
                    agent.id === selectedAgentId
                      ? "bg-muted border"
                      : "hover:bg-muted/50 border border-transparent"
                  )}
                  onClick={() => setSelectedAgent(agent.id)}
                >
                  <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
                    {agent.identity?.emoji ? (
                      <span className="text-lg">{agent.identity.emoji}</span>
                    ) : (
                      <Cpu className="h-4 w-4 text-primary" />
                    )}
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-medium truncate">
                      {agent.identity?.name || agent.name || agent.id}
                    </div>
                    <div className="text-xs text-muted-foreground font-mono truncate">
                      {agent.id}
                    </div>
                  </div>
                </button>
              ))
            )}
          </div>
        </ScrollArea>
      </div>

      {/* Agent detail */}
      <div className="flex-1 flex flex-col">
        {selectedAgent ? (
          <div className="flex flex-col h-full">
            {/* Agent header */}
            <div className="p-4 border-b">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-primary/10 flex items-center justify-center">
                  {selectedAgent.identity?.emoji ? (
                    <span className="text-xl">{selectedAgent.identity.emoji}</span>
                  ) : (
                    <Cpu className="h-5 w-5 text-primary" />
                  )}
                </div>
                <div>
                  <h3 className="font-medium">
                    {selectedAgent.identity?.name || selectedAgent.name || selectedAgent.id}
                  </h3>
                  <div className="text-xs text-muted-foreground font-mono">{selectedAgent.id}</div>
                </div>
              </div>
            </div>

            {/* Tabs */}
            <div className="flex-1 flex flex-col p-4">
              <Tabs value={activeTab} onValueChange={setActiveTab} className="flex-1 flex flex-col">
                <TabsList className="mb-4">
                  <TabsTrigger value="files" className="text-sm">
                    Files
                  </TabsTrigger>
                  <TabsTrigger value="tools" className="text-sm">
                    Tools
                  </TabsTrigger>
                  <TabsTrigger value="skills" className="text-sm">
                    Skills
                  </TabsTrigger>
                </TabsList>

                <ScrollArea className="flex-1">
                  {selectedAgent ? (
                    <>
                      <TabsContent value="files" className="h-full m-0">
                        <AgentFilesTab agentId={selectedAgentId!} />
                      </TabsContent>
                      <TabsContent value="tools" className="h-full m-0">
                        <AgentToolsTab />
                      </TabsContent>
                      <TabsContent value="skills" className="h-full m-0">
                        <AgentSkillsTab />
                      </TabsContent>
                    </>
                  ) : (
                    <div className="flex items-center justify-center py-8">
                      <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                    </div>
                  )}
                </ScrollArea>
                </Tabs>
            </div>
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <Cpu className="h-10 w-10 text-muted-foreground/50 mb-4" />
            <h3 className="text-lg font-medium mb-1">Select an agent</h3>
            <p className="text-sm text-muted-foreground">
              Choose an agent from the list to view details
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
