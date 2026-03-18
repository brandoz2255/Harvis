"use client"

import React from 'react'
import { Button } from '@/components/ui/button'
import { RotateCcw } from 'lucide-react'

interface ResetMigrationPromptProps {
  className?: string
}

export default function ResetMigrationPrompt({ className = "" }: ResetMigrationPromptProps) {
  const handleReset = () => {
    localStorage.removeItem('ide-migration-seen')
    console.log('🔄 Migration prompt reset - will show again on next visit')
    // Optionally reload the page to show the prompt immediately
    window.location.reload()
  }

  return (
    <Button
      onClick={handleReset}
      variant="outline"
      size="sm"
      className={`text-xs text-gray-400 hover:text-gray-300 hover:bg-gray-800/50 px-2 py-1 ${className}`}
      title="Reset migration prompt (for testing)"
    >
      <RotateCcw className="w-3 h-3 mr-1" />
      Reset Prompt
    </Button>
  )
}