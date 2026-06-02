<script lang="ts">
	import { onMount, onDestroy, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { showControls, workspaceControlsTab } from '$lib/stores';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import {
		createWorkspaceStream,
		WORKSPACE_TERMINAL,
		type WorkspaceEvent
	} from '$lib/apis/streaming/workspace-stream';

	const i18n: any = getContext('i18n');

	// Props come from the marked `<details type="workspace_run" …>` token.
	export let id = '';
	export let attributes: Record<string, string> = {};
	export let className = 'w-full';

	$: workspaceId = attributes?.workspaceid ?? '';
	$: taskLabel = attributes?.tasklabel ?? 'Workspace task';
	$: taskBrief = attributes?.taskbrief ?? '';
	// Opt-in approval gate (P1.5): the marker carries needsapproval="1" when the
	// run is parked pending Approve. Read once — the marker doesn't change.
	const needsApproval = attributes?.needsapproval === '1';

	type Phase =
		| 'awaiting'
		| 'connecting'
		| 'thinking'
		| 'executing'
		| 'done'
		| 'error'
		| 'cancelled';
	let phase: Phase = needsApproval ? 'awaiting' : 'connecting';
	let currentStep = 'Connecting…';
	let recent: { ok: boolean; text: string }[] = [];
	let toolCount = 0;
	let summary = '';
	let errorMessage = '';
	let fixHint = '';
	let elapsed = 0;

	let controller: AbortController | null = null;
	let timer: ReturnType<typeof setInterval> | null = null;
	let startedAt = Date.now();

	$: running = phase === 'connecting' || phase === 'thinking' || phase === 'executing';

	// Map raw tool names → human phrases (mirrors chat_bridge._humanize_tool_call).
	const PHRASES: Record<string, string> = {
		exec: 'Running a command…',
		run_code: 'Running code…',
		read: 'Reading a file…',
		file_fetch: 'Reading a file…',
		write: 'Writing a file…',
		file_write: 'Writing a file…',
		edit: 'Editing a file…',
		dir_list: 'Scanning the project…',
		dir_fetch: 'Scanning the project…',
		web_search: 'Searching the web…',
		web_fetch: 'Reading a web page…',
		browser: 'Browsing…',
		local_rag: 'Searching knowledge…',
		memory_search: 'Recalling memory…'
	};
	const phrase = (tool?: string) =>
		(tool && PHRASES[tool]) || (tool ? `Using ${tool}…` : 'Working…');

	const fmt = (ms: number) => {
		const s = Math.floor(ms / 1000);
		return s < 60 ? `${s}s` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
	};

	const handle = (evt: WorkspaceEvent) => {
		switch (evt.type) {
			case 'agent_start':
				if (phase === 'connecting' || phase === 'thinking') {
					phase = 'thinking';
					currentStep = 'Planning the task…';
				}
				break;
			case 'log':
				if (evt.message) currentStep = String(evt.message).slice(0, 140);
				break;
			case 'tool_call':
				phase = 'executing';
				toolCount += 1;
				currentStep = phrase(evt.tool);
				recent = [...recent, { ok: true, text: phrase(evt.tool) }].slice(-4);
				break;
			case 'tool_result':
				if (recent.length) {
					recent[recent.length - 1].ok = evt.success !== false;
					recent = recent;
				}
				break;
			case 'done':
				phase = 'done';
				summary = evt.summary ?? '';
				break;
			case 'error':
				phase = 'error';
				errorMessage = evt.message ?? 'Workspace error';
				fixHint = evt.fix_hint ?? '';
				break;
			case 'cancelled':
				phase = 'cancelled';
				break;
		}
	};

	const consume = async () => {
		if (!workspaceId) {
			phase = 'error';
			errorMessage = 'Missing workspace id.';
			return;
		}
		controller = new AbortController();
		try {
			for await (const evt of createWorkspaceStream(
				workspaceId,
				localStorage.token,
				controller.signal
			)) {
				handle(evt);
				if (WORKSPACE_TERMINAL.has(evt.type)) break;
			}
		} catch (e: any) {
			if (e?.name !== 'AbortError' && phase !== 'done') {
				phase = 'error';
				errorMessage = String(e?.message ?? e);
			}
		} finally {
			if (timer) {
				clearInterval(timer);
				timer = null;
			}
		}
	};

	const stop = async () => {
		if (!workspaceId) return;
		try {
			await fetch(`${WEBUI_BASE_URL}/api/workspace/cancel/${workspaceId}`, {
				method: 'POST',
				headers: { Authorization: `Bearer ${localStorage.token}` },
				credentials: 'include'
			});
		} catch (e) {
			console.error('workspace cancel failed', e);
		}
	};

	const openStudio = () => goto(`/harvis/agent-studio?ws=${workspaceId}`);
	const viewActivity = () => {
		workspaceControlsTab.set('activity');
		showControls.set(true);
	};

	const startTimerAndStream = () => {
		startedAt = Date.now();
		timer = setInterval(() => {
			if (running) elapsed = Date.now() - startedAt;
		}, 1000);
		consume();
	};

	const approve = async () => {
		phase = 'connecting';
		currentStep = 'Starting…';
		try {
			const r = await fetch(`${WEBUI_BASE_URL}/api/owui/workspace/${workspaceId}/approve`, {
				method: 'POST',
				headers: { Authorization: `Bearer ${localStorage.token}` },
				credentials: 'include'
			});
			if (!r.ok) throw new Error(`HTTP ${r.status}`);
			startTimerAndStream();
		} catch (e: any) {
			phase = 'error';
			errorMessage = `Couldn't start the task: ${e?.message ?? e}`;
		}
	};

	const deny = async () => {
		try {
			await fetch(`${WEBUI_BASE_URL}/api/owui/workspace/${workspaceId}/deny`, {
				method: 'POST',
				headers: { Authorization: `Bearer ${localStorage.token}` },
				credentials: 'include'
			});
		} catch (e) {
			console.error('workspace deny failed', e);
		}
		phase = 'cancelled';
	};

	onMount(() => {
		// A parked (approval-gated) run waits for Approve before streaming;
		// otherwise (default) stream immediately, exactly as before.
		if (needsApproval) return;
		startTimerAndStream();
	});

	onDestroy(() => {
		controller?.abort();
		if (timer) clearInterval(timer);
	});
</script>

<div
	class="{className} my-2 rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 px-3.5 py-3 text-sm"
>
	<div class="flex items-center gap-2">
		{#if running}
			<span class="relative flex size-2.5">
				<span
					class="animate-ping absolute inline-flex h-full w-full rounded-full bg-teal-400 opacity-60"
				></span>
				<span class="relative inline-flex rounded-full size-2.5 bg-teal-500"></span>
			</span>
		{:else if phase === 'done'}
			<span class="text-teal-500 font-semibold">✓</span>
		{:else if phase === 'error'}
			<span class="text-red-500 font-semibold">!</span>
		{:else}
			<span class="text-amber-500">■</span>
		{/if}

		<span class="font-medium text-gray-700 dark:text-gray-200">
			{#if phase === 'done'}{$i18n.t('Workspace complete')}
			{:else if phase === 'error'}{$i18n.t('Workspace error')}
			{:else if phase === 'cancelled'}{$i18n.t('Workspace cancelled')}
			{:else if phase === 'awaiting'}{$i18n.t('Approval needed')}
			{:else}{taskLabel}{/if}
		</span>

		{#if phase !== 'awaiting'}
			<span class="ml-auto text-xs text-gray-400 tabular-nums">
				{fmt(elapsed)}{#if toolCount > 0} · {toolCount}
					{toolCount === 1 ? $i18n.t('tool') : $i18n.t('tools')}{/if}
			</span>
		{/if}
	</div>

	{#if running}
		<div class="mt-1.5 text-gray-600 dark:text-gray-300">{currentStep}</div>
		{#if recent.length}
			<div class="mt-1.5 space-y-0.5">
				{#each recent as r}
					<div class="flex items-center gap-1.5 text-xs text-gray-500">
						<span class={r.ok ? 'text-teal-500' : 'text-red-500'}>{r.ok ? '✓' : '✗'}</span>
						<span class="truncate">{r.text}</span>
					</div>
				{/each}
			</div>
		{/if}
	{:else if phase === 'done'}
		<div class="mt-1.5 text-gray-700 dark:text-gray-200 whitespace-pre-wrap">{summary}</div>
	{:else if phase === 'error'}
		<div class="mt-1.5 text-red-600 dark:text-red-400">{errorMessage}</div>
		{#if fixHint}<div class="mt-1 text-xs text-gray-500">{fixHint}</div>{/if}
	{:else if phase === 'cancelled'}
		<div class="mt-1.5 text-gray-500">{$i18n.t('Cancelled.')}</div>
	{:else if phase === 'awaiting'}
		<div class="mt-1.5 text-gray-600 dark:text-gray-300">
			{$i18n.t('Harvis wants to run an agent task:')}
		</div>
		{#if taskBrief}
			<div class="mt-1 text-xs text-gray-500 line-clamp-3">{taskBrief}</div>
		{/if}
	{/if}

	<div class="mt-2.5 flex items-center gap-2">
		{#if phase === 'awaiting'}
			<button
				class="text-xs px-3 py-1 rounded-lg bg-teal-600 hover:bg-teal-700 text-white transition"
				on:click={approve}>{$i18n.t('Approve')}</button
			>
			<button
				class="text-xs px-3 py-1 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-950 transition"
				on:click={deny}>{$i18n.t('Deny')}</button
			>
		{:else if running}
			<button
				class="text-xs px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition"
				on:click={viewActivity}>{$i18n.t('View activity')}</button
			>
			<button
				class="text-xs px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition"
				on:click={openStudio}>{$i18n.t('Open Agent Studio')}</button
			>
			<button
				class="text-xs px-2 py-1 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-950 transition ml-auto"
				on:click={stop}>{$i18n.t('Stop')}</button
			>
		{:else}
			<button
				class="text-xs px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition"
				on:click={openStudio}>{$i18n.t('Open Agent Studio')}</button
			>
		{/if}
	</div>
</div>
