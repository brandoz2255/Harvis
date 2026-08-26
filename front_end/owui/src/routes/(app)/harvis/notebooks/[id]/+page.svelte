<script lang="ts">
	import { getContext, onDestroy, tick } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { WEBUI_NAME, showSidebar } from '$lib/stores';
	import {
		getNotebook,
		listSources,
		addUrlSource,
		addTextSource,
		addYoutubeSource,
		uploadFileSource,
		deleteSource,
		autonameNotebook,
		listNotes,
		createNote,
		chatNotebook,
		listPodcasts,
		generatePodcast,
		podcastAudioUrl,
		type Notebook,
		type NotebookSource,
		type NotebookNote,
		type Podcast
	} from '$lib/apis/notebooks';

	const i18n: any = getContext('i18n');

	$: id = $page.params.id;

	let nb: Notebook | null = null;
	let sources: NotebookSource[] = [];
	let notes: NotebookNote[] = [];
	let podcasts: Podcast[] = [];
	let loaded = false;

	// ── Add source (popup modal) — Upload / Website / Copied text / YouTube ──
	let showAddModal = false;
	let srcMode: 'link' | 'text' | 'file' | 'youtube' = 'file';
	let urlVal = '';
	let ytVal = '';
	let textTitle = '';
	let textVal = '';
	let adding = false;
	let addError = '';
	let fileEl: HTMLInputElement;

	// ── Notes (Studio) ──
	let noteOpen = false;
	let noteTitle = '';
	let noteVal = '';
	let savingNote = false;

	// ── Audio Overview (Studio) ──
	let genningPodcast = false;
	let podcastError = '';
	let pollTimer: ReturnType<typeof setTimeout> | null = null;

	// ── Chat ──
	let messages: { role: 'user' | 'assistant'; content: string; sources?: any[] }[] = [];
	let input = '';
	let sending = false;
	let feedEl: HTMLElement | null = null;
	let inputEl: HTMLTextAreaElement | null = null;

	const NB_EMOJIS = [
		'📓', '📘', '📗', '📙', '📕', '🧠', '🔬', '🗂️', '📊', '🧪',
		'💡', '🚀', '🌐', '📚', '🧭', '🎯', '⚙️', '🔭', '📈', '🗺️'
	];
	const fallbackEmoji = (key: string): string => {
		let h = 0;
		for (let i = 0; i < key.length; i++) h = (h + key.charCodeAt(i)) % NB_EMOJIS.length;
		return NB_EMOJIS[h];
	};
	$: displayEmoji = nb?.emoji || (nb ? fallbackEmoji(nb.id) : '📓');

	// ── Which notebook this component is actually showing ──────────────────────
	// SvelteKit reuses one component instance across /notebooks/A → /notebooks/B,
	// so `onMount(load)` fired exactly once: every later switch left the notebook
	// you LEFT on screen — its sources, its notes, and worst of all its chat
	// transcript — under the new notebook's id. A question typed after the switch
	// was then sent to B while the screen showed A's conversation.
	//
	// `openId` is the notebook currently on screen; `loadSeq` bumps on every
	// switch. An async that started before a switch compares its captured seq and
	// drops its result rather than writing it into the notebook now being viewed.
	// Same discipline as the chat-session guard.
	let openId = '';
	let loadSeq = 0;
	const isCurrent = (seq: number) => seq === loadSeq;

	const load = async (target: string, seq: number) => {
		loaded = false;
		const [_nb, _sources, _notes, _podcasts] = await Promise.all([
			getNotebook(target),
			listSources(target),
			listNotes(target),
			listPodcasts(target)
		]);
		if (!isCurrent(seq)) return; // switched notebooks mid-fetch — drop the stale answer
		nb = _nb;
		sources = _sources;
		notes = _notes;
		podcasts = _podcasts;
		loaded = true;
		schedulePodcastPoll();
	};
	const reloadSources = async (target = openId, seq = loadSeq) => {
		const v = await listSources(target);
		if (isCurrent(seq)) sources = v;
	};
	const reloadNotes = async (target = openId, seq = loadSeq) => {
		const v = await listNotes(target);
		if (isCurrent(seq)) notes = v;
	};
	const reloadPodcasts = async (target = openId, seq = loadSeq) => {
		const v = await listPodcasts(target);
		if (isCurrent(seq)) podcasts = v;
	};

	// Every piece of per-notebook state is reset here. Anything left behind is
	// something the next notebook inherits from the last one.
	const switchTo = (target: string) => {
		openId = target;
		const seq = ++loadSeq;
		if (pollTimer) {
			clearTimeout(pollTimer);
			pollTimer = null;
		}
		nb = null;
		sources = [];
		notes = [];
		podcasts = [];
		messages = [];
		input = '';
		sending = false;
		noteOpen = false;
		noteTitle = '';
		noteVal = '';
		savingNote = false;
		genningPodcast = false;
		podcastError = '';
		closeAdd();
		void load(target, seq);
	};

	// Fires on first render as well as on every later param change, which is why
	// there is no onMount(load) any more.
	$: if (id && id !== openId) switchTo(id);

	onDestroy(() => pollTimer && clearTimeout(pollTimer));

	const isUntitled = (t?: string | null): boolean =>
		['', 'untitled', 'untitled notebook', 'new notebook'].includes((t || '').trim().toLowerCase());

	// After sources change, give an untitled / emoji-less notebook an identity from its sources.
	const maybeAutoname = async () => {
		if (!nb) return;
		if (!isUntitled(nb.title) && nb.emoji) return;
		if (sources.length === 0) return;
		const seq = loadSeq;
		const res = await autonameNotebook(openId);
		// Without this check a name generated for the notebook you left lands on
		// the one you opened.
		if (res && nb && isCurrent(seq)) {
			nb = { ...nb, title: res.title || nb.title, emoji: res.emoji || nb.emoji };
		}
	};

	const openAdd = (mode: typeof srcMode) => {
		srcMode = mode;
		addError = '';
		showAddModal = true;
	};
	const closeAdd = () => {
		showAddModal = false;
		urlVal = ytVal = textTitle = textVal = '';
		addError = '';
	};
	const afterAdd = async (ok: boolean) => {
		adding = false;
		if (ok) {
			closeAdd();
			await reloadSources();
			await maybeAutoname();
		} else {
			addError = $i18n.t('Could not add source. Check the backend logs.');
		}
	};
	const submitLink = async () => {
		if (!urlVal.trim()) return;
		adding = true;
		addError = '';
		await afterAdd(await addUrlSource(openId, urlVal.trim()));
	};
	const submitYoutube = async () => {
		if (!ytVal.trim()) return;
		adding = true;
		addError = '';
		await afterAdd(await addYoutubeSource(openId, ytVal.trim()));
	};
	const submitText = async () => {
		if (!textTitle.trim() || !textVal.trim()) return;
		adding = true;
		addError = '';
		await afterAdd(await addTextSource(openId, textTitle.trim(), textVal.trim()));
	};
	const onFile = async (e: Event) => {
		const f = (e.target as HTMLInputElement).files?.[0];
		if (!f) return;
		adding = true;
		addError = '';
		await afterAdd(await uploadFileSource(openId, f));
	};
	const removeSource = async (sourceId: string) => {
		if (await deleteSource(openId, sourceId)) await reloadSources();
	};

	const submitNote = async () => {
		if (!noteVal.trim()) return;
		savingNote = true;
		await createNote(openId, noteVal.trim(), noteTitle.trim());
		savingNote = false;
		noteTitle = noteVal = '';
		noteOpen = false;
		await reloadNotes();
	};

	// ── Audio Overview generation + polling ──
	const podcastActive = (p: Podcast): boolean =>
		(p.status || '') === 'pending' || (p.status || '') === 'generating';
	const schedulePodcastPoll = () => {
		if (pollTimer) clearTimeout(pollTimer);
		if (podcasts.some(podcastActive)) {
			const seq = loadSeq;
			const target = openId;
			pollTimer = setTimeout(async () => {
				await reloadPodcasts(target, seq);
				if (!isCurrent(seq)) return; // this timer belongs to a notebook that is no longer open
				genningPodcast = podcasts.some(podcastActive);
				schedulePodcastPoll();
			}, 5000);
		} else {
			genningPodcast = false;
		}
	};
	const makeAudioOverview = async () => {
		if (sources.length === 0 || genningPodcast) return;
		genningPodcast = true;
		podcastError = '';
		const seq = loadSeq;
		const target = openId;
		const res = await generatePodcast(target, { title: nb?.title || 'Audio Overview' });
		if (!isCurrent(seq)) return;
		if (!res.ok) {
			genningPodcast = false;
			podcastError = res.error || $i18n.t('Could not start generation.');
			return;
		}
		await reloadPodcasts(target, seq);
		if (isCurrent(seq)) schedulePodcastPoll();
	};

	const send = async () => {
		const q = input.trim();
		if (!q || sending) return;
		input = '';
		messages = [...messages, { role: 'user', content: q }];
		sending = true;
		await tick();
		feedEl && (feedEl.scrollTop = feedEl.scrollHeight);
		const seq = loadSeq;
		const res = await chatNotebook(openId, q);
		// An answer about the notebook you left must not appear in the one you opened.
		if (!isCurrent(seq)) return;
		messages = [...messages, { role: 'assistant', content: res.answer, sources: res.sources }];
		sending = false;
		await tick();
		feedEl && (feedEl.scrollTop = feedEl.scrollHeight);
	};

	const starter = async (prefix: string) => {
		input = prefix;
		await tick();
		inputEl?.focus();
	};

	const srcEmoji = (t?: string): string => {
		const k = (t || '').toLowerCase();
		if (k.includes('pdf')) return '📕';
		if (k.includes('url')) return '🔗';
		if (k.includes('youtube')) return '▶️';
		if (k.includes('text') || k.includes('markdown')) return '📝';
		if (k.includes('image')) return '🖼️';
		if (k.includes('audio') || k.includes('transcript')) return '🎵';
		return '📄';
	};
	const srcStatusColor = (s?: string): string =>
		s === 'completed' || s === 'ready' || s === 'done'
			? 'text-green-500'
			: s === 'error' || s === 'failed'
				? 'text-red-500'
				: 'text-amber-500';
	const isAiNote = (n: NotebookNote) => (n.note_type || n.type || '').toLowerCase().includes('ai');
	const relTime = (iso?: string): string => {
		if (!iso) return '';
		const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
		if (s < 60) return 'just now';
		if (s < 3600) return `${Math.floor(s / 60)}m ago`;
		if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
		return `${Math.floor(s / 86400)}d ago`;
	};
	// Citation label: prefer a resolved source title over the raw UUID.
	const citeLabel = (src: any): string =>
		src?.title ||
		sources.find((s) => s.id === (src?.source_id || src?.id))?.title ||
		src?.snippet ||
		'Source';

	const SRC_MODES: { key: typeof srcMode; label: string }[] = [
		{ key: 'file', label: 'Upload' },
		{ key: 'link', label: 'Website' },
		{ key: 'text', label: 'Copied text' },
		{ key: 'youtube', label: 'YouTube' }
	];
	const STARTERS = [
		{ label: 'Learn about a new topic', prefix: 'Help me learn about ' },
		{ label: 'Create something new', prefix: 'Help me create ' },
		{ label: 'Make progress on a project', prefix: 'Help me make progress on ' }
	];
</script>

<svelte:head>
	<title>{nb?.title ?? $i18n.t('Notebook')} • {$WEBUI_NAME}</title>
</svelte:head>

<div class="w-full h-full {$showSidebar ? 'md:max-w-[calc(100%-var(--sidebar-width))]' : ''} flex flex-col">
	<!-- ── Header ── -->
	<header class="shrink-0 px-5 py-3 flex items-center gap-3 border-b border-gray-100 dark:border-gray-850">
		<button
			class="text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 shrink-0"
			title={$i18n.t('Open Notebook')}
			on:click={() => goto('/harvis/notebooks')}
		>
			<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5"
				><path
					fill-rule="evenodd"
					d="M12.79 5.23a.75.75 0 0 1-.02 1.06L8.832 10l3.938 3.71a.75.75 0 1 1-1.04 1.08l-4.5-4.25a.75.75 0 0 1 0-1.08l4.5-4.25a.75.75 0 0 1 1.06.02Z"
					clip-rule="evenodd"
				/></svg
			>
		</button>
		<span class="text-xl leading-none shrink-0">{displayEmoji}</span>
		<div class="min-w-0">
			<h1 class="text-base font-semibold text-gray-800 dark:text-gray-100 truncate">
				{nb?.title ?? $i18n.t('Loading…')}
			</h1>
			{#if nb?.description}<p class="text-xs text-gray-500 truncate">{nb.description}</p>{/if}
		</div>
	</header>

	<!-- ── 3 columns: Sources | Chat | Studio ── -->
	<div class="flex-1 min-h-0 flex flex-col lg:flex-row">
		<!-- ── Sources (left) ── -->
		<aside
			class="lg:w-72 shrink-0 border-b lg:border-b-0 lg:border-r border-gray-100 dark:border-gray-850 flex flex-col min-h-0 max-h-[35vh] lg:max-h-none"
		>
			<div class="flex items-center justify-between px-4 py-2.5 shrink-0">
				<span class="text-sm font-medium text-gray-800 dark:text-gray-100"
					>{$i18n.t('Sources')}{#if loaded}<span class="text-xs text-gray-400"> {sources.length}</span>{/if}</span
				>
				<button
					class="text-xs px-2 py-0.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white"
					on:click={() => openAdd('file')}>＋ {$i18n.t('Add')}</button
				>
			</div>
			<div class="flex-1 min-h-0 overflow-y-auto px-3 pb-4 space-y-1.5">
				{#if loaded && sources.length === 0}
					<div class="text-xs text-gray-400 text-center mt-6 px-2">
						{$i18n.t('Saved sources will appear here. Add a PDF, website, text, or video.')}
					</div>
				{/if}
				{#each sources as s (s.id)}
					<div class="group rounded-lg border border-gray-100 dark:border-gray-850 px-2.5 py-2 flex items-start gap-2">
						<span class="text-base leading-none mt-0.5">{srcEmoji(s.source_type || (s as any).type)}</span>
						<div class="min-w-0 flex-1">
							<div class="text-xs text-gray-700 dark:text-gray-200 truncate">{s.title || 'Source'}</div>
							<div class="text-[10px] {srcStatusColor(s.status)} mt-0.5 uppercase tracking-wide">{s.status || 'ready'}</div>
						</div>
						<button
							class="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 transition shrink-0"
							title={$i18n.t('Delete')}
							on:click={() => removeSource(s.id)}
						>
							<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3.5 h-3.5"
								><path
									fill-rule="evenodd"
									d="M8.75 1A2.75 2.75 0 0 0 6 3.75v.443c-.795.077-1.58.177-2.365.298a.75.75 0 1 0 .23 1.482l.149-.022.841 10.518A2.75 2.75 0 0 0 7.596 19h4.807a2.75 2.75 0 0 0 2.742-2.53l.841-10.52.149.023a.75.75 0 0 0 .23-1.482A41.03 41.03 0 0 0 14 4.193V3.75A2.75 2.75 0 0 0 11.25 1h-2.5ZM10 4c.84 0 1.673.025 2.5.075V3.75c0-.69-.56-1.25-1.25-1.25h-2.5c-.69 0-1.25.56-1.25 1.25v.325C8.327 4.025 9.16 4 10 4Z"
									clip-rule="evenodd"
								/></svg
							>
						</button>
					</div>
				{/each}
			</div>
		</aside>

		<!-- ── Chat (center) ── -->
		<section class="flex-1 min-h-0 flex flex-col">
			<div bind:this={feedEl} class="flex-1 min-h-0 overflow-y-auto">
				{#if sources.length === 0 && messages.length === 0}
					<!-- Welcome / "untitled" empty state -->
					<div class="max-w-2xl mx-auto px-5 py-10">
						<div class="text-4xl mb-3">👋</div>
						<h2 class="text-3xl font-light text-gray-800 dark:text-gray-100">
							{$i18n.t("Let's start your notebook…")}
						</h2>
						<p class="text-sm text-gray-500 mt-3 leading-relaxed max-w-lg">
							{$i18n.t(
								'This is your blank canvas to understand, create, or make progress on something new. Add sources, then ask anything — answers stay grounded in what you add.'
							)}
						</p>

						<p class="text-sm font-medium text-gray-700 dark:text-gray-200 mt-7">
							{$i18n.t('What would you like this notebook to help you do?')}
						</p>
						<div class="flex flex-col items-start gap-2 mt-3">
							{#each STARTERS as s}
								<button
									class="px-4 py-2 rounded-lg border border-gray-200 dark:border-gray-800 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
									on:click={() => starter(s.prefix)}>{$i18n.t(s.label)}</button
								>
							{/each}
						</div>

						<div class="mt-8 rounded-2xl border border-dashed border-gray-200 dark:border-gray-800 p-6 text-center">
							<div class="text-sm font-medium text-gray-700 dark:text-gray-200">
								{$i18n.t('Add a source to get started')}
							</div>
							<div class="text-xs text-gray-400 mt-1">{$i18n.t('pdf, docs, text, websites, and more')}</div>
							<div class="flex flex-wrap justify-center gap-2 mt-4">
								<button
									class="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
									on:click={() => openAdd('file')}>⬆️ {$i18n.t('Upload files')}</button
								>
								<button
									class="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
									on:click={() => openAdd('link')}>🔗 {$i18n.t('Websites')}</button
								>
								<button
									class="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
									on:click={() => openAdd('text')}>📋 {$i18n.t('Copied text')}</button
								>
								<button
									class="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-800 text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
									on:click={() => openAdd('youtube')}>▶️ {$i18n.t('YouTube')}</button
								>
							</div>
						</div>
					</div>
				{:else}
					<div class="max-w-3xl mx-auto px-5 py-4 space-y-3">
						{#if messages.length === 0}
							<div class="text-center text-sm text-gray-400 mt-6">
								{$i18n.t('Ask a question — answers are grounded in your sources.')}
							</div>
						{/if}
						{#each messages as m}
							<div class="flex {m.role === 'user' ? 'justify-end' : 'justify-start'}">
								<div
									class="max-w-[80%] rounded-2xl px-3.5 py-2 text-sm {m.role === 'user'
										? 'bg-blue-600 text-white'
										: 'bg-gray-100 dark:bg-gray-850 text-gray-800 dark:text-gray-100'}"
								>
									<div class="whitespace-pre-wrap leading-relaxed">{m.content}</div>
									{#if m.sources && m.sources.length}
										<div
											class="mt-2 pt-2 border-t border-gray-200/40 dark:border-gray-700/40 text-[11px] opacity-80 space-y-0.5"
										>
											<div class="font-medium opacity-70">{$i18n.t('Citations')}</div>
											{#each m.sources.slice(0, 5) as src}
												<div class="truncate">· {citeLabel(src)}</div>
											{/each}
										</div>
									{/if}
								</div>
							</div>
						{/each}
						{#if sending}
							<div class="flex justify-start">
								<div class="rounded-2xl px-3.5 py-2 bg-gray-100 dark:bg-gray-850 text-gray-400 text-sm">
									{$i18n.t('Thinking…')}
								</div>
							</div>
						{/if}
					</div>
				{/if}
			</div>

			<!-- Bottom composer -->
			<div class="shrink-0 px-4 pb-4 pt-2">
				<div
					class="max-w-3xl mx-auto rounded-2xl border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 px-4 py-3"
				>
					<textarea
						bind:this={inputEl}
						bind:value={input}
						rows="1"
						placeholder={$i18n.t('Ask a question or create something')}
						class="w-full bg-transparent text-sm outline-none resize-none placeholder:text-gray-400"
						on:keydown={(e) => {
							if (e.key === 'Enter' && !e.shiftKey) {
								e.preventDefault();
								send();
							}
						}}
					></textarea>
					<div class="flex items-center justify-between mt-2">
						<span class="text-xs text-gray-400">
							{sources.length}
							{sources.length === 1 ? $i18n.t('source') : $i18n.t('sources')}
						</span>
						<button
							class="shrink-0 w-8 h-8 rounded-full flex items-center justify-center bg-blue-600 hover:bg-blue-700 text-white transition disabled:opacity-40"
							disabled={sending || !input.trim()}
							on:click={send}
							title={$i18n.t('Send')}
						>
							<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4"
								><path
									fill-rule="evenodd"
									d="M10 17a.75.75 0 0 1-.75-.75V5.612L5.29 9.77a.75.75 0 0 1-1.08-1.04l5.25-5.5a.75.75 0 0 1 1.08 0l5.25 5.5a.75.75 0 1 1-1.08 1.04l-3.96-4.158V16.25A.75.75 0 0 1 10 17Z"
									clip-rule="evenodd"
								/></svg
							>
						</button>
					</div>
				</div>
			</div>
		</section>

		<!-- ── Studio (right): Notes + Audio Overview ── -->
		<aside
			class="lg:w-80 shrink-0 border-t lg:border-t-0 lg:border-l border-gray-100 dark:border-gray-850 flex flex-col min-h-0 max-h-[40vh] lg:max-h-none overflow-y-auto"
		>
			<div class="px-4 py-2.5 text-sm font-medium text-gray-800 dark:text-gray-100 shrink-0">
				{$i18n.t('Studio')}
			</div>

			<!-- Audio Overview -->
			<div class="px-4 pb-3">
				<div class="rounded-xl border border-gray-100 dark:border-gray-850 p-3">
					<div class="flex items-center justify-between">
						<span class="text-sm font-medium text-gray-700 dark:text-gray-200">🎙️ {$i18n.t('Audio Overview')}</span>
						<button
							class="text-xs px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 disabled:opacity-50"
							disabled={sources.length === 0 || genningPodcast}
							on:click={makeAudioOverview}
							>{genningPodcast ? $i18n.t('Generating…') : $i18n.t('Generate')}</button
						>
					</div>
					{#if sources.length === 0}
						<div class="text-[11px] text-gray-400 mt-1">{$i18n.t('Add a source first.')}</div>
					{/if}
					{#if podcastError}<div class="text-[11px] text-red-500 mt-1">{podcastError}</div>{/if}
					<div class="mt-2 space-y-2">
						{#each podcasts as p (p.id)}
							<div class="rounded-lg bg-gray-50 dark:bg-gray-850 px-2.5 py-2">
								<div class="flex items-center justify-between">
									<span class="text-xs text-gray-700 dark:text-gray-200 truncate">{p.title || 'Audio Overview'}</span>
									<span class="text-[10px] {srcStatusColor(p.status)} uppercase tracking-wide ml-2 shrink-0">{p.status || ''}</span>
								</div>
								{#if p.status === 'completed'}
									<audio controls src={podcastAudioUrl(openId, p.id)} class="w-full mt-1.5 h-8"></audio>
								{:else if p.status === 'error'}
									<div class="text-[11px] text-red-500 mt-1">{p.error_message || $i18n.t('Generation failed.')}</div>
								{/if}
							</div>
						{/each}
					</div>
				</div>
			</div>

			<!-- Notes -->
			<div class="px-4 pb-4 flex-1 min-h-0 flex flex-col">
				<div class="flex items-center justify-between mb-2 shrink-0">
					<span class="text-sm font-medium text-gray-700 dark:text-gray-200"
						>📝 {$i18n.t('Notes')}{#if loaded}<span class="text-xs text-gray-400"> {notes.length}</span>{/if}</span
					>
					<button
						class="text-xs px-2 py-0.5 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800"
						on:click={() => (noteOpen = !noteOpen)}>＋ {$i18n.t('Note')}</button
					>
				</div>
				{#if noteOpen}
					<div class="space-y-1.5 mb-2 shrink-0">
						<input
							bind:value={noteTitle}
							placeholder={$i18n.t('Title (optional)')}
							class="w-full px-2.5 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 text-xs outline-none focus:border-blue-500/50"
						/>
						<textarea
							bind:value={noteVal}
							rows="3"
							placeholder={$i18n.t('Write a note…')}
							class="w-full px-2.5 py-1.5 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 text-xs outline-none focus:border-blue-500/50 resize-none"
						></textarea>
						<button
							class="text-xs px-2.5 py-1 rounded-lg bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"
							disabled={savingNote}
							on:click={submitNote}>{savingNote ? $i18n.t('Saving…') : $i18n.t('Save note')}</button
						>
					</div>
				{/if}
				<div class="flex-1 min-h-0 overflow-y-auto space-y-1.5">
					{#if loaded && notes.length === 0}
						<div class="text-xs text-gray-400">{$i18n.t('No notes yet.')}</div>
					{/if}
					{#each notes as n (n.id)}
						<div class="rounded-lg border border-gray-100 dark:border-gray-850 px-2.5 py-2">
							<div class="flex items-center gap-1.5 mb-0.5">
								<span
									class="text-[9px] uppercase tracking-wide px-1 py-0.5 rounded {isAiNote(n)
										? 'bg-blue-500/15 text-blue-600 dark:text-blue-300'
										: 'bg-gray-100 dark:bg-gray-800 text-gray-500'}">{isAiNote(n) ? $i18n.t('AI') : $i18n.t('Note')}</span
								>
								<span class="text-[10px] text-gray-400">{relTime(n.updated_at || n.created_at)}</span>
							</div>
							{#if n.title}<div class="text-xs font-medium text-gray-700 dark:text-gray-200 truncate">{n.title}</div>{/if}
							<div class="text-[11px] text-gray-500 dark:text-gray-400 line-clamp-4 whitespace-pre-wrap">{n.content}</div>
						</div>
					{/each}
				</div>
			</div>
		</aside>
	</div>
</div>

<!-- ── Add source popup modal ── -->
{#if showAddModal}
	<div class="fixed inset-0 z-50 flex items-center justify-center">
		<button class="absolute inset-0 bg-black/40" aria-label={$i18n.t('Close')} on:click={closeAdd}></button>
		<div
			class="relative w-full max-w-lg mx-4 rounded-2xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-850 shadow-xl p-5"
		>
			<div class="flex items-center justify-between mb-4">
				<h3 class="text-base font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Add source')}</h3>
				<button class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200" on:click={closeAdd}>
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5"
						><path
							d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z"
						/></svg
					>
				</button>
			</div>

			<div class="flex gap-1.5 mb-3">
				{#each SRC_MODES as m}
					<button
						class="text-xs px-2.5 py-1 rounded-lg transition {srcMode === m.key
							? 'bg-blue-500/15 text-blue-600 dark:text-blue-300'
							: 'bg-gray-100 dark:bg-gray-850 text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}"
						on:click={() => {
							srcMode = m.key;
							addError = '';
						}}>{$i18n.t(m.label)}</button
					>
				{/each}
			</div>

			{#if srcMode === 'link'}
				<input
					bind:value={urlVal}
					placeholder="https://…"
					class="w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 text-sm outline-none focus:border-blue-500/50"
				/>
				<button
					class="mt-3 text-sm px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"
					disabled={adding}
					on:click={submitLink}>{adding ? $i18n.t('Adding…') : $i18n.t('Add link')}</button
				>
			{:else if srcMode === 'youtube'}
				<input
					bind:value={ytVal}
					placeholder="https://youtube.com/watch?v=…"
					class="w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 text-sm outline-none focus:border-blue-500/50"
				/>
				<button
					class="mt-3 text-sm px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"
					disabled={adding}
					on:click={submitYoutube}>{adding ? $i18n.t('Adding…') : $i18n.t('Add video')}</button
				>
			{:else if srcMode === 'text'}
				<input
					bind:value={textTitle}
					placeholder={$i18n.t('Title')}
					class="w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 text-sm outline-none focus:border-blue-500/50 mb-2"
				/>
				<textarea
					bind:value={textVal}
					rows="5"
					placeholder={$i18n.t('Paste text…')}
					class="w-full px-3 py-2 rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 text-sm outline-none focus:border-blue-500/50 resize-none"
				></textarea>
				<button
					class="mt-3 text-sm px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50"
					disabled={adding}
					on:click={submitText}>{adding ? $i18n.t('Adding…') : $i18n.t('Add text')}</button
				>
			{:else if srcMode === 'file'}
				<input
					bind:this={fileEl}
					type="file"
					on:change={onFile}
					class="w-full text-sm text-gray-500 file:mr-2 file:px-3 file:py-1.5 file:rounded-lg file:border-0 file:bg-gray-100 dark:file:bg-gray-850 file:text-gray-700 dark:file:text-gray-200"
				/>
				{#if adding}<div class="text-sm text-gray-400 mt-2">{$i18n.t('Uploading…')}</div>{/if}
			{/if}

			{#if addError}<div class="text-xs text-red-500 mt-2">{addError}</div>{/if}
		</div>
	</div>
{/if}
