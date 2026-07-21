<script lang="ts">
	// Marathon P2: the Build dock's MANUAL shell — a user-driven PTY into the
	// SESSION's runner container (never the host). Raw byte streaming over the
	// existing /ws/vibecoding/terminal WebSocket (vibecoding/terminal.py), which
	// is itself gated server-side by HARVIS_BUILD_SHELL (default OFF).
	//
	// Provenance: everything typed here is the USER's — the agent's commands run
	// through the orchestration path and never touch this socket.
	import { onDestroy, getContext } from 'svelte';
	import { Terminal } from '@xterm/xterm';
	import { FitAddon } from '@xterm/addon-fit';
	import '@xterm/xterm/css/xterm.css';

	const i18n: any = getContext('i18n');

	export let sessionId = '';

	let terminalEl: HTMLDivElement | null = null;
	let term: Terminal | null = null;
	let fitAddon: FitAddon | null = null;
	let ws: WebSocket | null = null;
	let resizeObserver: ResizeObserver | null = null;
	let status: 'idle' | 'connecting' | 'connected' | 'closed' | 'error' = 'idle';
	let errMsg = '';

	const dot = () =>
		status === 'connected'
			? 'bg-emerald-500'
			: status === 'connecting'
				? 'bg-blue-500 animate-pulse'
				: status === 'error'
					? 'bg-red-500'
					: 'bg-gray-400 dark:bg-gray-600';

	const disconnect = () => {
		try {
			ws?.close();
		} catch {
			/* ignore */
		}
		ws = null;
		if (status !== 'error') status = 'closed';
	};

	const teardownTerm = () => {
		resizeObserver?.disconnect();
		resizeObserver = null;
		term?.dispose();
		term = null;
		fitAddon = null;
	};

	const connect = () => {
		if (!sessionId || status === 'connecting' || status === 'connected') return;
		errMsg = '';
		status = 'connecting';

		// Fresh terminal per connection (simplest correct lifecycle).
		teardownTerm();
		term = new Terminal({
			fontFamily: 'JetBrainsMono, ui-monospace, monospace',
			fontSize: 12,
			cursorBlink: true,
			convertEol: false,
			theme: {
				background: '#0a0f1a',
				foreground: '#d1d5db',
				cursor: '#93c5fd',
				selectionBackground: '#1e3a5f'
			}
		});
		fitAddon = new FitAddon();
		term.loadAddon(fitAddon);
		if (terminalEl) {
			term.open(terminalEl);
			fitAddon.fit();
			resizeObserver = new ResizeObserver(() => {
				try {
					fitAddon?.fit();
				} catch {
					/* ignore */
				}
			});
			resizeObserver.observe(terminalEl);
		}

		const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
		const url = `${proto}//${location.host}/ws/vibecoding/terminal?session_id=${encodeURIComponent(
			sessionId
		)}&token=${encodeURIComponent(localStorage.token || '')}`;
		ws = new WebSocket(url);
		ws.binaryType = 'arraybuffer';

		ws.onopen = () => {
			status = 'connected';
			term?.focus();
		};
		ws.onmessage = (ev) => {
			if (typeof ev.data === 'string') {
				// The backend sends JSON control frames for auth/flag/container errors.
				try {
					const j = JSON.parse(ev.data);
					if (j && typeof j === 'object' && 'error' in j) {
						errMsg = String(j.error);
						status = 'error';
						return;
					}
				} catch {
					/* not JSON — plain terminal text */
				}
				term?.write(ev.data);
			} else {
				term?.write(new Uint8Array(ev.data));
			}
		};
		ws.onerror = () => {
			if (status !== 'error') {
				errMsg = errMsg || $i18n.t('Connection failed.');
				status = 'error';
			}
		};
		ws.onclose = () => {
			if (status !== 'error') status = 'closed';
			ws = null;
		};

		term.onData((data) => {
			if (ws && ws.readyState === WebSocket.OPEN) ws.send(data);
		});
	};

	onDestroy(() => {
		disconnect();
		teardownTerm();
	});
</script>

<div class="flex flex-col min-h-0 h-full">
	<!-- header: provenance label + status + connect control -->
	<div class="shrink-0 flex items-center gap-2 px-3 py-1.5 border-b border-gray-200 dark:border-white/10 text-[11px]">
		<span class="size-1.5 rounded-full shrink-0 {dot()}"></span>
		<span class="text-gray-400 truncate">
			{$i18n.t('Manual shell — runs inside this session’s container, not your machine.')}
		</span>
		<div class="ml-auto shrink-0 flex items-center gap-1.5">
			{#if status === 'connected'}
				<button
					class="px-2 py-0.5 rounded-lg border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-black/[0.04] dark:hover:bg-white/[0.06] transition"
					on:click={disconnect}>{$i18n.t('Disconnect')}</button
				>
			{:else}
				<button
					class="px-2 py-0.5 rounded-lg border border-sky-400/20 bg-sky-500/80 text-white hover:bg-sky-500 transition disabled:opacity-50"
					disabled={!sessionId || status === 'connecting'}
					on:click={connect}
					>{status === 'connecting' ? $i18n.t('Connecting…') : $i18n.t('Connect')}</button
				>
			{/if}
		</div>
	</div>

	<!-- body -->
	{#if !sessionId}
		<div class="flex-1 flex items-center justify-center text-xs text-gray-500 px-4 text-center">
			{$i18n.t('Start a coding session first — the shell attaches to the session’s container.')}
		</div>
	{:else}
		<div class="flex-1 min-h-0 relative bg-gray-50 dark:bg-gray-900">
			<div bind:this={terminalEl} class="absolute inset-0 p-1.5"></div>
			{#if status === 'idle'}
				<div
					class="absolute inset-0 flex items-center justify-center text-xs text-gray-500 px-4 text-center"
				>
					{$i18n.t('Press Connect to open a shell in the session container.')}
				</div>
			{:else if status === 'error'}
				<div
					class="absolute inset-x-0 bottom-0 px-3 py-2 text-[11px] text-red-400 bg-red-500/10 border-t border-red-500/20"
				>
					{errMsg || $i18n.t('Shell unavailable.')}
				</div>
			{:else if status === 'closed'}
				<div
					class="absolute inset-x-0 bottom-0 px-3 py-1.5 text-[11px] text-gray-500 bg-black/[0.03] dark:bg-white/[0.05] border-t border-gray-200 dark:border-white/10"
				>
					{$i18n.t('Session ended.')}
				</div>
			{/if}
		</div>
	{/if}
</div>
