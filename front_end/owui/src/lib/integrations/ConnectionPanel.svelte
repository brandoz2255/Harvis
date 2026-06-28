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
		getEngineAuth,
		saveEngineKey,
		verifyEngineKey,
		disconnectEngine,
		type OpenclawConfig,
		type EngineAuthStatus
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

	// ── Cloud engine API key (Phase E2: codex / claude-code) ──
	$: authEngine = def.id === 'codex-app' ? 'codex' : 'claude-code';
	// E4B: only Claude Code offers a Claude-subscription (OAuth token) mode; Codex is API-key-only.
	$: supportsOauth = authEngine === 'claude-code';
	let ea: EngineAuthStatus | null = null;
	let eaLoaded = false;
	let engineKey = '';
	let authMode = 'api_key'; // 'api_key' | 'oauth_token'
	let replacingKey = false;
	let eaBusy = false;
	let eaMsg: { text: string; ok: boolean } | null = null;
	let copiedCmd = false;
	const copySetupCmd = async () => {
		try {
			await navigator.clipboard.writeText('claude setup-token');
			copiedCmd = true;
			setTimeout(() => (copiedCmd = false), 1500);
		} catch (_) {}
	};

	const loadEngineAuth = async () => {
		eaLoaded = false;
		ea = await getEngineAuth(authEngine);
		eaLoaded = true;
		replacingKey = false;
		engineKey = '';
		authMode = ea?.auth_mode || 'api_key';
	};

	const saveAndVerifyKey = async () => {
		if (!engineKey.trim()) {
			eaMsg = {
				text: authMode === 'oauth_token' ? $i18n.t('Enter your Claude subscription token') : $i18n.t('Enter your API key'),
				ok: false
			};
			return;
		}
		eaBusy = true;
		eaMsg = null;
		await saveEngineKey(authEngine, engineKey.trim(), authMode);
		const r = await verifyEngineKey(authEngine, engineKey.trim(), authMode);
		eaBusy = false;
		eaMsg = r.ok
			? { text: $i18n.t('Connected & verified.'), ok: true }
			: { text: r.error || $i18n.t('Verification failed'), ok: false };
		await loadEngineAuth();
	};

	const verifySavedKey = async () => {
		eaBusy = true;
		eaMsg = null;
		const r = await verifyEngineKey(authEngine, undefined, authMode);
		eaBusy = false;
		eaMsg = r.ok
			? { text: $i18n.t('Verified.'), ok: true }
			: { text: r.error || $i18n.t('Verification failed'), ok: false };
		await loadEngineAuth();
	};

	const disconnectEngineKey = async () => {
		eaBusy = true;
		await disconnectEngine(authEngine);
		eaBusy = false;
		eaMsg = null;
		await loadEngineAuth();
	};

	onMount(() => {
		if (def.connect === 'openclaw_byo') loadOpenclaw();
		else if (def.connect === 'github_oauth') loadGithub();
		else if (def.connect === 'mcp_link') loadMcp();
		else if (def.connect === 'engine_api_key') loadEngineAuth();
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
	{:else if def.connect === 'engine_api_key'}
		<div class="rounded-lg border border-gray-100 dark:border-white/8 bg-gray-50 dark:bg-white/[0.02] p-3 space-y-3">
			<div class="flex items-center justify-between gap-2 text-xs">
				<span class="text-gray-500 dark:text-gray-400">
					{$i18n.t('Status')}:
					<span class="font-medium text-gray-700 dark:text-gray-200">
						{!eaLoaded
							? $i18n.t('Loading…')
							: ea?.verified_at
								? $i18n.t('Connected')
								: ea?.api_key_saved
									? $i18n.t('Key saved · not verified')
									: $i18n.t('Not connected')}
					</span>
				</span>
				{#if ea?.verified_at}<span class="text-[11px] text-green-600 dark:text-green-400">{$i18n.t('Verified')}</span>{/if}
			</div>
			{#if ea?.last_error}<p class="text-[11px] text-red-500">{ea.last_error}</p>{/if}

			{#if supportsOauth}
				<p class="text-[11px] text-gray-500 dark:text-gray-400">
					{$i18n.t('Connect Claude Code with an Anthropic API key or a Claude subscription token.')}
				</p>
				<!-- E4B: auth-mode toggle (Claude Code only). Switching clears the field so the user
				     enters a credential for the chosen mode; only one is ever stored/injected. -->
				<div class="inline-flex rounded-lg border border-gray-200 dark:border-white/10 overflow-hidden text-[11px]">
					<button
						type="button"
						class="px-2.5 py-1 transition {authMode === 'api_key'
							? 'bg-blue-600 text-white'
							: 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5'}"
						on:click={() => {
							if (authMode !== 'api_key') {
								authMode = 'api_key';
								replacingKey = true;
								engineKey = '';
								eaMsg = null;
							}
						}}>{$i18n.t('API key')}</button
					>
					<button
						type="button"
						class="px-2.5 py-1 transition {authMode === 'oauth_token'
							? 'bg-blue-600 text-white'
							: 'text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5'}"
						on:click={() => {
							if (authMode !== 'oauth_token') {
								authMode = 'oauth_token';
								replacingKey = true;
								engineKey = '';
								eaMsg = null;
							}
						}}>{$i18n.t('Claude subscription')}</button
					>
				</div>
			{/if}

			{#if authMode === 'oauth_token' && (!ea?.api_key_saved || replacingKey)}
				<div class="rounded-lg border border-blue-500/20 bg-blue-500/5 p-2.5 space-y-1.5 text-[11px]">
					<div class="font-medium text-gray-700 dark:text-gray-200">
						{$i18n.t('Get your subscription token (one-time):')}
					</div>
					<ol class="list-decimal ml-3.5 space-y-1 text-gray-500 dark:text-gray-400">
						<li>
							{$i18n.t('In a terminal, run:')}
							<span class="mt-1 flex items-center gap-1.5">
								<code class="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-white/10 text-gray-700 dark:text-gray-200 font-mono">claude setup-token</code>
								<button type="button" class="text-blue-600 dark:text-blue-300 hover:underline" on:click={copySetupCmd}>
									{copiedCmd ? $i18n.t('Copied') : $i18n.t('Copy')}
								</button>
							</span>
						</li>
						<li>{$i18n.t('Sign in with your Claude account (Pro, Max, Team, or Enterprise).')}</li>
						<li>{$i18n.t('Copy the token it prints and paste it below.')}</li>
					</ol>
					<div class="text-gray-400">
						{$i18n.t('Lasts ~1 year · no API credits used · stored encrypted, never shown.')}
					</div>
				</div>
			{/if}

			<div class="space-y-1">
				<span class="text-[11px] text-gray-500 dark:text-gray-400">
					{authMode === 'oauth_token' ? $i18n.t('Claude subscription token') : $i18n.t('API key')}
				</span>
				{#if ea?.api_key_saved && !replacingKey}
					<div class="flex items-center gap-2 text-xs">
						<span class="text-gray-500 dark:text-gray-400"
							>🔑 {ea?.auth_mode === 'oauth_token'
								? $i18n.t('Subscription token saved')
								: $i18n.t('API key saved')}</span
						>
						<button type="button" class="text-blue-600 dark:text-blue-300 hover:underline" on:click={() => (replacingKey = true)}>
							{$i18n.t('Replace')}
						</button>
					</div>
				{:else}
					<input
						bind:value={engineKey}
						type="password"
						autocomplete="off"
						placeholder={authMode === 'oauth_token'
							? $i18n.t('Paste your Claude subscription token')
							: $i18n.t('Write-only — never displayed')}
						class="w-full text-xs font-mono rounded-lg border border-gray-200 dark:border-white/10 bg-white dark:bg-[#0a0e18] px-2.5 py-1.5 text-gray-700 dark:text-gray-200 outline-none focus:border-blue-500/40"
					/>
				{/if}
			</div>

			<p class="text-[11px] text-gray-400">
				{#if def.id === 'codex-app'}
					{$i18n.t('Your OpenAI API key — used only to run Codex in Build, stored encrypted, never shown. OpenCode needs no key (local).')}
				{:else if authMode === 'oauth_token'}
					{$i18n.t('Run `claude setup-token` in your terminal (needs Claude Pro/Max/Team/Enterprise), then paste the token here. No API credits required — stored encrypted, never shown.')}
				{:else}
					{$i18n.t('Your Anthropic API key — used only to run Claude Code in Build, stored encrypted, never shown.')}
				{/if}
			</p>

			{#if eaMsg}
				<p class="text-[11px] {eaMsg.ok ? 'text-green-600 dark:text-green-400' : 'text-red-500'}">{eaMsg.text}</p>
			{/if}

			<div class="flex flex-wrap items-center gap-2">
				{#if !ea?.api_key_saved || replacingKey}
					<button
						type="button"
						disabled={eaBusy}
						class="text-xs px-2.5 py-1 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium transition"
						on:click={saveAndVerifyKey}
					>
						{$i18n.t('Connect & verify')}
					</button>
				{:else}
					<button
						type="button"
						disabled={eaBusy}
						class="text-xs px-2.5 py-1 rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium transition"
						on:click={verifySavedKey}
					>
						{$i18n.t('Re-verify')}
					</button>
				{/if}
				{#if ea?.api_key_saved}
					<button
						type="button"
						disabled={eaBusy}
						class="text-xs px-2.5 py-1 rounded-lg border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5 transition"
						on:click={disconnectEngineKey}
					>
						{$i18n.t('Disconnect')}
					</button>
				{/if}
			</div>
		</div>
	{/if}
</div>
