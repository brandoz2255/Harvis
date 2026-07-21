<script lang="ts">
	// Harvis: VibeCode session list for the OWUI left sidebar (Code mode). Matches the
	// main-chat sidebar shape — the shared top (New Chat / Search) + HarvisNav come from
	// Sidebar.svelte; this only owns the "New session" action + the user's CUMULATIVE
	// VibeCode sessions (their own kind, separate from the main chat), in the slot where
	// the chat list sits. Clicking a row drives the center via ?session=.
	import { getContext, onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import {
		listVibecodeSessions,
		renameVibecodeSession,
		deleteVibecodeSession,
		type VibecodeSession
	} from '$lib/apis/agent-runs';
	import SidebarMore from './SidebarMore.svelte';

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
	$: unviewed = new Set(sessions.filter((s) => viewedAt && isUnviewed(s)).map((s) => s.id));

	const load = async () => {
		sessions = await listVibecodeSessions();
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
	// Routines / Customize open as in-Build right drawers (the vibecode page reads
	// ?panel=…) — they stay inside the coding area instead of bouncing to Agent Studio.
	const openPanel = (panel: 'routines' | 'customize') => {
		const q = new URLSearchParams();
		if (activeSession) q.set('session', activeSession);
		q.set('panel', panel);
		goto(`/harvis/vibecode?${q.toString()}`, { noScroll: true, keepFocus: true });
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
</script>

<div class="flex flex-col px-[0.4375rem]">
	<!-- New session — the code-mode equivalent of "New Chat". -->
	<a
		class="group flex items-center gap-3 rounded-xl px-2.5 py-2 text-blue-600 dark:text-blue-400 font-medium hover:bg-blue-500/10 transition outline-none"
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

	<!-- Code-mode tools: Routines · Customize. (Agent Studio / Model Comparison / etc.
	     live in the footer "More".) -->
	<button
		type="button"
		on:click={() => openPanel('routines')}
		class="w-full flex items-center gap-3 rounded-xl px-2.5 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 transition outline-none"
		aria-label={$i18n.t('Routines')}
	>
		<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="size-4.5 shrink-0"><path d="M12 6v6l4 2M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z" /></svg>
		<span class="self-center translate-y-[0.5px] truncate">{$i18n.t('Routines')}</span>
	</button>
	<button
		type="button"
		on:click={() => openPanel('customize')}
		class="w-full flex items-center gap-3 rounded-xl px-2.5 py-2 text-sm text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 transition outline-none"
		aria-label={$i18n.t('Customize')}
	>
		<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="size-4.5 shrink-0"><path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6" /></svg>
		<span class="self-center translate-y-[0.5px] truncate">{$i18n.t('Customize')}</span>
	</button>

	<!-- Sessions (this kind only — sits where the chat list sits in chat mode). -->
	<div
		class="px-2.5 pt-3 pb-1 text-[0.625rem] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500"
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
						class="w-full text-sm rounded-xl bg-gray-100 dark:bg-gray-850 border-0 px-2 py-1 outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40"
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
					class="group relative flex items-center rounded-xl transition {activeSession === s.id
						? 'bg-gray-100 dark:bg-gray-850'
						: 'hover:bg-gray-100 dark:hover:bg-gray-850'}"
				>
					<button
						type="button"
						on:click={() => open(s.id)}
						aria-current={activeSession === s.id ? 'page' : undefined}
						class="flex-1 min-w-0 flex items-center gap-2 px-2.5 py-1.5 text-sm outline-none {activeSession ===
						s.id
							? 'text-gray-900 dark:text-gray-50 font-medium'
							: 'text-gray-700 dark:text-gray-300'}"
					>
						<span
							class="shrink-0 w-4 flex items-center justify-center"
							title={unviewed.has(s.id) ? $i18n.t('New activity') : $i18n.t('Viewed')}
						>
							<span
								class="size-2 rounded-full {unviewed.has(s.id)
									? 'bg-blue-500 dark:bg-blue-400'
									: 'border border-gray-300 dark:border-gray-600'}"
							></span>
						</span>
						<span class="flex-1 overflow-hidden whitespace-nowrap name-fade text-left translate-y-[0.5px]"
							>{s.title || $i18n.t('Untitled session')}</span
						>
					</button>
					<div
						class="absolute right-1 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition"
					>
						<button
							type="button"
							title={$i18n.t('Rename')}
							class="p-1 rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-200/60 dark:hover:bg-gray-850"
							on:click|stopPropagation={() => startRename(s)}
						>
							<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-3.5"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" stroke-linecap="round" stroke-linejoin="round"/></svg>
						</button>
						<button
							type="button"
							title={$i18n.t('Delete')}
							class="p-1 rounded-lg text-gray-400 hover:text-red-500 hover:bg-gray-200/60 dark:hover:bg-gray-850"
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
