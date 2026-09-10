<script lang="ts">
	import { onDestroy, onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import {
		closeComputerSession,
		computerHealth,
		getComputerSession,
		listComputerSessions,
		navigateComputer,
		setComputerTakeover,
		startComputerSession,
		vncUrl,
		type ComputerSession
	} from './computer';

	const i18n = getContext('i18n');

	// The screen a teammate works on, docked beside the chat the way Claude Desktop
	// docks its browser. The iframe is noVNC talking to the session's own display;
	// your mouse and keyboard already work in it. "Take over" is not what makes it
	// interactive — it is what tells the agent to stop: while you hold the wheel,
	// every action the agent tries comes back 423 until you hand it back.

	let token = '';
	let headedAvailable = true;
	let healthReason = '';
	// Until the first health+list round-trip lands we know nothing. Without this
	// the pane rendered its empty state on every open, so a teammate that was
	// already browsing showed "no computer" for a beat before the screen appeared.
	let loading = true;
	let sessions: ComputerSession[] = [];
	let session: ComputerSession | null = null;
	let busy = false;
	let goUrl = '';
	let poll: ReturnType<typeof setInterval> | null = null;

	const refreshOne = async () => {
		if (!session) return;
		try {
			session = await getComputerSession(token, session.sessionId);
		} catch (e) {
			// 404 = closed elsewhere (or the backend restarted and forgot it).
			session = null;
			sessions = [];
		}
	};

	// With no screen showing, keep looking for one: a teammate that starts
	// browsing opens its own session, and the pane should pick it up without the
	// user doing anything. The list is an in-memory lookup on the backend.
	const attach = async () => {
		try {
			sessions = await listComputerSessions(token);
			session = sessions[0] ?? null;
			if (session) await refreshOne();
		} catch (e) {
			console.error('computer: list failed', e);
		}
	};

	const load = async () => {
		token = localStorage.token ?? '';
		try {
			const h = await computerHealth(token);
			headedAvailable = h.headedAvailable;
			healthReason = h.reason ?? '';
		} catch (e) {
			headedAvailable = false;
			healthReason = (e as Error).message;
		}
		await attach();
		loading = false;
	};

	const tickPoll = () => (session ? refreshOne() : attach());

	const start = async () => {
		if (busy) return;
		busy = true;
		try {
			session = await startComputerSession(token, { url: goUrl.trim() || undefined });
			goUrl = '';
			await refreshOne();
		} catch (e) {
			toast.error((e as Error).message);
		} finally {
			busy = false;
		}
	};

	const go = async () => {
		const url = goUrl.trim();
		if (!session || !url || busy) return;
		busy = true;
		try {
			await navigateComputer(token, session.sessionId, url);
			goUrl = '';
			await refreshOne();
		} catch (e) {
			toast.error((e as Error).message);
		} finally {
			busy = false;
		}
	};

	const takeover = async (taken: boolean) => {
		if (!session || busy) return;
		busy = true;
		try {
			session = await setComputerTakeover(token, session.sessionId, taken);
		} catch (e) {
			toast.error((e as Error).message);
		} finally {
			busy = false;
		}
	};

	const close = async () => {
		if (!session || busy) return;
		busy = true;
		try {
			await closeComputerSession(token, session.sessionId);
			session = null;
			sessions = [];
		} catch (e) {
			toast.error((e as Error).message);
		} finally {
			busy = false;
		}
	};

	onMount(() => {
		load();
		poll = setInterval(tickPoll, 3000);
	});
	onDestroy(() => {
		if (poll) clearInterval(poll);
	});

	$: frameSrc = session ? vncUrl(session.vncPath) : '';
</script>

<div class="flex h-full min-h-0 flex-col">
	{#if session}
		<div class="flex shrink-0 items-center gap-2 border-b border-gray-100 px-3 py-2 dark:border-gray-800">
			<span
				class="inline-block h-2 w-2 shrink-0 rounded-full {session.takenOver
					? 'bg-amber-400'
					: 'bg-emerald-400'}"
				aria-hidden="true"
			></span>
			<div class="min-w-0 flex-1">
				<div class="truncate text-sm font-medium" title={session.title ?? ''}>
					{session.title || $i18n.t('Computer')}
				</div>
				<div class="truncate text-[11px] text-gray-500 dark:text-gray-400" title={session.url ?? ''}>
					<!-- Who is holding the mouse, then where. The dot alone never said
					     which of the two states it meant. -->
					<span class={session.takenOver ? 'text-amber-500 dark:text-amber-400' : ''}
						>{session.takenOver
							? $i18n.t("You're driving")
							: $i18n.t('Teammate is driving')}</span
					>{#if session.url}<span class="mx-1 opacity-40">·</span>{session.url}{/if}
				</div>
			</div>
			{#if session.takenOver}
				<button
					class="rounded-md bg-amber-500/20 px-2.5 py-1 text-xs hover:bg-amber-500/30 disabled:opacity-50"
					disabled={busy}
					title={$i18n.t('Let the teammate act again')}
					on:click={() => takeover(false)}>{$i18n.t('Hand back')}</button
				>
			{:else}
				<button
					class="rounded-md bg-gray-100 px-2.5 py-1 text-xs hover:bg-gray-200 disabled:opacity-50 dark:bg-gray-800 dark:hover:bg-gray-700"
					disabled={busy}
					title={$i18n.t('Pause the teammate while you drive')}
					on:click={() => takeover(true)}>{$i18n.t('Take over')}</button
				>
			{/if}
			<button
				class="rounded-md px-2 py-1 text-xs text-gray-500 hover:bg-gray-100 disabled:opacity-50 dark:text-gray-400 dark:hover:bg-gray-800"
				disabled={busy}
				title={$i18n.t('Close this computer')}
				on:click={close}>{$i18n.t('Close')}</button
			>
		</div>

		<form
			class="flex shrink-0 gap-1.5 border-b border-gray-100 px-3 py-1.5 dark:border-gray-800"
			on:submit|preventDefault={go}
		>
			<input
				class="min-w-0 flex-1 rounded-md border border-gray-200 bg-gray-50 px-2 py-1 text-xs outline-none focus:border-gray-400 dark:border-gray-700 dark:bg-gray-800 dark:focus:border-gray-500"
				placeholder="https://"
				bind:value={goUrl}
				disabled={busy}
			/>
			<button
				class="rounded-md bg-gray-100 px-2.5 py-1 text-xs hover:bg-gray-200 disabled:opacity-50 dark:bg-gray-800 dark:hover:bg-gray-700"
				type="submit"
				disabled={busy || !goUrl.trim()}>{$i18n.t('Go')}</button
			>
		</form>

		{#if !session.takenOver}
			<div
				class="shrink-0 border-b border-gray-100 px-3 py-1 text-[11px] text-gray-500 dark:border-gray-800 dark:text-gray-400"
			>
				{$i18n.t('You can click and type in here now. Take over to pause the teammate first.')}
			</div>
		{/if}

		<div class="min-h-0 flex-1 bg-black">
			<iframe
				class="h-full w-full border-0"
				src={frameSrc}
				title={$i18n.t("Teammate's screen")}
				allow="clipboard-read; clipboard-write"
			></iframe>
		</div>
	{:else if loading}
		<div class="flex h-full items-center justify-center px-6 text-center">
			<p class="text-xs text-gray-500 dark:text-gray-400">{$i18n.t('Looking for a screen…')}</p>
		</div>
	{:else}
		<!-- The empty state is most of what this pane ever shows, so it is a card
		     rather than dim text floating in a black rectangle: an icon to anchor
		     the eye, one sentence of what this is, and a control you can see. -->
		<div class="flex h-full items-center justify-center px-5 py-6">
			<div
				class="w-full max-w-sm rounded-xl border border-gray-200 bg-gray-50 p-5 text-center dark:border-gray-800 dark:bg-gray-900"
			>
				<div
					class="mx-auto mb-3 flex size-10 items-center justify-center rounded-lg bg-gray-100 text-gray-500 dark:bg-gray-850 dark:text-gray-400"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						width="20"
						height="20"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.7"
						stroke-linecap="round"
						stroke-linejoin="round"
						aria-hidden="true"
						><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" /></svg
					>
				</div>

				{#if headedAvailable}
					<h3 class="text-sm font-medium text-gray-900 dark:text-gray-50">
						{$i18n.t('No screen open')}
					</h3>
					<p class="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
						{$i18n.t(
							'This is a real browser your teammate drives. When it starts browsing, its screen appears here — you can watch, click and type in it, or take the wheel.'
						)}
					</p>

					<form class="mt-4 flex flex-col gap-2" on:submit|preventDefault={start}>
						<input
							class="w-full rounded-md border border-gray-200 bg-white px-2.5 py-1.5 text-xs outline-none focus:border-gray-400 dark:border-gray-700 dark:bg-gray-850 dark:focus:border-gray-500"
							placeholder={$i18n.t('Start on a page (optional): https://')}
							bind:value={goUrl}
							disabled={busy}
						/>
						<button
							class="w-full rounded-md bg-gray-900 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-gray-700 disabled:opacity-50 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white"
							type="submit"
							disabled={busy}
							>{busy ? $i18n.t('Starting…') : $i18n.t('Start a computer')}</button
						>
					</form>
				{:else}
					<h3 class="text-sm font-medium text-gray-900 dark:text-gray-50">
						{$i18n.t('This install has no watchable screen.')}
					</h3>
					<p class="mt-1 text-xs leading-relaxed text-gray-500 dark:text-gray-400">
						{healthReason ||
							$i18n.t('The browser sandbox is not running, so there is nothing to show.')}
					</p>
				{/if}
			</div>
		</div>
	{/if}
</div>
