"use client"

import { Search } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface SearchToggleProps {
    isResearchMode: boolean
    onToggle: (enabled: boolean) => void
    className?: string
}

export default function SearchToggle({
    isResearchMode,
    onToggle,
    className = ''
}: SearchToggleProps) {
    return (
        <Button
            variant={isResearchMode ? "default" : "outline"}
            size="sm"
            onClick={() => onToggle(!isResearchMode)}
            className={className}
        >
            <Search className="h-4 w-4 mr-2" />
            {isResearchMode ? 'Research Mode' : 'Chat Mode'}
        </Button>
    )
}
