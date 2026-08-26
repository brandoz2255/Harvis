<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { fade } from 'svelte/transition';
	import { getContext } from 'svelte';

	const i18n = getContext('i18n');

	// The strip under the composer. Harvis is not finished software and the person
	// using it should know that without having to be told twice — so this rotates
	// slowly, stays one line, and never asks to be clicked.
	const NOTICES = [
		'Harvis is a work in progress — new features and fixes land regularly.',
		'Answers can be wrong. Check anything that matters before you rely on it.',
		'Something broken or missing? It probably is — this is still being built.',
		'More engines, more tools, and a lot more polish are on the way.'
	];

	// Rotation is slow on purpose: fast enough to be noticed once, slow enough that
	// it never competes with the conversation for attention.
	const ROTATE_MS = 12000;

	let index = 0;
	let timer: ReturnType<typeof setInterval> | null = null;

	// A person who asked the OS for less motion gets the text swapped, not faded.
	let reduceMotion = false;

	onMount(() => {
		try {
			reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false;
		} catch {
			reduceMotion = false;
		}
		timer = setInterval(() => {
			index = (index + 1) % NOTICES.length;
		}, ROTATE_MS);
	});

	onDestroy(() => {
		if (timer) clearInterval(timer);
	});
</script>

<div class="relative h-4 select-none pointer-events-none" aria-live="off">
	{#key index}
		<div
			class="absolute inset-x-0 text-[11px] leading-4 text-gray-500 dark:text-gray-500 text-center line-clamp-1 px-4"
			in:fade={{ duration: reduceMotion ? 0 : 400 }}
			out:fade={{ duration: reduceMotion ? 0 : 250 }}
		>
			{$i18n.t(NOTICES[index])}
		</div>
	{/key}
</div>
