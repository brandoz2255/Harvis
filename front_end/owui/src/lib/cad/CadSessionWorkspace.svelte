<script lang="ts">
	// A CAD session — the room one part is made in (CS-1, filled in by CS-4).
	//
	// Not the same surface as `/harvis/cad`, which is a studio you bring a project to.
	// A session is project-bound: it was opened by a request in an ordinary chat, it
	// owns its own conversation, and returning to it later is supposed to put the part
	// back exactly where it was.
	//
	// Once the part exists this page hands its whole area to the workspace: a rail on the
	// left, the part in the middle, the panels on the right, and the global sidebar out of
	// the way — the session spec asks for a room, not a page with a room on it.
	//
	// The state worth naming is *starting*: a room is created before the model has
	// created anything, so for the first seconds there is genuinely no project to show.
	// Saying so beats drawing an empty studio that looks like a part that failed.
	import { getContext, onDestroy, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { get } from 'svelte/store';
	import { WEBUI_NAME, cadFocus, hideNavRail, showSidebar } from '$lib/stores';

	import Chat from '$lib/components/chat/Chat.svelte';
	import CadFocusWorkspace from '$lib/cad/CadFocusWorkspace.svelte';
	import CadConceptSketch from '$lib/cad/CadConceptSketch.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import { getCadJob, getCadSession, type CadSession } from '$lib/apis/cad';

	const i18n: any = getContext('i18n');

	export let sessionId = '';

	let session: CadSession | null = null;
	let loading = true;
	let error = '';
	let timer: ReturnType<typeof setInterval> | null = null;

	// Long enough to cover a slow first authoring turn, bounded so a room whose job
	// died does not poll for the life of the tab.
	const POLL_MS = 3000;
	const POLL_LIMIT = 200;
	let polls = 0;

	// What the request pinned down, drawn while there is still nothing else to draw.
	// The server extracts it before the model is asked anything, so it exists during the
	// whole pre-project wait — which is the longest, emptiest stretch of an authoring
	// turn and the one a bare spinner served worst.
	let concept: { stated: Record<string, any>; unknowns: string[]; units: string | null } | null =
		null;

	const loadConcept = async (jobId: string) => {
		try {
			const job = await getCadJob(jobId);
			const row = [...(job.activity ?? [])].reverse().find((e) => e.kind === 'spec');
			if (row) concept = { stated: row.stated ?? {}, unknowns: row.unknowns ?? [], units: row.units };
		} catch {
			// The sketch is a courtesy during the wait. Failing to fetch it changes nothing
			// about whether the part arrives, so it stays silent rather than putting an
			// error over a turn that is going fine.
		}
	};

	const load = async () => {
		try {
			const view = await getCadSession(sessionId);
			session = view.session;
			error = '';
			// Only while waiting: once the project exists the workspace owns the sketch and
			// draws it from its own live stream.
			if (!session?.project_id && session?.job_id && !concept) await loadConcept(session.job_id);
		} catch (e: any) {
			error = e?.status === 404 ? 'not_found' : e?.message || 'unavailable';
			session = null;
		}
		loading = false;
	};

	const stopPolling = () => {
		if (timer) clearInterval(timer);
		timer = null;
	};

	// The session spec asks for no permanent global rail in this room, so the sidebar is
	// folded away while the page is mounted and put back on the way out — but only if it
	// is still closed. Reopening it by hand is a decision, and restoring over it would
	// undo something the user just did.
	//
	// Closing it is not enough on its own: a closed sidebar still draws a narrow icon
	// strip so it can be reopened, and that strip is exactly the global rail the spec
	// rules out. `hideNavRail` removes it, and the header's back button is what replaces
	// it — leaving both off would be a room with no exit.
	let sidebarWasOpen = false;
	const hideSidebar = () => {
		sidebarWasOpen = get(showSidebar);
		if (sidebarWasOpen) showSidebar.set(false);
		hideNavRail.set(true);
	};
	const restoreSidebar = () => {
		hideNavRail.set(false);
		if (sidebarWasOpen && !get(showSidebar)) showSidebar.set(true);
	};

	onMount(async () => {
		hideSidebar();
		await load();
		timer = setInterval(async () => {
			polls += 1;
			if (session?.project_id || error === 'not_found' || polls > POLL_LIMIT) {
				stopPolling();
				return;
			}
			await load();
		}, POLL_MS);
	});

	onDestroy(() => {
		stopPolling();
		restoreSidebar();
		cadFocus.set(null);
	});

	$: if (session?.project_id) stopPolling();

	// The room is the studio with the session's own conversation down its right side —
	// the same overlay an ordinary chat opens, not a second, lesser copy of it. Driving
	// it through `cadFocus` is what makes that literally true: one component, one layout,
	// and the right-hand strip Chat already owns. The exit is told where to go because
	// there is no page underneath this one to fall back to.
	$: if (session?.project_id && session?.cad_conversation_id) {
		cadFocus.set({
			projectId: session.project_id,
			jobId: session.job_id ?? '',
			closeTo: session.source_conversation_id ? `/c/${session.source_conversation_id}` : '/',
			closeLabel: $i18n.t('Back to the chat')
		});
	}

	// Back to where the request was made, which is the point of keeping the link: the
	// part left a card there, and that chat is the context the person came from.
	const back = () =>
		goto(session?.source_conversation_id ? `/c/${session.source_conversation_id}` : '/');
</script>

<svelte:head>
	<title>{session?.title || $i18n.t('CAD session')} • {$WEBUI_NAME}</title>
</svelte:head>

{#if session?.project_id && session?.cad_conversation_id}
	<!-- The room itself: the session's conversation, with the studio opened over it by
	     `cadFocus` above. Chat draws the right-hand strip and the workspace draws its own
	     top bar, so there is no page header and no second layout here. -->
	<Chat chatIdProp={session.cad_conversation_id} />
{:else if session?.project_id}
	<!-- A session from before CS-1 gave every room its own conversation. The part is
	     real and still worth showing; there is simply nothing to put beside it. -->
	<div class="w-full h-full {$showSidebar ? 'md:max-w-[calc(100%-var(--sidebar-width))]' : ''}">
		<!-- The job id is not decoration. Without it the room cannot tell a turn that is
		     still authoring from one that finished long ago: `jobRunning` is gated on it,
		     so the viewport skipped straight to "no geometry yet" and the concept sketch
		     never drew. The session row has carried `job_id` since CS-1. -->
		<CadFocusWorkspace
			standalone
			projectId={session.project_id}
			jobId={session.job_id ?? ''}
			onClose={back}
			closeLabel={$i18n.t('Back to the chat')}
		/>
	</div>
{:else}
	<div
		class="w-full h-full overflow-y-auto {$showSidebar
			? 'md:max-w-[calc(100%-var(--sidebar-width))]'
			: ''}"
	>
		<div class="max-w-5xl mx-auto px-5 py-6 space-y-4">
			<header>
				<button
					class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
					on:click={back}
				>
					← {$i18n.t('Back to the chat that started this')}
				</button>
				<div class="mt-2">
					<h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-100">
						{session?.title || $i18n.t('CAD session')}
					</h1>
					<p class="text-sm text-gray-500 mt-0.5">
						{$i18n.t(
							'This session has its own conversation and its own part. Everything you ask here changes that part.'
						)}
					</p>
				</div>
			</header>

			{#if loading}
				<div class="flex items-center gap-2 text-sm text-gray-500 py-10 justify-center">
					<Spinner className="size-4" />
					{$i18n.t('Opening the session…')}
				</div>
			{:else if error === 'not_found'}
				<div
					class="rounded-2xl border border-gray-100 dark:border-gray-850 p-6 text-sm text-gray-500"
				>
					{$i18n.t('That CAD session does not exist, or it is not yours.')}
				</div>
			{:else if error}
				<div
					class="rounded-2xl border border-gray-100 dark:border-gray-850 p-6 text-sm text-gray-500"
				>
					{$i18n.t('The session could not be loaded.')}
					<span class="text-gray-400">{error}</span>
				</div>
			{:else}
				<div
					class="rounded-2xl border border-gray-100 dark:border-gray-850 p-6 text-sm text-gray-500 flex flex-col items-center gap-4"
				>
					{#if concept && polls <= POLL_LIMIT}
						<CadConceptSketch
							stated={concept.stated}
							unknowns={concept.unknowns}
							units={concept.units}
						/>
					{/if}
					<div class="flex items-center gap-2">
						<Spinner className="size-4" />
						{#if polls > POLL_LIMIT}
							{$i18n.t('No part was created in this session. Ask again in its conversation.')}
						{:else}
							{$i18n.t('Designing the part. This page fills in as soon as it exists.')}
						{/if}
					</div>
				</div>
			{/if}
		</div>
	</div>
{/if}
