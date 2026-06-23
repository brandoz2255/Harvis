<script lang="ts">
	// Harvis: VibeCode navigation in the OWUI left sidebar (Code mode).
	// Under "New session": a GLOBAL-destinations block (Agent Studio / Automations /
	// Customize) — these are app-wide, NOT per-session. Then the list of the user's
	// CUMULATIVE VibeCode sessions (their own kind, separate from the main chat),
	// each with hover rename + delete. Clicking a row drives the center via ?session=.
	import { getContext, onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import {
		listVibecodeSessions,
		renameVibecodeSession,
		deleteVibecodeSession,
		type VibecodeSession
	} from '$lib/apis/agent-runs';

	const i18n: any = getContext('i18n');

	let sessions: VibecodeSession[] = [];
	let timer: any = null;
	let editingId = '';
	let editValue = '';

	// Per-session "last viewed" timestamps (localStorage). A session whose updated_at is newer
	// than when you last opened it has UNVIEWED activity (colored dot); else it reads as viewed.
	let viewedAt: Record<string, string> = {};
	try {
		viewedAt = JSON.parse(localStorage.getItem('vibecodeViewedAt') || '{}');
	} catch (_) {}
	const markViewed = (id: string) => {
		viewedAt = { ...viewedAt, [id]: new Date().toISOString() };
		try {
			localStorage.setItem('vibecodeViewedAt', JSON.stringify(viewedAt));
		} catch (_) {}
	};
	const isUnviewed = (s: VibecodeSession): boolean => {
		if (!s.updated_at) return false;
		const v = viewedAt[s.id];
		return !v || new Date(s.updated_at).getTime() > new Date(v).getTime();
	};
	// Reactive set of unviewed session ids — re-derives when sessions OR viewedAt change.
	$: unviewed = new Set(sessions.filter((s) => viewedAt && isUnviewed(s)).map((s) => s.id));

	const load = async () => {
		sessions = await listVibecodeSessions();
		// The session you're currently viewing counts as seen — keep its dot neutral.
		if (activeSession) markViewed(activeSession);
	};
	const schedule = () => {
		timer = setTimeout(async () => {
			await load();
			schedule();
		}, 20000);
	};
	onMount(async () => {
		await load();
		schedule();
	});
	onDestroy(() => clearTimeout(timer));

	$: activeSession = $page?.url?.searchParams?.get('session') ?? '';
	const open = (id: string) => {
		markViewed(id);
		goto(`/harvis/vibecode?session=${id}`);
	};

	const startRename = (s: VibecodeSession) => {
		editingId = s.id;
		editValue = s.title || '';
	};
	const commitRename = async (id: string) => {
		const t = editValue.trim();
		editingId = '';
		if (!t) return;
		try {
			await renameVibecodeSession(id, t);
			await load();
		} catch (_) {}
	};
	const remove = async (s: VibecodeSession) => {
		if (!confirm(`Delete session "${s.title || 'Untitled'}"? This removes its working copy.`)) return;
		try {
			await deleteVibecodeSession(s.id);
			if (activeSession === s.id) goto('/harvis/vibecode');
			await load();
		} catch (_) {}
	};

	// Global destinations (app-wide, not per-session). Each has its OWN icon (stroke path).
	const NAV = [
		{ label: 'Agent Studio', href: '/harvis/agent-studio', icon: 'M3 3h8v10H3zM13 3h8v6h-8zM13 11h8v10h-8zM3 15h8v6H3z' },
		{ label: 'Automations', href: '/automations', icon: 'M13 2 3 14h7v8l10-12h-7z' },
		{ label: 'Customize', href: '/harvis/agent-studio/tuning', icon: 'M21 4H14M10 4H3M21 12H12M8 12H3M21 20H16M12 20H3M14 2v4M8 10v4M16 18v4' }
	];
	// Secondary destinations, revealed by the "More" expander.
	const MORE = [
		{ label: 'Brain', href: '/harvis/agent-studio/brain', icon: 'M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2M6 6h12v12H6zM10 10h4v4h-4z' },
		{ label: 'Neural Map', href: '/harvis/agent-studio/global-map', icon: 'M18 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM18 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM8.6 13.5l6.8 4M15.4 6.5l-6.8 4' },
		{ label: 'Model Comparison', href: '/harvis/agent-studio/model-comparison', icon: 'M3 3v18h18M7 16v-5M12 16V8M17 16v-9' },
		{ label: 'Artifacts', href: '/harvis/agent-studio/activity', icon: 'M21 8l-9-5-9 5 9 5 9-5zM3 8v8l9 5M21 8v8l-9 5' }
	];
	let showMore = false;
</script>

<div class="flex flex-col px-[0.4375rem]">
	<!-- New session (top) -->
	<a
		class="group flex items-center space-x-3 rounded-2xl px-2.5 py-2 text-gray-800 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-900 transition outline-none"
		href="/harvis/vibecode"
		draggable="false"
		aria-label={$i18n.t('New session')}
	>
		<div class="self-center">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
				class="size-4.5"
			>
				<path d="M12 5v14M5 12h14" />
			</svg>
		</div>
		<div class="flex flex-1 self-center translate-y-[0.5px]">
			<div class="self-center text-sm font-primary">{$i18n.t('New session')}</div>
		</div>
	</a>

	<!-- Global destinations (app-wide) — each with its own icon -->
	{#each NAV as item}
		<a
			class="group flex items-center space-x-3 rounded-2xl px-2.5 py-2 transition outline-none hover:bg-gray-100 dark:hover:bg-gray-900 {$page.url
				.pathname === item.href
				? 'bg-gray-100 dark:bg-gray-900 text-gray-900 dark:text-gray-50'
				: 'text-gray-700 dark:text-gray-300'}"
			href={item.href}
			draggable="false"
		>
			<div class="self-center">
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="size-4"><path d={item.icon} /></svg>
			</div>
			<div class="flex flex-1 self-center translate-y-[0.5px]">
				<div class="self-center text-sm font-primary">{$i18n.t(item.label)}</div>
			</div>
		</a>
	{/each}

	<!-- More: a down-arrow expander revealing secondary destinations -->
	<button
		type="button"
		class="group flex items-center space-x-3 rounded-2xl px-2.5 py-2 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-900 transition outline-none"
		on:click={() => (showMore = !showMore)}
		aria-expanded={showMore}
	>
		<div class="self-center">
			<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" class="size-4"><path d="M5 12h.01M12 12h.01M19 12h.01" /></svg>
		</div>
		<div class="flex flex-1 self-center translate-y-[0.5px]">
			<div class="self-center text-sm font-primary">{$i18n.t('More')}</div>
		</div>
		<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="size-4 shrink-0 transition-transform {showMore ? 'rotate-180' : ''}"><path d="M6 9l6 6 6-6" /></svg>
	</button>
	{#if showMore}
		{#each MORE as item}
			<a
				class="group flex items-center space-x-3 rounded-2xl pl-7 pr-2.5 py-1.5 transition outline-none hover:bg-gray-100 dark:hover:bg-gray-900 {$page.url
					.pathname === item.href
					? 'bg-gray-100 dark:bg-gray-900 text-gray-900 dark:text-gray-50'
					: 'text-gray-600 dark:text-gray-400'}"
				href={item.href}
				draggable="false"
			>
				<div class="self-center">
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="size-3.5"><path d={item.icon} /></svg>
				</div>
				<div class="flex flex-1 self-center translate-y-[0.5px]">
					<div class="self-center text-sm font-primary">{$i18n.t(item.label)}</div>
				</div>
			</a>
		{/each}
	{/if}

	<!-- Sessions (this kind only — separate from the main chat) -->
	<div
		class="px-2.5 pt-3 pb-0.5 text-[0.625rem] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500"
	>
		{$i18n.t('Sessions')}
	</div>
	{#if !sessions.length}
		<div class="px-2.5 py-1 text-xs text-gray-400">{$i18n.t('No sessions yet.')}</div>
	{:else}
		{#each sessions as s (s.id)}
			{#if editingId === s.id}
				<div class="px-2.5 py-1">
					<!-- svelte-ignore a11y-autofocus -->
					<input
						class="w-full text-sm rounded-lg bg-gray-100 dark:bg-gray-850 border-0 px-2 py-1 outline-none"
						bind:value={editValue}
						autofocus
						on:keydown={(e) => {
							if (e.key === 'Enter') commitRename(s.id);
							if (e.key === 'Escape') editingId = '';
						}}
						on:blur={() => commitRename(s.id)}
					/>
				</div>
			{:else}
				<div
					class="group relative flex items-center rounded-2xl transition {activeSession === s.id
						? 'bg-gray-100 dark:bg-gray-900'
						: 'hover:bg-gray-100 dark:hover:bg-gray-900'}"
				>
					<button
						type="button"
						on:click={() => open(s.id)}
						aria-current={activeSession === s.id ? 'page' : undefined}
						class="flex-1 min-w-0 flex items-center gap-2 px-2.5 py-1.5 text-sm outline-none {activeSession ===
						s.id
							? 'text-gray-900 dark:text-gray-50 font-medium'
							: 'text-gray-700 dark:text-gray-200'}"
					>
						<span
							class="shrink-0 w-4 flex items-center justify-center"
							title={unviewed.has(s.id) ? $i18n.t('New activity') : $i18n.t('Viewed')}
						>
							<span
								class="size-2 rounded-full {unviewed.has(s.id)
									? 'bg-blue-500'
									: 'border border-gray-300 dark:border-gray-600'}"
							></span>
						</span>
						<span class="flex-1 truncate text-left translate-y-[0.5px]"
							>{s.title || $i18n.t('Untitled session')}</span
						>
					</button>
					<div
						class="absolute right-1 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition"
					>
						<button
							type="button"
							title={$i18n.t('Rename')}
							class="p-1 rounded-md text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-200/60 dark:hover:bg-gray-800"
							on:click|stopPropagation={() => startRename(s)}
						>
							<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-3.5"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" stroke-linecap="round" stroke-linejoin="round"/></svg>
						</button>
						<button
							type="button"
							title={$i18n.t('Delete')}
							class="p-1 rounded-md text-gray-400 hover:text-red-500 hover:bg-gray-200/60 dark:hover:bg-gray-800"
							on:click|stopPropagation={() => remove(s)}
						>
							<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-3.5"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" stroke-linecap="round" stroke-linejoin="round"/></svg>
						</button>
					</div>
				</div>
			{/if}
		{/each}
	{/if}
</div>
