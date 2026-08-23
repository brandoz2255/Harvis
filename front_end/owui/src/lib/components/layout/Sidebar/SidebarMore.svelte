<script lang="ts">
	// "More" — control-surface tools that aren't session types. Clicking pops a floating
	// island ABOVE the button (portaled to <body> + fixed-positioned so the
	// sidebar's overflow-x-hidden doesn't clip it). Each item keeps its icon.
	import { goto } from '$app/navigation';

	export let activePath: string = '';
	// `bold` emphasizes the "More" toggle label (used when it sits inline under Customize).
	export let bold = false;

	let btnEl: HTMLButtonElement;
	let open = false;
	let pos = { bottom: 0, left: 0, maxH: 0 };

	// `wip: true` renders a small chip so you know a surface is unfinished BEFORE you
	// click it. Remove the flag (and the matching one in agent-studio/surfaces.ts) when
	// the surface is ready.
	const ITEMS = [
		{
			label: 'Agent Studio',
			href: '/harvis/agent-studio',
			d: 'M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z',
			match: (p: string) => p === '/harvis/agent-studio',
			wip: true
		},
		{
			label: 'Neural Map',
			href: '/harvis/agent-studio/global-map',
			d: 'M18 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 22a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM8.6 13.5l6.8 3.9M15.4 6.6l-6.8 3.9',
			match: (p: string) => p.startsWith('/harvis/agent-studio/global-map'),
			wip: true
		},
		{
			label: 'Model Comparison',
			href: '/harvis/agent-studio/model-comparison',
			d: 'M12 20V10M18 20V4M6 20v-4',
			match: (p: string) => p.startsWith('/harvis/agent-studio/model-comparison')
		}
		// Cookbook + Settings removed — both live directly in the footer bottom-nav cluster now.
	];

	const toggle = () => {
		if (!open && btnEl) {
			const r = btnEl.getBoundingClientRect();
			// Open UPWARD: anchor the island's bottom edge just above the button (the
			// toggle lives in the footer cluster, so downward would run off-screen).
			// maxH caps the panel so it can never overflow the top of the viewport.
			pos = {
				bottom: window.innerHeight - r.top + 6,
				left: r.left,
				maxH: Math.max(120, r.top - 14)
			};
		}
		open = !open;
	};
	const go = (it: any) => {
		open = false;
		if (it.action) {
			it.action();
			return;
		}
		goto(it.href);
	};

	// Portal the flyout to <body> so `fixed` spans the real viewport (the sidebar clips x-overflow).
	const portal = (node: HTMLElement) => {
		document.body.appendChild(node);
		return {
			destroy() {
				if (node.parentNode) node.parentNode.removeChild(node);
			}
		};
	};
	const onKey = (e: KeyboardEvent) => {
		if (e.key === 'Escape') open = false;
	};
</script>

<svelte:window on:keydown={onKey} />

<div class="px-[0.4375rem]">
	<button
		bind:this={btnEl}
		type="button"
		class="group flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-sm font-primary text-left transition outline-none {open
			? 'bg-gray-100 dark:bg-gray-850 text-gray-900 dark:text-gray-100'
			: 'text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)] hover:text-gray-900 dark:hover:text-gray-100'}"
		on:click={toggle}
		aria-expanded={open}
		aria-label="More"
	>
		<svg
			xmlns="http://www.w3.org/2000/svg"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
			stroke-linejoin="round"
			class="size-4.5 shrink-0"
		>
			<circle cx="5" cy="12" r="1" />
			<circle cx="12" cy="12" r="1" />
			<circle cx="19" cy="12" r="1" />
		</svg>
		<span
			class="flex-1 self-center translate-y-[0.5px] {bold
				? 'font-semibold text-gray-800 dark:text-gray-100'
				: ''}">More</span
		>
		<svg
			xmlns="http://www.w3.org/2000/svg"
			viewBox="0 0 24 24"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
			stroke-linejoin="round"
			class="size-4 shrink-0 text-gray-400 transition-transform duration-150 {open ? 'translate-x-0.5' : ''}"
		>
			<path d="M9 18l6-6-6-6" />
		</svg>
	</button>
</div>

{#if open}
	<div use:portal>
		<!-- click-away backdrop -->
		<button class="fixed inset-0 z-[80] cursor-default" on:click={() => (open = false)} aria-label="Close" tabindex="-1"></button>
		<!-- floating island -->
		<div
			class="fixed z-[81] min-w-[210px] overflow-y-auto rounded-2xl border border-gray-200 dark:border-white/10 bg-white dark:bg-gray-900 shadow-lg shadow-black/20 p-1.5"
			style="bottom: {pos.bottom}px; left: {pos.left}px; max-height: {pos.maxH}px;"
		>
			{#each ITEMS as it}
				{@const active = it.match(activePath)}
				<button
					type="button"
					class="group flex w-full items-center gap-3 rounded-xl px-2.5 py-2 text-sm font-primary text-left transition outline-none {active
						? 'bg-blue-500/10 text-blue-600 dark:text-blue-400 font-medium'
						: 'text-gray-700 dark:text-gray-200 hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)]'}"
					on:click={() => go(it)}
					aria-current={active ? 'page' : undefined}
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.8"
						stroke-linecap="round"
						stroke-linejoin="round"
						class="size-4.5 shrink-0"
					>
						<path d={it.d} />
					</svg>
					<span class="flex-1 self-center translate-y-[0.5px]">{it.label}</span>
					{#if it.wip}
						<!-- Plain text, not $i18n: this menu renders `it.label` untranslated too. -->
						<span
							class="shrink-0 text-[10px] px-1.5 py-0.5 rounded-md border border-amber-300 dark:border-amber-800 text-amber-700 dark:text-amber-400"
							title="Under construction">WIP</span
						>
					{/if}
				</button>
			{/each}
		</div>
	</div>
{/if}
