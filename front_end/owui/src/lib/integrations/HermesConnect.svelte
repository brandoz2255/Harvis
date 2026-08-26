<script lang="ts">
	// "Bring your Hermes into Harvis" — the Hermes integration reframed around USER-OWNED Hermes.
	// Modes, in order: 1) Import an existing Hermes profile, 2) Connect an external Hermes Agent,
	// 3) Harvis-managed fallback (Advanced/Experimental — a fresh local profile).
	import { createEventDispatcher, onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import {
		getCapabilityRegistry,
		saveHermesModel,
		getHermesExternal,
		saveHermesExternal,
		verifyHermesExternal,
		disconnectHermesExternal,
		previewHermesImport,
		doHermesImport
	} from '$lib/integrations/registry';
	import { getIntegrationsStatus } from '$lib/apis/integrations';

	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();
	const changed = () => dispatch('changed');

	type Mode = 'import' | 'external' | 'managed';
	let mode: Mode = 'import';

	// ── shared status ──
	let hermesReady: { ready: boolean; reason?: string } | null = null;
	let hermesReachable: boolean | null = null;
	let ext: any = null; // external connection status

	// ── managed (local sidecar) model ──
	let hermesModel: string | null = null;
	let hermesModelPref: string | null = null;
	let installedModels: string[] = [];
	let modelBusy = false;

	const load = async () => {
		const [reg, live, e] = await Promise.all([
			getCapabilityRegistry(localStorage.token),
			getIntegrationsStatus(localStorage.token),
			getHermesExternal()
		]);
		hermesReady = reg?.engine_readiness?.['hermes-agent'] ?? null;
		hermesModel = reg?.hermes_agent_model ?? null;
		hermesModelPref = reg?.hermes_agent_model_pref ?? null;
		installedModels = reg?.installed_models ?? [];
		const s = (live?.services as any)?.hermes?.status;
		hermesReachable = s ? s === 'ready' || s === 'running' : null;
		ext = e;
		// Default to the active mode if one is already configured.
		if (ext?.url) mode = 'external';
	};
	onMount(load);

	// ── Mode 1: Import ──
	let importPath = '';
	let preview: any = null;
	let previewBusy = false;
	let importBusy = false;
	let importDone: any = null;
	const runPreview = async () => {
		preview = null;
		importDone = null;
		if (!importPath.trim()) return;
		previewBusy = true;
		try {
			preview = await previewHermesImport(importPath.trim());
		} catch (e: any) {
			toast.error(e?.message || $i18n.t('Could not preview that folder'));
		}
		previewBusy = false;
	};
	const runImport = async () => {
		if (!preview) return;
		if (!confirm($i18n.t('Replace your current Harvis Hermes profile with this one? Your current profile is backed up first.'))) return;
		importBusy = true;
		try {
			importDone = await doHermesImport(importPath.trim());
			toast.success($i18n.t('Hermes profile imported'));
			await load();
			changed();
		} catch (e: any) {
			toast.error(e?.message || $i18n.t('Import failed'));
		}
		importBusy = false;
	};

	// ── Mode 2: Connect external ──
	let extUrl = '';
	let extToken = '';
	let extBusy = false;
	$: if (ext?.url && !extUrl) extUrl = ext.url;
	const saveExternal = async () => {
		if (!extUrl.trim()) return;
		extBusy = true;
		try {
			await saveHermesExternal(extUrl.trim(), extToken.trim() ? extToken.trim() : null);
			extToken = '';
			const v = await verifyHermesExternal();
			if (!v.ok) toast.error(v.error || $i18n.t('Could not reach that Hermes Agent'));
			else toast.success($i18n.t('Connected to your Hermes Agent'));
			await load();
			changed();
		} catch (e: any) {
			toast.error(e?.message || $i18n.t('Save failed'));
		}
		extBusy = false;
	};
	const disconnectExternal = async () => {
		extBusy = true;
		await disconnectHermesExternal();
		extUrl = '';
		extToken = '';
		await load();
		changed();
		extBusy = false;
	};

	// ── Mode 3: Managed model ──
	const onModelChange = async (e: Event) => {
		const v = (e.target as HTMLSelectElement).value;
		modelBusy = true;
		const res = await saveHermesModel(v || null);
		modelBusy = false;
		if (res.ok) {
			hermesModel = res.resolved;
			hermesModelPref = v || null;
			toast.success($i18n.t('Hermes Agent model updated'));
			changed();
		} else {
			toast.error($i18n.t('Could not update the Hermes model'));
		}
	};

	const MODES: { id: Mode; label: string }[] = [
		{ id: 'import', label: 'Import profile' },
		{ id: 'external', label: 'Connect external' },
		{ id: 'managed', label: 'Harvis-managed' }
	];
	const fmtBytes = (n: number) => (n > 1e6 ? `${(n / 1e6).toFixed(1)} MB` : n > 1e3 ? `${(n / 1e3).toFixed(0)} KB` : `${n} B`);
</script>

<div class="space-y-3">
	<!-- framing -->
	<div>
		<div class="text-sm font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Bring your Hermes into Harvis')}</div>
		<p class="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5 leading-relaxed">
			{$i18n.t('Use your own Hermes — import your existing profile or connect an external Hermes Agent. A Harvis-managed fallback is available for demos and new users.')}
		</p>
	</div>

	<!-- mode tabs -->
	<div class="inline-flex w-full gap-0.5 rounded-lg p-0.5 bg-gray-100 dark:bg-gray-850">
		{#each MODES as m}
			<button
				type="button"
				class="flex-1 px-2 py-1 rounded-md text-xs font-medium transition {mode === m.id
					? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm'
					: 'text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'}"
				on:click={() => (mode = m.id)}
			>
				{$i18n.t(m.label)}{#if m.id === 'managed'}<span class="opacity-50"> · {$i18n.t('Advanced')}</span>{/if}
			</button>
		{/each}
	</div>

	{#if ext?.connected}
		<div class="rounded-lg border border-blue-500/20 bg-blue-500/[0.04] px-3 py-2 text-[11px] text-blue-700 dark:text-blue-300 leading-relaxed">
			{$i18n.t('Active: your external Hermes Agent')} — <span class="font-mono">{ext.url}</span>.
			{$i18n.t('Chat routes there. Build is unavailable in external mode (the external server has no access to the Build workspace).')}
		</div>
	{/if}

	<!-- ── Mode 1: Import ── -->
	{#if mode === 'import'}
		<div class="rounded-xl border border-gray-100 dark:border-white/8 bg-gray-50/60 dark:bg-[#0f1626] p-3.5 space-y-2.5">
			<p class="text-xs text-gray-600 dark:text-gray-300 leading-relaxed">
				{$i18n.t('Import your existing desktop Hermes profile (memory, skills, config, persona) into Harvis. Point at the folder of your Hermes home.')}
			</p>
			<div class="flex gap-2">
				<input
					type="text"
					bind:value={importPath}
					placeholder={$i18n.t('Path under the import folder, e.g. my-hermes')}
					class="flex-1 text-xs rounded-lg border border-gray-200 dark:border-white/10 bg-white dark:bg-[#0b1220] px-2.5 py-1.5 text-gray-700 dark:text-gray-200"
				/>
				<button
					type="button"
					disabled={previewBusy || !importPath.trim()}
					class="text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5 transition disabled:opacity-50"
					on:click={runPreview}>{previewBusy ? $i18n.t('Scanning…') : $i18n.t('Preview')}</button
				>
			</div>

			{#if preview}
				<div class="rounded-lg border border-gray-100 dark:border-white/8 bg-white dark:bg-white/[0.02] p-2.5 space-y-1.5 text-[11px]">
					<div class="font-medium text-gray-700 dark:text-gray-200">
						{preview.total_files} {$i18n.t('files')} · {fmtBytes(preview.total_bytes)}
					</div>
					<div class="flex flex-wrap gap-1">
						{#each Object.entries(preview.categories) as [k, v]}
							{#if v}<span class="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-white/5 text-gray-500 dark:text-gray-400">{k}: {v}</span>{/if}
						{/each}
					</div>
					{#each preview.warnings ?? [] as w}
						<p class="text-amber-600 dark:text-amber-400 flex items-start gap-1"><span>⚠</span><span>{w}</span></p>
					{/each}
				</div>
				<button
					type="button"
					disabled={importBusy}
					class="w-full text-xs px-2.5 py-1.5 rounded-lg border border-blue-500/30 text-blue-600 dark:text-blue-300 bg-blue-500/10 hover:bg-blue-500/15 transition disabled:opacity-50"
					on:click={runImport}>{importBusy ? $i18n.t('Importing…') : $i18n.t('Back up & import this profile')}</button
				>
			{/if}

			{#if importDone}
				<p class="text-[11px] text-green-600 dark:text-green-400">
					{$i18n.t('Imported')} {importDone.files} {$i18n.t('files')}. {$i18n.t('Previous profile backed up.')} {$i18n.t('The local Hermes sidecar now runs with your profile.')}
				</p>
			{/if}
			<p class="text-[10px] text-gray-500 dark:text-gray-400 leading-relaxed">
				{$i18n.t('Only folders under the server import root can be imported. Symlinks are skipped. Files that look like secrets/credentials are flagged but imported as-is.')}
			</p>
		</div>

	<!-- ── Mode 2: Connect external ── -->
	{:else if mode === 'external'}
		<div class="rounded-xl border border-gray-100 dark:border-white/8 bg-gray-50/60 dark:bg-[#0f1626] p-3.5 space-y-2.5">
			<p class="text-xs text-gray-600 dark:text-gray-300 leading-relaxed">
				{$i18n.t('Point Harvis at a Hermes Agent API server you already run. Chat routes to it; Harvis keeps the UI, history and safety.')}
			</p>
			<div class="space-y-1.5">
				<input
					type="text"
					bind:value={extUrl}
					placeholder="http://your-hermes-host:8642"
					class="w-full text-xs rounded-lg border border-gray-200 dark:border-white/10 bg-white dark:bg-[#0b1220] px-2.5 py-1.5 text-gray-700 dark:text-gray-200 font-mono"
				/>
				<input
					type="password"
					bind:value={extToken}
					placeholder={ext?.token_saved ? $i18n.t('Token saved · enter a new one to replace') : $i18n.t('API token (optional)')}
					class="w-full text-xs rounded-lg border border-gray-200 dark:border-white/10 bg-white dark:bg-[#0b1220] px-2.5 py-1.5 text-gray-700 dark:text-gray-200"
				/>
			</div>
			<div class="flex items-center gap-2 text-[11px]">
				<span class="text-gray-500 dark:text-gray-400">{$i18n.t('Status')}:</span>
				{#if ext?.connected}
					<span class="text-green-600 dark:text-green-400">● {$i18n.t('Connected & verified')}</span>
				{:else if ext?.last_error}
					<span class="text-red-500">● {ext.last_error}</span>
				{:else if ext?.url}
					<span class="text-amber-500">● {$i18n.t('Saved · not verified')}</span>
				{:else}
					<span class="text-gray-500 dark:text-gray-400">{$i18n.t('Not connected')}</span>
				{/if}
			</div>
			<div class="flex items-center gap-2">
				<button
					type="button"
					disabled={extBusy || !extUrl.trim()}
					class="text-xs px-3 py-1.5 rounded-lg border border-blue-500/30 text-blue-600 dark:text-blue-300 bg-blue-500/10 hover:bg-blue-500/15 transition disabled:opacity-50"
					on:click={saveExternal}>{extBusy ? $i18n.t('Connecting…') : $i18n.t('Save & verify')}</button
				>
				{#if ext?.url}
					<button
						type="button"
						disabled={extBusy}
						class="text-xs px-3 py-1.5 rounded-lg border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5 transition disabled:opacity-50"
						on:click={disconnectExternal}>{$i18n.t('Disconnect')}</button
					>
				{/if}
			</div>
			<p class="text-[10px] text-amber-600/90 dark:text-amber-400/90 leading-relaxed">
				{$i18n.t('Build is unavailable in external mode — it needs workspace access the external server does not have. Shared filesystem, workspace sync and a tool bridge are on the roadmap.')}
			</p>
		</div>

	<!-- ── Mode 3: Harvis-managed fallback (Advanced) ── -->
	{:else}
		<div class="rounded-xl border border-gray-100 dark:border-white/8 bg-gray-50/60 dark:bg-[#0f1626] p-3.5 space-y-2.5">
			<p class="text-xs text-gray-600 dark:text-gray-300 leading-relaxed">
				{$i18n.t('A fresh, Harvis-managed Hermes profile running in the local sidecar — good for demos, dev and new users. It does NOT import your desktop Hermes automatically (use Import for that).')}
			</p>
			<div class="text-xs text-gray-500 dark:text-gray-400 space-y-1">
				<div class="flex items-center justify-between">
					<span>{$i18n.t('Sidecar (harvis-hermes-agent)')}</span>
					<span class={hermesReachable ? 'text-green-600 dark:text-green-400' : 'text-orange-500'}>
						{hermesReachable === null ? '—' : hermesReachable ? $i18n.t('Reachable') : $i18n.t('Not reachable')}
					</span>
				</div>
				<div class="flex items-center justify-between">
					<span>{$i18n.t('Provider')}</span><span>{$i18n.t('Ollama · no credentials')}</span>
				</div>
				<div class="flex items-center justify-between">
					<span>{$i18n.t('Powered by')}</span>
					<span class="font-mono text-gray-700 dark:text-gray-200">{hermesModel ?? '—'}</span>
				</div>
			</div>
			<div class="space-y-1.5">
				<label class="text-xs font-medium text-gray-700 dark:text-gray-200" for="hermes-managed-model">{$i18n.t('Hermes Agent model')}</label>
				<select
					id="hermes-managed-model"
					class="w-full text-xs rounded-lg border border-gray-200 dark:border-white/10 bg-white dark:bg-[#0b1220] px-2.5 py-1.5 text-gray-700 dark:text-gray-200 disabled:opacity-50"
					disabled={modelBusy || installedModels.length === 0}
					value={hermesModelPref ?? ''}
					on:change={onModelChange}
				>
					<option value="">{$i18n.t('Auto (recommended installed model)')}</option>
					{#each installedModels as m}<option value={m}>{m}</option>{/each}
				</select>
				<p class="text-[11px] text-gray-500 dark:text-gray-400 leading-relaxed">
					{$i18n.t('Smaller models are faster but may be less reliable with tools. Larger models may be slower but better for complex tasks.')}
				</p>
			</div>
		</div>
	{/if}
</div>
