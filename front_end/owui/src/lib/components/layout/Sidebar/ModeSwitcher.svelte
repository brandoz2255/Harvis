<script lang="ts">
	// Claude-Desktop-style mode switcher pill for the top of the sidebar.
	// Route-based: clicking a segment navigates to that mode's surface; the active
	// segment is driven by the caller (derived from the current route). Shape/states
	// mirror Claude Desktop's segmented control; colors are Harvis theme tokens.
	import { goto } from '$app/navigation';
	import ChatBubble from '../../icons/ChatBubble.svelte';
	import Code from '../../icons/Code.svelte';
	import { chatActivity } from '$lib/utils/chatActivity';

	export let activeMode: 'chat' | 'code' = 'chat';

	// A run in the OTHER mode is invisible from here: switching modes swaps the whole list
	// out, so a finished Build session leaves no row behind in Chat to carry its dot. The
	// segment itself carries it instead — pulsing while the run is going, solid once it has
	// something to read. The active segment never shows one; its own list already does.
	$: modeActivity = (() => {
		const out = { chat: '', code: '' };
		for (const v of Object.values($chatActivity)) {
			const k = v.kind === 'vibecode' ? 'code' : 'chat';
			// `done` outranks `running` — something finished and unread is the stronger signal.
			if (v.state === 'done') out[k] = 'done';
			else if (v.state === 'running' && out[k] !== 'done') out[k] = 'running';
		}
		return out;
	})();

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
			<span class="relative flex shrink-0">
				<svelte:component this={m.icon} className="size-4 shrink-0" strokeWidth="1.8" />
				{#if activeMode !== m.id && modeActivity[m.id]}
					<span
						class="absolute -top-0.5 -right-0.5 size-1.5 rounded-full bg-blue-500 dark:bg-blue-400 {modeActivity[
							m.id
						] === 'running'
							? 'animate-pulse'
							: ''}"
						title={modeActivity[m.id] === 'running'
							? `Still working in ${m.label}`
							: `Finished in ${m.label}`}
					></span>
				{/if}
			</span>
			{#if activeMode === m.id}<span class="whitespace-nowrap">{m.label}</span>{/if}
		</button>
	{/each}
</div>
