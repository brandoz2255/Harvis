<script lang="ts">
	import { slide } from 'svelte/transition';
	import { quintOut } from 'svelte/easing';
	import ChevronDown from '$lib/components/icons/ChevronDown.svelte';

	export let title = '';
	export let icon: any = null;
	export let open = true;
	export let collapsible = true;
	export let count: number | null = null;
	// localStorage key for the open state; read once at init (SSR is off globally)
	export let persistKey: string | null = null;
	export let className = '';
	export let bodyClassName = 'px-3.5 pb-3.5';

	if (persistKey) {
		const v = localStorage.getItem(persistKey);
		if (v !== null) open = v === 'true';
	}

	const toggle = () => {
		if (!collapsible) return;
		open = !open;
		if (persistKey) localStorage.setItem(persistKey, String(open));
	};
</script>

<section
	class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 {className}"
>
	<div class="flex items-center gap-1 pl-3.5 pr-2 py-2.5">
		<button
			type="button"
			class="flex-1 flex items-center gap-2 text-left min-w-0 {collapsible ? '' : 'cursor-default'}"
			on:click={toggle}
		>
			{#if icon}
				<svelte:component this={icon} className="size-4 text-gray-400 shrink-0" />
			{/if}
			<span class="text-sm font-medium text-gray-800 dark:text-gray-100 truncate">{title}</span>
			{#if count !== null}
				<span class="text-xs text-gray-400 shrink-0">({count})</span>
			{/if}
		</button>
		<!-- actions render OUTSIDE the toggle button (no nested-button a11y bug) -->
		<slot name="actions" />
		{#if collapsible}
			<button
				type="button"
				class="p-1 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
				aria-label={open ? 'Collapse' : 'Expand'}
				on:click={toggle}
			>
				<ChevronDown
					className="size-3.5 transition-transform duration-200 {open ? 'rotate-180' : ''}"
				/>
			</button>
		{/if}
	</div>
	{#if open}
		<div class={bodyClassName} transition:slide={{ duration: 200, easing: quintOut }}>
			<slot />
		</div>
	{/if}
</section>
