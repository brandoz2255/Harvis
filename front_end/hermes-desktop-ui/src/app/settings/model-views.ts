/**
 * The nested pages under Settings → Model. Each is a `?mview=` value so it is
 * deep-linkable and survives a refresh, the same way the provider views do.
 */
export const MODEL_VIEWS = ['main', 'fallback', 'moa', 'auxiliary'] as const

export type ModelView = (typeof MODEL_VIEWS)[number]

export const MODEL_VIEW_LABELS: Record<ModelView, string> = {
  auxiliary: 'Auxiliary task models',
  fallback: 'Fallback models',
  main: 'Main model',
  moa: 'Mixture of agents'
}

/** Which config.yaml fields of the `model` section render on each page. */
export const MODEL_VIEW_FIELDS: Record<ModelView, readonly string[]> = {
  auxiliary: [],
  fallback: ['fallback_providers'],
  main: [],
  moa: []
}
