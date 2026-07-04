<script lang="ts">
	// Agent presets — a named preset = {model, engine, run-mode default, persona}.
	// Stored per-user at settings.harvis.presets (+ activePresetId) via
	// /api/owui/harvis/settings. Create / edit / delete / apply.
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { models } from '$lib/stores';

	export let token = '';

	const i18n: any = getContext('i18n');

	const ENGINES: { id: string; label: string }[] = [
		{ id: '', label: 'Session default' },
		{ id: 'native', label: 'Harvis native' },
		{ id: 'opencode', label: 'OpenCode' },
		{ id: 'codex', label: 'Codex' },
		{ id: 'claude-code', label: 'Claude Code' },
		{ id: 'hermes-agent', label: 'Hermes Agent' }
	];
	const RUN_MODES = [
		{ id: 'auto', label: 'Auto' },
		{ id: 'plan', label: 'Plan' }
	];

	let presets: any[] = [];
	let activePresetId: string | null = null;
	let loaded = false;
	let saving = false;

	let showForm = false;
	let editingId: string | null = null;
	let pName = '';
	let pModel = '';
	let pEngine = '';
	let pRunMode = 'auto';
	let pPersona = '';

	const engineLabel = (id: string) => ENGINES.find((e) => e.id === id)?.label ?? id;

	const load = async () => {
		const r = await fetch('/api/owui/harvis/settings', {
			headers: { authorization: `Bearer ${token}` }
		})
			.then((x) => (x.ok ? x.json() : null))
			.catch(() => null);
		presets = Array.isArray(r?.presets) ? r.presets : [];
		activePresetId = r?.activePresetId ?? null;
		loaded = true;
	};

	const persist = async (body: any) => {
		saving = true;
		const res = await fetch('/api/owui/harvis/settings', {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json', authorization: `Bearer ${token}` },
			body: JSON.stringify(body)
		})
			.then((x) => (x.ok ? x.json() : null))
			.catch(() => null);
		saving = false;
		if (res) {
			presets = Array.isArray(res.presets) ? res.presets : presets;
			activePresetId = res.activePresetId ?? null;
			return true;
		}
		toast.error($i18n.t('Could not save presets.'));
		return false;
	};

	const resetForm = () => {
		pName = pModel = pPersona = '';
		pEngine = '';
		pRunMode = 'auto';
		editingId = null;
		showForm = false;
	};

	const editPreset = (p: any) => {
		editingId = p.id;
		pName = p.name ?? '';
		pModel = p.model ?? '';
		pEngine = p.engine ?? '';
		pRunMode = p.runMode ?? 'auto';
		pPersona = p.persona ?? '';
		showForm = true;
	};

	const savePreset = async () => {
		if (!pName.trim() || saving) return;
		const entry = {
			id: editingId ?? (crypto?.randomUUID?.() ?? `${Date.now()}`),
			name: pName.trim(),
			model: pModel,
			engine: pEngine,
			runMode: pRunMode,
			persona: pPersona
		};
		const next = editingId
			? presets.map((p) => (p.id === editingId ? entry : p))
			: [...presets, entry];
		if (await persist({ presets: next })) resetForm();
	};

	const removePreset = async (id: string) => {
		const body: any = { presets: presets.filter((p) => p.id !== id) };
		if (activePresetId === id) body.activePresetId = null;
		await persist(body);
	};

	const applyPreset = async (p: any) => {
		if (await persist({ activePresetId: activePresetId === p.id ? null : p.id })) {
			if (activePresetId === p.id) {
				toast.success($i18n.t('Preset "{{name}}" applied.', { name: p.name }));
			}
		}
	};

	onMount(load);
</script>

<section class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
	<div class="flex items-center justify-between gap-2 mb-1">
		<div class="flex items-center gap-2">
			<svg class="size-5 text-violet-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="7" rx="2" /><rect x="3" y="14" width="18" height="7" rx="2" /><path d="M7 7.5h.01M7 17.5h.01" /></svg>
			<h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Agent presets')}</h2>
		</div>
		<button
			on:click={() => {
				if (showForm) resetForm();
				else {
					resetForm();
					showForm = true;
				}
			}}
			class="inline-flex items-center gap-1.5 rounded-full bg-blue-600 text-white px-3 py-1.5 text-xs font-medium hover:bg-blue-700 transition"
		>
			<svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
			{$i18n.t('New preset')}
		</button>
	</div>
	<p class="text-sm text-gray-500 mb-3">
		{$i18n.t(
			'A preset bundles a model, engine, run-mode default and persona under one name. Apply one to make it the starting point for new agents.'
		)}
	</p>

	{#if showForm}
		<div class="rounded-xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 p-3 mb-3 space-y-2">
			<input
				bind:value={pName}
				placeholder={$i18n.t('Preset name, e.g. "Careful reviewer"')}
				class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-1.5 text-sm outline-none focus:border-blue-500"
			/>
			<div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
				<select
					bind:value={pModel}
					class="rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent dark:bg-gray-950 px-3 py-1.5 text-sm outline-none focus:border-blue-500"
				>
					<option value="">{$i18n.t('Model: session default')}</option>
					{#each $models || [] as m}
						{#if m?.id}
							<option value={m.id}>{m.name || m.id}</option>
						{/if}
					{/each}
				</select>
				<select
					bind:value={pEngine}
					class="rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent dark:bg-gray-950 px-3 py-1.5 text-sm outline-none focus:border-blue-500"
				>
					{#each ENGINES as e (e.id)}
						<option value={e.id}>{$i18n.t('Engine')}: {$i18n.t(e.label)}</option>
					{/each}
				</select>
				<select
					bind:value={pRunMode}
					class="rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent dark:bg-gray-950 px-3 py-1.5 text-sm outline-none focus:border-blue-500"
				>
					{#each RUN_MODES as rm (rm.id)}
						<option value={rm.id}>{$i18n.t('Run mode')}: {$i18n.t(rm.label)}</option>
					{/each}
				</select>
			</div>
			<textarea
				bind:value={pPersona}
				rows="4"
				placeholder={$i18n.t('Persona / system prompt — tone, priorities, constraints for this agent')}
				class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-500 resize-y"
			></textarea>
			<div class="flex justify-end gap-2">
				<button on:click={resetForm} class="rounded-lg px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-850">{$i18n.t('Cancel')}</button>
				<button
					on:click={savePreset}
					disabled={saving || !pName.trim()}
					class="rounded-lg bg-blue-600 text-white px-4 py-1.5 text-sm font-medium hover:bg-blue-700 disabled:opacity-40"
					>{saving ? $i18n.t('Saving…') : editingId ? $i18n.t('Save') : $i18n.t('Create preset')}</button
				>
			</div>
		</div>
	{/if}

	{#if presets.length}
		<div class="space-y-1.5">
			{#each presets as p (p.id)}
				<div class="group rounded-xl border {activePresetId === p.id ? 'border-violet-300 dark:border-violet-800' : 'border-gray-100 dark:border-gray-850'} bg-white dark:bg-gray-950 px-3 py-2.5">
					<div class="flex items-center gap-3">
						<div class="min-w-0 flex-1">
							<div class="flex items-center gap-2">
								<span class="truncate text-sm font-medium text-gray-800 dark:text-gray-100">{p.name}</span>
								{#if activePresetId === p.id}
									<span class="shrink-0 text-[10px] font-medium text-violet-600 dark:text-violet-400 bg-violet-50 dark:bg-violet-950 rounded px-1.5 py-0.5">{$i18n.t('Active')}</span>
								{/if}
							</div>
							<div class="flex flex-wrap items-center gap-1.5 mt-1">
								<span class="text-[10px] text-gray-500 bg-gray-100 dark:bg-gray-850 rounded px-1.5 py-0.5 font-mono">{p.model || $i18n.t('session model')}</span>
								<span class="text-[10px] text-gray-500 bg-gray-100 dark:bg-gray-850 rounded px-1.5 py-0.5">{$i18n.t(engineLabel(p.engine || ''))}</span>
								<span class="text-[10px] text-gray-500 bg-gray-100 dark:bg-gray-850 rounded px-1.5 py-0.5">{p.runMode === 'plan' ? $i18n.t('Plan') : $i18n.t('Auto')}</span>
							</div>
						</div>
						<button
							on:click={() => applyPreset(p)}
							class="shrink-0 rounded-lg px-2.5 py-1 text-xs font-medium transition {activePresetId === p.id
								? 'text-violet-600 dark:text-violet-400 hover:bg-violet-50 dark:hover:bg-violet-950'
								: 'text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-850'}"
							>{activePresetId === p.id ? $i18n.t('Deactivate') : $i18n.t('Apply')}</button
						>
						<button on:click={() => editPreset(p)} title={$i18n.t('Edit')} class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-blue-500 transition shrink-0">
							<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" /></svg>
						</button>
						<button on:click={() => removePreset(p.id)} title={$i18n.t('Delete')} class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition shrink-0">
							<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></svg>
						</button>
					</div>
					{#if p.persona}
						<div class="mt-1.5 text-xs text-gray-500 line-clamp-2">{p.persona}</div>
					{/if}
				</div>
			{/each}
		</div>
	{:else if !showForm && loaded}
		<div class="text-xs text-gray-500 py-1">{$i18n.t('No presets yet. Create one to reuse a model + persona setup.')}</div>
	{/if}
</section>
