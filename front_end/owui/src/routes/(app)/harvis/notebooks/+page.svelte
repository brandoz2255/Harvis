<script lang="ts">
	import { getContext, onMount, onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { WEBUI_NAME, showSidebar } from '$lib/stores';

	const i18n: any = getContext('i18n');

	// Open Notebook is the vendored open-notebook Next.js app served at /onb. We embed
	// it in an iframe INSIDE the Harvis shell. Same-origin → it shares the Harvis JWT
	// (localStorage.token) and talks to the onb_compat facade at /onb-api.
	//
	// The open-notebook nav now lives in the Harvis left sidebar (NotebookNav), which
	// drives this iframe via the `?onb=` query param (e.g. ?onb=/sources → /onb/sources).
	// Default (no param) = the notebooks home. The app's own AppSidebar is not rendered,
	// so the iframe content runs full-width.
	$: onbPath = $page.url.searchParams.get('onb') ?? '';
	$: iframeSrc = `/onb${onbPath}`;

	// ── Honest load states ──────────────────────────────────────────────────────
	// Before mounting the iframe we probe both halves of the lane so failures are
	// visible instead of a blank frame:
	//   /onb-api/notebooks (backend facade — also validates the Harvis JWT)
	//   /onb               (the embedded Next app behind nginx)
	// 'checking' is bounded (probe timeout below), never an indefinite spinner.
	//
	// 'not-installed' is a fourth outcome and NOT an error: Notebooks ships behind
	// the opt-in `notebooks` compose profile, so a correct default install has no
	// open-notebook-ui container and nginx 502s /onb. Calling that "unreachable"
	// blamed the operator for a choice the project made for them.
	type ErrorKind = 'auth' | 'backend' | 'app' | 'frame-timeout';
	let status: 'checking' | 'ready' | 'error' | 'not-installed' = 'checking';
	let errorKind: ErrorKind | null = null;
	let errorDetail = '';
	let frameLoaded = false;
	let frameTimer: ReturnType<typeof setTimeout> | null = null;
	let probeSeq = 0;

	const PROBE_TIMEOUT_MS = 8000;
	const FRAME_TIMEOUT_MS = 20000;
	const INSTALL_POLL_MS = 6000;

	type Capability = {
		state: string;
		reason?: string;
		profile?: string;
		services?: string[];
		download_mb?: number;
		enable?: { command?: string; run_from?: string };
	};
	let capability: Capability | null = null;
	let installTimer: ReturnType<typeof setTimeout> | null = null;
	let copied = false;

	// Server-supplied, not hardcoded here: the backend measured it and owns the
	// compose command, so this page can't drift from what actually installs.
	$: downloadLabel = capability?.download_mb
		? capability.download_mb >= 1024
			? `${(capability.download_mb / 1024).toFixed(1)} GB`
			: `${capability.download_mb} MB`
		: '';
	$: enableCommand = capability?.enable?.command ?? 'docker compose --profile notebooks up -d';

	const probe = async (
		url: string,
		headers: Record<string, string> = {}
	): Promise<{ ok: boolean; status: number; timedOut: boolean }> => {
		const ctrl = new AbortController();
		const t = setTimeout(() => ctrl.abort(), PROBE_TIMEOUT_MS);
		try {
			const r = await fetch(url, {
				headers,
				credentials: 'include',
				cache: 'no-store',
				signal: ctrl.signal
			});
			return { ok: r.ok, status: r.status, timedOut: false };
		} catch (_) {
			return { ok: false, status: 0, timedOut: ctrl.signal.aborted };
		} finally {
			clearTimeout(t);
		}
	};

	const clearFrameTimer = () => {
		if (frameTimer) {
			clearTimeout(frameTimer);
			frameTimer = null;
		}
	};

	const clearInstallTimer = () => {
		if (installTimer) {
			clearTimeout(installTimer);
			installTimer = null;
		}
	};

	// Asked only when /onb fails — a healthy lane never pays for this round-trip.
	const fetchCapability = async (token: string): Promise<Capability | null> => {
		try {
			const r = await fetch('/api/capabilities/notebooks', {
				headers: { Authorization: `Bearer ${token}` },
				credentials: 'include',
				cache: 'no-store'
			});
			if (!r.ok) return null;
			return (await r.json()) as Capability;
		} catch (_) {
			return null;
		}
	};

	const copyCommand = async () => {
		try {
			await navigator.clipboard.writeText(enableCommand);
			copied = true;
			setTimeout(() => (copied = false), 1600);
		} catch (_) {
			copied = false;
		}
	};

	const onFrameLoad = () => {
		frameLoaded = true;
		clearFrameTimer();
	};

	const armFrameTimer = () => {
		clearFrameTimer();
		frameLoaded = false;
		frameTimer = setTimeout(() => {
			if (!frameLoaded) {
				status = 'error';
				errorKind = 'frame-timeout';
				errorDetail = `${$i18n.t('The embedded app did not finish loading within')} ${
					FRAME_TIMEOUT_MS / 1000
				}s.`;
			}
		}, FRAME_TIMEOUT_MS);
	};

	const check = async () => {
		const seq = ++probeSeq;
		// Only the not-installed branch re-arms the poll, so clearing here means a
		// lane that recovers (or breaks differently) stops polling on its own.
		clearInstallTimer();
		errorKind = null;
		errorDetail = '';
		clearFrameTimer();
		// Don't flash the spinner over the install panel while polling behind it —
		// the panel says what it's waiting for and stays put until it succeeds.
		if (status !== 'not-installed') status = 'checking';

		const token = localStorage.getItem('token');
		if (!token) {
			status = 'error';
			errorKind = 'auth';
			errorDetail = $i18n.t('No session token was found — you are signed out.');
			return;
		}

		const [api, app] = await Promise.all([
			probe('/onb-api/notebooks', { Authorization: `Bearer ${token}` }),
			probe(iframeSrc)
		]);
		if (seq !== probeSeq) return; // superseded by a newer retry

		if (api.status === 401 || api.status === 403) {
			status = 'error';
			errorKind = 'auth';
			errorDetail = `${$i18n.t('Your session is expired or invalid')} (HTTP ${api.status}).`;
			return;
		}
		if (!api.ok) {
			status = 'error';
			errorKind = 'backend';
			errorDetail = api.timedOut
				? `${$i18n.t('No response within')} ${PROBE_TIMEOUT_MS / 1000}s.`
				: api.status
					? `HTTP ${api.status}.`
					: $i18n.t('Network error — the request did not reach the server.');
			return;
		}
		if (!app.ok) {
			// Ask the backend whether this is a missing capability or a broken one
			// before blaming anything. It probes open-notebook-ui directly, so it
			// can tell "container absent" from "container erroring".
			const cap = await fetchCapability(token);
			if (seq !== probeSeq) return;
			if (cap?.state === 'not_installed') {
				capability = cap;
				status = 'not-installed';
				// Auto-flip: once the operator runs the command the services answer
				// and the next poll drops straight into the iframe below — no reload.
				installTimer = setTimeout(check, INSTALL_POLL_MS);
				return;
			}
			status = 'error';
			errorKind = 'app';
			errorDetail = app.timedOut
				? `${$i18n.t('No response within')} ${PROBE_TIMEOUT_MS / 1000}s.`
				: app.status
					? `HTTP ${app.status} ${
							app.status === 502 || app.status === 504
								? $i18n.t('— the open-notebook-ui container may be down.')
								: ''
						}`.trim() + '.'
					: $i18n.t('Network error — the request did not reach the server.');
			return;
		}

		status = 'ready';
		armFrameTimer();
	};

	onMount(check);
	onDestroy(() => {
		clearFrameTimer();
		clearInstallTimer();
	});

	const ERROR_TITLES: Record<ErrorKind, string> = {
		auth: 'Sign-in required',
		backend: 'Harvis backend unreachable',
		app: 'Open Notebook app unreachable',
		'frame-timeout': 'Open Notebook is not loading'
	};
</script>

<svelte:head>
	<title>{$i18n.t('Open Notebook')} • {$WEBUI_NAME}</title>
</svelte:head>

<div class="w-full h-full {$showSidebar ? 'md:max-w-[calc(100%-var(--sidebar-width))]' : ''}">
	{#if status === 'ready'}
		<iframe
			src={iframeSrc}
			title={$i18n.t('Open Notebook')}
			class="w-full h-full border-0 block"
			allow="clipboard-read; clipboard-write; microphone"
			on:load={onFrameLoad}
		></iframe>
	{:else if status === 'checking'}
		<!-- Bounded pre-flight (max {PROBE_TIMEOUT_MS}ms) — resolves to ready or an error state. -->
		<div class="w-full h-full flex items-center justify-center">
			<div class="flex items-center gap-2.5 text-sm text-gray-500 dark:text-gray-400">
				<svg
					xmlns="http://www.w3.org/2000/svg"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="1.8"
					stroke-linecap="round"
					class="size-4 animate-spin"
				>
					<path d="M21 12a9 9 0 1 1-6.219-8.56" />
				</svg>
				<span>{$i18n.t('Checking Open Notebook…')}</span>
			</div>
		</div>
	{:else if status === 'not-installed'}
		<!-- Not an error state: the pack is opt-in and simply hasn't been pulled. -->
		<div class="w-full h-full flex items-center justify-center px-6">
			<div
				class="max-w-lg w-full rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 px-6 py-7"
			>
				<div
					class="mx-auto mb-3 flex size-10 items-center justify-center rounded-full bg-blue-500/10 text-blue-600 dark:text-blue-400"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.8"
						stroke-linecap="round"
						stroke-linejoin="round"
						class="size-5"
					>
						<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
						<path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
					</svg>
				</div>
				<div class="text-center text-sm font-medium text-gray-800 dark:text-gray-100">
					{$i18n.t('Notebooks is not installed yet')}
				</div>
				<div class="mt-1.5 text-center text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t(
						'Notebooks turns your sources into notes, summaries and podcasts. It is an optional pack, so a default Harvis install leaves it out to stay small.'
					)}
					{#if downloadLabel}
						<span class="whitespace-nowrap"
							>{$i18n.t('Adds about')} {downloadLabel} {$i18n.t('of images.')}</span
						>
					{/if}
				</div>

				<div class="mt-4">
					<div
						class="text-[0.65rem] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500"
					>
						{$i18n.t('Run this')}{#if capability?.enable?.run_from}
							&nbsp;{$i18n.t('from')} {capability.enable.run_from}{/if}
					</div>
					<div
						class="mt-1.5 flex items-center gap-2 rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 px-3 py-2"
					>
						<code
							class="flex-1 overflow-x-auto whitespace-pre text-xs text-gray-800 dark:text-gray-200"
							>{enableCommand}</code
						>
						<button
							type="button"
							on:click={copyCommand}
							class="shrink-0 rounded-md border border-gray-200 dark:border-gray-800 px-2 py-1 text-[0.7rem] font-medium text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						>
							{copied ? $i18n.t('Copied') : $i18n.t('Copy')}
						</button>
					</div>
					{#if capability?.services?.length}
						<div class="mt-1.5 text-[0.7rem] text-gray-400 dark:text-gray-500">
							{$i18n.t('Starts')}: {capability.services.join(', ')}
						</div>
					{/if}
				</div>

				<div
					class="mt-4 flex items-center justify-center gap-2 text-xs text-gray-500 dark:text-gray-400"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.8"
						stroke-linecap="round"
						class="size-3.5 animate-spin"
					>
						<path d="M21 12a9 9 0 1 1-6.219-8.56" />
					</svg>
					<span>{$i18n.t('Watching — this page opens Notebooks as soon as it answers.')}</span>
				</div>
				<div class="mt-3 flex items-center justify-center">
					<button
						type="button"
						on:click={check}
						class="rounded-lg bg-blue-600 hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600 px-3.5 py-1.5 text-xs font-medium text-white transition"
					>
						{$i18n.t('Check now')}
					</button>
				</div>
			</div>
		</div>
	{:else if status === 'error' && errorKind}
		<div class="w-full h-full flex items-center justify-center px-6">
			<div
				class="max-w-md w-full rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 px-6 py-7 text-center"
			>
				<div
					class="mx-auto mb-3 flex size-10 items-center justify-center rounded-full bg-blue-500/10 text-blue-600 dark:text-blue-400"
				>
					{#if errorKind === 'auth'}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.8"
							stroke-linecap="round"
							stroke-linejoin="round"
							class="size-5"
						>
							<rect x="3" y="11" width="18" height="11" rx="2" />
							<path d="M7 11V7a5 5 0 0 1 10 0v4" />
						</svg>
					{:else}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="1.8"
							stroke-linecap="round"
							stroke-linejoin="round"
							class="size-5"
						>
							<path
								d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"
							/>
							<path d="M12 9v4M12 17h.01" />
						</svg>
					{/if}
				</div>
				<div class="text-sm font-medium text-gray-800 dark:text-gray-100">
					{$i18n.t(ERROR_TITLES[errorKind])}
				</div>
				<div class="mt-1.5 text-xs text-gray-500 dark:text-gray-400 break-words">
					{errorDetail}
				</div>
				<div class="mt-4 flex items-center justify-center gap-2">
					<button
						type="button"
						on:click={check}
						class="rounded-lg bg-blue-600 hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600 px-3.5 py-1.5 text-xs font-medium text-white transition"
					>
						{$i18n.t('Retry')}
					</button>
					{#if errorKind === 'auth'}
						<a
							href="/auth"
							class="rounded-lg border border-gray-200 dark:border-gray-800 px-3.5 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						>
							{$i18n.t('Go to sign in')}
						</a>
					{/if}
				</div>
			</div>
		</div>
	{/if}
</div>
