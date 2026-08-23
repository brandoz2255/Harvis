<script lang="ts">
	// Claude-Desktop-style mode switcher pill for the top of the sidebar.
	// Route-based: clicking a segment navigates to that mode's surface; the active
	// segment is driven by the caller (derived from the current route). Shape/states
	// mirror Claude Desktop's segmented control; colors are Harvis theme tokens.
	import { goto } from '$app/navigation';
	import ChatBubble from '../../icons/ChatBubble.svelte';
	import Code from '../../icons/Code.svelte';

	export let activeMode: 'chat' | 'code' = 'chat';

	// Notebooks is a destination, not a mode — it lives under Projects now.
	const MODES = [
		{ id: 'chat', label: 'Chat', href: '/', icon: ChatBubble },
		{ id: 'code', label: 'Code', href: '/harvis/vibecode', icon: Code }
	];

	const select = (m: { id: string; href: string }) => {
		if (activeMode !== m.id) goto(m.href);
	};
</script>

<div
	class="inline-flex w-full items-center gap-1 rounded-lg p-1 bg-gray-100 dark:bg-[oklch(0.24_0.022_258)]"
	role="tablist"
	aria-label="Mode"
>
	{#each MODES as m}
		<button
			type="button"
			role="tab"
			aria-selected={activeMode === m.id}
			aria-label={m.label}
			title={m.label}
			class="flex h-7 items-center justify-center rounded-lg text-xs font-medium transition-all duration-200 outline-none {activeMode ===
			m.id
				? 'grow gap-1.5 px-3 bg-white dark:bg-[oklch(0.32_0.024_258)] text-blue-600 dark:text-blue-400'
				: 'shrink-0 px-2 text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)]'}"
			on:click={() => select(m)}
		>
			<svelte:component this={m.icon} className="size-4 shrink-0" strokeWidth="1.8" />
			{#if activeMode === m.id}<span class="whitespace-nowrap">{m.label}</span>{/if}
		</button>
	{/each}
</div>
