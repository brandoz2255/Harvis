'use client'

import React, { useEffect, useState, useRef } from 'react'
import { ChevronDown, Cpu, WifiOff, KeyRound } from 'lucide-react'
import { useOpenClawStore } from '@/stores/openclawStore'
import { cn } from '@/lib/utils'

interface ProviderInfo {
  id: string
  label: string
  description?: string
  status: 'online' | 'offline' | 'no_key' | 'online_no_models'
  models: string[]
  reason: string | null
}

export function ModelSelectorDropdown() {
  const { workspaceModel, workspaceModelName, setWorkspaceModel, setWorkspaceModelName } = useOpenClawStore()
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [isOpen, setIsOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const dropdownRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const fetchProviders = async () => {
      try {
        const token = localStorage.getItem('token') || ''
        const res = await fetch('/api/workspace/providers', {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (res.ok) {
          const data = await res.json()
          setProviders(data.providers)
          autoSelectBestProvider(data.providers)
        }
      } catch (err) {
        console.error('Failed to fetch providers:', err)
      } finally {
        setLoading(false)
      }
    }
    fetchProviders()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const autoSelectBestProvider = (providerList: ProviderInfo[]) => {
    const currentProvider = providerList.find(p => p.id === workspaceModel)
    if (currentProvider?.status === 'online') return

    const priority = ['local', 'kimi', 'cloud-ollama', 'nvidia-kimi']
    for (const id of priority) {
      const p = providerList.find(prov => prov.id === id)
      if (p?.status === 'online') {
        setWorkspaceModel(id as 'local' | 'kimi' | 'nvidia-kimi' | 'cloud-ollama')
        if (p.models.length > 0) setWorkspaceModelName(p.models[0])
        return
      }
    }
  }

  const statusIcon = (status: string) => {
    switch (status) {
      case 'online': return <span className="w-2 h-2 rounded-full bg-green-400 shrink-0" />
      case 'no_key': return <KeyRound className="w-3 h-3 text-amber-400 shrink-0" />
      case 'offline': return <WifiOff className="w-3 h-3 text-red-400 shrink-0" />
      default: return <span className="w-2 h-2 rounded-full bg-gray-400 shrink-0" />
    }
  }

  const currentProvider = providers.find(p => p.id === workspaceModel)
  const displayLabel = workspaceModelName
    ? workspaceModelName
    : currentProvider?.label ?? workspaceModel

  const handleSelect = (provider: ProviderInfo, modelName?: string) => {
    if (provider.status !== 'online') return
    setWorkspaceModel(provider.id as 'local' | 'kimi' | 'nvidia-kimi' | 'cloud-ollama')
    setWorkspaceModelName(modelName || provider.models[0] || '')
    setIsOpen(false)
  }

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className={cn(
          'flex items-center gap-1.5 text-[10px] font-medium text-muted-foreground',
          'bg-muted px-2 py-1 rounded-full border border-border/50',
          'hover:bg-muted/80 hover:border-border transition-colors cursor-pointer',
        )}
      >
        <Cpu className="h-2.5 w-2.5" />
        <span className="max-w-[120px] truncate">{displayLabel}</span>
        {currentProvider && statusIcon(currentProvider.status)}
        <ChevronDown className={cn('h-2.5 w-2.5 transition-transform', isOpen && 'rotate-180')} />
      </button>

      {isOpen && (
        <div className={cn(
          'absolute top-full right-0 mt-1 z-50 min-w-[240px]',
          'bg-popover border border-border rounded-lg shadow-lg overflow-hidden',
        )}>
          {loading ? (
            <div className="px-3 py-2 text-xs text-muted-foreground">Checking providers...</div>
          ) : providers.length === 0 ? (
            <div className="px-3 py-2 text-xs text-muted-foreground">No providers available</div>
          ) : (
            providers.map(provider => {
              const isAvailable = provider.status === 'online'
              const isSelected = provider.id === workspaceModel

              if (isAvailable && provider.models.length > 1 && (provider.id === 'local' || provider.id === 'cloud-ollama')) {
                return (
                  <div key={provider.id}>
                    <div className="px-3 py-1.5 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider border-b border-border/50">
                      {provider.label}
                    </div>
                    {provider.models.map(m => (
                      <button
                        key={m}
                        onClick={() => handleSelect(provider, m)}
                        className={cn(
                          'w-full flex items-center gap-2 px-3 py-2 text-left text-xs',
                          'hover:bg-muted/50 transition-colors',
                          isSelected && workspaceModelName === m && 'bg-violet-500/10 text-violet-300',
                        )}
                      >
                        {statusIcon(provider.status)}
                        <span className="truncate">{m}</span>
                      </button>
                    ))}
                  </div>
                )
              }

              return (
                <button
                  key={provider.id}
                  onClick={() => handleSelect(provider)}
                  disabled={!isAvailable}
                  title={provider.reason || undefined}
                  className={cn(
                    'w-full flex items-center gap-2 px-3 py-2 text-left text-xs',
                    'hover:bg-muted/50 transition-colors',
                    !isAvailable && 'opacity-50 cursor-not-allowed',
                    isSelected && 'bg-violet-500/10 text-violet-300',
                  )}
                >
                  {statusIcon(provider.status)}
                  <div className="flex-1 min-w-0">
                    <div className="truncate font-medium">{provider.label}</div>
                    {provider.description && (
                      <div className="text-[10px] text-muted-foreground">{provider.description}</div>
                    )}
                    {!isAvailable && provider.reason && (
                      <div className="text-[10px] text-amber-400/80 mt-0.5">{provider.reason}</div>
                    )}
                  </div>
                </button>
              )
            })
          )}
        </div>
      )}
    </div>
  )
}
