<script lang="ts">
	import { getContext, onMount, onDestroy } from 'svelte';
	import { toast } from 'svelte-sonner';
	import {
		getNodes,
		getSystem,
		recommend,
		searchModels,
		getInstalled,
		downloadModel,
		addNode,
		removeNode,
		type CookbookNode,
		type CookbookModel,
		type InstalledModel
	} from '$lib/apis/cookbook';
	import Cube from '$lib/components/icons/Cube.svelte';
	import Bolt from '$lib/components/icons/Bolt.svelte';
	import ArrowDownTray from '$lib/components/icons/ArrowDownTray.svelte';
	import Skeleton from '$lib/components/common/Skeleton.svelte';

	const i18n: any = getContext('i18n');

	// One component, two mounts: 'dock' (right-rail Controls tab) vs 'full' (Agent Studio surface).
	export let mode: 'full' | 'dock' = 'dock';

	const token = () => localStorage.token;

	const USE_CASES = ['general', 'coding', 'reasoning', 'chat', 'multimodal', 'embedding'];
	// Scope = the universe of models. Local (Ollama/llama.cpp) is the default; switching
	// scope SWAPS the table (never interleaves server + local). Odysseus's core rule.
	const SCOPES: { key: string; label: string; runtime: string }[] = [
		{ key: 'local', label: 'Local (Ollama)', runtime: 'llamacpp' },
		{ key: 'server', label: 'GPU server', runtime: 'vllm' }
	];
	const FETCH_LIMIT = 60;

	// Two tabs: Recommend (fit-ranked download list) ⇄ Installed (what's pulled — swap to any).
	const TABS: { key: 'recommend' | 'installed'; label: string }[] = [
		{ key: 'recommend', label: 'Recommend' },
		{ key: 'installed', label: 'Installed models' }
	];
	let tab: 'recommend' | 'installed' = 'recommend';
	let installed: InstalledModel[] = [];
	let loadingInstalled = false;
	let installedErr = '';
	let activeModelId = ''; // the model OWUI will open new chats with (sessionStorage)

	let loadingNodes = true;
	let topErr = '';
	let nodes: CookbookNode[] = [];
	let activeNode = '';
	let useCase = 'coding';
	let scope = 'local';
	let query = '';
	let searchTimer: any = null;

	// Selected node's data.
	let system: any = null;
	let models: CookbookModel[] = [];
	let loading = false;
	let err = '';

	let downloads: Record<string, { pct: number | null; status: string; done?: boolean; error?: string }> = {};

	// Manual pull-by-tag (Installed tab) — pulls ANY Ollama tag onto the SELECTED
	// node (so the rig can be pulled from the laptop via the node selector).
	let pullTag = '';
	const PULL_SUGGESTIONS = ['gemma4:12b', 'gemma4:e4b', 'qwen3.5:9b'];

	const aliveNodes = () => nodes.filter((n) => n.alive);
	const node = () => nodes.find((n) => n.name === activeNode);
	const runtimeFor = () => SCOPES.find((s) => s.key === scope)?.runtime;

	const loadNodes = async () => {
		loadingNodes = true;
		topErr = '';
		try {
			nodes = await getNodes(token());
			const alive = aliveNodes();
			activeNode =
				(alive.find((n) => n.role === 'main') ?? alive[0] ?? nodes[0])?.name ?? '';
		} catch (e: any) {
			topErr = e?.detail ?? `${e}`;
			nodes = [];
		}
		loadingNodes = false;
		if (activeNode) await loadNode();
	};

	const loadNode = async () => {
		const n = node();
		system = null;
		models = [];
		err = '';
		if (!n || !n.alive) return; // offline → render the start hint
		loading = true;
		try {
			const q = query.trim();
			const [sys, rec] = await Promise.all([
				getSystem(token(), activeNode).catch(() => null),
				q
					? searchModels(token(), activeNode, {
							search: q,
							runtime: runtimeFor(),
							limit: FETCH_LIMIT
						})
					: recommend(token(), activeNode, {
							use_case: useCase,
							runtime: runtimeFor(),
							limit: FETCH_LIMIT
						})
			]);
			system = sys?.system ?? sys;
			models = rec?.models ?? [];
		} catch (e: any) {
			err = e?.detail ?? `${e}`;
			models = [];
		}
		loading = false;
	};

	const pickNode = (name: string) => {
		if (name === activeNode) return;
		activeNode = name;
		if (tab === 'installed') loadInstalled();
		else loadNode();
	};

	// ── Add-node modal: register another GPU machine (running `llmfit serve`) as an
	// inference node. Admin-only on the backend, which probes reachability before saving.
	let showAddNode = false;
	let addForm = { name: '', llmfit_url: '', ollama_url: '' };
	let addingNode = false;
	let addErr = '';

	const openAddNode = () => {
		addForm = { name: '', llmfit_url: '', ollama_url: '' };
		addErr = '';
		showAddNode = true;
	};

	const submitAddNode = async () => {
		addErr = '';
		const name = addForm.name.trim();
		const llmfit = addForm.llmfit_url.trim();
		if (!name || !llmfit) {
			addErr = $i18n.t('Give the device a name and its llmfit URL.');
			return;
		}
		addingNode = true;
		try {
			const saved = await addNode(token(), {
				name,
				llmfit_url: llmfit,
				ollama_url: addForm.ollama_url.trim()
			});
			showAddNode = false;
			toast.success($i18n.t('Added device {{name}}', { name }));
			await loadNodes();
			pickNode(saved.name);
		} catch (e: any) {
			addErr = e?.detail ?? `${e}`;
		}
		addingNode = false;
	};

	const deleteNode = async (name: string) => {
		if (!confirm($i18n.t('Remove device {{name}}? Its models stay on that machine.', { name }))) return;
		try {
			await removeNode(token(), name);
			toast.success($i18n.t('Removed device {{name}}', { name }));
			if (activeNode === name) activeNode = '';
			await loadNodes();
		} catch (e: any) {
			toast.error(e?.detail ?? `${e}`);
		}
	};
	const onFilters = () => loadNode();
	const onSearchInput = () => {
		if (searchTimer) clearTimeout(searchTimer);
		searchTimer = setTimeout(loadNode, 400);
	};

	// ── Installed-models tab: what's pulled into this node's Ollama (swap to any) ──
	const readActiveModel = () => {
		try {
			activeModelId = (JSON.parse(sessionStorage.selectedModels || '[]')[0] || '') as string;
		} catch (_) {
			activeModelId = '';
		}
	};
	// `silent` = background refresh: no spinner, no blanking, and a failed/empty
	// response keeps the current list in place (fail-soft) so a periodic re-check
	// never disturbs what the user is looking at.
	const loadInstalled = async (silent = false) => {
		const n = node();
		readActiveModel();
		if (!n || !n.alive) {
			installed = [];
			installedErr = '';
			return;
		}
		if (!silent) {
			installed = [];
			installedErr = '';
			loadingInstalled = true;
		}
		try {
			// Load installed models + this node's hardware together so the fit
			// ranking (size vs gpu_vram_gb) uses the SELECTED node, not a stale one.
			const [r, sys] = await Promise.all([
				getInstalled(token(), activeNode),
				getSystem(token(), activeNode).catch(() => null)
			]);
			const next = r?.models ?? [];
			if (!silent || next.length) {
				installed = next;
				installedErr = r?.error ?? '';
			}
			if (sys) system = sys?.system ?? sys;
		} catch (e: any) {
			if (!silent) installedErr = e?.detail ?? `${e}`;
		}
		if (!silent) loadingInstalled = false;
	};
	const selectTab = (t: 'recommend' | 'installed') => {
		tab = t;
		if (t === 'installed') {
			// Always re-check on tab entry (silently when a list is already showing)
			// so models pulled since the last visit appear without a reload.
			loadInstalled(installed.length > 0);
		} else if (!models.length) {
			loadNode();
		}
	};
	const useModel = (name: string) => {
		try {
			sessionStorage.selectedModels = JSON.stringify([name]);
			activeModelId = name;
			toast.success($i18n.t('{{name}} set as your model — opens with new chats', { name }));
		} catch (_) {
			/* ignore */
		}
	};
	const fmtSize = (b?: number) => (!b ? '' : (b / 1e9).toFixed(1) + ' GB');

	const download = async (m: CookbookModel) => {
		if (!m.downloadable) return;
		const key = m.name;
		downloads[key] = { pct: null, status: 'starting' };
		downloads = { ...downloads };
		try {
			await downloadModel(
				token(),
				{ node: activeNode, repo: m.name, quant: m.best_quant },
				(ev) => {
					if (ev?.error) downloads[key] = { pct: null, status: 'error', error: ev.error };
					else if (ev?.final || ev?.status === 'done' || ev?.status === 'success')
						downloads[key] = { pct: 100, status: 'done', done: true };
					else {
						const pct =
							ev?.total && ev?.completed ? Math.round((ev.completed / ev.total) * 100) : null;
						downloads[key] = { pct, status: ev?.status ?? 'pulling' };
					}
					downloads = { ...downloads };
				}
			);
			if (!downloads[key]?.done) {
				downloads[key] = { pct: 100, status: 'done', done: true };
				downloads = { ...downloads };
			}
			toast.success($i18n.t('Downloaded {{name}}', { name: m.name }));
		} catch (e: any) {
			downloads[key] = { pct: null, status: 'error', error: `${e?.message ?? e}` };
			downloads = { ...downloads };
			toast.error(`${e?.message ?? e}`);
		}
	};

	// Pull an explicit Ollama tag onto the SELECTED node (rig pulls from the laptop
	// via the node selector). Reuses the `downloads` progress map keyed by the tag.
	const pullByTag = async () => {
		const tag = pullTag.trim();
		if (!tag) return;
		const key = tag;
		downloads[key] = { pct: null, status: 'starting' };
		downloads = { ...downloads };
		try {
			await downloadModel(token(), { node: activeNode, ollama_tag: tag }, (ev) => {
				if (ev?.error) downloads[key] = { pct: null, status: 'error', error: ev.error };
				else if (ev?.final || ev?.status === 'done' || ev?.status === 'success')
					downloads[key] = { pct: 100, status: 'done', done: true };
				else {
					const pct = ev?.total && ev?.completed ? Math.round((ev.completed / ev.total) * 100) : null;
					downloads[key] = { pct, status: ev?.status ?? 'pulling' };
				}
				downloads = { ...downloads };
			});
			if (!downloads[key]?.done) {
				downloads[key] = { pct: 100, status: 'done', done: true };
				downloads = { ...downloads };
			}
			toast.success($i18n.t('Pulled {{name}} on {{node}}', { name: tag, node: activeNode }));
			await loadInstalled();
		} catch (e: any) {
			downloads[key] = { pct: null, status: 'error', error: `${e?.message ?? e}` };
			downloads = { ...downloads };
			toast.error(`${e?.message ?? e}`);
		}
	};

	const fitColor = (lvl?: string) => {
		switch ((lvl || '').toLowerCase()) {
			case 'perfect':
				return 'text-blue-500 bg-blue-500/10';
			case 'good':
				return 'text-green-500 bg-green-500/10';
			case 'marginal':
				return 'text-amber-500 bg-amber-500/10';
			default:
				return 'text-gray-400 bg-gray-500/10';
		}
	};
	const MODE_LABEL: Record<string, string> = {
		gpu: 'GPU',
		moe_offload: 'MoE offload',
		cpu_offload: 'cpu+offload',
		cpu: 'CPU'
	};
	const modeLabel = (m: CookbookModel) =>
		MODE_LABEL[String(m.run_mode || '').toLowerCase()] ?? (m.run_mode || '—');
	const modeColor = (m: CookbookModel) =>
		String(m.run_mode || '').toLowerCase() === 'gpu' ? 'text-blue-500' : 'text-gray-400';
	const fmtCtx = (n?: number) => (!n ? '—' : n >= 1024 ? Math.round(n / 1024) + 'k' : `${n}`);
	const fmtVram = (g?: number) => (g == null ? '—' : `${g}G`);

	// ── Fit of INSTALLED models vs THIS node's GPU VRAM ──────────────────────
	// Ollama reports each model's on-disk size; rank it against gpu_vram_gb
	// (weights + ~15% KV/context overhead) on the same Perfect/Good/Marginal
	// scale as the Recommend tab, so the Installed list is fit-ranked too.
	const FIT_ORDER: Record<string, number> = { perfect: 4, good: 3, marginal: 2, tight: 1, too_tight: 0 };
	const FIT_LABEL: Record<string, string> = {
		perfect: 'Perfect',
		good: 'Good',
		marginal: 'Marginal',
		tight: 'Tight',
		too_tight: 'Too tight'
	};
	const rankInstalled = (list: InstalledModel[], sys: any): (InstalledModel & { _fit: string })[] => {
		const vram = Number(sys?.gpu_vram_gb) || 0;
		const lvl = (m: InstalledModel): string => {
			const gb = m.size ? m.size / 1e9 : 0;
			if (!vram || !gb) return '';
			const r = (gb * 1.15) / vram; // weights + rough KV/context overhead
			return r <= 0.7 ? 'perfect' : r <= 0.9 ? 'good' : r <= 1.0 ? 'marginal' : r <= 1.3 ? 'tight' : 'too_tight';
		};
		return list
			.map((m) => ({ ...m, _fit: lvl(m) }))
			.sort((a, b) => (FIT_ORDER[b._fit] ?? -1) - (FIT_ORDER[a._fit] ?? -1) || (b.size || 0) - (a.size || 0));
	};
	// Re-ranks when the installed list OR the node's hardware (system) changes.
	$: installedRanked = rankInstalled(installed, system);

	// Ollama-style capability tags from llmfit's `capabilities` array (tool_use, vision,
	// thinking, …). Rendered as small colored labels next to the name, like the MoE badge.
	const CAP_LABEL: Record<string, string> = {
		tool_use: 'tools',
		tools: 'tools',
		function_calling: 'tools',
		vision: 'vision',
		image: 'vision',
		thinking: 'thinking',
		reasoning: 'thinking',
		audio: 'audio',
		embedding: 'embed',
		insert: 'insert'
	};
	const capLabel = (c: string) => CAP_LABEL[String(c).toLowerCase()] ?? String(c);
	const CAP_COLOR: Record<string, string> = {
		tools: 'text-sky-500 bg-sky-500/10',
		vision: 'text-pink-500 bg-pink-500/10',
		thinking: 'text-violet-500 bg-violet-500/10',
		audio: 'text-amber-500 bg-amber-500/10',
		embed: 'text-gray-500 bg-gray-500/10',
		insert: 'text-gray-500 bg-gray-500/10'
	};
	const capColor = (c: string) => CAP_COLOR[capLabel(c)] ?? 'text-gray-500 bg-gray-500/10';

	$: aliveCount = nodes.filter((n) => n.alive).length;

	// Calm periodic re-check of the installed list (silent — no spinner/blanking) so
	// models pulled while the panel sits open appear without a reload.
	let _installedRefreshTimer: ReturnType<typeof setInterval> | null = null;
	onMount(() => {
		loadNodes();
		_installedRefreshTimer = setInterval(() => {
			if (tab === 'installed') loadInstalled(true);
		}, 60000);
	});
	onDestroy(() => {
		if (_installedRefreshTimer) clearInterval(_installedRefreshTimer);
	});
</script>

<div class="w-full h-full flex flex-col {mode === 'full' ? 'max-w-5xl mx-auto px-4 py-4' : 'px-1 py-2'}">
	<!-- title -->
	<div class="flex items-center gap-2 mb-2 shrink-0">
		<Bolt className="size-4 text-blue-500" />
		<div class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Models')}</div>
		<span class="text-[11px] text-gray-400 hidden sm:inline">{$i18n.t('your installed models + hardware-aware picks')}</span>
		<button
			class="ml-auto text-[11px] text-gray-400 hover:text-blue-500 transition"
			on:click={loadNodes}
			title={$i18n.t('Rescan')}>↻ {$i18n.t('Rescan')}</button
		>
	</div>

	<!-- tabs: Recommend (download list) ⇄ Installed models (swap to any pulled model) -->
	<div class="flex items-center gap-1 mb-2 shrink-0 text-xs">
		{#each TABS as t}
			<button
				class="px-2.5 py-1 rounded-lg border transition {tab === t.key
					? 'border-blue-500/50 bg-blue-500/10 text-blue-600 dark:text-blue-300'
					: 'border-gray-200 dark:border-gray-800 text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800/50'}"
				on:click={() => selectTab(t.key)}
			>
				{t.label}
			</button>
		{/each}
	</div>

	{#if loadingNodes}
		<!-- Skeleton mirrors the node-selector chip row + hardware chips below it. -->
		<div aria-busy="true">
			<div aria-hidden="true">
				<div class="flex items-center gap-1.5 mb-2">
					{#each Array.from({ length: 2 }) as _, i}
						<Skeleton width={['5.5rem', '4.5rem'][i]} height="1.625rem" rounded="rounded-lg" delay={i * 90} />
					{/each}
				</div>
				<div class="flex items-center gap-1 mb-2">
					{#each Array.from({ length: 3 }) as _, i}
						<Skeleton width={['7rem', '5rem', '4rem'][i]} height="1.125rem" rounded="rounded-lg" delay={i * 90} />
					{/each}
				</div>
			</div>
			<span class="sr-only" role="status">{$i18n.t('Checking devices…')}</span>
		</div>
	{:else if topErr}
		<div class="text-xs text-red-500 px-2 py-2">{topErr}</div>
	{:else if nodes.length === 0}
		<div class="text-xs text-gray-500 dark:text-gray-400 px-2 py-4">{$i18n.t('No devices configured.')}</div>
	{:else}
		<!-- node selector: one node, one table (clear which device you're viewing) -->
		<div class="flex items-center gap-1.5 flex-wrap mb-2 shrink-0">
			{#each nodes as n (n.name)}
				<div
					class="group flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs border transition {activeNode === n.name
						? 'border-blue-500/50 bg-blue-500/10 text-blue-600 dark:text-blue-300'
						: 'border-gray-200 dark:border-gray-800 text-gray-500 hover:bg-gray-50 dark:hover:bg-gray-800/50'}"
				>
					<button class="flex items-center gap-1.5" on:click={() => pickNode(n.name)}>
						<span class="size-2 rounded-full shrink-0 {n.alive ? 'bg-blue-500' : 'bg-gray-300 dark:bg-gray-700'}"></span>
						{n.name}
						{#if n.role === 'main'}<span class="text-[9px] uppercase text-blue-500/70">main</span>{/if}
					</button>
					{#if n.role !== 'main'}
						<!-- remove a user-added device (built-in main is protected) -->
						<button
							class="opacity-0 group-hover:opacity-100 focus:opacity-100 text-gray-400 hover:text-red-500 transition leading-none"
							title={$i18n.t('Remove device')}
							aria-label={$i18n.t('Remove device {{name}}', { name: n.name })}
							on:click|stopPropagation={() => deleteNode(n.name)}>×</button
						>
					{/if}
				</div>
			{/each}
			<!-- "+" — register another GPU machine as an inference node -->
			<button
				class="flex items-center gap-1 px-2 py-1 rounded-lg text-xs border border-dashed border-gray-300 dark:border-gray-700 text-gray-400 hover:text-blue-500 hover:border-blue-500/50 transition"
				title={$i18n.t('Add another device running llmfit serve')}
				on:click={openAddNode}>+ {$i18n.t('Add device')}</button
			>
		</div>

		<!-- detected-hardware chips for the selected node (/api/cookbook/system) -->
		{#if system}
			<div class="flex items-center gap-1 flex-wrap mb-2 shrink-0 text-[11px]">
				{#each [system.gpu_name, system.gpu_vram_gb ? `VRAM ${system.gpu_vram_gb} GB` : null, system.backend, system.total_ram_gb ? `RAM ${system.total_ram_gb} GB` : null, system.cpu_cores ? `${system.cpu_cores} cores` : null].filter(Boolean) as chip}
					<span class="px-2 py-0.5 rounded-md bg-gray-100 dark:bg-gray-850 text-gray-600 dark:text-gray-300 truncate max-w-[180px]">{chip}</span>
				{/each}
			</div>
		{/if}

		{#if tab === 'recommend'}
		<!-- filter row: Type (use-case) · scope (Local/GPU server) · search -->
		<div class="flex items-center gap-1.5 mb-2 shrink-0">
			<select
				bind:value={useCase}
				on:change={onFilters}
				class="text-xs bg-transparent border border-gray-200 dark:border-gray-800 rounded-lg px-2 py-1 outline-none"
				title={$i18n.t('Type')}
			>
				{#each USE_CASES as uc}<option value={uc}>{uc}</option>{/each}
			</select>
			<select
				bind:value={scope}
				on:change={onFilters}
				class="text-xs bg-transparent border border-gray-200 dark:border-gray-800 rounded-lg px-2 py-1 outline-none"
				title={$i18n.t('Scope')}
			>
				{#each SCOPES as s}<option value={s.key}>{s.label}</option>{/each}
			</select>
			<input
				type="text"
				bind:value={query}
				on:input={onSearchInput}
				placeholder={$i18n.t('Search models…')}
				class="flex-1 min-w-0 text-xs bg-transparent border border-gray-200 dark:border-gray-800 rounded-lg px-2.5 py-1 outline-none focus:border-blue-500/50 transition"
			/>
		</div>

		<!-- body -->
		<div class="flex-1 min-h-0 overflow-auto -mx-1 px-1">
			{#if !node()?.alive}
				<div class="text-[11px] text-gray-500 dark:text-gray-400 px-1 py-3 leading-relaxed">
					{$i18n.t('Device offline.')}
					{$i18n.t('Start')}
					<code class="text-blue-500">llmfit serve --host 0.0.0.0 --port 8787</code>
					{$i18n.t('on it, then Rescan.')}
					{#if node()?.error}<div class="mt-0.5 text-gray-400 truncate" title={node()?.error}>{node()?.error}</div>{/if}
				</div>
			{:else if loading}
				<!-- Skeleton mirrors the ranked table rows: FIT chip + model name + numeric columns. -->
				<div class="px-1 pt-2" aria-busy="true">
					<div aria-hidden="true">
						{#each Array.from({ length: 8 }) as _, i}
							<div class="flex items-center gap-2 py-1.5 border-b border-gray-50 dark:border-gray-850/50">
								<Skeleton width="3rem" height="1rem" rounded="rounded" delay={i * 70} />
								<Skeleton width={['34%', '26%', '38%', '22%', '30%', '28%', '36%', '24%'][i]} height="0.75rem" delay={i * 70} />
								<div class="flex-1"></div>
								{#each Array.from({ length: 4 }) as _, j}
									<Skeleton width="2rem" height="0.625rem" delay={i * 70} className={j > 1 ? 'hidden sm:block' : ''} />
								{/each}
							</div>
						{/each}
					</div>
					<span class="sr-only" role="status">{$i18n.t('Scoring models…')}</span>
				</div>
			{:else if err}
				<div class="text-xs text-red-500 px-1 py-2">{err}</div>
			{:else if models.length === 0}
				<div class="text-xs text-gray-400 px-1 py-3">{$i18n.t('No models returned.')}</div>
			{:else}
				<!-- one node, one scope, one ranked table — sorted FIT → GPU → SCORE (backend).
				     min-w keeps columns from crushing in the narrow dock (panel scrolls x);
				     the wide full-page surface fills via w-full. -->
				<table class="w-full min-w-[680px] whitespace-nowrap text-[11px] border-collapse">
					<thead class="text-gray-400 dark:text-gray-500">
						<tr class="text-left border-b border-gray-100 dark:border-gray-850">
							<th class="font-medium py-1 pr-2">{$i18n.t('FIT')}</th>
							<th class="font-medium py-1 pr-2">{$i18n.t('MODEL')}</th>
							<th class="font-medium py-1 pr-2 text-right">{$i18n.t('PARAM')}</th>
							<th class="font-medium py-1 pr-2">{$i18n.t('QUANT')}</th>
							<th class="font-medium py-1 pr-2 text-right">{$i18n.t('VRAM')}</th>
							<th class="font-medium py-1 pr-2 text-right">{$i18n.t('CTX')}</th>
							<th class="font-medium py-1 pr-2 text-right">{$i18n.t('SPEED')}</th>
							<th class="font-medium py-1 pr-2 text-right">{$i18n.t('SCORE')}</th>
							<th class="font-medium py-1 pr-2">{$i18n.t('MODE')}</th>
							<th class="font-medium py-1"></th>
						</tr>
					</thead>
					<tbody class="tabular-nums">
						{#each models as m (m.name)}
							<tr class="border-b border-gray-50 dark:border-gray-850/50 hover:bg-gray-50/60 dark:hover:bg-gray-850/30">
								<td class="py-1 pr-2"><span class="px-1.5 py-0.5 rounded {fitColor(m.fit_level)}">{m.fit_label ?? m.fit_level}</span></td>
								<td class="py-1 pr-2 max-w-[280px]">
									<div class="flex items-center gap-1 min-w-0">
										<span class="text-gray-800 dark:text-gray-100 truncate" title={m.name}>{m.name}</span>
										{#if m.is_moe}<span class="px-1.5 py-0.5 rounded-md text-[9px] leading-none bg-purple-500/10 text-purple-400 shrink-0">MoE</span>{/if}
										{#each m.capabilities ?? [] as cap}
											<span class="px-1.5 py-0.5 rounded-md text-[9px] leading-none {capColor(cap)} shrink-0">{capLabel(cap)}</span>
										{/each}
									</div>
								</td>
								<td class="py-1 pr-2 text-right text-gray-500 dark:text-gray-400">{m.parameter_count ?? (m.params_b ? m.params_b + 'B' : '—')}</td>
								<td class="py-1 pr-2 text-gray-500 dark:text-gray-400 whitespace-nowrap">{m.best_quant ?? '—'}</td>
								<td class="py-1 pr-2 text-right text-gray-500 dark:text-gray-400">{fmtVram(m.memory_required_gb)}</td>
								<td class="py-1 pr-2 text-right text-gray-500 dark:text-gray-400">{fmtCtx(m.context_length)}</td>
								<td class="py-1 pr-2 text-right text-gray-500 dark:text-gray-400">{m.estimated_tps ? Math.round(m.estimated_tps) + ' t/s' : '—'}</td>
								<td class="py-1 pr-2 text-right text-gray-700 dark:text-gray-200">{m.score != null ? Math.round(m.score * 10) / 10 : '—'}</td>
								<td class="py-1 pr-2 whitespace-nowrap {modeColor(m)}">{modeLabel(m)}</td>
								<td class="py-1 text-right whitespace-nowrap">
									{#if downloads[m.name]}
										{@const d = downloads[m.name]}
										{#if d.error}<button class="text-red-500" on:click={() => download(m)} title={d.error}>{$i18n.t('Retry')}</button>
										{:else if d.done}<span class="text-blue-500">✓</span>
										{:else}<span class="text-gray-400">{d.pct != null ? d.pct + '%' : d.status}</span>{/if}
									{:else if m.downloadable}
										<button
											class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded border border-blue-500/40 text-blue-600 dark:text-blue-300 hover:bg-blue-500/10 transition"
											on:click={() => download(m)}
											title={$i18n.t('Pull into {{node}}’s Ollama (resolves the GGUF on HuggingFace)', { node: activeNode })}
										>
											<ArrowDownTray className="size-3" />
										</button>
									{:else}
										<span class="text-gray-400" title={m.reason ?? ''}>{$i18n.t('server')}</span>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</div>
		{:else}
			<!-- Installed models: what's pulled into this node's Ollama (swap to any) -->
			<div class="flex-1 min-h-0 overflow-auto -mx-1 px-1">
				<!-- Pull any Ollama tag onto the SELECTED node (rig pulls from the laptop via the node selector above) -->
				<div class="mb-2.5 rounded-lg border border-gray-100 dark:border-gray-850 p-2">
					<div class="flex items-center gap-1.5">
						<input
							bind:value={pullTag}
							placeholder="gemma4:12b"
							on:keydown={(e) => e.key === 'Enter' && pullByTag()}
							class="flex-1 min-w-0 text-xs bg-transparent border border-gray-200 dark:border-gray-800 rounded-lg px-2.5 py-1 outline-none focus:border-blue-500/50 transition"
						/>
						<button
							on:click={pullByTag}
							disabled={!pullTag.trim()}
							class="shrink-0 inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-blue-500/40 text-blue-600 dark:text-blue-300 hover:bg-blue-500/10 transition text-xs disabled:opacity-40"
							title={$i18n.t('Pull this Ollama tag onto {{node}}', { node: activeNode })}
						>
							<ArrowDownTray className="size-3.5" /> {$i18n.t('Pull on')} {activeNode}
						</button>
					</div>
					<div class="flex items-center gap-1 mt-1.5 flex-wrap">
						<span class="text-[10px] text-gray-400">{$i18n.t('try')}:</span>
						{#each PULL_SUGGESTIONS as s}
							<button
								on:click={() => (pullTag = s)}
								class="text-[10px] px-1.5 py-0.5 rounded-md bg-gray-100 dark:bg-gray-850 text-gray-500 hover:text-blue-500 transition"
							>{s}</button>
						{/each}
					</div>
					{#if pullTag.trim() && downloads[pullTag.trim()]}
						{@const d = downloads[pullTag.trim()]}
						<div
							class="mt-1.5 text-[11px] {d.status === 'error'
								? 'text-red-500'
								: d.done
									? 'text-blue-500'
									: 'text-gray-500'}"
						>
							{#if d.error}{d.error}{:else if d.done}✓ {$i18n.t('pulled — now in the list below')}{:else}{d.status}{d.pct != null
									? ` ${d.pct}%`
									: ''}…{/if}
						</div>
					{/if}
				</div>
				{#if !node()?.alive}
					<div class="text-[11px] text-gray-500 dark:text-gray-400 px-1 py-3">{$i18n.t('Device offline.')}</div>
				{:else if loadingInstalled}
					<!-- Skeleton mirrors installed-model cards: fit chip + name/meta lines + Use button. -->
					<div aria-busy="true">
						<div aria-hidden="true" class="space-y-1.5">
							{#each Array.from({ length: 4 }) as _, i}
								<div class="flex items-center gap-2 rounded-lg border border-gray-100 dark:border-gray-850 px-2.5 py-1.5">
									<Skeleton width="2.75rem" height="1.125rem" rounded="rounded" className="shrink-0" delay={i * 90} />
									<div class="min-w-0 flex-1">
										<Skeleton width={['48%', '36%', '56%', '42%'][i]} height="0.75rem" delay={i * 90} />
										<Skeleton width={['34%', '26%', '38%', '30%'][i]} height="0.5rem" className="mt-1.5" delay={i * 90} />
									</div>
									<Skeleton width="2.25rem" height="1.5rem" rounded="rounded-lg" className="shrink-0" delay={i * 90} />
								</div>
							{/each}
						</div>
						<span class="sr-only" role="status">{$i18n.t('Loading installed models…')}</span>
					</div>
				{:else if installedErr}
					<div class="text-xs text-red-500 px-1 py-2">{installedErr}</div>
				{:else if installed.length === 0}
					<div class="text-xs text-gray-400 px-1 py-3">{$i18n.t('No models installed on this device yet — download some from the Recommend tab.')}</div>
				{:else}
					<div class="text-[11px] text-gray-400 mb-1.5">{installed.length} {$i18n.t('installed · ranked by fit · Use to swap')}</div>
					<div class="space-y-1.5">
						{#each installedRanked as m (m.name)}
							<div class="flex items-center gap-2 rounded-lg border {m.name === activeModelId ? 'border-blue-500/50 bg-blue-500/5' : 'border-gray-100 dark:border-gray-850'} px-2.5 py-1.5">
								{#if m._fit}<span class="shrink-0 text-[10px] px-1.5 py-0.5 rounded {fitColor(m._fit)}" title={$i18n.t('Fit on {{node}} ({{vram}})', { node: activeNode, vram: system?.gpu_vram_gb ? system.gpu_vram_gb + 'GB VRAM' : 'this device' })}>{FIT_LABEL[m._fit] ?? m._fit}</span>{/if}
								<div class="min-w-0 flex-1">
									<div class="text-xs font-medium text-gray-800 dark:text-gray-100 truncate" title={m.name}>{m.name}</div>
									<div class="flex flex-wrap items-center gap-1.5 mt-0.5 text-[10px] text-gray-400 tabular-nums">
										{#if m.details?.parameter_size}<span>{m.details.parameter_size}</span>{/if}
										{#if m.details?.quantization_level}<span>{m.details.quantization_level}</span>{/if}
										{#if m.details?.family}<span>{m.details.family}</span>{/if}
										{#if m.size}<span>{fmtSize(m.size)}</span>{/if}
									</div>
								</div>
								{#if m.name === activeModelId}
									<span class="shrink-0 text-[10px] px-1.5 py-0.5 rounded-md bg-blue-500/10 text-blue-600 dark:text-blue-300">{$i18n.t('active')}</span>
								{:else}
									<button class="shrink-0 text-[11px] px-2 py-1 rounded-lg border border-blue-500/40 text-blue-600 dark:text-blue-300 hover:bg-blue-500/10 transition" on:click={() => useModel(m.name)}>{$i18n.t('Use')}</button>
								{/if}
							</div>
						{/each}
					</div>
				{/if}
			</div>
		{/if}
	{/if}
</div>

<!-- Add-device modal: register another machine running `llmfit serve` as an inference node -->
{#if showAddNode}
	<div
		class="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4"
		on:click|self={() => (showAddNode = false)}
		role="presentation"
	>
		<div class="w-full max-w-sm rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-xl p-4">
			<div class="flex items-center gap-2 mb-1">
				<Cube className="size-4 text-blue-500" />
				<div class="text-sm font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Add inference device')}</div>
			</div>
			<p class="text-[11px] text-gray-500 dark:text-gray-400 leading-relaxed mb-3">
				{$i18n.t('Point Harvis at another machine on your network running')}
				<code class="text-blue-500">llmfit serve --host 0.0.0.0 --port 8787</code>.
				{$i18n.t('Harvis checks it responds before saving.')}
			</p>

			<label class="block text-[11px] text-gray-500 dark:text-gray-400 mb-1" for="cb-node-name">{$i18n.t('Name')}</label>
			<input
				id="cb-node-name"
				type="text"
				bind:value={addForm.name}
				placeholder={$i18n.t('e.g. rig, gaming-pc')}
				class="w-full mb-2.5 text-xs bg-transparent border border-gray-200 dark:border-gray-800 rounded-lg px-2.5 py-1.5 outline-none focus:border-blue-500/50 transition"
			/>

			<label class="block text-[11px] text-gray-500 dark:text-gray-400 mb-1" for="cb-node-llmfit">{$i18n.t('llmfit URL')}</label>
			<input
				id="cb-node-llmfit"
				type="text"
				bind:value={addForm.llmfit_url}
				placeholder="http://192.168.1.50:8787"
				class="w-full mb-2.5 text-xs bg-transparent border border-gray-200 dark:border-gray-800 rounded-lg px-2.5 py-1.5 outline-none focus:border-blue-500/50 transition"
			/>

			<label class="block text-[11px] text-gray-500 dark:text-gray-400 mb-1" for="cb-node-ollama"
				>{$i18n.t('Ollama URL')} <span class="text-gray-400">({$i18n.t('optional — for pulling models')})</span></label
			>
			<input
				id="cb-node-ollama"
				type="text"
				bind:value={addForm.ollama_url}
				placeholder="http://192.168.1.50:11434"
				class="w-full mb-1 text-xs bg-transparent border border-gray-200 dark:border-gray-800 rounded-lg px-2.5 py-1.5 outline-none focus:border-blue-500/50 transition"
			/>

			{#if addErr}<div class="mt-2 text-[11px] text-red-500 leading-relaxed">{addErr}</div>{/if}

			<div class="flex items-center justify-end gap-2 mt-4">
				<button
					class="text-xs px-3 py-1.5 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
					on:click={() => (showAddNode = false)}
					disabled={addingNode}>{$i18n.t('Cancel')}</button
				>
				<button
					class="text-xs px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-500 transition disabled:opacity-50"
					on:click={submitAddNode}
					disabled={addingNode}
					>{addingNode ? $i18n.t('Checking…') : $i18n.t('Add device')}</button
				>
			</div>
		</div>
	</div>
{/if}
