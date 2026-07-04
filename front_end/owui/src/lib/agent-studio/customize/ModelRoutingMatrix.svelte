<script lang="ts">
	// Model routing matrix — EXPLICIT task-type → model assignment (Cursor-style).
	// Persisted per-user at settings.harvis.modelRouting via /api/owui/harvis/settings.
	// There is deliberately NO keyword/content-based automatic routing (locked decision):
	// only what the user sets here is stored, and empty = session default.
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { models } from '$lib/stores';

	export let token = '';

	const i18n: any = getContext('i18n');

	const TASKS: { key: string; label: string; desc: string }[] = [
		{ key: 'chat', label: 'Chat', desc: 'New chat sessions.' },
		{ key: 'build', label: 'Build / coding', desc: 'Build workspace + coding runs.' },
		{ key: 'research', label: 'Research', desc: 'Research and web-augmented answers.' },
		{ key: 'notebook', label: 'Notebook', desc: 'Notebook chats, quizzes and podcasts.' },
		{
			key: 'orchestrated',
			label: 'Orchestrated sub-agents',
			desc: 'Default model handed to planner-spawned sub-agents.'
		}
	];

	let routing: Record<string, string> = {};
	let loaded = false;
	let saving = false;
	let savedTick = false;

	const load = async () => {
		const r = await fetch('/api/owui/harvis/settings', {
			headers: { authorization: `Bearer ${token}` }
		})
			.then((x) => (x.ok ? x.json() : null))
			.catch(() => null);
		routing = r?.modelRouting ?? {};
		for (const t of TASKS) routing[t.key] = routing[t.key] ?? '';
		loaded = true;
	};

	const save = async () => {
		if (!loaded || saving) return;
		saving = true;
		const res = await fetch('/api/owui/harvis/settings', {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json', authorization: `Bearer ${token}` },
			body: JSON.stringify({ modelRouting: routing })
		})
			.then((x) => (x.ok ? x.json() : null))
			.catch(() => null);
		saving = false;
		if (res) {
			routing = { ...routing, ...(res.modelRouting ?? {}) };
			savedTick = true;
			setTimeout(() => (savedTick = false), 1500);
		} else {
			toast.error($i18n.t('Could not save model routing.'));
		}
	};

	onMount(load);
</script>

<section class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
	<div class="flex items-center justify-between gap-2 mb-1">
		<div class="flex items-center gap-2">
			<svg class="size-5 text-blue-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h7M4 12h7M4 18h7" /><circle cx="17" cy="6" r="2" /><circle cx="17" cy="12" r="2" /><circle cx="17" cy="18" r="2" /></svg>
			<h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Model routing')}</h2>
		</div>
		{#if savedTick}
			<span class="text-xs font-medium text-green-600 dark:text-green-400">{$i18n.t('Saved')}</span>
		{:else if saving}
			<span class="text-xs text-gray-400">{$i18n.t('Saving…')}</span>
		{/if}
	</div>
	<p class="text-sm text-gray-500 mb-3">
		{$i18n.t(
			'Pick which model handles each kind of task. Routing is explicit — Harvis only uses what you set here and never infers a model from message content.'
		)}
	</p>

	<div class="rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950 divide-y divide-gray-100 dark:divide-gray-850">
		{#each TASKS as t (t.key)}
			<div class="flex flex-col sm:flex-row sm:items-center gap-1.5 sm:gap-3 px-3 py-2.5">
				<div class="min-w-0 sm:w-56 shrink-0">
					<div class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t(t.label)}</div>
					<div class="text-xs text-gray-500">{$i18n.t(t.desc)}</div>
				</div>
				<select
					bind:value={routing[t.key]}
					on:change={save}
					disabled={!loaded}
					class="flex-1 rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent dark:bg-gray-950 px-3 py-1.5 text-sm outline-none focus:border-blue-500 disabled:opacity-50"
				>
					<option value="">{$i18n.t('Session default')}</option>
					{#each $models || [] as m}
						{#if m?.id}
							<option value={m.id}>{m.name || m.id}</option>
						{/if}
					{/each}
				</select>
			</div>
		{/each}
	</div>
</section>
