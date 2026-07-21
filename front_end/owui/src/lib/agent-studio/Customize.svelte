<script lang="ts">
	// Customize — Agent Studio surface for routing, presets, sub-agents, the
	// orchestration pool, and the shared Skills / Connectors panels.
	// The panels live in ./customize/* so the Settings modal ("Customize" group)
	// and this full page mount ONE implementation each — no duplicated logic.
	import { getContext, onMount } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { models } from '$lib/stores';
	// P4/P5 (marathon): model routing matrix + agent presets.
	import ModelRoutingMatrix from './customize/ModelRoutingMatrix.svelte';
	import AgentPresets from './customize/AgentPresets.svelte';
	import SubAgents from './customize/SubAgents.svelte';
	// Shared Customize panels (also mounted by SettingsModal's Customize group).
	import SkillsPanel from './customize/SkillsPanel.svelte';
	import ConnectorsPanel from './customize/ConnectorsPanel.svelte';

	export let mode: 'full' | 'dock' = 'full';

	const i18n: any = getContext('i18n');
	let token = '';

	// ── Orchestration model pool (opt-in) ──────────────────────────────────────
	// When Active, a multi-agent (Agents) run draws models from this pool instead of
	// the session's model. Single-agent turns are unaffected. Persisted per-user.
	let poolActive = false;
	let poolModels: string[] = [];
	let poolModelToAdd = '';
	let poolLoaded = false;
	let poolLoadError = '';
	// Last server-confirmed pool state (successful load or save). A failed save
	// rolls the UI back to this, so the screen never shows a pool the server
	// doesn't actually have.
	let poolSavedActive = false;
	let poolSavedModels: string[] = [];
	const loadPool = async () => {
		// Honest load: never mark the pool "loaded" on a failed GET — presenting an
		// empty pool as truth would let the next save overwrite the real server state.
		poolLoadError = '';
		const r = await fetch('/api/owui/orchestration/pool', {
			headers: { authorization: `Bearer ${token}` }
		})
			.then(async (x) => {
				if (!x.ok) throw new Error(`HTTP ${x.status}`);
				return x.json();
			})
			.catch((e) => {
				poolLoadError = `${e?.message ?? e ?? 'Request failed'}`;
				return null;
			});
		if (r) {
			poolActive = !!r.active;
			poolModels = Array.isArray(r.models) ? r.models : [];
			poolSavedActive = poolActive;
			poolSavedModels = [...poolModels];
			poolLoaded = true;
		}
	};
	const savePool = async () => {
		if (!poolLoaded) return; // never write over server state we haven't seen
		// Snapshot the payload so a slow response commits what was actually sent.
		const active = poolActive;
		const modelsSent = [...poolModels];
		const res = await fetch('/api/owui/orchestration/pool', {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json', authorization: `Bearer ${token}` },
			body: JSON.stringify({ active, models: modelsSent })
		}).catch(() => null);
		if (!res || !res.ok) {
			// Roll the optimistic change back to the last server-confirmed state —
			// the toggle/chips must not keep showing state the server rejected.
			poolActive = poolSavedActive;
			poolModels = [...poolSavedModels];
			toast.error(
				$i18n.t(
					"Couldn't save the orchestration pool — your change was not stored and has been reverted."
				)
			);
			return;
		}
		poolSavedActive = active;
		poolSavedModels = modelsSent;
	};
	const addPoolModel = () => {
		if (!poolLoaded) return;
		const m = poolModelToAdd.trim();
		if (m && !poolModels.includes(m)) {
			poolModels = [...poolModels, m];
			poolModelToAdd = '';
			savePool();
		}
	};
	const removePoolModel = (m: string) => {
		if (!poolLoaded) return;
		poolModels = poolModels.filter((x) => x !== m);
		savePool();
	};
	const togglePoolActive = () => {
		if (!poolLoaded) return;
		poolActive = !poolActive;
		savePool();
	};

	onMount(async () => {
		token = localStorage.getItem('token') || '';
		loadPool();
	});
</script>

<div class="w-full {mode === 'full' ? 'max-w-4xl mx-auto px-1 py-2' : ''} space-y-5">
	{#if mode === 'full'}
		<div>
			<h1 class="text-xl font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Customize')}</h1>
			<p class="text-sm text-gray-500 mt-1">
				{$i18n.t('Create your own skills and add connectors. Your agents can use what you add here.')}
			</p>
		</div>
	{/if}

	<!-- Section nav — nothing buried: jump chips to every settings group. -->
	<nav class="sticky top-0 z-10 -mx-1 px-1 py-1.5 bg-gray-50/90 dark:bg-gray-950/90 backdrop-blur flex flex-wrap gap-1.5">
		{#each [
			{ id: 'sec-routing', label: $i18n.t('Model routing') },
			{ id: 'sec-presets', label: $i18n.t('Presets') },
			{ id: 'sec-subagents', label: $i18n.t('Sub-agents') },
			{ id: 'sec-models', label: $i18n.t('Orchestration') },
			{ id: 'sec-skills', label: $i18n.t('Skills') },
			{ id: 'sec-mcp', label: $i18n.t('Connectors') }
		] as chip (chip.id)}
			<button
				type="button"
				class="text-[11px] px-2.5 py-1 rounded-full border border-gray-200 dark:border-gray-800 text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-100 hover:border-gray-300 dark:hover:border-gray-700 transition"
				on:click={() => document.getElementById(chip.id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
				>{chip.label}</button
			>
		{/each}
	</nav>

	<!-- ── Models & routing ─────────────────────────────────────────────── -->
	<!-- P4: task-type → model routing (explicit user config; never keyword auto-routing) -->
	{#if token}
		<section id="sec-routing" class="scroll-mt-12 rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
			<ModelRoutingMatrix {token} />
		</section>

		<!-- P4: named agent presets (model + persona + engine + run-mode defaults) -->
		<section id="sec-presets" class="scroll-mt-12 rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
			<AgentPresets {token} />
		</section>

		<!-- Custom sub-agents: define specialists the orchestrator delegates to by description -->
		<section id="sec-subagents" class="scroll-mt-12 rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
			<SubAgents {token} />
		</section>
	{/if}

	<!-- Orchestration models (the custom agent model pool) -->
	<section id="sec-models" class="scroll-mt-12 rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
		<div class="flex items-center justify-between gap-2 mb-1">
			<div class="flex items-center gap-2">
				<svg class="size-5 text-violet-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="5" r="2.2" /><circle cx="5" cy="19" r="2.2" /><circle cx="19" cy="19" r="2.2" /><path d="M12 7.2v3m0 0-5 6.6m5-6.6 5 6.6" /></svg>
				<h2 class="text-lg font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Orchestration models')}</h2>
			</div>
			<button
				on:click={togglePoolActive}
				disabled={!poolLoaded}
				class="inline-flex items-center gap-1.5 text-xs font-medium disabled:opacity-40 disabled:cursor-not-allowed {poolActive
					? 'text-green-600 dark:text-green-400'
					: 'text-gray-400'}"
				title={poolLoaded
					? $i18n.t('Use this pool for multi-agent runs')
					: $i18n.t('Pool not loaded yet — changes are disabled so your saved pool stays untouched')}
			>
				<span
					class="relative inline-block w-9 h-5 rounded-full transition {poolActive
						? 'bg-green-500'
						: 'bg-gray-300 dark:bg-gray-700'}"
				>
					<span
						class="absolute top-0.5 size-4 rounded-full bg-white transition-all {poolActive
							? 'left-[1.125rem]'
							: 'left-0.5'}"
					></span>
				</span>
				{poolActive ? $i18n.t('Active') : $i18n.t('Off')}
			</button>
		</div>
		<p class="text-sm text-gray-500 mb-3">
			{$i18n.t(
				'When active, a multi-agent (Agents) run splits work across these models instead of your session model. Single-agent turns are never affected.'
			)}
		</p>

		{#if poolLoadError}
			<!-- Load failed: don't render an empty pool as truth — a save from here
			     would overwrite the real server-side pool. Same pattern as SkillsManager. -->
			<div
				class="rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-950 px-3 py-4 text-center text-sm text-gray-500"
			>
				{$i18n.t('Could not load the orchestration pool')} — {poolLoadError}.
				{$i18n.t('Your saved pool is untouched; changes are disabled until it loads.')}
				<button class="ml-2 text-blue-600 dark:text-blue-400 hover:underline" on:click={loadPool}>
					{$i18n.t('Retry')}
				</button>
			</div>
		{:else if !poolLoaded}
			<div class="text-xs text-gray-500 py-1" role="status">{$i18n.t('Loading pool…')}</div>
		{:else}
			<div class="flex gap-2 mb-3">
				<select
					bind:value={poolModelToAdd}
					class="flex-1 rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent dark:bg-gray-950 px-3 py-1.5 text-sm outline-none focus:border-blue-500"
				>
					<option value="">{$i18n.t('Choose a model to add…')}</option>
					{#each ($models || []).filter((m) => m?.id && !poolModels.includes(m.id)) as m}
						<option value={m.id}>{m.name || m.id}</option>
					{/each}
				</select>
				<button
					on:click={addPoolModel}
					disabled={!poolModelToAdd}
					class="rounded-lg bg-blue-600 text-white px-4 py-1.5 text-sm font-medium hover:bg-blue-700 disabled:opacity-40"
					>{$i18n.t('Add')}</button
				>
			</div>

			{#if poolModels.length}
				<div class="flex flex-wrap gap-1.5">
					{#each poolModels as m (m)}
						<span
							class="inline-flex items-center gap-1.5 rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 pl-3 pr-1.5 py-1 text-xs text-gray-700 dark:text-gray-200"
						>
							<code class="font-mono">{m}</code>
							<button
								on:click={() => removePoolModel(m)}
								title={$i18n.t('Remove')}
								class="text-gray-400 hover:text-red-500 transition"
								><svg class="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg></button
							>
						</span>
					{/each}
				</div>
			{:else}
				<div class="text-xs text-gray-500 py-1">
					{$i18n.t('No models in the pool. Add a few to fan multi-agent work across them.')}
				</div>
			{/if}
		{/if}
	</section>

	<!-- Skills (shared panel — same component as Settings → Customize → Skills) -->
	<section id="sec-skills" class="scroll-mt-12 rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
		<SkillsPanel {token} />
	</section>

	<!-- Connectors (MCP under the hood; shared panel) -->
	<section id="sec-mcp" class="scroll-mt-12 rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-5">
		<ConnectorsPanel {token} />
	</section>
</div>
