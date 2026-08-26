<script lang="ts">
	// Two composer surfaces for the local CAD lane, in one component because they
	// share a capability probe and are mutually exclusive:
	//
	//   1. the capability chip — shown only while the CAD marker is actually in the
	//      composer, so it reads as "this turn goes to the local kernel, in mm"
	//      rather than as a permanent badge nobody reads after the first day;
	//   2. the intent suggestion — a dismissible offer when the text plainly names a
	//      shape this engine can build. It never switches mode on its own; the user
	//      clicks, and the click does exactly what the + menu does.
	//
	// If the lane is off, or the engine is not answering, this renders nothing at
	// all. Offering to build a part on a server that cannot build it is worse than
	// staying quiet.
	import { getContext, onMount } from 'svelte';
	import { getCadCapability } from '$lib/apis/cad';
	import Cube from '$lib/components/icons/Cube.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';

	const i18n: any = getContext('i18n');

	export let prompt: string = '';
	export let onInsertMarker: () => void = () => {};

	// The composer remounts per chat and `prompt` changes on every keystroke, so the
	// probe is cached at module scope — one request per page load, not per character.
	let capPromise: Promise<any> | null = null;
	let recipes: string[] = [];
	let ready = false;
	let dismissed = false;

	onMount(async () => {
		if (!capPromise) capPromise = getCadCapability();
		const cap = await capPromise;
		if (cap?.enabled && cap?.engine_reachable) {
			recipes = cap.recipes ?? [];
			ready = recipes.length > 0;
		}
	});

	// Mirrors cad_bridge._EXPLICIT_PREFIX_RE. The marker is what the backend keys on,
	// so the chip is showing a fact about where this turn is going, not a guess.
	const MARKER_RE = /^\s*(?:[\u{1F9CA}\u{1F4D0}\u{1F9F1}\u{1F5A8}]️?\s*)?create\s+cad/iu;

	$: markerPresent = MARKER_RE.test(prompt ?? '');

	// A recipe id like `studded_brick_v1` yields the phrases a person would type for
	// it. Derived from what the engine reports rather than hardcoded, so a recipe the
	// engine drops stops being suggested instead of failing after the click.
	const phrasesFor = (recipe: string): string[] => {
		const words = recipe.replace(/_v\d+$/i, '').split('_').filter(Boolean);
		if (!words.length) return [];
		const full = words.join(' ');
		const last = words[words.length - 1];
		return last !== full ? [full, last] : [full];
	};

	$: phrases = recipes.flatMap(phrasesFor);

	const VERB_RE = /\b(make|build|create|model|design|print|generate)\b/i;

	// Deliberately conservative: a shape name alone ("the brick wall was red") must
	// not fire, and a build verb alone ("design me a bracket") must not either —
	// the lane cannot build a bracket, and offering would be a lie the user only
	// discovers after clicking.
	$: suggest =
		ready &&
		!dismissed &&
		!markerPresent &&
		(prompt ?? '').trim().length > 0 &&
		VERB_RE.test(prompt) &&
		phrases.some((p) => new RegExp(`(?:^|\\s)${p}(?:s|es)?(?:\\s|$|[.,!?])`, 'i').test(prompt));

	// A new prompt deserves a new offer; dismissing one shouldn't silence the feature.
	let lastPrompt = '';
	$: if ((prompt ?? '') !== lastPrompt) {
		if (!(prompt ?? '').startsWith(lastPrompt)) dismissed = false;
		lastPrompt = prompt ?? '';
	}
</script>

{#if ready && markerPresent}
	<div class="mx-2 mt-2.5 flex items-center">
		<div
			class="flex items-center gap-1.5 text-xs px-2 py-1 rounded-lg bg-gray-50 dark:bg-gray-850 text-gray-600 dark:text-gray-300"
		>
			<Cube className="size-3.5" />
			<span>{$i18n.t('Local CAD')}</span>
			<span class="text-gray-400 dark:text-gray-500">·</span>
			<span>{$i18n.t('millimetres')}</span>
		</div>
	</div>
{:else if suggest}
	<div class="mx-2 mt-2.5 flex items-center gap-2">
		<button
			type="button"
			class="flex items-center gap-1.5 text-xs px-2 py-1 rounded-lg border border-gray-100 dark:border-gray-850 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
			on:click={() => {
				dismissed = true;
				onInsertMarker();
			}}
		>
			<Cube className="size-3.5" />
			<span>{$i18n.t('Build this locally as a 3D part')}</span>
		</button>
		<button
			type="button"
			class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 transition"
			aria-label={$i18n.t('Dismiss')}
			on:click={() => {
				dismissed = true;
			}}
		>
			<XMark className="size-3.5" />
		</button>
	</div>
{/if}
