"""
Task Starter Component

Button and dialog to start OpenClaw tasks from the chat interface.
"""

'use client'

import React, { useState } from 'react'
import { useOpenClawStore } from '@/stores/openclawStore'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Play, Monitor, Settings2 } from 'lucide-react'

export function TaskStarter() {
  const { instances, getOnlineInstances, setWorkspaceActive } = useOpenClawStore()
  const [isOpen, setIsOpen] = useState(false)
  const [taskDescription, setTaskDescription] = useState('')
  const [selectedInstance, setSelectedInstance] = useState('')
  const [policyProfile, setPolicyProfile] = useState('default')
  const [isStarting, setIsStarting] = useState(false)

  const onlineInstances = getOnlineInstances()

  const handleStartTask = async () => {
    if (!taskDescription.trim() || !selectedInstance) return

    setIsStarting(true)

    try {
      // Call API to start task
      const response = await fetch('/api/openclaw/tasks', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          task_prompt: taskDescription,
          instance_id: selectedInstance,
          policy_profile: policyProfile,
        }),
      })

      if (!response.ok) {
        throw new Error('Failed to start task')
      }

      const data = await response.json()

      // Add task to store
      // TODO: Implement proper task creation

      // Switch to workspace mode
      setWorkspaceActive(true)
      setIsOpen(false)
    } catch (error) {
      console.error('Failed to start task:', error)
      alert('Failed to start task. Please try again.')
    } finally {
      setIsStarting(false)
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2">
          <Monitor className="w-4 h-4" />
          <span className="hidden sm:inline">OpenClaw</span>
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-[600px]">
        <DialogHeader>
          <DialogTitle>Start Automation Task</DialogTitle>
          <DialogDescription>
            Use OpenClaw to automate browser tasks and computer interactions.
            The task will run in an isolated VM.
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          {/* Task Description */}
          <div className="grid gap-2">
            <Label htmlFor="task-description">What should I do?</Label>
            <Textarea
              id="task-description"
              placeholder="e.g., Research competitors for AI coding tools. Search Google, visit the top 5 websites, and compile a report of their key features."
              value={taskDescription}
              onChange={(e) => setTaskDescription(e.target.value)}
              rows={4}
            />
          </div>

          {/* Instance Selection */}
          <div className="grid gap-2">
            <Label>VM Instance</Label>
            <Select value={selectedInstance} onValueChange={setSelectedInstance}>
              <SelectTrigger>
                <SelectValue placeholder="Select an instance" />
              </SelectTrigger>
              <SelectContent>
                {onlineInstances.map((instance) => (
                  <SelectItem key={instance.id} value={instance.id}>
                    <div className="flex items-center gap-2">
                      <span>{instance.name}</span>
                      <Badge variant="outline" className="text-xs">
                        {instance.status}
                      </Badge>
                    </div>
                  </SelectItem>
                ))}
                {onlineInstances.length === 0 && (
                  <SelectItem value="none" disabled>
                    No online instances available
                  </SelectItem>
                )}
              </SelectContent>
            </Select>
          </div>

          {/* Policy Profile */}
          <div className="grid gap-2">
            <Label>Security Profile</Label>
            <Select value={policyProfile} onValueChange={setPolicyProfile}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="default">
                  <div>
                    <div className="font-medium">Balanced (Default)</div>
                    <div className="text-xs text-muted-foreground">
                      Approval for destructive actions
                    </div>
                  </div>
                </SelectItem>
                <SelectItem value="strict">
                  <div>
                    <div className="font-medium">Strict</div>
                    <div className="text-xs text-muted-foreground">
                      All actions require approval
                    </div>
                  </div>
                </SelectItem>
                <SelectItem value="unattended">
                  <div>
                    <div className="font-medium">Unattended</div>
                    <div className="text-xs text-muted-foreground">
                      Minimal approvals for trusted tasks
                    </div>
                  </div>
                </SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setIsOpen(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleStartTask}
            disabled={!taskDescription.trim() || !selectedInstance || isStarting}
          >
            {isStarting ? (
              <>Starting...</>
            ) : (
              <>
                <Play className="w-4 h-4 mr-2" />
                Start Task
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
