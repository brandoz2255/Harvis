import { atom } from 'nanostores'

import { persistString, storedString } from '@/lib/storage'
import type { ModelOptionProvider } from '@/types/hermes'

/** What the user has hidden. Models that are not listed here show up, so a model
 *  installed later is never swallowed by a choice made before it existed. */
const STORAGE_KEY = 'hermes.desktop.hidden-models'

/** The old format: the list of models the user chose to SHOW. A model installed
 *  after that list was saved was never in it, so it stayed hidden for good. It is
 *  read once, converted when the catalog is first available, then removed. */
const LEGACY_STORAGE_KEY = 'hermes.desktop.visible-models'

/** Models shown per provider in the status-bar dropdown before the user has
 *  customized the list. Backend `models` are already relevance-ordered. */
export const DEFAULT_VISIBLE_PER_PROVIDER = 50

/** Stable key for a provider/model pair (`::` avoids colliding with model ids
 *  that contain a single colon, e.g. `model:tag`). */
export const modelVisibilityKey = (provider: string, model: string): string => `${provider}::${model}`

/** Sentinel key suffix stored when the user explicitly hides a whole provider.
 *  Models that provider gets later stay hidden too, which is what hiding the
 *  provider means. */
export const EMPTY_PROVIDER_SENTINEL = ''

/** Build the sentinel key for a provider whose last model was toggled off. */
export const emptyProviderSentinelKey = (provider: string): string =>
  modelVisibilityKey(provider, EMPTY_PROVIDER_SENTINEL)

/** Check whether a stored key is a provider-hidden sentinel. */
export const isProviderSentinel = (key: string): boolean => key.endsWith('::')

/** A model and its optional `…-fast` sibling, collapsed into one logical row.
 *  `id` is the canonical (base) model; `fastId` is the fast variant if present. */
export interface ModelFamily {
  fastId: string | null
  id: string
}

/** Collapse a provider's model list so a base model and its `…-fast` variant
 *  become a single family (one row, one toggle). Order is preserved by the
 *  base model's position. A `…-fast` model with no base stands on its own. */
export function collapseModelFamilies(models: readonly string[]): ModelFamily[] {
  const present = new Set(models)
  const families: ModelFamily[] = []
  const consumed = new Set<string>()

  for (const model of models) {
    if (consumed.has(model)) {
      continue
    }

    if (/-fast$/i.test(model) && present.has(model.replace(/-fast$/i, ''))) {
      // Represented by its base entry — the base attaches it as `fastId`.
      continue
    }

    if (/-\d{8}$/.test(model) && present.has(model.replace(/-\d{8}$/, ''))) {
      // A date-pinned snapshot superseded by its rolling alias — drop the dupe.
      continue
    }

    const fastId = `${model}-fast`
    const hasFast = present.has(fastId)
    families.push({ fastId: hasFast ? fastId : null, id: model })
    consumed.add(model)

    if (hasFast) {
      consumed.add(fastId)
    }
  }

  return families
}

function loadKeys(storageKey: string): Set<string> | null {
  const raw = storedString(storageKey)

  if (!raw) {
    return null
  }

  try {
    const parsed = JSON.parse(raw)

    return Array.isArray(parsed) ? new Set(parsed.filter((x): x is string => typeof x === 'string')) : null
  } catch {
    return null
  }
}

const initialHidden = loadKeys(STORAGE_KEY)

/** Explicit set of hidden `provider::model` keys (plus provider sentinels), or
 *  null when the user hasn't customized anything. */
export const $hiddenModels = atom<Set<string> | null>(initialHidden)

/** The old show-list, kept only until the catalog is available to convert it. */
export const $legacyVisibleModels = atom<Set<string> | null>(initialHidden ? null : loadKeys(LEGACY_STORAGE_KEY))

export const $modelVisibilityOpen = atom(false)

export function setHiddenModels(keys: Set<string>): void {
  $hiddenModels.set(new Set(keys))
  persistString(STORAGE_KEY, JSON.stringify([...keys]))
}

export function setModelVisibilityOpen(open: boolean): void {
  $modelVisibilityOpen.set(open)
}

/** Models in this provider's list, one key per family (a `-fast` sibling rides
 *  on its base model's key). */
function familyKeys(provider: ModelOptionProvider): string[] {
  return collapseModelFamilies(provider.models ?? []).map(family => modelVisibilityKey(provider.slug, family.id))
}

/** Keys for the model the user is in the middle of using. These are always
 *  visible, so no cap or hide can make the active model vanish from a menu. */
export function inUseKeys(
  providers: readonly ModelOptionProvider[],
  current: { model: string; provider: string }
): Set<string> {
  const keys = new Set<string>()

  if (!current.model) {
    return keys
  }

  for (const provider of providers) {
    if (provider.slug !== current.provider && !(provider.aliases?.includes(current.provider) ?? false)) {
      continue
    }

    for (const family of collapseModelFamilies(provider.models ?? [])) {
      if (family.id === current.model || family.fastId === current.model) {
        keys.add(modelVisibilityKey(provider.slug, family.id))
      }
    }
  }

  return keys
}

/** The default-visible key set: the curated top-N per provider. Used both as
 *  the dropdown fallback and to seed the Edit Models dialog. `inUse` models are
 *  added on top, so the cap can never hide the one the user is using. */
export function defaultVisibleKeys(
  providers: readonly ModelOptionProvider[],
  inUse?: ReadonlySet<string>
): Set<string> {
  const keys = new Set<string>()

  for (const provider of providers) {
    expandProviderDefaults(provider, keys)
  }

  inUse?.forEach(key => keys.add(key))

  return keys
}

/** Add a provider's curated default model keys to `target`. Prefers the
 *  backend's `featured_models` shortlist (one flagship per lab) for aggregator
 *  providers that would otherwise flood the default view with dozens of models;
 *  falls back to the top-N collapsed families when a provider ships no featured
 *  list. Shared by `defaultVisibleKeys` and `resolveVisibleKeys` so the
 *  expansion rule lives in exactly one place. */
function expandProviderDefaults(provider: ModelOptionProvider, target: Set<string>): void {
  const families = collapseModelFamilies(provider.models ?? [])

  const featured = provider.featured_models ?? []

  const defaults = featured.length
    ? families.filter(family => featured.includes(family.id))
    : families.slice(0, DEFAULT_VISIBLE_PER_PROVIDER)

  for (const family of defaults) {
    target.add(modelVisibilityKey(provider.slug, family.id))
  }
}

/** Resolve which keys are visible: everything the user has not hidden. A
 *  provider with no hides of its own (never customized, or newly configured)
 *  gets the curated default, so a 400-model aggregator does not flood the menu.
 *  A provider the user has customized shows every model they did not hide,
 *  including ones installed after they customized it. Hidden-provider
 *  sentinels are bookkeeping and never appear in the result. */
export function resolveVisibleKeys(
  hidden: Set<string> | null,
  providers: readonly ModelOptionProvider[],
  inUse?: ReadonlySet<string>
): Set<string> {
  if (!hidden) {
    return defaultVisibleKeys(providers, inUse)
  }

  const visible = new Set<string>()

  for (const provider of providers) {
    const keys = familyKeys(provider)
    const providerHidden = hidden.has(emptyProviderSentinelKey(provider.slug))

    if (!providerHidden && !keys.some(key => hidden.has(key))) {
      expandProviderDefaults(provider, visible)

      continue
    }

    if (!providerHidden) {
      keys.filter(key => !hidden.has(key)).forEach(key => visible.add(key))
    }
  }

  inUse?.forEach(key => visible.add(key))

  return visible
}

/** The keys to DISPLAY: the resolved visible set. `legacyVisible` is a saved
 *  old-format list not yet converted (it is honoured in the meantime, so the
 *  menu does not flash a different selection before the conversion runs);
 *  `inUse` keys are always included. */
export function effectiveVisibleKeys(
  stored: Set<string> | null,
  providers: readonly ModelOptionProvider[],
  options: { inUse?: ReadonlySet<string>; legacyVisible?: Set<string> | null } = {}
): Set<string> {
  const hidden = stored ?? (options.legacyVisible ? hiddenFromLegacy(options.legacyVisible, providers) : null)

  return resolveVisibleKeys(hidden, providers, options.inUse)
}

function keyProvider(key: string): string {
  const at = key.indexOf('::')

  return at < 0 ? key : key.slice(0, at)
}

/** Turn "these are visible" into "these are hidden". Every model in the catalog
 *  that is not visible becomes an explicit hide; a provider with nothing visible
 *  also gets its sentinel. Hides for models that are missing from the catalog
 *  right now (a provider that is offline, a model that was removed) are kept,
 *  so a flaky catalog fetch cannot quietly un-hide them. */
export function hiddenFromVisible(
  visible: ReadonlySet<string>,
  providers: readonly ModelOptionProvider[],
  previous: ReadonlySet<string> | null
): Set<string> {
  const hidden = new Set<string>()
  const catalog = new Map(providers.map(provider => [provider.slug, new Set(familyKeys(provider))]))

  for (const key of previous ?? []) {
    const keys = catalog.get(keyProvider(key))

    if (!keys || (!isProviderSentinel(key) && !keys.has(key))) {
      hidden.add(key)
    }
  }

  for (const provider of providers) {
    const keys = familyKeys(provider)

    if (keys.length === 0) {
      continue
    }

    keys.filter(key => !visible.has(key)).forEach(key => hidden.add(key))

    if (!keys.some(key => visible.has(key))) {
      hidden.add(emptyProviderSentinelKey(provider.slug))
    }
  }

  return hidden
}

/** The old "show these" list, resolved the way the old code did: a provider the
 *  list never mentions gets its curated default, a hide-all sentinel hides the
 *  provider, an empty list hides everything. */
function resolveLegacyVisibleKeys(
  stored: Set<string>,
  providers: readonly ModelOptionProvider[]
): Set<string> {
  if (stored.size === 0) {
    return new Set()
  }

  const next = new Set(stored)

  for (const provider of providers) {
    const prefix = `${provider.slug}::`
    const mentioned = [...stored].some(key => key.startsWith(prefix))

    if (!mentioned) {
      expandProviderDefaults(provider, next)
    }
  }

  return next
}

/** Convert the old show-list into hides, keeping every choice the user made. */
export function hiddenFromLegacy(legacy: Set<string>, providers: readonly ModelOptionProvider[]): Set<string> {
  return hiddenFromVisible(resolveLegacyVisibleKeys(legacy, providers), providers, null)
}

/** Convert a saved old-format list once a real catalog is in hand. Safe to call
 *  on every catalog load: it does nothing when there is nothing to convert or
 *  the catalog is still empty (converting against nothing would hide nothing
 *  and quietly throw the user's choices away). */
export function migrateLegacyVisibility(providers: readonly ModelOptionProvider[]): void {
  const legacy = $legacyVisibleModels.get()

  if (!legacy || !providers.some(provider => (provider.models ?? []).length > 0)) {
    return
  }

  setHiddenModels(hiddenFromLegacy(legacy, providers))
  $legacyVisibleModels.set(null)
  persistString(LEGACY_STORAGE_KEY, null)
}

/** Compute the next persisted hide set when one model row is toggled. */
export function toggleModelVisibility(
  stored: Set<string> | null,
  providers: readonly ModelOptionProvider[],
  providerSlug: string,
  model: string
): Set<string> {
  const visible = resolveVisibleKeys(stored, providers)
  const key = modelVisibilityKey(providerSlug, model)

  if (visible.has(key)) {
    visible.delete(key)
  } else {
    visible.add(key)
  }

  return hiddenFromVisible(visible, providers, stored)
}

/** Compute the next persisted hide set when a provider's master switch is
 *  flipped. Turning it on shows every model it has now (and any it gets later);
 *  turning it off hides them all and records the sentinel, so models it gets
 *  later stay hidden too. Other providers are untouched. */
export function setProviderVisibility(
  stored: Set<string> | null,
  providers: readonly ModelOptionProvider[],
  providerSlug: string,
  visible: boolean
): Set<string> {
  const shown = resolveVisibleKeys(stored, providers)
  const provider = providers.find(p => p.slug === providerSlug)

  for (const key of [...shown]) {
    if (key.startsWith(`${providerSlug}::`)) {
      shown.delete(key)
    }
  }

  if (visible && provider) {
    familyKeys(provider).forEach(key => shown.add(key))
  }

  return hiddenFromVisible(shown, providers, stored)
}
