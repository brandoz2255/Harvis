<script lang="ts">
	// Integrations → Connection panel (Phase B1). Surfaces the user's per-integration
	// connection state + connect/manage actions, driving the EXISTING encrypted endpoints.
	// No new backend. Source of truth for per-user connection state (cards stay deploy-level).
	import { onMount, onDestroy, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import type { IntegrationDefinition } from '$lib/integrations/catalog';
	import {
		getOpenclawConfig,
		verifyOpenclawByo,
		saveOpenclawConfig,
		getMcpConnections,
		type OpenclawConfig
	} from '$lib/apis/integrations';
	import { getGithubStatus, getGithubStartUrl, disconnectGithub } from '$lib/apis/agent-runs';

	const i18n: any = getContext('i18n');
	export let def: IntegrationDefinition;

	// ── OpenClaw BYO ──
	let cfg: OpenclawConfig | null = null;
	let loaded = false;
	let url = '';
	let token = '';
	let replacingToken = false;
	let busy = false;
	let ocMsg: { text: string; ok: boolean } | null = null;

	const loadOpenclaw = async () => {
		loaded = false;
		cfg = await getOpenclawConfig();
		loaded = true;
		url = cfg?.byo_url ?? '';
		replacingToken = false;
		token = '';
	};

	const validUrl = (u: string) => /^wss?:\/\//.test(u.trim());

	const verify = async () => {
		if (!validUrl(url)) {
			ocMsg = { text: $i18n.t('Gateway URL must start with ws:// or wss://'), ok: false };
			return;
		}
		busy = true;
		ocMsg = null;
		const r = await verifyOpenclawByo(url.trim(), token || undefined);
		busy = false;
		if (r.ok) {
			ocMsg = { text: $i18n.t('Verified — your workspace sessions will route to your gateway.'), ok: true };
			await loadOpenclaw();
		} else {
			ocMsg = { text: (r.error || $i18n.t('Verification failed')) + (r.hint ? ` — ${r.hint}` : ''), ok: false };
		}
	};

	const saveOnly = async () => {
		if (!validUrl(url)) {
			ocMsg = { text: $i18n.t('Gateway URL must start with ws:// or wss://'), ok: false };
			return;
		}
		busy = true;
		const r = await saveOpenclawConfig({ mode: 'byo', byo_url: url.trim(), byo_token: token || undefined });
		busy = false;
		if (r.ok) {
			ocMsg = { text: $i18n.t('Saved. Routing stays bundled until you Verify.'), ok: true };
			await loadOpenclaw();
		} else {
			ocMsg = { text: r.error || $i18n.t('Save failed'), ok: false };
		}
	};

	const useBundled = async () => {
		busy = true;
		const r = await saveOpenclawConfig({ mode: 'bundled' });
		busy = false;
		if (r.ok) {
			ocMsg = { text: $i18n.t('Switched to the bundled OpenClaw runtime.'), ok: true };
			await loadOpenclaw();
		} else {
			ocMsg = { text: r.error || $i18n.t('Failed'), ok: false };
		}
	};

	// ── GitHub OAuth ──
	let gh: { connected: boolean; login?: string; name?: string; avatar_url?: string } = { connected: false };
	let ghBusy = false;
	let ghMsg = '';
	let pollTimer: any = null;

	const loadGithub = async () => {
		try {
			gh = await getGithubStatus();
		} catch (_) {
			gh = { connected: false };
		}
	};

	const connectGithub = async () => {
		ghBusy = true;
		ghMsg = '';
		const res = await getGithubStartUrl();
		ghBusy = false;
		if (!res.ok || !res.redirect) {
			ghMsg = res.error || $i18n.t("GitHub OAuth isn't configured on this server.");
			return;
		}
		const w = window.open(res.redirect, '_blank', 'noopener');
		if (!w) {
			// popup blocked — fall back to a full navigation
			ghMsg = $i18n.t('Popup blocked — opening GitHub authorization…');
			window.location.href = res.redirect;
			return;
		}
		let tries = 0;
		if (pollTimer) clearInterval(pollTimer);
		pollTimer = setInterval(async () => {
			tries += 1;
			const s = await getGithubStatus();
			if (s.connected || tries > 60) {
				clearInterval(pollTimer);
				pollTimer = null;
				if (s.connected) {
					gh = s;
					toast.success($i18n.t('GitHub connected'));
				}
			}
		}, 2000);
	};

	const disconnectGh = async () => {
		ghBusy = true;
		try {
			await disconnectGithub();
		} catch (_) {}
		ghBusy = false;
		gh = { connected: false };
	};

	// ── MCP ──
	let mcpCount: number | null = null;
	const loadMcp = async () => {
		const items = await getMcpConnections();
		mcpCount = items.length;
	};

	onMount(() => {
		if (def.connect === 'openclaw_byo') loadOpenclaw();
		else if (def.connect === 'github_oauth') loadGithub();
		else if (def.connect === 'mcp_link') loadMcp();
	});
	onDestroy(() => {
		if (pollTimer) clearInterval(pollTimer);
	});
</script>

<div class="space-y-2.5">
	<div class="text-xs font-semibold text-gray-700 dark:text-gray-200">{$i18n.t('Connection')}</div>

	{#if def.connect === 'openclaw_byo'}
		<div class="rounded-lg border border-gray-100 dark:border-white/8 bg-gray-50 dark:bg-white/[0.02] p-3 space-y-3">
			<div class="flex items-center justify-between gap-2 text-xs">
				<span class="text-gray-500 dark:text-gray-400">
					{$i18n.t('Current runtime')}:
					<span class="font-medium text-gray-700 dark:text-gray-200">
						{!loaded
							? $i18n.t('Loading…')
							: !cfg
								? $i18n.t('Unknown')
								: cfg.mode === 'byo'
									? $i18n.t('Your gateway')
									: $i18n.t('Bundled OpenClaw')}
					</span>
				</span>
				{#if cfg?.mode === 'byo' && cfg?.byo_verified_at}
					<span class="text-[11px] text-green-600 dark:text-green-400">{$i18n.t('Verified')}</span>
				{/if}
			</div>
			{#if loaded && !cfg}
				<p class="text-[11px] text-red-500">{$i18n.t("Couldn't load connection state.")}</p>
			{:else if cfg?.byo_last_error}
				<p class="text-[11px] text-red-500">{cfg.byo_last_error}</p>
			{/if}

			<label class="block space-y-1">
				<span class="text-[11px] text-gray-500 dark:text-gray-400">{$i18n.t('Gateway URL')}</span>
				<input
					bind:value={url}
					type="text"
					placeholder="ws://your-openclaw-host:18789"
					class="w-full text-xs font-mono rounded-lg border border-gray-200 dark:border-white/10 bg-white dark:bg-[#0a0e18] px-2.5 py-1.5 text-gray-700 dark:text-gray-200 outline-none focus:border-blue-500/40"
				/>
			</label>

			<div class="space-y-1">
				<span class="text-[11px] text-gray-500 dark:text-gray-400">{$i18n.t('Gateway token')}</span>
				{#if cfg?.byo_token_saved && !replacingToken}
					<div class="flex items-center gap-2 text-xs">
						<span class="text-gray-500 dark:text-gray-400">🔒 {$i18n.t('Token saved')}</span>
						<button type="button" class="text-blue-600 dark:text-blue-300 hover:underline" on:click={() => (replacingToken = true)}>
							{$i18n.t('Replace token')}
						</button>
					</div>
				{:else}
					<input
						bind:value={token}
						type="password"
						autocomplete="off"
						placeholder={$i18n.t('Write-only — never displayed')}
						class="w-full text-xs font-mono rounded-lg border border-gray-200 dark:border-white/10 bg-white dark:bg-[#0a0e18] px-2.5 py-1.5 text-gray-700 dark:text-gray-200 outline-none focus:border-blue-500/40"
					/>
				{/if}
			</div>

			<p class="text-[11px] text-gray-400">
				{$i18n.t('Verify enables routing to your gateway. Saving without verifying keeps bundled routing until verified.')}
			</p>

			{#if ocMsg}
				<p class="text-[11px] {ocMsg.ok ? 'text-green-600 dark:text-green-400' : 'text-red-500'}">{ocMsg.text}</p>
			{/if}

			<div class="flex flex-wrap items-center gap-2">
				<button
					type="button"
					disabled={busy}
					class="text-xs px-2.5 py-1 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium transition"
					on:click={verify}
				>
					{$i18n.t('Verify & connect')}
				</button>
				<button
					type="button"
					disabled={busy}
					class="text-xs px-2.5 py-1 rounded-lg border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5 transition"
					on:click={saveOnly}
				>
					{$i18n.t('Save connection')}
				</button>
				{#if cfg?.mode === 'byo'}
					<button
						type="button"
						disabled={busy}
						class="text-xs px-2.5 py-1 rounded-lg border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5 transition"
						on:click={useBundled}
					>
						{$i18n.t('Use bundled')}
					</button>
				{/if}
			</div>
		</div>
	{:else if def.connect === 'github_oauth'}
		<div class="rounded-lg border border-gray-100 dark:border-white/8 bg-gray-50 dark:bg-white/[0.02] p-3 space-y-2.5">
			{#if gh.connected}
				<div class="flex items-center gap-2.5">
					{#if gh.avatar_url}<img src={gh.avatar_url} alt="" class="size-6 rounded-full" />{/if}
					<span class="text-xs text-gray-700 dark:text-gray-200">
						{$i18n.t('Connected as')} <span class="font-medium">@{gh.login}</span>
					</span>
				</div>
				<button
					type="button"
					disabled={ghBusy}
					class="text-xs px-2.5 py-1 rounded-lg border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5 transition"
					on:click={disconnectGh}
				>
					{$i18n.t('Disconnect')}
				</button>
			{:else}
				<p class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Not connected.')}</p>
				<button
					type="button"
					disabled={ghBusy}
					class="text-xs px-2.5 py-1 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium transition"
					on:click={connectGithub}
				>
					{$i18n.t('Connect GitHub')}
				</button>
			{/if}
			{#if ghMsg}<p class="text-[11px] text-amber-500">{ghMsg}</p>{/if}
		</div>
	{:else if def.connect === 'mcp_link'}
		<div class="rounded-lg border border-gray-100 dark:border-white/8 bg-gray-50 dark:bg-white/[0.02] p-3 flex items-center justify-between gap-3">
			<span class="text-xs text-gray-600 dark:text-gray-300">
				{#if mcpCount === null}{$i18n.t('Loading…')}{:else}{mcpCount}
					{mcpCount === 1 ? $i18n.t('server connected') : $i18n.t('servers connected')}{/if}
			</span>
			<button
				type="button"
				class="text-xs px-2.5 py-1 rounded-lg border border-blue-500/30 text-blue-600 dark:text-blue-300 bg-blue-500/10 hover:bg-blue-500/15 transition"
				on:click={() => goto('/harvis/agent-studio/customize')}
			>
				{$i18n.t('Manage connections')}
			</button>
		</div>
	{/if}
</div>
