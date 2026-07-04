<script lang="ts">
	// Adaptive Space (marathon P8) — launcher: state a task, PICK a template
	// (suggestions only rank; the user always chooses), open the shaped space.
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { WEBUI_NAME } from '$lib/stores';

	const i18n: any = getContext('i18n');

	type Template = {
		key: string;
		name: string;
		description: string;
		steps: number;
		gates?: number;
		panels?: string[];
	};
	type SpaceRow = { id: string; title: string; intent: string; template_key: string; status: string; updated_at: string };

	let templates: Template[] = [];
	let spaces: SpaceRow[] = [];
	let loading = true;
	let intent = '';
	let picked = '';
	let suggestions: Record<string, number> = {};
	let creating = false;
	let error = '';

	const hdrs = () => ({
		Authorization: `Bearer ${localStorage.token}`,
		'Content-Type': 'application/json'
	});

	onMount(async () => {
		try {
			const [tRes, sRes] = await Promise.all([
				fetch('/api/adaptive/templates', { headers: hdrs(), credentials: 'include' }),
				fetch('/api/adaptive/spaces', { headers: hdrs(), credentials: 'include' })
			]);
			if (tRes.ok) templates = (await tRes.json()).templates ?? [];
			if (sRes.ok) spaces = (await sRes.json()).spaces ?? [];
		} catch (e) {
			console.error('adaptive launcher', e);
		}
		loading = false;
	});

	let suggestTimer: ReturnType<typeof setTimeout> | null = null;
	const onIntentInput = () => {
		if (suggestTimer) clearTimeout(suggestTimer);
		suggestTimer = setTimeout(async () => {
			if (!intent.trim()) {
				suggestions = {};
				return;
			}
			try {
				const r = await fetch('/api/adaptive/suggest', {
					method: 'POST',
					headers: hdrs(),
					credentials: 'include',
					body: JSON.stringify({ intent })
				});
				if (r.ok) {
					suggestions = Object.fromEntries(
						((await r.json()).suggestions ?? []).map((s: any) => [s.key, s.score])
					);
				}
			} catch {
				/* suggestions are optional */
			}
		}, 350);
	};

	$: orderedTemplates = [...templates].sort(
		(a, b) => (suggestions[b.key] ?? 0) - (suggestions[a.key] ?? 0)
	);
	$: topSuggested =
		intent.trim() && orderedTemplates.length && (suggestions[orderedTemplates[0].key] ?? 0) > 0
			? orderedTemplates[0].key
			: '';

	const create = async () => {
		if (!picked || creating) return;
		creating = true;
		error = '';
		try {
			const r = await fetch('/api/adaptive/spaces', {
				method: 'POST',
				headers: hdrs(),
				credentials: 'include',
				body: JSON.stringify({ template_key: picked, intent, title: intent.slice(0, 80) })
			});
			if (!r.ok) throw new Error((await r.json())?.detail || 'Create failed');
			const { id } = await r.json();
			goto(`/harvis/adaptive/${id}`);
		} catch (e: any) {
			error = e?.message || 'Create failed';
		}
		creating = false;
	};

	const statusDot = (s: string) =>
		s === 'done' ? 'bg-emerald-500' : s === 'abandoned' ? 'bg-gray-400' : 'bg-blue-500';
</script>

<svelte:head>
	<title>{$i18n.t('Adaptive Space')} • {$WEBUI_NAME}</title>
</svelte:head>

<div class="w-full h-full overflow-y-auto">
	<div class="max-w-4xl mx-auto px-5 py-6 space-y-7">
		<header>
			<h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-100">
				{$i18n.t('Adaptive Space')}
			</h1>
			<p class="text-sm text-gray-500 mt-1">
				{$i18n.t(
					'Tell Harvis the task — it shapes a workspace around it: steps, approval gates, notes, and a to-do list for the parts only you can do.'
				)}
			</p>
		</header>

		<!-- Create -->
		<section
			class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4 space-y-3"
		>
			<input
				class="w-full text-sm bg-transparent border border-gray-200 dark:border-gray-800 rounded-xl px-3 py-2 outline-none focus:border-blue-500/50 text-gray-800 dark:text-gray-100 placeholder:text-gray-400"
				placeholder={$i18n.t('e.g. Connect Harvis to my 3D printer · Research local RAG options · Add dark-mode to settings')}
				bind:value={intent}
				on:input={onIntentInput}
			/>
			<div class="grid grid-cols-1 md:grid-cols-2 gap-2">
				{#each orderedTemplates as t (t.key)}
					<button
						type="button"
						class="text-left rounded-xl border p-3 transition {picked === t.key
							? 'border-blue-500/60 bg-blue-500/5'
							: 'border-gray-100 dark:border-gray-850 hover:border-gray-300 dark:hover:border-gray-700'}"
						on:click={() => (picked = t.key)}
					>
						<div class="flex items-center gap-2">
							<span class="text-sm font-medium text-gray-800 dark:text-gray-100">{t.name}</span>
							{#if topSuggested === t.key}
								<span
									class="text-[10px] px-1.5 py-0.5 rounded-full bg-blue-500/15 text-blue-500 dark:text-blue-300"
									>{$i18n.t('suggested')}</span
								>
							{/if}
							<span class="ml-auto text-[10px] text-gray-400"
								>{t.steps} {$i18n.t('steps')}{#if t.gates} · {t.gates} ✋{/if}</span
							>
						</div>
						<div class="text-xs text-gray-500 mt-1 leading-snug">{t.description}</div>
						{#if t.panels?.length}
							<!-- workspace-shape preview: the panels this template lays out -->
							<div class="flex flex-wrap gap-1 mt-2">
								{#each t.panels as p}
									<span class="text-[10px] px-1.5 py-0.5 rounded border border-gray-200 dark:border-gray-800 text-gray-400">{p}</span>
								{/each}
							</div>
						{/if}
					</button>
				{/each}
			</div>
			<div class="flex items-center gap-2">
				<button
					class="text-sm font-medium px-4 py-1.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white transition disabled:opacity-50"
					disabled={!picked || creating}
					on:click={create}>{creating ? $i18n.t('Creating…') : $i18n.t('Create space')}</button
				>
				<span class="text-[11px] text-gray-400"
					>{$i18n.t('Suggestions only rank — you pick the shape.')}</span
				>
				{#if error}<span class="text-[11px] text-red-500">{error}</span>{/if}
			</div>
		</section>

		<!-- Existing spaces -->
		<section>
			<div class="text-sm font-medium text-gray-800 dark:text-gray-100 mb-2">
				{$i18n.t('Your spaces')}
			</div>
			{#if loading}
				<div class="text-xs text-gray-500 py-2">{$i18n.t('Loading…')}</div>
			{:else if !spaces.length}
				<div class="text-xs text-gray-500 py-2">
					{$i18n.t('No spaces yet — describe a task above to shape one.')}
				</div>
			{:else}
				<div
					class="rounded-2xl border border-gray-100 dark:border-gray-850 divide-y divide-gray-100 dark:divide-gray-850 overflow-hidden"
				>
					{#each spaces as s (s.id)}
						<button
							type="button"
							class="w-full flex items-center gap-3 px-4 py-2.5 text-left hover:bg-gray-50 dark:hover:bg-gray-900 transition group"
							on:click={() => goto(`/harvis/adaptive/${s.id}`)}
						>
							<span class="size-1.5 rounded-full shrink-0 {statusDot(s.status)}"></span>
							<div class="min-w-0 flex-1">
								<div
									class="truncate text-sm text-gray-800 dark:text-gray-100 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition"
								>
									{s.title || s.intent || $i18n.t('Space')}
								</div>
								<div class="truncate text-[11px] text-gray-400">{s.template_key}</div>
							</div>
							<svg
								class="size-4 text-gray-400 shrink-0 group-hover:text-blue-500 transition"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"><path d="m9 18 6-6-6-6" /></svg
							>
						</button>
					{/each}
				</div>
			{/if}
		</section>
	</div>
</div>
