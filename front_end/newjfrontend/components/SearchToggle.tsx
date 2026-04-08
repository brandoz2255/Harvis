"use client"

import { useState } from 'react'
import { Search, Globe, AlertTriangle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogFooter,
    DialogTitle,
    DialogDescription,
} from '@/components/ui/dialog'

export type ResearchMode = 'off' | 'live'

interface SearchToggleProps {
    researchMode: ResearchMode
    onModeChange: (mode: ResearchMode) => void
    className?: string
}

export default function SearchToggle({
    researchMode,
    onModeChange,
    className = ''
}: SearchToggleProps) {
    const [showWarning, setShowWarning] = useState(false)
    const [acknowledged, setAcknowledged] = useState(false)

    const handleClick = () => {
        if (researchMode === 'off') {
            if (acknowledged) {
                // Already acknowledged this session — go straight to live
                onModeChange('live')
            } else {
                setShowWarning(true)
            }
        } else {
            onModeChange('off')
        }
    }

    const handleConfirm = () => {
        setShowWarning(false)
        setAcknowledged(true)
        onModeChange('live')
    }

    const handleCancel = () => {
        setShowWarning(false)
    }

    return (
        <>
            <Button
                variant={researchMode === 'off' ? 'outline' : 'default'}
                size="sm"
                onClick={handleClick}
                className={`${className} ${
                    researchMode === 'live'
                        ? 'bg-amber-600 hover:bg-amber-700 text-white border-amber-500'
                        : ''
                }`}
            >
                {researchMode === 'live' ? (
                    <Globe className="h-4 w-4 mr-2" />
                ) : (
                    <Search className="h-4 w-4 mr-2" />
                )}
                {researchMode === 'live' ? 'Web Research' : 'Chat Mode'}
            </Button>

            <Dialog open={showWarning} onOpenChange={setShowWarning}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2">
                            <AlertTriangle className="h-5 w-5 text-amber-500" />
                            Enable Web Research
                        </DialogTitle>
                        <DialogDescription asChild>
                            <div className="space-y-3 pt-2">
                                <p>
                                    This enables <strong>live web research</strong> through OpenClaw.
                                    The agent will search the internet and fetch pages to answer your questions.
                                </p>
                                <div className="rounded-md bg-amber-500/10 border border-amber-500/30 p-3 text-sm">
                                    <ul className="list-disc list-inside space-y-1 text-muted-foreground">
                                        <li>OpenClaw will search and fetch from public websites</li>
                                        <li>Results may include external content</li>
                                        <li>All requests are logged and audited</li>
                                    </ul>
                                </div>
                                <p className="text-xs text-muted-foreground">
                                    You won't be asked again this session.
                                </p>
                            </div>
                        </DialogDescription>
                    </DialogHeader>
                    <DialogFooter>
                        <Button variant="outline" onClick={handleCancel}>
                            Cancel
                        </Button>
                        <Button
                            onClick={handleConfirm}
                            className="bg-amber-600 hover:bg-amber-700 text-white"
                        >
                            <Globe className="h-4 w-4 mr-2" />
                            Enable Web Research
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    )
}
