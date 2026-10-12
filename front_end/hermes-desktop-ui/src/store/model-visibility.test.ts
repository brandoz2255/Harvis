import { beforeEach, describe, expect, it } from 'vitest'

import type { ModelOptionProvider } from '@/types/hermes'

import {
  $hiddenModels,
  $legacyVisibleModels,
  collapseModelFamilies,
  DEFAULT_VISIBLE_PER_PROVIDER,
  defaultVisibleKeys,
  effectiveVisibleKeys,
  emptyProviderSentinelKey,
  hiddenFromLegacy,
  inUseKeys,
  isProviderSentinel,
  migrateLegacyVisibility,
  modelVisibilityKey,
  resolveVisibleKeys,
  setProviderVisibility,
  toggleModelVisibility
} from './model-visibility'

const provider = (slug: string, models: string[]): ModelOptionProvider => ({
  models,
  name: slug,
  slug
})

const key = modelVisibilityKey

describe('hidden models, not shown models', () => {
  it('shows a model installed after the user customised the list (the Gemma bug)', () => {
    // The user hid one model while only qwen3 and llama were installed.
    const hidden = new Set([key('local-ollama', 'llama3.2:latest')])

    const visible = effectiveVisibleKeys(hidden, [
      provider('local-ollama', ['qwen3:latest', 'llama3.2:latest', 'gemma4:e2b'])
    ])

    expect(visible.has(key('local-ollama', 'qwen3:latest'))).toBe(true)
    expect(visible.has(key('local-ollama', 'gemma4:e2b'))).toBe(true)
    expect(visible.has(key('local-ollama', 'llama3.2:latest'))).toBe(false)
  })

  it('keeps a model hidden when the user hid it, even after the catalog changes around it', () => {
    const hidden = new Set([key('ollama', 'a')])

    const visible = effectiveVisibleKeys(hidden, [provider('ollama', ['a', 'b', 'c', 'd'])])

    expect(visible.has(key('ollama', 'a'))).toBe(false)
    expect(['b', 'c', 'd'].every(m => visible.has(key('ollama', m)))).toBe(true)
  })

  it('keeps newly configured providers on their curated default', () => {
    const hidden = new Set([key('copilot', 'claude-sonnet-4.6')])

    const visible = effectiveVisibleKeys(hidden, [
      provider('copilot', ['claude-sonnet-4.6', 'gpt-5']),
      provider('local-ollama', ['qwen3:latest', 'llama3.2:latest'])
    ])

    expect(visible.has(key('copilot', 'gpt-5'))).toBe(true)
    expect(visible.has(key('copilot', 'claude-sonnet-4.6'))).toBe(false)
    expect(visible.has(key('local-ollama', 'qwen3:latest'))).toBe(true)
    expect(visible.has(key('local-ollama', 'llama3.2:latest'))).toBe(true)
  })

  it('a hidden provider stays hidden, including models it gets later', () => {
    const hidden = new Set([emptyProviderSentinelKey('nous'), key('nous', 'hermes-a')])

    const visible = effectiveVisibleKeys(hidden, [
      provider('nous', ['hermes-a', 'hermes-brand-new']),
      provider('ollama', ['qwen3:latest'])
    ])

    expect(visible.has(key('nous', 'hermes-a'))).toBe(false)
    expect(visible.has(key('nous', 'hermes-brand-new'))).toBe(false)
    expect(visible.has(key('ollama', 'qwen3:latest'))).toBe(true)
    // The sentinel is bookkeeping, never a visible model.
    expect([...visible].some(isProviderSentinel)).toBe(false)
  })

  it('treats an empty hidden set like an un-customised one (curated defaults)', () => {
    const providers = [provider('openai', ['gpt-a', 'gpt-b'])]

    expect(resolveVisibleKeys(new Set(), providers)).toEqual(defaultVisibleKeys(providers))
  })
})

describe('the visible cap', () => {
  const many = (n: number) => Array.from({ length: n }, (_, i) => `model-${String(i).padStart(3, '0')}`)

  it('caps a provider the user never touched at the default size', () => {
    const visible = defaultVisibleKeys([provider('openrouter', many(80))])

    expect(visible.size).toBe(DEFAULT_VISIBLE_PER_PROVIDER)
    expect(visible.has(key('openrouter', 'model-079'))).toBe(false)
  })

  it('never hides the model in use, however far down the list it is', () => {
    const providers = [provider('openrouter', many(80))]
    const inUse = inUseKeys(providers, { model: 'model-079', provider: 'openrouter' })

    expect(effectiveVisibleKeys(null, providers, { inUse }).has(key('openrouter', 'model-079'))).toBe(true)
    // Even if the user hid it, the model in use stays listed.
    const hidden = new Set([key('openrouter', 'model-079')])

    expect(effectiveVisibleKeys(hidden, providers, { inUse }).has(key('openrouter', 'model-079'))).toBe(true)
  })

  it('finds the in-use model through a provider alias and a -fast variant', () => {
    const providers: ModelOptionProvider[] = [
      { aliases: ['claude'], models: ['opus', 'opus-fast'], name: 'Anthropic', slug: 'anthropic' }
    ]

    expect(inUseKeys(providers, { model: 'opus-fast', provider: 'claude' })).toEqual(
      new Set([key('anthropic', 'opus')])
    )
    expect(inUseKeys(providers, { model: '', provider: 'claude' }).size).toBe(0)
    expect(inUseKeys(providers, { model: 'opus', provider: 'someone-else' }).size).toBe(0)
  })

  it('shows every model a customised provider has, past the cap, except the ones hidden', () => {
    const providers = [provider('openrouter', many(80))]
    // Toggling once writes explicit hides for everything beyond the cap.
    const afterToggle = toggleModelVisibility(null, providers, 'openrouter', 'model-000')

    expect(afterToggle.has(key('openrouter', 'model-000'))).toBe(true)
    expect(afterToggle.has(key('openrouter', 'model-079'))).toBe(true)

    // A model installed later is not in that list, so it shows.
    const grown = [provider('openrouter', [...many(80), 'model-brand-new'])]

    expect(effectiveVisibleKeys(afterToggle, grown).has(key('openrouter', 'model-brand-new'))).toBe(true)
    expect(effectiveVisibleKeys(afterToggle, grown).has(key('openrouter', 'model-000'))).toBe(false)
  })
})

describe('moving from the old show-list', () => {
  const providers = [provider('ollama', ['qwen3:latest', 'llama3.2:latest']), provider('nous', ['hermes-x', 'hermes-y'])]

  it('keeps what the user chose and hides what they left out', () => {
    const legacy = new Set([key('ollama', 'qwen3:latest'), key('nous', 'hermes-x')])
    const hidden = hiddenFromLegacy(legacy, providers)
    const visible = effectiveVisibleKeys(hidden, providers)

    expect(visible).toEqual(legacy)
  })

  it('shows a model installed after the conversion', () => {
    const legacy = new Set([key('ollama', 'qwen3:latest'), key('nous', 'hermes-x')])
    const hidden = hiddenFromLegacy(legacy, providers)
    const grown = [provider('ollama', ['qwen3:latest', 'llama3.2:latest', 'gemma4:e2b']), providers[1]]

    expect(effectiveVisibleKeys(hidden, grown).has(key('ollama', 'gemma4:e2b'))).toBe(true)
    expect(effectiveVisibleKeys(hidden, grown).has(key('ollama', 'llama3.2:latest'))).toBe(false)
  })

  it('gives a provider the old list never mentioned its curated default', () => {
    const legacy = new Set([key('ollama', 'qwen3:latest')])

    expect(effectiveVisibleKeys(hiddenFromLegacy(legacy, providers), providers).has(key('nous', 'hermes-y'))).toBe(true)
  })

  it('keeps an old hide-all provider hidden', () => {
    const legacy = new Set([emptyProviderSentinelKey('nous'), key('ollama', 'qwen3:latest')])
    const visible = effectiveVisibleKeys(hiddenFromLegacy(legacy, providers), providers)

    expect(visible.has(key('nous', 'hermes-x'))).toBe(false)
    expect(visible.has(key('ollama', 'qwen3:latest'))).toBe(true)
  })

  it('keeps an old "hide everything" list hiding everything', () => {
    const visible = effectiveVisibleKeys(hiddenFromLegacy(new Set(), providers), providers)

    expect(visible.size).toBe(0)
  })

  it('displays the old list as-is before it has been converted', () => {
    const legacy = new Set([key('ollama', 'qwen3:latest')])
    const visible = effectiveVisibleKeys(null, [providers[0]], { legacyVisible: legacy })

    expect(visible).toEqual(legacy)
  })

  describe('migrateLegacyVisibility', () => {
    beforeEach(() => {
      $hiddenModels.set(null)
      $legacyVisibleModels.set(null)
      localStorage.clear()
    })

    it('stores the hides, drops the old list, and removes the old storage key', () => {
      localStorage.setItem('hermes.desktop.visible-models', JSON.stringify([key('ollama', 'qwen3:latest')]))
      $legacyVisibleModels.set(new Set([key('ollama', 'qwen3:latest')]))

      migrateLegacyVisibility([providers[0]])

      expect($legacyVisibleModels.get()).toBeNull()
      expect($hiddenModels.get()).toEqual(new Set([key('ollama', 'llama3.2:latest')]))
      expect(JSON.parse(localStorage.getItem('hermes.desktop.hidden-models') ?? 'null')).toEqual([
        key('ollama', 'llama3.2:latest')
      ])
      expect(localStorage.getItem('hermes.desktop.visible-models')).toBeNull()
    })

    it('waits for a real catalog instead of discarding the old choices', () => {
      $legacyVisibleModels.set(new Set([key('ollama', 'qwen3:latest')]))

      migrateLegacyVisibility([])
      migrateLegacyVisibility([provider('ollama', [])])

      expect($legacyVisibleModels.get()).not.toBeNull()
      expect($hiddenModels.get()).toBeNull()
    })

    it('does nothing when there is no old list', () => {
      migrateLegacyVisibility(providers)

      expect($hiddenModels.get()).toBeNull()
    })
  })
})

describe('model families', () => {
  it('folds a date-pinned snapshot into its rolling alias when present', () => {
    const families = collapseModelFamilies(['claude-opus-4-5', 'claude-opus-4-5-20251101'])

    expect(families.map(f => f.id)).toEqual(['claude-opus-4-5'])
  })

  it('keeps a date-pinned snapshot standing alone when it has no alias', () => {
    const families = collapseModelFamilies(['claude-opus-4-5-20251101', 'claude-haiku-4-5-20251001'])

    expect(families.map(f => f.id)).toEqual(['claude-opus-4-5-20251101', 'claude-haiku-4-5-20251001'])
  })

  it('sentinel key helper produces correct format', () => {
    expect(emptyProviderSentinelKey('openai')).toBe('openai::')
    expect(isProviderSentinel('openai::')).toBe(true)
    expect(isProviderSentinel('openai::gpt-4o')).toBe(false)
  })
})

describe('toggleModelVisibility', () => {
  const providers = [provider('openai', ['gpt-a', 'gpt-b']), provider('nous', ['hermes-x', 'hermes-y'])]
  const visibleOf = (hidden: Set<string> | null) => effectiveVisibleKeys(hidden, providers)

  it('hides a model and leaves every other default alone', () => {
    const next = toggleModelVisibility(null, providers, 'openai', 'gpt-a')

    expect(next.has(key('openai', 'gpt-a'))).toBe(true)
    expect(visibleOf(next).has(key('openai', 'gpt-a'))).toBe(false)
    expect(visibleOf(next).has(key('openai', 'gpt-b'))).toBe(true)
    expect(visibleOf(next).has(key('nous', 'hermes-x'))).toBe(true)
    expect(next.has(emptyProviderSentinelKey('openai'))).toBe(false)
  })

  it('shows a hidden model again by toggling it back', () => {
    const hidden = toggleModelVisibility(null, providers, 'openai', 'gpt-a')
    const shown = toggleModelVisibility(hidden, providers, 'openai', 'gpt-a')

    expect(visibleOf(shown).has(key('openai', 'gpt-a'))).toBe(true)
    expect(shown.has(key('openai', 'gpt-a'))).toBe(false)
  })

  it('records a hidden-provider sentinel when the last model of a provider is hidden', () => {
    let hidden: Set<string> | null = null
    hidden = toggleModelVisibility(hidden, providers, 'openai', 'gpt-a')
    hidden = toggleModelVisibility(hidden, providers, 'openai', 'gpt-b')

    expect(hidden.has(emptyProviderSentinelKey('openai'))).toBe(true)
    expect(visibleOf(hidden).has(key('openai', 'gpt-a'))).toBe(false)
    expect(visibleOf(hidden).has(key('openai', 'gpt-b'))).toBe(false)
  })

  it('keeps a hidden provider hidden when a different provider is toggled (regression for #43485)', () => {
    let hidden: Set<string> | null = null
    hidden = toggleModelVisibility(hidden, providers, 'nous', 'hermes-x')
    hidden = toggleModelVisibility(hidden, providers, 'nous', 'hermes-y')
    expect(hidden.has(emptyProviderSentinelKey('nous'))).toBe(true)

    hidden = toggleModelVisibility(hidden, providers, 'openai', 'gpt-a')

    expect(hidden.has(emptyProviderSentinelKey('nous'))).toBe(true)
    expect(visibleOf(hidden).has(key('nous', 'hermes-x'))).toBe(false)
    expect(visibleOf(hidden).has(key('nous', 'hermes-y'))).toBe(false)
  })

  it('re-enabling one model of a hidden provider restores only that model and clears its sentinel', () => {
    let hidden: Set<string> | null = new Set([emptyProviderSentinelKey('openai'), emptyProviderSentinelKey('nous')])

    hidden = toggleModelVisibility(hidden, providers, 'openai', 'gpt-a')

    expect(hidden.has(emptyProviderSentinelKey('openai'))).toBe(false)
    expect(hidden.has(emptyProviderSentinelKey('nous'))).toBe(true)
    expect(visibleOf(hidden).has(key('openai', 'gpt-a'))).toBe(true)
    expect(visibleOf(hidden).has(key('openai', 'gpt-b'))).toBe(false)
  })

  it('re-hiding the last re-enabled model puts the sentinel back (full round-trip)', () => {
    let hidden: Set<string> | null = new Set([emptyProviderSentinelKey('openai')])

    hidden = toggleModelVisibility(hidden, providers, 'openai', 'gpt-a')
    expect(hidden.has(emptyProviderSentinelKey('openai'))).toBe(false)
    hidden = toggleModelVisibility(hidden, providers, 'openai', 'gpt-a')

    expect(hidden.has(emptyProviderSentinelKey('openai'))).toBe(true)
    expect(visibleOf(hidden).has(key('openai', 'gpt-a'))).toBe(false)
  })

  it('keeps hides for models the catalog does not list right now', () => {
    // The provider is offline for one fetch: its hides must survive the next toggle.
    const hidden = new Set([key('ollama', 'offline-model')])

    const next = toggleModelVisibility(hidden, providers, 'openai', 'gpt-a')

    expect(next.has(key('ollama', 'offline-model'))).toBe(true)
  })

  it('tolerates a provider with zero models', () => {
    const ps = [provider('empty', []), provider('openai', ['gpt-a'])]

    const next = toggleModelVisibility(new Set(), ps, 'empty', 'ghost')

    expect([...next].some(k => k.startsWith('empty::'))).toBe(false)
    expect(effectiveVisibleKeys(next, ps).has(key('openai', 'gpt-a'))).toBe(true)
  })
})

describe('featured defaults', () => {
  const featuredProvider = (slug: string, models: string[], featured_models: string[]): ModelOptionProvider => ({
    featured_models,
    models,
    name: slug,
    slug
  })

  it('defaults to the featured shortlist when a provider publishes one', () => {
    const nous = featuredProvider(
      'nous',
      ['anthropic/opus', 'anthropic/haiku', 'google/gemini', 'x-ai/grok'],
      ['anthropic/opus', 'google/gemini', 'x-ai/grok']
    )

    const visible = defaultVisibleKeys([nous])

    expect(visible.has(key('nous', 'anthropic/opus'))).toBe(true)
    expect(visible.has(key('nous', 'google/gemini'))).toBe(true)
    expect(visible.has(key('nous', 'x-ai/grok'))).toBe(true)
    expect(visible.has(key('nous', 'anthropic/haiku'))).toBe(false)
  })

  it('falls back to top-N when a provider ships no featured list', () => {
    const visible = defaultVisibleKeys([provider('ollama', ['qwen3:latest', 'llama3.2:latest'])])

    expect(visible.has(key('ollama', 'qwen3:latest'))).toBe(true)
    expect(visible.has(key('ollama', 'llama3.2:latest'))).toBe(true)
  })

  it('ignores an empty featured list and falls back to top-N', () => {
    const visible = defaultVisibleKeys([featuredProvider('ollama', ['qwen3:latest', 'llama3.2:latest'], [])])

    expect(visible.has(key('ollama', 'qwen3:latest'))).toBe(true)
    expect(visible.has(key('ollama', 'llama3.2:latest'))).toBe(true)
  })
})

describe('setProviderVisibility', () => {
  const providers = [provider('openai', ['gpt-a', 'gpt-b']), provider('nous', ['hermes-x', 'hermes-y'])]

  it('enabling a provider makes every one of its models visible and clears its sentinel', () => {
    const hidden = new Set([emptyProviderSentinelKey('openai')])

    const next = setProviderVisibility(hidden, providers, 'openai', true)

    const visible = effectiveVisibleKeys(next, providers)
    expect(visible.has(key('openai', 'gpt-a'))).toBe(true)
    expect(visible.has(key('openai', 'gpt-b'))).toBe(true)
    expect(next.has(emptyProviderSentinelKey('openai'))).toBe(false)
  })

  it('disabling a provider hides all its models and records the sentinel', () => {
    const next = setProviderVisibility(null, providers, 'openai', false)

    expect(next.has(emptyProviderSentinelKey('openai'))).toBe(true)
    const visible = effectiveVisibleKeys(next, providers)
    expect(visible.has(key('openai', 'gpt-a'))).toBe(false)
    expect(visible.has(key('openai', 'gpt-b'))).toBe(false)
    expect(visible.has(key('nous', 'hermes-x'))).toBe(true)
  })

  it('leaves other providers untouched (their sentinels survive)', () => {
    const hidden = new Set([emptyProviderSentinelKey('nous')])

    const next = setProviderVisibility(hidden, providers, 'openai', true)

    expect(next.has(emptyProviderSentinelKey('nous'))).toBe(true)
    const visible = effectiveVisibleKeys(next, providers)
    expect(visible.has(key('nous', 'hermes-x'))).toBe(false)
    expect(visible.has(key('openai', 'gpt-a'))).toBe(true)
  })

  it('round-trips: enable then disable returns to a clean hidden provider', () => {
    const enabled = setProviderVisibility(null, providers, 'openai', true)
    const disabled = setProviderVisibility(enabled, providers, 'openai', false)

    expect(disabled.has(emptyProviderSentinelKey('openai'))).toBe(true)
    expect(effectiveVisibleKeys(disabled, providers).has(key('openai', 'gpt-a'))).toBe(false)
  })

  it('collapses model families to one key per family', () => {
    const ps = [provider('nous', ['model', 'model-fast'])]

    const next = setProviderVisibility(null, ps, 'nous', false)

    expect(next.has(key('nous', 'model'))).toBe(true)
    // The -fast sibling rides on its base family, so it has no key of its own.
    expect(next.has(key('nous', 'model-fast'))).toBe(false)
  })

  it('a provider with zero models is not stranded as hidden', () => {
    const next = setProviderVisibility(null, [provider('empty', [])], 'empty', true)

    expect(next.has(emptyProviderSentinelKey('empty'))).toBe(false)
  })
})
