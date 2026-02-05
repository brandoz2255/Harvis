"""
OpenClaw Workspace Component

Main workspace view when an OpenClaw task is active.
Displays task progress, live preview, event logs, and artifacts.
"""

'use client'

import React, { useEffect, useState } from 'react'
import { useOpenClawStore } from '@/stores/openclawStore'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import {
  Play,
  Pause,
  Square,
  Minimize2,
  Maximize2,
  Monitor,
  List,
  Image,
  FileText,
  CheckCircle2,
  Circle,
  XCircle,
  Clock,
  AlertCircle,
} from 'lucide-react'

export function OpenClawWorkspace() {
  const {
    currentTask,
    events,
    screenshots,
    isChatMinimized,
    activeTab,
    setActiveTab,
    setChatMinimized,
    getEventsForTask,
    getScreenshotsForTask,
  } = useOpenClawStore()

  const [selectedScreenshot, setSelectedScreenshot] = useState<string | null>(
    null
  )

  if (!currentTask) {
    return (
      <Card className="h-full">
        <CardContent className="flex flex-col items-center justify-center h-full p-8">
          <Monitor className="w-16 h-16 text-muted-foreground mb-4" />
          <h3 className="text-lg font-semibold mb-2">No Active Task</h3>
          <p className="text-muted-foreground text-center">
            Start a task to see the workspace view with live progress and
            previews.
          </p>
        </CardContent>
      </Card>
    )
  }

  const taskEvents = getEventsForTask(currentTask.id)
  const taskScreenshots = getScreenshotsForTask(currentTask.id)

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle2 className="w-5 h-5 text-green-500" />
      case 'running':
        return <Clock className="w-5 h-5 text-blue-500 animate-pulse" />
      case 'failed':
        return <XCircle className="w-5 h-5 text-red-500" />
      case 'cancelled':
        return <Square className="w-5 h-5 text-gray-500" />
      default:
        return <Circle className="w-5 h-5 text-muted-foreground" />
    }
  }

  const getStatusBadge = (status: string) => {
    const variants: Record<string, string> = {
      pending: 'bg-yellow-500/10 text-yellow-500',
      running: 'bg-blue-500/10 text-blue-500',
      paused: 'bg-orange-500/10 text-orange-500',
      completed: 'bg-green-500/10 text-green-500',
      failed: 'bg-red-500/10 text-red-500',
      cancelled: 'bg-gray-500/10 text-gray-500',
    }
    return (
      <Badge className={variants[status] || variants.pending}>
        {status.charAt(0).toUpperCase() + status.slice(1)}
      </Badge>
    )
  }

  return (
    <div className="flex flex-col h-full bg-background">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b">
        <div className="flex items-center gap-4">
          {getStatusIcon(currentTask.status)}
          <div>
            <h2 className="text-lg font-semibold">{currentTask.description}</h2>
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>Task ID: {currentTask.id.slice(0, 8)}</span>
              <Separator orientation="vertical" className="h-4" />
              {getStatusBadge(currentTask.status)}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {currentTask.status === 'running' && (
            <Button variant="outline" size="sm">
              <Pause className="w-4 h-4 mr-2" />
              Pause
            </Button>
          )}
          {(currentTask.status === 'running' ||
            currentTask.status === 'paused') && (
            <Button variant="destructive" size="sm">
              <Square className="w-4 h-4 mr-2" />
              Stop
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setChatMinimized(!isChatMinimized)}
          >
            {isChatMinimized ? (
              <Maximize2 className="w-4 h-4" />
            ) : (
              <Minimize2 className="w-4 h-4" />
            )}
          </Button>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="px-4 py-2 border-b bg-muted/50">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium">Progress</span>
          <span className="text-sm text-muted-foreground">
            {currentTask.progressPercentage.toFixed(0)}%
          </span>
        </div>
        <div className="w-full bg-muted rounded-full h-2">
          <div
            className="bg-primary h-2 rounded-full transition-all duration-300"
            style={{ width: `${currentTask.progressPercentage}%` }}
          />
        </div>
      </div>

      {/* Main Content */}
      <Tabs
        value={activeTab}
        onValueChange={(v) => setActiveTab(v as typeof activeTab)}
        className="flex-1 flex flex-col"
      >
        <TabsList className="mx-4 mt-2">
          <TabsTrigger value="progress">
            <List className="w-4 h-4 mr-2" />
            Progress
          </TabsTrigger>
          <TabsTrigger value="preview">
            <Monitor className="w-4 h-4 mr-2" />
            Preview
          </TabsTrigger>
          <TabsTrigger value="logs">
            <FileText className="w-4 h-4 mr-2" />
            Logs
          </TabsTrigger>
          <TabsTrigger value="artifacts">
            <Image className="w-4 h-4 mr-2" />
            Artifacts ({taskScreenshots.length})
          </TabsTrigger>
        </TabsList>

        {/* Progress Tab */}
        <TabsContent value="progress" className="flex-1 p-4">
          <ScrollArea className="h-full">
            <div className="space-y-2">
              {currentTask.steps.map((step, index) => (
                <Card
                  key={index}
                  className={`transition-colors ${
                    step.status === 'running' ? 'border-blue-500' : ''
                  }`}
                >
                  <CardContent className="p-4">
                    <div className="flex items-start gap-3">
                      <div className="mt-0.5">
                        {step.status === 'completed' && (
                          <CheckCircle2 className="w-5 h-5 text-green-500" />
                        )}
                        {step.status === 'running' && (
                          <Clock className="w-5 h-5 text-blue-500 animate-pulse" />
                        )}
                        {step.status === 'failed' && (
                          <XCircle className="w-5 h-5 text-red-500" />
                        )}
                        {step.status === 'pending' && (
                          <Circle className="w-5 h-5 text-muted-foreground" />
                        )}
                      </div>
                      <div className="flex-1">
                        <div className="flex items-center justify-between">
                          <h4 className="font-medium">{step.description}</h4>
                          <Badge variant="outline">
                            Step {index + 1} of {currentTask.steps.length}
                          </Badge>
                        </div>
                        {step.result && (
                          <p className="text-sm text-muted-foreground mt-1">
                            {step.result}
                          </p>
                        )}
                        {step.errorMessage && (
                          <p className="text-sm text-red-500 mt-1">
                            {step.errorMessage}
                          </p>
                        )}
                        {step.screenshots && step.screenshots.length > 0 && (
                          <div className="flex gap-2 mt-2">
                            {step.screenshots.map((screenshotId) => {
                              const screenshot = taskScreenshots.find(
                                (s) => s.id === screenshotId
                              )
                              return screenshot ? (
                                <button
                                  key={screenshotId}
                                  onClick={() =>
                                    setSelectedScreenshot(screenshot.url)
                                  }
                                  className="relative w-20 h-14 rounded overflow-hidden border hover:border-primary transition-colors"
                                >
                                  <img
                                    src={screenshot.thumbnailUrl || screenshot.url}
                                    alt={screenshot.caption || 'Screenshot'}
                                    className="w-full h-full object-cover"
                                  />
                                </button>
                              ) : null
                            })}
                          </div>
                        )}
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </ScrollArea>
        </TabsContent>

        {/* Preview Tab */}
        <TabsContent value="preview" className="flex-1 p-4">
          <div className="h-full flex flex-col">
            {taskScreenshots.length > 0 ? (
              <>
                <div className="flex-1 bg-muted rounded-lg overflow-hidden relative">
                  <img
                    src={
                      selectedScreenshot ||
                      taskScreenshots[taskScreenshots.length - 1]?.url
                    }
                    alt="Latest screenshot"
                    className="w-full h-full object-contain"
                  />
                </div>
                <div className="mt-4 flex gap-2 overflow-x-auto pb-2">
                  {taskScreenshots.map((screenshot) => (
                    <button
                      key={screenshot.id}
                      onClick={() => setSelectedScreenshot(screenshot.url)}
                      className={`flex-shrink-0 w-24 h-16 rounded overflow-hidden border-2 transition-colors ${
                        selectedScreenshot === screenshot.url
                          ? 'border-primary'
                          : 'border-muted hover:border-muted-foreground'
                      }`}
                    >
                      <img
                        src={screenshot.thumbnailUrl || screenshot.url}
                        alt={screenshot.caption || 'Screenshot'}
                        className="w-full h-full object-cover"
                      />
                    </button>
                  ))}
                </div>
              </>
            ) : (
              <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground">
                <Image className="w-16 h-16 mb-4" />
                <p>No screenshots available yet</p>
              </div>
            )}
          </div>
        </TabsContent>

        {/* Logs Tab */}
        <TabsContent value="logs" className="flex-1 p-4">
          <ScrollArea className="h-full">
            <div className="space-y-1 font-mono text-sm">
              {taskEvents.map((event, index) => (
                <div
                  key={index}
                  className="flex gap-2 py-1 border-b border-muted/50"
                >
                  <span className="text-muted-foreground">
                    {new Date(event.createdAt).toLocaleTimeString()}
                  </span>
                  <Badge variant="outline" className="text-xs">
                    {event.type}
                  </Badge>
                  <span className="flex-1">
                    {event.payload.message ||
                      event.payload.step_description ||
                      JSON.stringify(event.payload).slice(0, 100)}
                  </span>
                </div>
              ))}
              {taskEvents.length === 0 && (
                <div className="text-center text-muted-foreground py-8">
                  No events yet
                </div>
              )}
            </div>
          </ScrollArea>
        </TabsContent>

        {/* Artifacts Tab */}
        <TabsContent value="artifacts" className="flex-1 p-4">
          <ScrollArea className="h-full">
            <div className="grid grid-cols-3 gap-4">
              {taskScreenshots.map((screenshot) => (
                <Card
                  key={screenshot.id}
                  className="overflow-hidden cursor-pointer hover:ring-2 ring-primary transition-all"
                  onClick={() => setSelectedScreenshot(screenshot.url)}
                >
                  <div className="aspect-video bg-muted">
                    <img
                      src={screenshot.thumbnailUrl || screenshot.url}
                      alt={screenshot.caption || 'Screenshot'}
                      className="w-full h-full object-cover"
                    />
                  </div>
                  <CardContent className="p-3">
                    <p className="text-sm font-medium truncate">
                      {screenshot.caption || 'Screenshot'}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {new Date(screenshot.takenAt).toLocaleString()}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {screenshot.width}x{screenshot.height}
                    </p>
                  </CardContent>
                </Card>
              ))}
            </div>
            {taskScreenshots.length === 0 && (
              <div className="text-center text-muted-foreground py-8">
                No artifacts yet
              </div>
            )}
          </ScrollArea>
        </TabsContent>
      </Tabs>
    </div>
  )
}
