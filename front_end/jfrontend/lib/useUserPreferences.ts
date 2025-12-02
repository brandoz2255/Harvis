/**
 * User Preferences Hook
 * 
 * Manages loading and saving user preferences for VibeCode IDE.
 * Handles theme, panel sizes, default model, and font size.
 */

import { useState, useEffect, useCallback, useRef } from 'react'

export interface UserPreferences {
  user_id: number
  theme: 'light' | 'dark'
  left_panel_width: number
  right_panel_width: number
  terminal_height: number
  default_model: string
  font_size: number
  created_at: string
  updated_at: string
}

interface UseUserPreferencesReturn {
  preferences: UserPreferences | null
  isLoading: boolean
  error: string | null
  updatePreferences: (updates: Partial<Omit<UserPreferences, 'user_id' | 'created_at' | 'updated_at'>>) => Promise<void>
  refreshPreferences: () => Promise<void>
}

const DEFAULT_PREFERENCES: Omit<UserPreferences, 'user_id' | 'created_at' | 'updated_at'> = {
  theme: 'dark',
  left_panel_width: 280,
  right_panel_width: 384,
  terminal_height: 200,
  default_model: 'mistral',
  font_size: 14
}

/**
 * Hook for managing user preferences
 * 
 * Features:
 * - Loads preferences on mount
 * - Debounced saves to avoid excessive API calls
 * - Optimistic updates for better UX
 * - Error handling and retry logic
 */
export function useUserPreferences(): UseUserPreferencesReturn {
  const [preferences, setPreferences] = useState<UserPreferences | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  
  // Debounce timer for saves
  const saveTimerRef = useRef<NodeJS.Timeout | null>(null)
  const pendingUpdatesRef = useRef<Partial<Omit<UserPreferences, 'user_id' | 'created_at' | 'updated_at'>>>({})

  /**
   * Load preferences from API
   */
  const loadPreferences = useCallback(async () => {
    try {
      const token = localStorage.getItem('token')
      if (!token) {
        setError('No authentication token')
        setIsLoading(false)
        return
      }

      const response = await fetch('/api/user/prefs', {
        method: 'GET',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        }
      })

      if (response.ok) {
        const data = await response.json()
        setPreferences(data)
        setError(null)
      } else if (response.status === 404) {
        // No preferences exist yet, use defaults
        console.log('No preferences found, using defaults')
        setError(null)
      } else {
        throw new Error(`Failed to load preferences: ${response.status}`)
      }
    } catch (err) {
      console.error('Error loading preferences:', err)
      setError(err instanceof Error ? err.message : 'Failed to load preferences')
    } finally {
      setIsLoading(false)
    }
  }, [])

  /**
   * Save preferences to API (debounced)
   */
  const savePreferences = useCallback(async (updates: Partial<Omit<UserPreferences, 'user_id' | 'created_at' | 'updated_at'>>) => {
    try {
      const token = localStorage.getItem('token')
      if (!token) {
        throw new Error('No authentication token')
      }

      const response = await fetch('/api/user/prefs', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(updates)
      })

      if (response.ok) {
        const data = await response.json()
        setPreferences(data)
        setError(null)
      } else {
        throw new Error(`Failed to save preferences: ${response.status}`)
      }
    } catch (err) {
      console.error('Error saving preferences:', err)
      setError(err instanceof Error ? err.message : 'Failed to save preferences')
      throw err
    }
  }, [])

  /**
   * Update preferences with debouncing
   * 
   * Accumulates updates and saves them after 500ms of inactivity
   * to avoid excessive API calls during rapid changes (e.g., panel resizing)
   */
  const updatePreferences = useCallback(async (updates: Partial<Omit<UserPreferences, 'user_id' | 'created_at' | 'updated_at'>>) => {
    // Optimistic update
    setPreferences(prev => prev ? { ...prev, ...updates } : null)

    // Accumulate pending updates
    pendingUpdatesRef.current = {
      ...pendingUpdatesRef.current,
      ...updates
    }

    // Clear existing timer
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current)
    }

    // Set new timer for debounced save
    saveTimerRef.current = setTimeout(async () => {
      const toSave = { ...pendingUpdatesRef.current }
      pendingUpdatesRef.current = {}
      
      try {
        await savePreferences(toSave)
      } catch (err) {
        // Revert optimistic update on error
        console.error('Failed to save preferences, reverting:', err)
        await loadPreferences()
      }
    }, 500) // 500ms debounce as per requirements
  }, [savePreferences, loadPreferences])

  /**
   * Refresh preferences from server
   */
  const refreshPreferences = useCallback(async () => {
    setIsLoading(true)
    await loadPreferences()
  }, [loadPreferences])

  // Load preferences on mount
  useEffect(() => {
    loadPreferences()
  }, [loadPreferences])

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current)
      }
    }
  }, [])

  return {
    preferences,
    isLoading,
    error,
    updatePreferences,
    refreshPreferences
  }
}

/**
 * Get default preferences merged with user preferences
 */
export function getPreferencesWithDefaults(preferences: UserPreferences | null): Omit<UserPreferences, 'user_id' | 'created_at' | 'updated_at'> {
  if (!preferences) {
    return DEFAULT_PREFERENCES
  }

  return {
    theme: preferences.theme || DEFAULT_PREFERENCES.theme,
    left_panel_width: preferences.left_panel_width || DEFAULT_PREFERENCES.left_panel_width,
    right_panel_width: preferences.right_panel_width || DEFAULT_PREFERENCES.right_panel_width,
    terminal_height: preferences.terminal_height || DEFAULT_PREFERENCES.terminal_height,
    default_model: preferences.default_model || DEFAULT_PREFERENCES.default_model,
    font_size: preferences.font_size || DEFAULT_PREFERENCES.font_size
  }
}
