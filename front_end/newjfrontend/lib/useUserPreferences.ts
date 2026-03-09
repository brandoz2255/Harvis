"use client"

import { useState, useEffect, useCallback, useRef } from 'react'

export interface UserPreferences {
  theme: 'light' | 'dark'
  font_size: number
  default_model: string
  left_panel_width: number
  right_panel_width: number
  terminal_height: number
}

const DEFAULT_PREFERENCES: UserPreferences = {
  theme: 'dark',
  font_size: 14,
  default_model: 'mistral',
  left_panel_width: 260,
  right_panel_width: 380,
  terminal_height: 250,
}

export function getPreferencesWithDefaults(prefs: UserPreferences | null): UserPreferences {
  if (!prefs) return { ...DEFAULT_PREFERENCES }
  return { ...DEFAULT_PREFERENCES, ...prefs }
}

export function useUserPreferences() {
  const [preferences, setPreferences] = useState<UserPreferences | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Load preferences from localStorage (or backend)
  useEffect(() => {
    try {
      const stored = localStorage.getItem('vibe-preferences')
      if (stored) {
        setPreferences(JSON.parse(stored))
      } else {
        setPreferences({ ...DEFAULT_PREFERENCES })
      }
    } catch {
      setPreferences({ ...DEFAULT_PREFERENCES })
    }
    setIsLoading(false)
  }, [])

  // Debounced save to localStorage
  const updatePreferences = useCallback((updates: Partial<UserPreferences>) => {
    setPreferences(prev => {
      const updated = { ...getPreferencesWithDefaults(prev), ...updates }

      // Debounce saving
      if (saveTimeoutRef.current) {
        clearTimeout(saveTimeoutRef.current)
      }
      saveTimeoutRef.current = setTimeout(() => {
        try {
          localStorage.setItem('vibe-preferences', JSON.stringify(updated))
        } catch {
          // localStorage may be unavailable
        }
      }, 300)

      return updated
    })
  }, [])

  return {
    preferences: getPreferencesWithDefaults(preferences),
    isLoading,
    updatePreferences,
  }
}
