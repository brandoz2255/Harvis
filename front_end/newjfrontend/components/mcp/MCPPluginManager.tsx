"""
MCP Plugin Manager Component

UI for managing MCP server registrations.
"""

'use client'

import React, { useState, useEffect } from 'react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import {
  Plus,
  Settings,
  Trash2,
  Power,
  PowerOff,
  Server,
  Tool,
} from 'lucide-react'

interface MCPServer {
  id: string
  name: string
  description?: string
  host: string
  port?: number
  transport: string
  enabled: boolean
  tools: MCPTool[]
}

interface MCPTool {
  id: string
  name: string
  description?: string
  enabled: boolean
}

export function MCPPluginManager() {
  const [servers, setServers] = useState<MCPServer[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false)

  // Form state
  const [newServerName, setNewServerName] = useState('')
  const [newServerHost, setNewServerHost] = useState('')
  const [newServerPort, setNewServerPort] = useState('')
  const [newServerTransport, setNewServerTransport] = useState('stdio')

  useEffect(() => {
    fetchServers()
  }, [])

  const fetchServers = async () => {
    try {
      const response = await fetch('/api/mcp/servers')
      if (response.ok) {
        const data = await response.json()
        setServers(data)
      }
    } catch (error) {
      console.error('Failed to fetch MCP servers:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleAddServer = async () => {
    try {
      const response = await fetch('/api/mcp/servers', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          name: newServerName,
          host: newServerHost,
          port: newServerPort ? parseInt(newServerPort) : undefined,
          transport: newServerTransport,
        }),
      })

      if (response.ok) {
        await fetchServers()
        setIsAddDialogOpen(false)
        resetForm()
      }
    } catch (error) {
      console.error('Failed to add server:', error)
    }
  }

  const handleToggleServer = async (serverId: string, enabled: boolean) => {
    try {
      const response = await fetch(`/api/mcp/servers/${serverId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ enabled }),
      })

      if (response.ok) {
        await fetchServers()
      }
    } catch (error) {
      console.error('Failed to toggle server:', error)
    }
  }

  const handleDeleteServer = async (serverId: string) => {
    if (!confirm('Are you sure you want to delete this server?')) return

    try {
      const response = await fetch(`/api/mcp/servers/${serverId}`, {
        method: 'DELETE',
      })

      if (response.ok) {
        await fetchServers()
      }
    } catch (error) {
      console.error('Failed to delete server:', error)
    }
  }

  const resetForm = () => {
    setNewServerName('')
    setNewServerHost('')
    setNewServerPort('')
    setNewServerTransport('stdio')
  }

  const getTransportIcon = (transport: string) => {
    switch (transport) {
      case 'stdio':
        return <Server className="w-4 h-4" />
      case 'websocket':
        return <Settings className="w-4 h-4" />
      default:
        return <Server className="w-4 h-4" />
    }
  }

  return (
    <Card className="h-full">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle>MCP Plugins</CardTitle>
            <CardDescription>
              Manage Model Context Protocol servers and tools
            </CardDescription>
          </div>
          <Dialog open={isAddDialogOpen} onOpenChange={setIsAddDialogOpen}>
            <DialogTrigger asChild>
              <Button size="sm">
                <Plus className="w-4 h-4 mr-2" />
                Add Server
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Add MCP Server</DialogTitle>
                <DialogDescription>
                  Register a new MCP server to extend Harvis capabilities.
                </DialogDescription>
              </DialogHeader>

              <div className="grid gap-4 py-4">
                <div className="grid gap-2">
                  <Label htmlFor="name">Server Name</Label>
                  <Input
                    id="name"
                    placeholder="my-mcp-server"
                    value={newServerName}
                    onChange={(e) => setNewServerName(e.target.value)}
                  />
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="host">Host</Label>
                  <Input
                    id="host"
                    placeholder="localhost"
                    value={newServerHost}
                    onChange={(e) => setNewServerHost(e.target.value)}
                  />
                </div>

                <div className="grid gap-2">
                  <Label htmlFor="port">Port (optional)</Label>
                  <Input
                    id="port"
                    type="number"
                    placeholder="8080"
                    value={newServerPort}
                    onChange={(e) => setNewServerPort(e.target.value)}
                  />
                </div>

                <div className="grid gap-2">
                  <Label>Transport</Label>
                  <Select
                    value={newServerTransport}
                    onValueChange={setNewServerTransport}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="stdio">Standard I/O (stdio)</SelectItem>
                      <SelectItem value="sse">Server-Sent Events (SSE)</SelectItem>
                      <SelectItem value="websocket">WebSocket</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <DialogFooter>
                <Button variant="outline" onClick={() => setIsAddDialogOpen(false)}>
                  Cancel
                </Button>
                <Button
                  onClick={handleAddServer}
                  disabled={!newServerName || !newServerHost}
                >
                  Add Server
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </CardHeader>

      <CardContent>
        {isLoading ? (
          <div className="text-center py-8 text-muted-foreground">
            Loading servers...
          </div>
        ) : servers.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">
            <Server className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <p>No MCP servers registered</p>
            <p className="text-sm">Add a server to extend Harvis capabilities</p>
          </div>
        ) : (
          <ScrollArea className="h-[400px]">
            <div className="space-y-4">
              {servers.map((server) => (
                <Card key={server.id}>
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between">
                      <div className="flex items-start gap-3">
                        {getTransportIcon(server.transport)}
                        <div>
                          <div className="flex items-center gap-2">
                            <h4 className="font-medium">{server.name}</h4>
                            <Badge
                              variant={server.enabled ? 'default' : 'secondary'}
                            >
                              {server.enabled ? 'Enabled' : 'Disabled'}
                            </Badge>
                          </div>
                          <p className="text-sm text-muted-foreground">
                            {server.host}
                            {server.port && `:${server.port}`} • {server.transport}
                          </p>
                          {server.tools.length > 0 && (
                            <div className="flex items-center gap-1 mt-2">
                              <Tool className="w-3 h-3" />
                              <span className="text-xs text-muted-foreground">
                                {server.tools.length} tools available
                              </span>
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() =>
                            handleToggleServer(server.id, !server.enabled)
                          }
                        >
                          {server.enabled ? (
                            <Power className="w-4 h-4 text-green-500" />
                          ) : (
                            <PowerOff className="w-4 h-4 text-gray-500" />
                          )}
                        </Button>
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleDeleteServer(server.id)}
                        >
                          <Trash2 className="w-4 h-4 text-red-500" />
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  )
}
