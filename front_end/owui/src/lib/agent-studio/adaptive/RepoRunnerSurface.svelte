<script lang="ts">
	// Repo Runner SURFACE — a task-shaped terminal workbench. Clone a public repo
	// into an isolated per-space checkout, read its setup, detect the stack, and
	// surface REAL terminal output (the git clone log). Running install/build/start
	// is a gated sandbox capability (off by default) — the detected commands are
	// shown so the user can run them, and nothing is faked.
	import { getContext, createEventDispatcher } from 'svelte';
	import { fade, fly } from 'svelte/transition';
	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let space: any = null;

	const hdrs = () => ({ Authorization: `Bearer ${localStorage.token}`, 'Content-Type': 'application/json' });

	$: repo = space?.manifest?.repo ?? null;

	// Pre-fill a URL if the task text already contains one.
	const urlInIntent = (space?.intent || '').match(/https?:\/\/[^\s)]+/);
	let url = repo?.url ?? (urlInIntent ? urlInIntent[0] : '');
	let cloning = false;
	let err = '';
	let runNote = '';

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

	// The gated run — honestly reports it isn't wired rather than executing.
	const runCmd = async (cmd: string) => {
		runNote = '';
		try {
			const r = await fetch(`/api/adaptive/spaces/${space.id}/repo/run`, {
				method: 'POST', headers: hdrs(), credentials: 'include', body: JSON.stringify({ cmd })
			});
			if (!r.ok) runNote = (await r.json().catch(() => null))?.detail || 'Sandbox run not enabled.';
		} catch {
			runNote = 'Sandbox run not available.';
		}
	};

	$: stack = repo?.stack ?? {};
	$: setupCmds = [
		{ key: 'install', label: 'Install', cmd: stack.install },
		{ key: 'build', label: 'Build', cmd: stack.build },
		{ key: 'start', label: 'Start', cmd: stack.start }
	].filter((c) => c.cmd);
</script>

{#if !repo}
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
{:else}
	<!-- WORKBENCH: file tree · terminal · setup tracker -->
	<div class="grid lg:grid-cols-[220px_minmax(0,1fr)] gap-3" in:fade={{ duration: 220 }}>
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
				<pre class="mt-2 max-h-56 overflow-auto text-[10.5px] leading-relaxed font-mono text-gray-300 bg-black/40 rounded-lg p-2.5 whitespace-pre-wrap">{repo.log}</pre>
			</article>

			<!-- SETUP TRACKER -->
			<article class="hud-panel min-w-0">
				<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
				<div class="flex items-center justify-between gap-2">
					<h3 class="text-xs font-semibold text-gray-100">{$i18n.t('Setup')}</h3>
					<span class="text-[8px] uppercase tracking-widest text-amber-300/70">{$i18n.t('Run = approval-gated')}</span>
				</div>
				{#if setupCmds.length}
					<div class="mt-2 space-y-1.5">
						{#each setupCmds as c (c.key)}
							<div class="flex items-center gap-2 text-[11px]">
								<span class="shrink-0 w-14 text-[9px] uppercase tracking-widest text-gray-500">{c.label}</span>
								<code class="flex-1 min-w-0 truncate font-mono text-cyan-100 bg-black/30 rounded px-1.5 py-0.5">{c.cmd}</code>
								<button class="shrink-0 text-[10px] px-2 py-0.5 rounded-lg border border-amber-400/30 text-amber-200 hover:bg-amber-400/10 transition" on:click={() => runCmd(c.cmd)}>{$i18n.t('Run')}</button>
							</div>
						{/each}
					</div>
				{:else}
					<p class="mt-2 text-[11px] text-gray-500">{$i18n.t('No standard setup commands detected — check the README.')}</p>
				{/if}
				{#if runNote}<div class="mt-2 text-[10px] text-amber-300/90 leading-relaxed" in:fade={{ duration: 150 }}>{runNote}</div>{/if}
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
