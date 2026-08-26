<script lang="ts">
	// Repo Runner SURFACE — a task-shaped terminal workbench. Clone a public repo
	// into an isolated per-space checkout, read its setup, detect the stack, and
	// surface REAL terminal output (the git clone log). ONE approval covers the
	// whole sandbox run (install → dev server → live preview) — Harvis keeps
	// going autonomously after that, and nothing is faked.
	import { getContext, createEventDispatcher, onDestroy } from 'svelte';
	import { fade, fly } from 'svelte/transition';
	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let space: any = null;

	const hdrs = () => ({ Authorization: `Bearer ${localStorage.token}`, 'Content-Type': 'application/json' });

	$: repo = space?.manifest?.repo ?? null;

	// ── Live app preview (gated: runs untrusted repo code in an isolated sandbox) ──
	// The sandbox dev server binds :3000 INSIDE the container; docker publishes it
	// to an auto-assigned 127.0.0.1 host port. The iframe loads that port directly,
	// so the app runs at the ROOT of its own localhost origin — no proxy, no base
	// path — and the distinct origin keeps it isolated from Harvis.
	$: preview = repo?.preview ?? null;
	$: runnable = !!repo?.stack?.run_plan?.web;
	// ── Runtime requirements (service graph from fab_repo.detect_stack) ──
	// `requirements` is the honest capability check: what the repo NEEDS (services,
	// processes, env) vs what the single-container sandbox can run RIGHT NOW.
	$: reqs = repo?.stack?.requirements ?? null;
	$: multiService = !!reqs?.multi_service;
	// A repo only actually runs here when it's a web app AND the sandbox can host it
	// (single-process). Older manifests without `requirements` behave as before.
	$: runnableNow = runnable && (reqs ? reqs.runnable_now !== false : true);
	$: inProgress = !!preview && ['cloning', 'installing', 'starting'].includes(preview.status);
	$: running = preview?.status === 'running';
	// Reload nonce: the FIRST iframe paint can be blank because dev servers often
	// pre-bundle the app's heavy deps on first load — the readiness probe passes on
	// the index while module requests are still optimizing. Auto-reload once when
	// the server goes live (by then it's warm), and expose a manual Reload. The
	// nonce is a harmless query the dev server ignores.
	let previewNonce = 0;
	let autoReloaded = false;
	// The sandbox dev port is published on the docker HOST's 127.0.0.1 only, and the
	// dev server speaks plain HTTP. So the browser can embed it ONLY when Harvis is
	// being viewed on that same host over http (the laptop/dev case). From a remote
	// or k8s origin — or over https (mixed content) — the port isn't reachable, so we
	// show an honest "open it on the host" note instead of a Live iframe that hangs.
	$: previewHostUrl = preview?.host_port ? `http://127.0.0.1:${preview.host_port}/` : '';
	$: previewViewable =
		running &&
		!!preview?.host_port &&
		typeof window !== 'undefined' &&
		window.location.protocol === 'http:' &&
		['localhost', '127.0.0.1', '0.0.0.0'].includes(window.location.hostname);
	$: previewSrc = previewViewable
		? `http://${window.location.hostname}:${preview.host_port}/?__hp=${previewNonce}`
		: '';
	$: framework = repo?.stack?.run_plan?.framework;
	$: if (running && !autoReloaded) { autoReloaded = true; setTimeout(() => (previewNonce += 1), 6000); }
	$: if (!running && autoReloaded) autoReloaded = false; // re-arm for the next run
	const reloadPreview = () => (previewNonce += 1);
	let runBusy = false;
	let runErr = '';

	const _statusLabel: Record<string, string> = {
		cloning: 'Cloning into the sandbox…',
		installing: 'Installing dependencies…',
		starting: 'Starting the dev server…',
		running: 'Running',
		failed: 'Could not start',
		stopped: 'Stopped'
	};

	// Goal-status ladder — the main status surface for the run flow.
	const _steps = [
		{ key: 'cloned', label: 'Cloned' },
		{ key: 'installing', label: 'Installing' },
		{ key: 'starting', label: 'Starting' },
		{ key: 'ready', label: 'Preview ready' }
	];
	$: stepIdx =
		preview?.status === 'installing' ? 1 : preview?.status === 'starting' ? 2 : running ? 3 : 0;
	$: isBlocked = preview?.status === 'failed';
	$: isStopped = preview?.status === 'stopped';

	const refresh = async () => {
		try {
			const r = await fetch(`/api/adaptive/spaces/${space.id}`, { headers: hdrs(), credentials: 'include' });
			if (r.ok) dispatch('updated', (await r.json()).manifest);
		} catch {
			/* transient */
		}
	};

	// `source` records WHY the run happened — an explicit button 'click', or the
	// task text asking for it ('intent'). The backend audits it, so `approved: true`
	// never asserts a consent event that didn't happen.
	const runApp = async (source: string = 'click') => {
		if (!space?.id || runBusy) return;
		runBusy = true;
		runErr = '';
		try {
			const r = await fetch(`/api/adaptive/spaces/${space.id}/repo/run`, {
				method: 'POST', headers: hdrs(), credentials: 'include', body: JSON.stringify({ approved: true, consent: source })
			});
			if (r.ok) await refresh();
			else runErr = (await r.json().catch(() => null))?.detail || 'Could not start the app.';
		} catch {
			runErr = 'Could not start the app.';
		}
		runBusy = false;
	};

	const stopApp = async () => {
		if (!space?.id) return;
		try {
			await fetch(`/api/adaptive/spaces/${space.id}/repo/stop`, { method: 'POST', headers: hdrs(), credentials: 'include' });
		} catch {
			/* best effort */
		}
		await refresh();
	};

	// Poll the space while a run is in flight so the status/log update live.
	let pollTimer: any = null;
	$: if (typeof window !== 'undefined') {
		if (inProgress && !pollTimer) pollTimer = setInterval(refresh, 2500);
		else if (!inProgress && pollTimer) {
			clearInterval(pollTimer);
			pollTimer = null;
		}
	}
	onDestroy(() => {
		if (pollTimer) clearInterval(pollTimer);
	});

	// Pre-fill a URL if the task text already contains one.
	const urlInIntent = (space?.intent || '').match(/https?:\/\/[^\s)]+/);
	let url = repo?.url ?? (urlInIntent ? urlInIntent[0] : '');
	let cloning = false;
	let err = '';

	const clone = async () => {
		if (!space?.id || cloning || !url.trim()) return;
		cloning = true;
		err = '';
		try {
			const r = await fetch(`/api/adaptive/spaces/${space.id}/repo/inspect`, {
				method: 'POST', headers: hdrs(), credentials: 'include', body: JSON.stringify({ url: url.trim() })
			});
			if (r.ok) dispatch('updated', (await r.json()).manifest);
			else { err = (await r.json().catch(() => null))?.detail || 'Clone failed'; }
		} catch {
			err = 'Clone failed';
		}
		cloning = false;
	};

	$: stack = repo?.stack ?? {};
	$: setupCmds = [
		{ key: 'install', label: 'Install', cmd: stack.install },
		{ key: 'build', label: 'Build', cmd: stack.build },
		{ key: 'start', label: 'Start', cmd: stack.start }
	].filter((c) => c.cmd);

	// ── AI auto-drive ────────────────────────────────────────────────────────
	// When the task says run/test it (not just "clone"), Harvis drives the whole
	// flow — clone → start the sandbox → live preview — with no clicks. The
	// natural-language request IS the run consent; "clone" alone stays inspect-only.
	// Auto-run only on an UNAMBIGUOUS request to run/test the app: a run verb with an
	// object ("run it", "test the app", "spin it up"), or an explicit run phrase.
	// Bare words — "test setup", "getting started", "check the code" — must NOT kick
	// off untrusted code execution; those stay inspect-only.
	const _AUTO_RE =
		/\b(?:run|launch|boot|start|preview|test|try)\s+(?:it|this|them|out\b|the\s+(?:app|repo|project|server|site|demo))\b/i;
	const _AUTO_RE2 =
		/\b(?:spin(?:\s+(?:it|them|this))?\s?up|fire(?:\s+(?:it|them|this))?\s?up|does it (?:work|run)|is it (?:working|running)|get it (?:working|running|up)|see it (?:run|running|work|working|live))\b/i;
	// Negation guard: an explicit "don't run / just inspect / only clone" must keep
	// untrusted code from auto-executing even if a run verb also appears. Errs toward
	// NOT running (the user can always click Approve & run).
	const _NO_AUTO_RE =
		/\b(?:don'?t|do not|no need to|without|not yet|rather not)\b[^.!?]*\b(?:run|start|launch|boot|execute)\b|\bjust\s+(?:inspect|clone|look|read|show|explain)\b|\bonly\s+(?:inspect|clone|read|look)\b/i;
	$: autoMode =
		!_NO_AUTO_RE.test(space?.intent || '') &&
		(_AUTO_RE.test(space?.intent || '') || _AUTO_RE2.test(space?.intent || ''));
	let autoCloneKicked = false;
	let autoRunKicked = false;

	// One honest line about the app, pulled from the real README (never invented) —
	// the first prose sentence, skipping headings, quotes, list items, badges and
	// bare links so we get a real description rather than a "- Preview: <url>" line.
	$: appBlurb = (() => {
		const rd = repo?.readme || '';
		const line = rd
			.split('\n')
			.map((l) => l.trim())
			.find(
				(l) => l && !/^[#!>[\-*|=]/.test(l) && !/^\S*:?\s*<?https?:\/\//.test(l) && /\s/.test(l) && l.length > 20
			);
		return line ? line.replace(/[*_`]/g, '').slice(0, 150) : '';
	})();

	// Harvis's running commentary — derived entirely from real state, never faked.
	$: narration = (() => {
		if (!autoMode) return '';
		if (!repo) return 'Cloning the repo into an isolated sandbox…';
		const what = repo.name || 'the repo';
		const kind = stack.stack ? `${stack.stack}${framework ? ` (${framework})` : ''}` : '';
		if (multiService && reqs) {
			// Honest multi-service narration — the requirement graph, not "it's a CLI".
			const svcs = (reqs.services ?? []).map((s: any) => s.name).join(', ');
			const procs = (reqs.processes ?? []).map((p: any) => p.name).join(', ');
			const env = (reqs.env_required ?? []).join(', ');
			const needs = [
				svcs && `services (${svcs})`,
				procs && `processes (${procs})`,
				env && `config (${env})`
			]
				.filter(Boolean)
				.join(' + ');
			return `Detected a multi-service ${reqs.runtime || ''} web app${what ? ` — ${what}` : ''} — it needs ${needs || 'multiple coordinated services'}. I can inspect it now and run simpler single-process apps; fully opening this needs trusted service provisioning (next milestone). The requirement breakdown is below.`;
		}
		if (runnable && !runnableNow)
			return `Cloned ${what}${kind ? ` — a ${kind} web app` : ''}, but the sandbox can't run it yet: ${reqs?.blocked_reason || 'it needs more than a single process'}. The requirement breakdown is below.`;
		if (!runnable)
			return `Cloned ${what}${kind ? ` — a ${kind} project` : ''}. It has no dev server (a CLI or library), so there's nothing to preview — the setup commands below show how to use it.`;
		if (runErr) return `I tried to start ${what} but couldn't: ${runErr}`;
		const st = preview?.status;
		if (st === 'running')
			return `${what} is live below${appBlurb ? ` — ${appBlurb}` : ''}. It started cleanly and is responding.`;
		if (st === 'failed')
			return `I couldn't get ${what} running: ${preview?.error || 'the dev server didn’t come up'}. The real log is below.`;
		if (st === 'installing') return `Cloned ${what}${kind ? ` — a ${kind} app` : ''}. Installing dependencies…`;
		if (st === 'starting') return 'Almost there — starting the dev server…';
		if (st === 'cloning') return `You asked me to run ${what}, so I'm setting it up in an isolated sandbox…`;
		return `Cloned ${what}${kind ? ` — a ${kind} app` : ''}. Starting it up…`;
	})();

	$: narrationBusy = autoMode && (cloning || inProgress || (!repo && !runErr));

	// The drive loop — clone, then (if runnable) run. Each step fires once; the
	// guard flags are set synchronously so the reactive block can't double-launch.
	$: if (autoMode && space?.id) {
		if (!repo && !cloning && !autoCloneKicked) {
			autoCloneKicked = true;
			clone();
		} else if (repo && runnableNow && !preview && !autoRunKicked && !runBusy) {
			autoRunKicked = true;
			runApp('intent'); // consent source: the task text asked to run it
		}
	}
</script>

{#if autoMode && narration}
	<!-- AI DRIVE: Harvis's running commentary — derived from real state, never faked -->
	<div class="hud-panel min-w-0" in:fade={{ duration: 200 }}>
		<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
		<div class="flex items-start gap-2.5">
			<div class="shrink-0 mt-0.5 size-6 rounded-full bg-cyan-500/15 border border-cyan-400/30 flex items-center justify-center">
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-3.5 text-cyan-300"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6.3 6.3l2.4 2.4M15.3 15.3l2.4 2.4M17.7 6.3l-2.4 2.4M8.7 15.3l-2.4 2.4" stroke-linecap="round" /></svg>
			</div>
			<div class="min-w-0 flex-1">
				<div class="text-[9px] uppercase tracking-widest text-cyan-300/70">{$i18n.t('Harvis')}</div>
				<p class="text-[12px] text-gray-200 leading-relaxed">{narration}{#if narrationBusy}<span class="inline-block ml-1 size-1.5 rounded-full bg-cyan-400 animate-pulse align-middle"></span>{/if}</p>
			</div>
		</div>
	</div>
{/if}

{#if !repo}
	{#if autoMode}
		<!-- AUTO-DRIVE: Harvis clones + starts it; no manual intake -->
		<div class="hud-panel" in:fly={{ y: 14, duration: 300 }}>
			<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
			<div class="flex items-center gap-2 text-[12px] text-cyan-100">
				<svg class="size-4 animate-spin shrink-0" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" /><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8V0C5.4 0 0 5.4 0 12h4z" /></svg>
				{$i18n.t('Cloning the repo into an isolated sandbox…')}
			</div>
			<div class="mt-2 text-[9px] uppercase tracking-widest text-gray-600">{$i18n.t('Public github / gitlab / bitbucket https only · isolated sandbox · read-only clone')}</div>
			{#if err}<div class="mt-2 text-[11px] text-red-400">{err}</div>{/if}
		</div>
	{:else}
	<!-- INTAKE: get the repo -->
	<div class="hud-panel" in:fly={{ y: 14, duration: 300 }}>
		<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
		<div class="flex items-center gap-2">
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-4 text-cyan-300/80"><path d="M4 4h16v12H4zM4 20h16M8 16v4M16 16v4" stroke-linecap="round" stroke-linejoin="round" /></svg>
			<h3 class="text-sm font-semibold text-gray-100">{$i18n.t('Fetch a repository')}</h3>
		</div>
		<p class="mt-1 text-[11px] text-gray-500">{$i18n.t('Harvis clones a public repo into an isolated per-space checkout, reads its setup, and detects the stack. Nothing from the repo runs until you approve it.')}</p>
		<div class="mt-3 flex items-center gap-2">
			<input
				type="url"
				placeholder="https://github.com/owner/repo"
				bind:value={url}
				on:keydown={(e) => { if (e.key === 'Enter') clone(); }}
				class="flex-1 text-xs bg-black/25 border border-white/10 rounded-lg px-2.5 py-2 outline-none focus:border-cyan-400/40 text-gray-100 placeholder:text-gray-500"
			/>
			<button
				class="shrink-0 text-xs px-3 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white transition disabled:opacity-50 inline-flex items-center gap-1.5"
				disabled={cloning || !url.trim()}
				on:click={clone}
			>
				{#if cloning}<svg class="size-3.5 animate-spin" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" /><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8V0C5.4 0 0 5.4 0 12h4z" /></svg>{$i18n.t('Cloning…')}{:else}{$i18n.t('Clone')}{/if}
			</button>
		</div>
		{#if err}<div class="mt-2 text-[11px] text-red-400">{err}</div>{/if}
		<div class="mt-2 text-[9px] uppercase tracking-widest text-gray-600">{$i18n.t('Public github / gitlab / bitbucket https only · shallow clone · read-only')}</div>
	</div>
	{/if}
{:else}
	<!-- WORKBENCH: goal ladder · live preview (hero) · file tree · terminal · setup tracker -->
	<div class="space-y-3" in:fade={{ duration: 220 }}>
	{#if reqs && (multiService || !runnableNow)}
		<!-- RUNTIME REQUIREMENTS — the honest service graph: what the repo needs vs
		     what the single-container sandbox can host right now. This replaces the
		     old "it's a CLI/library" cop-out for multi-service apps. -->
		<article class="hud-panel min-w-0" in:fly={{ y: 8, duration: 250 }}>
			<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
			<div class="flex items-center justify-between gap-2">
				<div class="flex items-center gap-2 min-w-0">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-4 text-cyan-300/80 shrink-0"><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><path d="M14 17.5h7M17.5 14v7" stroke-linecap="round" /></svg>
					<h3 class="text-sm font-semibold text-gray-100">{$i18n.t('Runtime requirements')}</h3>
				</div>
				<span class="shrink-0 text-[8px] uppercase tracking-widest {multiService ? 'text-amber-300/70' : 'text-cyan-300/60'}">{$i18n.t(multiService ? 'Multi-service app' : 'Detected from the repo')}</span>
			</div>

			<div class="mt-2.5 space-y-2">
				<div class="flex items-center gap-2 text-[11px]">
					<span class="shrink-0 w-20 text-[9px] uppercase tracking-widest text-gray-500">{$i18n.t('Runtime')}</span>
					<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md border border-cyan-400/25 text-cyan-100 bg-cyan-400/5 text-[10px] font-mono">{reqs.runtime || 'unknown'}</span>
					{#if reqs.package_manager}<span class="inline-flex items-center px-2 py-0.5 rounded-md border border-white/10 text-gray-400 text-[10px] font-mono">{reqs.package_manager}</span>{/if}
				</div>
				{#if (reqs.frameworks ?? []).length}
					<div class="flex items-start gap-2 text-[11px]">
						<span class="shrink-0 w-20 mt-0.5 text-[9px] uppercase tracking-widest text-gray-500">{$i18n.t('Frameworks')}</span>
						<div class="flex flex-wrap gap-1">
							{#each reqs.frameworks as f (f)}
								<span class="inline-flex items-center px-2 py-0.5 rounded-md border border-cyan-400/20 text-cyan-200/90 text-[10px] font-mono">{f}</span>
							{/each}
						</div>
					</div>
				{/if}
				{#if (reqs.services ?? []).length}
					<div class="flex items-start gap-2 text-[11px]">
						<span class="shrink-0 w-20 mt-0.5 text-[9px] uppercase tracking-widest text-gray-500">{$i18n.t('Services')}</span>
						<div class="flex flex-wrap gap-1">
							{#each reqs.services as s (s.name)}
								<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md border border-amber-400/30 text-amber-100 bg-amber-400/5 text-[10px] font-mono" title={s.why || ''}>
									<span class="size-1.5 rounded-full bg-amber-400/80"></span>{s.name}
								</span>
							{/each}
						</div>
					</div>
				{/if}
				{#if (reqs.processes ?? []).length}
					<div class="flex items-start gap-2 text-[11px]">
						<span class="shrink-0 w-20 mt-0.5 text-[9px] uppercase tracking-widest text-gray-500">{$i18n.t('Processes')}</span>
						<div class="flex flex-wrap gap-1">
							{#each reqs.processes as p (p.name)}
								<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md border border-white/12 text-gray-300 text-[10px] font-mono" title={p.cmd || ''}>
									{p.name}{#if p.role}<span class="text-gray-500">· {p.role}</span>{/if}
								</span>
							{/each}
						</div>
					</div>
				{/if}
				{#if (reqs.env_required ?? []).length}
					<div class="flex items-start gap-2 text-[11px]">
						<span class="shrink-0 w-20 mt-0.5 text-[9px] uppercase tracking-widest text-gray-500">{$i18n.t('Config')}</span>
						<div class="flex flex-wrap gap-1">
							{#each reqs.env_required as v (v)}
								<span class="inline-flex items-center px-2 py-0.5 rounded-md border border-white/12 text-gray-300 text-[10px] font-mono">{v}</span>
							{/each}
						</div>
					</div>
				{/if}
			</div>

			<!-- Honest capability split: sandbox-now vs provisioning-later -->
			<div class="mt-3 grid sm:grid-cols-2 gap-2">
				<div class="rounded-md bg-emerald-400/5 border border-emerald-400/15 p-2">
					<div class="text-[8px] uppercase tracking-widest text-emerald-300/80">{$i18n.t('What Harvis can run now')}</div>
					<p class="mt-1 text-[10.5px] leading-relaxed text-emerald-100/80">
						{#if reqs.runnable_now}
							{$i18n.t('This app — it fits the single-process sandbox (install, dev server, live preview).')}
						{:else}
							{$i18n.t('Inspect this repo (tree, setup, README) and run simpler single-process Node or Python web apps.')}
						{/if}
					</p>
				</div>
				<div class="rounded-md bg-amber-400/5 border border-amber-400/25 p-2">
					<!-- Header is honest per case: multi-service apps DO get unlocked by future
					     provisioning; a CLI/library never becomes previewable, so don't imply it will. -->
					<div class="text-[8px] uppercase tracking-widest text-amber-300/80">{$i18n.t(multiService ? 'Needs provisioning (coming)' : 'Why there’s no preview')}</div>
					<p class="mt-1 text-[10.5px] leading-relaxed text-amber-100/80">
						{#if reqs.runnable_now}
							{$i18n.t('Nothing — no extra services required.')}
						{:else if multiService}
							{reqs.provision_note || reqs.blocked_reason || $i18n.t('Running the full multi-service stack needs trusted service provisioning — the next milestone.')}
						{:else}
							{reqs.blocked_reason || $i18n.t('This repo exposes no single-process web server, so there is nothing to preview.')}
						{/if}
					</p>
				</div>
			</div>
		</article>
	{/if}
	{#if runnableNow || preview}
		<!-- Render whenever the app is runnable OR a sandbox preview exists — so a
		     still-serving container (and its Stop control) can never be hidden by a
		     later re-classification of the repo. -->
		<!-- GOAL-STATUS LADDER — the main status surface for the run flow -->
		<div class="hud-panel min-w-0 !py-2" in:fade={{ duration: 200 }}>
			<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
			<div class="flex items-center gap-1.5 flex-wrap">
				{#each _steps as s, i (s.key)}
					{#if i > 0}<span class="w-4 h-px shrink-0 {i <= stepIdx && !isBlocked && !isStopped ? 'bg-cyan-400/40' : 'bg-white/10'}"></span>{/if}
					<span
						class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[10px] {i === stepIdx && !isBlocked && !isStopped
							? i === 3
								? 'border-emerald-400/50 text-emerald-100 bg-emerald-400/10'
								: 'border-cyan-400/50 text-cyan-100 bg-cyan-400/10'
							: i < stepIdx && !isBlocked && !isStopped
								? 'border-emerald-400/25 text-emerald-200/80'
								: 'border-white/10 text-gray-500'}"
					>
						{#if i < stepIdx && !isBlocked && !isStopped}<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" class="size-2.5"><path d="M5 13l4 4L19 7" stroke-linecap="round" stroke-linejoin="round" /></svg>{/if}
						{$i18n.t(s.label)}
					</span>
				{/each}
				{#if isBlocked}
					<span class="ml-1 inline-flex items-center gap-1 px-2 py-0.5 rounded-md border border-red-400/40 text-red-200 bg-red-400/10 text-[10px]">
						<span class="size-1.5 rounded-full bg-red-400"></span>{$i18n.t('Blocked')}
					</span>
				{:else if isStopped}
					<span class="ml-1 inline-flex items-center gap-1 px-2 py-0.5 rounded-md border border-white/15 text-gray-300 bg-white/5 text-[10px]">
						<span class="size-1.5 rounded-full bg-gray-400"></span>{$i18n.t('Stopped')}
					</span>
				{/if}
			</div>
		</div>

		{#if runnableNow && (reqs?.env_required ?? []).length}
			<!-- Known-required config the sandbox starts WITHOUT — so a start failure is
			     pre-explained rather than a surprise. Detection already knows these. -->
			<div class="hud-panel min-w-0 !py-2" in:fade={{ duration: 200 }}>
				<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
				<div class="flex items-start gap-2 text-[11px]">
					<span class="shrink-0 mt-0.5 text-[9px] uppercase tracking-widest text-amber-300/70">{$i18n.t('May need config')}</span>
					<div class="min-w-0">
						<div class="flex flex-wrap gap-1">
							{#each reqs.env_required as v (v)}
								<span class="inline-flex items-center px-2 py-0.5 rounded-md border border-white/12 text-gray-300 text-[10px] font-mono">{v}</span>
							{/each}
						</div>
						<p class="mt-1 text-[10px] text-gray-500 leading-relaxed">{$i18n.t('This app may expect these variables. The sandbox starts without them, so if the run fails it is likely config-related.')}</p>
					</div>
				</div>
			</div>
		{/if}

		<!-- LIVE APP PREVIEW (gated: runs untrusted repo code in an isolated sandbox) -->
		<article class="hud-panel min-w-0" in:fly={{ y: 8, duration: 250 }}>
			<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
			<div class="flex items-center justify-between gap-2">
				<div class="flex items-center gap-2 min-w-0">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-4 text-cyan-300/80 shrink-0"><rect x="3" y="4" width="18" height="14" rx="2" /><path d="M3 8h18M8 21h8" stroke-linecap="round" /></svg>
					<h3 class="text-sm font-semibold text-gray-100">{$i18n.t('App preview')}</h3>
					{#if preview?.framework}<span class="shrink-0 text-[9px] uppercase tracking-widest text-cyan-300/50">{preview.framework}</span>{/if}
				</div>
				<div class="flex items-center gap-2 shrink-0">
					{#if running}
						<span class="text-[9px] uppercase tracking-widest text-emerald-300/80 inline-flex items-center gap-1"><span class="size-1.5 rounded-full bg-emerald-400 animate-pulse"></span>{$i18n.t('Live')}</span>
						<button class="text-[10px] px-2 py-0.5 rounded-lg border border-cyan-400/25 text-cyan-200 hover:bg-cyan-400/10 transition" on:click={reloadPreview} title={$i18n.t('Reload the preview (useful right after it starts)')}>{$i18n.t('Reload')}</button>
						{#if previewSrc}<a href={previewSrc} target="_blank" rel="noopener" class="text-[10px] px-2 py-0.5 rounded-lg border border-cyan-400/25 text-cyan-200 hover:bg-cyan-400/10 transition">{$i18n.t('Open')}</a>{/if}
						<button class="text-[10px] px-2 py-0.5 rounded-lg border border-red-400/30 text-red-200 hover:bg-red-400/10 transition" on:click={stopApp}>{$i18n.t('Stop')}</button>
					{:else}
						<span class="text-[8px] uppercase tracking-widest text-amber-300/70">{$i18n.t('Runs untrusted code · approval-gated')}</span>
					{/if}
				</div>
			</div>

			{#if running && previewViewable}
				<div class="log-pane mt-2 rounded-lg overflow-hidden border border-cyan-400/15 bg-black/40">
					<iframe
						title="App preview"
						src={previewSrc}
						class="w-full h-[520px] bg-white block"
						sandbox="allow-scripts allow-forms allow-same-origin allow-popups allow-modals"
						referrerpolicy="no-referrer"
					></iframe>
				</div>
				<div class="mt-1.5 text-[9px] text-gray-600">{$i18n.t('Isolated sandbox · own local port · separate origin · live dev server')}</div>
			{:else if running}
				<!-- Live in the sandbox, but the published port is on the server host's
				     loopback over http — not embeddable from a remote/https origin. Say so
				     honestly and give the URL to open on the host, instead of a dead iframe. -->
				<div class="mt-3 rounded-lg border border-cyan-400/20 bg-cyan-400/5 p-3">
					<div class="flex items-center gap-2 text-[12px] text-cyan-100">
						<span class="size-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
						{$i18n.t('The app is live in the sandbox — but its preview port is published on the server host only.')}
					</div>
					<p class="mt-1.5 text-[10.5px] leading-relaxed text-gray-400">
						{#if previewHostUrl}
							{$i18n.t('It embeds here only when you view Harvis on that host over http. From here, open it directly on the server:')}
							<code class="font-mono text-cyan-200 bg-black/30 rounded px-1.5 py-0.5">{previewHostUrl}</code>
						{:else}
							{$i18n.t('It embeds here only when you view Harvis on the sandbox host over http.')}
						{/if}
					</p>
				</div>
			{:else if inProgress}
				<div class="mt-3 flex items-center gap-2 text-[12px] text-cyan-100">
					<svg class="size-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" /><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8V0C5.4 0 0 5.4 0 12h4z" /></svg>
					{$i18n.t(_statusLabel[preview.status] ?? 'Working…')}
				</div>
				{#if preview?.log_tail}<pre class="log-pane mt-2 max-h-44 overflow-auto text-[10px] font-mono text-gray-400 bg-black/40 rounded-lg p-2.5 whitespace-pre-wrap">{preview.log_tail}</pre>{/if}
				<div class="mt-1.5 flex items-center justify-between gap-2">
					<div class="text-[9px] text-gray-600">{$i18n.t('Running in an isolated sandbox — no access to your database, models, or other users’ data. First install can take a minute.')}</div>
					<button class="shrink-0 text-[10px] px-2 py-0.5 rounded-lg border border-red-400/30 text-red-200 hover:bg-red-400/10 transition" on:click={stopApp}>{$i18n.t('Cancel')}</button>
				</div>
			{:else}
				{#if preview?.status === 'failed'}
					<div class="mt-2 text-[11px] text-red-300">{preview.error || $i18n.t('The app did not start.')}</div>
					{#if preview?.log_tail}<pre class="log-pane mt-2 max-h-40 overflow-auto text-[10px] font-mono text-gray-400 bg-black/40 rounded-lg p-2.5 whitespace-pre-wrap">{preview.log_tail}</pre>{/if}
				{/if}
				{#if runErr}<div class="mt-2 text-[11px] text-amber-300">{runErr}</div>{/if}
				{#if autoMode}
					<!-- Auto mode: the natural-language request IS the consent — no card, it just runs. -->
					{#if preview?.status === 'failed' || preview?.status === 'stopped'}
						<button class="mt-2.5 inline-flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white transition disabled:opacity-50" on:click={() => runApp('click')} disabled={runBusy}>
							<svg viewBox="0 0 24 24" fill="currentColor" class="size-3.5"><path d="M8 5v14l11-7z" /></svg>
							{$i18n.t('Run again')}
						</button>
					{/if}
				{:else}
					<!-- ONE approval for the whole flow: install → start → probe run autonomously after it. -->
					<div class="mt-2 rounded-lg border border-amber-400/25 bg-amber-400/5 p-3" in:fade={{ duration: 150 }}>
						<div class="flex items-center gap-2">
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-4 text-amber-300 shrink-0"><path d="M12 3l8 4v5c0 4.6-3.2 8.1-8 9-4.8-.9-8-4.4-8-9V7z" stroke-linecap="round" stroke-linejoin="round" /></svg>
							<h4 class="text-[12px] font-semibold text-amber-100">{$i18n.t('Approve sandbox run')}</h4>
						</div>
						<p class="mt-1 text-[10.5px] text-amber-100/70 leading-relaxed">{$i18n.t('One approval covers the whole flow — install, dev server, live preview. Harvis keeps going on its own; the commands it will run are listed under Setup.')}</p>
						<div class="mt-2 grid sm:grid-cols-2 gap-2">
							<div class="rounded-md bg-emerald-400/5 border border-emerald-400/15 p-2">
								<div class="text-[8px] uppercase tracking-widest text-emerald-300/80">{$i18n.t('Allowed')}</div>
								<ul class="mt-1 space-y-0.5 text-[10.5px] leading-relaxed text-emerald-100/80">
									<li>{$i18n.t('Install dependencies in the isolated sandbox')}</li>
									<li>{$i18n.t('Run package scripts')}</li>
									<li>{$i18n.t('Start the dev server')}</li>
									<li>{$i18n.t('Read logs')}</li>
									<li>{$i18n.t('Stop / clean up')}</li>
								</ul>
							</div>
							<div class="rounded-md bg-red-400/5 border border-red-400/15 p-2">
								<div class="text-[8px] uppercase tracking-widest text-red-300/80">{$i18n.t('Denied')}</div>
								<ul class="mt-1 space-y-0.5 text-[10.5px] leading-relaxed text-red-100/70">
									<li>{$i18n.t('Host filesystem')}</li>
									<li>{$i18n.t('Secrets')}</li>
									<li>{$i18n.t('Commits / pushes')}</li>
									<li>{$i18n.t('Account login')}</li>
									<li>{$i18n.t('Local devices')}</li>
									<li>{$i18n.t('Paid / cloud services')}</li>
								</ul>
							</div>
						</div>
						<button class="mt-2.5 inline-flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white transition disabled:opacity-50" on:click={() => runApp('click')} disabled={runBusy}>
							<svg viewBox="0 0 24 24" fill="currentColor" class="size-3.5"><path d="M8 5v14l11-7z" /></svg>
							{runBusy ? $i18n.t('Starting…') : $i18n.t('Approve & run')}
						</button>
					</div>
				{/if}
			{/if}
		</article>
	{/if}
	<div class="grid lg:grid-cols-[220px_minmax(0,1fr)] gap-3">
		<!-- FILE TREE -->
		<article class="hud-panel min-w-0">
			<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
			<div class="flex items-center justify-between gap-2">
				<h3 class="text-xs font-semibold text-gray-100 truncate">{repo.name}</h3>
				<span class="shrink-0 text-[8px] uppercase tracking-widest text-emerald-300/70">{stack.stack ?? 'repo'}</span>
			</div>
			<div class="mt-2 max-h-72 overflow-y-auto text-[11px] font-mono">
				{#each repo.tree ?? [] as e (e.path)}
					<div class="flex items-center gap-1.5 py-0.5 text-gray-400" style="padding-left:{(e.path.split('/').length - 1) * 10}px">
						{#if e.dir}
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" class="size-3 text-cyan-300/60 shrink-0"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" /></svg>
						{:else}
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="size-3 text-gray-600 shrink-0"><path d="M6 2h9l5 5v15H6zM15 2v5h5" /></svg>
						{/if}
						<span class="truncate {e.dir ? 'text-gray-300' : ''}">{e.path.split('/').pop()}</span>
					</div>
				{/each}
			</div>
		</article>

		<div class="space-y-3 min-w-0">
			<!-- TERMINAL (real clone output) -->
			<article class="hud-panel min-w-0">
				<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
				<div class="flex items-center justify-between gap-2">
					<h3 class="text-xs font-semibold text-gray-100">{$i18n.t('Terminal')}</h3>
					<span class="text-[8px] uppercase tracking-widest text-cyan-300/60">{$i18n.t('Clone log · real output')}</span>
				</div>
				<pre class="log-pane mt-2 max-h-56 overflow-auto text-[10.5px] leading-relaxed font-mono text-gray-300 bg-black/40 rounded-lg p-2.5 whitespace-pre-wrap">{repo.log}</pre>
			</article>

			<!-- SETUP TRACKER -->
			<article class="hud-panel min-w-0">
				<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
				<div class="flex items-center justify-between gap-2">
					<h3 class="text-xs font-semibold text-gray-100">{$i18n.t('Setup')}</h3>
					<span class="text-[8px] uppercase tracking-widest text-cyan-300/60">{$i18n.t(runnableNow ? 'What Harvis will run' : 'Detected commands')}</span>
				</div>
				{#if setupCmds.length}
					<div class="mt-2 space-y-1.5">
						{#each setupCmds as c (c.key)}
							<div class="flex items-center gap-2 text-[11px]">
								<span class="shrink-0 w-14 text-[9px] uppercase tracking-widest text-gray-500">{c.label}</span>
								<code class="flex-1 min-w-0 truncate font-mono text-cyan-100 bg-black/30 rounded px-1.5 py-0.5">{c.cmd}</code>
							</div>
						{/each}
					</div>
					{#if !runnable}
						<p class="mt-2 text-[10px] text-gray-600 leading-relaxed">{$i18n.t('This repo has no dev server (a CLI or library), so there is nothing to preview — use these commands to run it locally.')}</p>
					{/if}
				{:else}
					<p class="mt-2 text-[11px] text-gray-500">{$i18n.t('No standard setup commands detected — check the README.')}</p>
				{/if}
			</article>

			<!-- README -->
			{#if repo.readme}
				<article class="hud-panel min-w-0">
					<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
					<div class="flex items-center justify-between gap-2">
						<h3 class="text-xs font-semibold text-gray-100">{$i18n.t('README')}</h3>
						<span class="text-[8px] uppercase tracking-widest text-cyan-300/60">{$i18n.t('from the repo')}</span>
					</div>
					<pre class="mt-2 max-h-64 overflow-auto text-[11px] leading-relaxed text-gray-400 whitespace-pre-wrap">{repo.readme}</pre>
				</article>
			{/if}

			<div class="flex items-center gap-2">
				<button class="text-[10px] px-2.5 py-1 rounded-lg border border-cyan-400/25 text-cyan-200 hover:bg-cyan-400/10 transition disabled:opacity-50" disabled={cloning} on:click={clone}>{cloning ? $i18n.t('Re-cloning…') : $i18n.t('Re-clone / pull')}</button>
				<span class="text-[9px] text-gray-600 truncate">{repo.url}</span>
			</div>
		</div>
	</div>
	</div>
{/if}

<style>
	.hud-panel {
		position: relative;
		padding: 0.85rem 1rem;
		background: linear-gradient(180deg, rgba(13, 21, 36, 0.92), rgba(8, 13, 24, 0.92));
		border: 1px solid rgba(56, 189, 248, 0.16);
	}
	.corner {
		position: absolute;
		width: 10px;
		height: 10px;
		border: 0 solid rgba(125, 211, 252, 0.55);
		pointer-events: none;
	}
	.corner.tl { top: -1px; left: -1px; border-top-width: 1.5px; border-left-width: 1.5px; }
	.corner.tr { top: -1px; right: -1px; border-top-width: 1.5px; border-right-width: 1.5px; }
	.corner.bl { bottom: -1px; left: -1px; border-bottom-width: 1.5px; border-left-width: 1.5px; }
	.corner.br { bottom: -1px; right: -1px; border-bottom-width: 1.5px; border-right-width: 1.5px; }
</style>
