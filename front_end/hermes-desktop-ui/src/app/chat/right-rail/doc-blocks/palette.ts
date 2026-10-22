/** Series colours for charts: first follows the theme accent, the rest are mid-tones that read on light and dark grounds. */
export const SERIES_COLORS = ['var(--color-primary)', '#14a098', '#f59e0b', '#8b5cf6', '#ef4444', '#64748b'] as const

export function seriesColor(index: number): string {
  return SERIES_COLORS[index % SERIES_COLORS.length]
}

/** Cut a label to `max` characters with an ellipsis; the SVG keeps the full text in a <title>. */
export function clip(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, Math.max(1, max - 1))}…` : text
}
