'use client'

import { useEffect } from 'react'
import { useThemeStore } from '@/lib/stores/theme-store'

interface ThemeProviderProps {
  children: React.ReactNode
}

export function ThemeProvider({ children }: ThemeProviderProps) {
  const { theme, getSystemTheme, getEffectiveTheme } = useThemeStore()

  useEffect(() => {
    const root = window.document.documentElement

    // Follow the Harvis shell theme (same-origin → shared localStorage.theme). Its
    // dark themes map to 'dark', its light/paper themes to 'light'; fall back to this
    // app's own store when Harvis is on 'system' or unset.
    const harvisDark = ['dark', 'midnight', 'harvis-dark', 'oled-dark', 'slate', 'oled', 'her']
    const resolve = (): 'light' | 'dark' => {
      let harvis: string | null = null
      try {
        harvis = localStorage.getItem('theme')
      } catch {}
      if (harvis && harvis !== 'system') {
        return harvisDark.includes(harvis) ? 'dark' : 'light'
      }
      return getEffectiveTheme() as 'light' | 'dark'
    }

    const apply = () => {
      const effectiveTheme = resolve()
      root.classList.remove('light', 'dark')
      root.classList.add(effectiveTheme)
      root.setAttribute('data-theme', effectiveTheme)
      // Palette variants: mirror the specific owui theme (warm/airy) so
      // globals.css can swap the default blue palette accordingly.
      let harvis: string | null = null
      try {
        harvis = localStorage.getItem('theme')
      } catch {}
      if (harvis === 'warm' || harvis === 'airy') {
        root.setAttribute('data-nb-theme', harvis)
      } else {
        root.removeAttribute('data-nb-theme')
      }
    }

    apply()

    // Re-apply when the OS preference changes, when the Harvis shell writes a new
    // theme (storage event fires cross-frame same-origin), or on tab focus.
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    mediaQuery.addEventListener('change', apply)
    window.addEventListener('storage', apply)
    window.addEventListener('focus', apply)
    return () => {
      mediaQuery.removeEventListener('change', apply)
      window.removeEventListener('storage', apply)
      window.removeEventListener('focus', apply)
    }
  }, [theme, getSystemTheme, getEffectiveTheme])

  return <>{children}</>
}
