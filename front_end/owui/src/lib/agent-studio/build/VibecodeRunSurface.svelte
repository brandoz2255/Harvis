<script lang="ts">
	// RUN tab — code it in Harvis, run it in Harvis.
	//
	// The session's workspace is bind-mounted into the same capability-stripped sandbox
	// the Repo Runner uses, its dev server is started there, and docker publishes that
	// port on the host's 127.0.0.1. The iframe below points at THAT port, so the app runs
	// at the root of its own origin.
	//
	// The separate origin is the security boundary, not an accident: Harvis accepts its
	// JWT from a cookie, so a same-origin preview would let model-written JavaScript call
	// the API as the signed-in user. The cost is that the frame only embeds when the
	// browser is on the docker host over plain http — this says so instead of showing a
	// frame that silently never loads.
	//
	// Pure props + events. The page owns fetching, exactly like the other panels here.
	import { createEventDispatcher, getContext } from 'svelte';
	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let preview: any = null; // { enabled, reason, plan, preview }
	export let busy = false;
	export let error = '';

	$: enabled = preview?.enabled === true;
	$: plan = preview?.plan ?? null;
	$: state = preview?.preview ?? null;
	$: status = state?.status ?? '';
	$: running = status === 'running';
	$: inProgress = status === 'installing' || status === 'starting';
	$: failed = status === 'failed';
	$: stopped = status === 'stopped';
	// Runnable = the detector found something that serves a page. A bare index.html
	// counts; an empty workspace does not.
	$: runnable = !!plan?.web && !!plan?.dev_cmd;

	// The published port lives on the docker host's loopback and speaks plain http, so
	// it is only embeddable when Harvis itself is being viewed from that host over http.
	$: hostUrl = state?.host_port ? `http://127.0.0.1:${state.host_port}/` : '';
	$: viewable =
		running &&
		!!state?.host_port &&
		typeof window !== 'undefined' &&
		window.location.protocol === 'http:' &&
		['localhost', '127.0.0.1', '0.0.0.0'].includes(window.location.hostname);
	let nonce = 0;
	$: src = viewable
		? `http://${window.location.hostname}:${state.host_port}/?__hp=${nonce}`
		: '';
	// A dev server answers the readiness probe before it has finished its first compile,
	// so the very first paint is often blank. One automatic reload a few seconds in fixes
	// that without the user wondering whether it worked.
	let autoReloaded = false;
	$: if (running && !autoReloaded) {
		autoReloaded = true;
		setTimeout(() => (nonce += 1), 6000);
	}
	$: if (!running && autoReloaded) autoReloaded = false;

	// Ladder. Install is a real step only when there is something to install — a
	// hand-written page has no manifest, and announcing a phase that never runs is a lie.
	$: steps = plan?.install
		? [
				{ key: 'installing', label: $i18n.t('Installing') },
				{ key: 'starting', label: $i18n.t('Starting') },
				{ key: 'ready', label: $i18n.t('Ready') }
			]
		: [
				{ key: 'starting', label: $i18n.t('Starting') },
				{ key: 'ready', label: $i18n.t('Ready') }
			];
	$: stepIdx = running
		? steps.length - 1
		: status === 'starting'
			? steps.length - 2
			: status === 'installing'
				? 0
				: -1;

	const LABEL: Record<string, string> = {
		installing: 'Installing dependencies…',
		starting: 'Starting the dev server…',
		running: 'Running',
		failed: 'Could not start',
		stopped: 'Stopped'
	};
</script>

<div class="h-full min-h-0 flex flex-col">
	<!-- Toolbar -->
	<div
		class="shrink-0 flex items-center gap-2 px-3 py-1.5 border-b border-gray-200 dark:border-white/10 bg-gray-50 dark:bg-gray-900"
	>
		<span class="text-[11px] font-medium text-gray-700 dark:text-gray-200">{$i18n.t('Run')}</span>
		{#if plan?.framework}
			<span
				class="text-[10px] font-mono px-1.5 py-0.5 rounded border border-gray-200 dark:border-white/10 text-gray-500"
				>{plan.framework}</span
			>
		{/if}
		{#if running}
			<span class="inline-flex items-center gap-1 text-[10px] text-emerald-600 dark:text-emerald-400">
				<span class="size-1.5 rounded-full bg-emerald-500 animate-pulse"></span>{$i18n.t('Live')}
			</span>
		{/if}
		<div class="ml-auto flex items-center gap-1.5">
			{#if running}
				<button
					class="text-[10px] px-2 py-1 rounded-lg border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-black/[0.04] dark:hover:bg-white/[0.06] transition"
					title={$i18n.t('Reload the preview (useful right after it starts)')}
					on:click={() => (nonce += 1)}>{$i18n.t('Reload')}</button
				>
				{#if src}
					<a
						href={src}
						target="_blank"
						rel="noopener"
						class="text-[10px] px-2 py-1 rounded-lg border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-black/[0.04] dark:hover:bg-white/[0.06] transition"
						>{$i18n.t('Open')}</a
					>
				{/if}
				<button
					class="text-[10px] px-2 py-1 rounded-lg border border-red-300 dark:border-red-400/30 text-red-600 dark:text-red-300 hover:bg-red-500/10 transition"
					on:click={() => dispatch('stop')}>{$i18n.t('Stop')}</button
				>
			{:else}
				<button
					class="text-[10px] px-2 py-1 rounded-lg border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-black/[0.04] dark:hover:bg-white/[0.06] transition"
					title={$i18n.t('Re-read the workspace and check what can run')}
					on:click={() => dispatch('refresh')}>{$i18n.t('Recheck')}</button
				>
			{/if}
		</div>
	</div>

	<div class="flex-1 min-h-0 overflow-auto">
		{#if !enabled}
			<!-- Off by deployment. Say what it is and what turns it on — never a dead button. -->
			<div class="h-full flex flex-col items-center justify-center text-center px-6 py-10">
				<div class="text-base font-medium text-gray-800 dark:text-gray-100">
					{$i18n.t('Running isn’t enabled here')}
				</div>
				<div class="mt-1.5 max-w-md text-xs text-gray-500 leading-relaxed">
					{preview?.reason ||
						$i18n.t('This deployment has the sandbox preview turned off.')}
				</div>
			</div>
		{:else}
			{#if status && (inProgress || running || failed)}
				<!-- Status ladder -->
				<div class="flex items-center gap-1.5 flex-wrap px-3 py-2 border-b border-gray-200 dark:border-white/10">
					{#each steps as s, i (s.key)}
						{#if i > 0}
							<span
								class="w-4 h-px shrink-0 {i <= stepIdx && !failed
									? 'bg-sky-400/50'
									: 'bg-gray-300 dark:bg-white/10'}"
							></span>
						{/if}
						<span
							class="inline-flex items-center gap-1 px-2 py-0.5 rounded-md border text-[10px] {i ===
								stepIdx && !failed
								? i === steps.length - 1
									? 'border-emerald-400/60 text-emerald-600 dark:text-emerald-200 bg-emerald-400/10'
									: 'border-sky-400/60 text-sky-600 dark:text-sky-200 bg-sky-400/10'
								: i < stepIdx && !failed
									? 'border-emerald-400/30 text-emerald-600/80 dark:text-emerald-200/80'
									: 'border-gray-200 dark:border-white/10 text-gray-500'}"
						>
							{s.label}
						</span>
					{/each}
					{#if failed}
						<span
							class="ml-1 inline-flex items-center gap-1 px-2 py-0.5 rounded-md border border-red-400/50 text-red-600 dark:text-red-200 bg-red-400/10 text-[10px]"
						>
							<span class="size-1.5 rounded-full bg-red-500"></span>{$i18n.t('Failed')}
						</span>
					{/if}
				</div>
			{/if}

			{#if running && viewable}
				<iframe
					title={$i18n.t('App preview')}
					{src}
					class="w-full h-full min-h-[420px] bg-white block border-0"
					sandbox="allow-scripts allow-forms allow-same-origin allow-popups allow-modals"
					referrerpolicy="no-referrer"
				></iframe>
			{:else if running}
				<!-- Live, but not embeddable from this browser. Give the real URL rather than
				     a frame that would just sit blank forever. -->
				<div class="px-6 py-8 max-w-xl mx-auto text-center">
					<div class="inline-flex items-center gap-2 text-sm text-gray-800 dark:text-gray-100">
						<span class="size-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
						{$i18n.t('Your app is running in the sandbox.')}
					</div>
					<p class="mt-2 text-xs text-gray-500 leading-relaxed">
						{#if hostUrl}
							{$i18n.t(
								'Its port is published on the machine running Harvis, so it embeds here only when you view Harvis on that machine over http. From here, open it on that machine:'
							)}
							<code
								class="mt-1.5 inline-block font-mono text-[11px] text-sky-600 dark:text-sky-300 bg-black/5 dark:bg-black/30 rounded px-1.5 py-0.5"
								>{hostUrl}</code
							>
						{:else}
							{$i18n.t('Its preview port is published on the machine running Harvis.')}
						{/if}
					</p>
				</div>
			{:else if inProgress}
				<div class="px-6 py-8">
					<div class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
						<svg class="size-4 animate-spin" viewBox="0 0 24 24" fill="none"
							><circle
								class="opacity-25"
								cx="12"
								cy="12"
								r="10"
								stroke="currentColor"
								stroke-width="3"
							/><path
								class="opacity-75"
								fill="currentColor"
								d="M4 12a8 8 0 0 1 8-8V0C5.4 0 0 5.4 0 12h4z"
							/></svg
						>
						{$i18n.t(LABEL[status] ?? 'Working…')}
					</div>
					{#if state?.log_tail}
						<pre
							class="mt-3 max-h-56 overflow-auto text-[10px] font-mono text-gray-500 bg-black/5 dark:bg-black/30 rounded-lg p-2.5 whitespace-pre-wrap">{state.log_tail}</pre>
					{/if}
					<div class="mt-2 flex items-center justify-between gap-2">
						<span class="text-[10px] text-gray-500"
							>{$i18n.t('Isolated sandbox — no access to your database, models, or other sessions.')}</span
						>
						<button
							class="shrink-0 text-[10px] px-2 py-1 rounded-lg border border-red-300 dark:border-red-400/30 text-red-600 dark:text-red-300 hover:bg-red-500/10 transition"
							on:click={() => dispatch('stop')}>{$i18n.t('Cancel')}</button
						>
					</div>
				</div>
			{:else}
				<div class="px-6 py-8 max-w-xl mx-auto">
					{#if failed}
						<div class="text-sm text-red-600 dark:text-red-300">
							{state?.error || $i18n.t('The app did not start.')}
						</div>
						{#if state?.log_tail}
							<pre
								class="mt-2 max-h-56 overflow-auto text-[10px] font-mono text-gray-500 bg-black/5 dark:bg-black/30 rounded-lg p-2.5 whitespace-pre-wrap">{state.log_tail}</pre>
						{/if}
					{/if}
					{#if error}
						<div class="mt-2 text-xs text-amber-600 dark:text-amber-300">{error}</div>
					{/if}
					{#if stopped}
						<!-- The approve card below is the right thing to show after a stop, but
						     landing on it with no acknowledgement reads as if Run never happened. -->
						<div class="mb-3 flex items-center gap-1.5 text-xs text-gray-500">
							<span class="size-1.5 rounded-full bg-gray-400"></span>
							{$i18n.t('Stopped. The sandbox was torn down — press Run to start it again.')}
						</div>
					{/if}

					{#if !runnable}
						<!-- Nothing to run yet. The reason comes from the detector, so it names the
						     actual gap instead of a generic "not supported". -->
						<div class="text-center">
							<div class="text-base font-medium text-gray-800 dark:text-gray-100">
								{$i18n.t('Nothing to run yet')}
							</div>
							<div class="mt-1.5 text-xs text-gray-500 leading-relaxed">
								{plan?.blocked_reason ||
									$i18n.t(
										'Ask Harvis for a page you can open — an index.html, or an app with a dev server — then come back and press Run.'
									)}
							</div>
						</div>
					{:else}
						<div class="rounded-lg border border-amber-300/60 dark:border-amber-400/25 bg-amber-400/5 p-3">
							<div class="flex items-center gap-2">
								<svg
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.8"
									class="size-4 text-amber-500 shrink-0"
									><path
										d="M12 3l8 4v5c0 4.6-3.2 8.1-8 9-4.8-.9-8-4.4-8-9V7z"
										stroke-linecap="round"
										stroke-linejoin="round"
									/></svg
								>
								<h4 class="text-[12px] font-semibold text-amber-700 dark:text-amber-100">
									{$i18n.t('Run this in a sandbox')}
								</h4>
							</div>
							<p class="mt-1 text-[11px] text-amber-800/80 dark:text-amber-100/70 leading-relaxed">
								{$i18n.t(
									'This runs the code in your session — written by a model — inside a container with every Linux capability dropped, on a network that carries no Harvis service: no database, no models, no other session. It mounts only this session\'s folder, and it can reach the public internet, because installing packages needs that. One approval covers install, start and preview.'
								)}
							</p>
							<div class="mt-2 space-y-1">
								{#if plan?.install}
									<div class="flex items-baseline gap-2 text-[10.5px]">
										<span class="shrink-0 w-12 text-gray-500 uppercase tracking-wide text-[9px]"
											>{$i18n.t('Install')}</span
										>
										<code class="font-mono text-gray-600 dark:text-gray-300 break-all">{plan.install}</code>
									</div>
								{/if}
								<div class="flex items-baseline gap-2 text-[10.5px]">
									<span class="shrink-0 w-12 text-gray-500 uppercase tracking-wide text-[9px]"
										>{$i18n.t('Start')}</span
									>
									<code class="font-mono text-gray-600 dark:text-gray-300 break-all">{plan?.dev_cmd}</code>
								</div>
							</div>
							<button
								class="mt-3 inline-flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white transition disabled:opacity-50"
								disabled={busy}
								on:click={() => dispatch('run')}
							>
								<svg viewBox="0 0 24 24" fill="currentColor" class="size-3.5"
									><path d="M8 5v14l11-7z" /></svg
								>
								{busy
									? $i18n.t('Starting…')
									: failed
										? $i18n.t('Run again')
										: $i18n.t('Approve & run')}
							</button>
						</div>
					{/if}
				</div>
			{/if}
		{/if}
	</div>
</div>
