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
	type ErrorKind = 'auth' | 'backend' | 'app' | 'frame-timeout';
	let status: 'checking' | 'ready' | 'error' = 'checking';
	let errorKind: ErrorKind | null = null;
	let errorDetail = '';
	let frameLoaded = false;
	let frameTimer: ReturnType<typeof setTimeout> | null = null;
	let probeSeq = 0;

	const PROBE_TIMEOUT_MS = 8000;
	const FRAME_TIMEOUT_MS = 20000;

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
		status = 'checking';
		errorKind = null;
		errorDetail = '';
		clearFrameTimer();

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
	onDestroy(clearFrameTimer);

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
