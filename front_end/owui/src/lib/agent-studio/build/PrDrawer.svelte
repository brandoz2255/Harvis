<script lang="ts">
	// PR right-drawer — THE single human-gated Create-PR path for a Build session.
	// Consolidates the three former entry points (header button, BuildActions row,
	// changes-card inline form) into one drawer with title/body, a TARGET (base)
	// branch selector, a readiness checklist, and the session's persisted PR history.
	// Human-triggered only: nothing here auto-submits — the Create-PR button stays
	// disabled until the checklist passes and the human clicks it.
	import { getContext } from 'svelte';
	import {
		createPrForVibecodeSession,
		getVibecodeSessionChanges,
		getVibecodeSessionPullRequests,
		startVibecodeSessionReview,
		listSubagents,
		type CodeFileChange,
		type CodePullRequest,
		type SubAgentLite,
		type VibecodeSession
	} from '$lib/apis/agent-runs';

	const i18n: any = getContext('i18n');

	export let show = false;
	export let sessionId = '';
	export let session: VibecodeSession | null = null;
	export let diff = ''; // the session's ACCUMULATED diff — prefills the body + gates "changes exist"
	export let hasGithub = false; // Create-PR needs a GitHub origin (from getVibecodeSessionDiff)
	// Set by the page when a turn ran tests (or the user knows they were skipped) —
	// there's no reliable machine signal yet, so the checklist row is a human ack.

	const close = () => (show = false);

	// ── data: tracked per-file AI edits + already-persisted PRs (both fail-soft) ──
	let changes: CodeFileChange[] = [];
	let pulls: CodePullRequest[] = [];
	let loading = false;
	let loadedFor = '';
	const load = async () => {
		const req = sessionId;
		if (!req) return;
		loading = true;
		try {
			const [c, p] = await Promise.all([
				getVibecodeSessionChanges(req),
				getVibecodeSessionPullRequests(req)
			]);
			if (req !== sessionId) return; // switched sessions mid-fetch → drop
			changes = c.changes;
			pulls = p.pull_requests;
		} finally {
			if (req === sessionId) loading = false;
		}
	};

	// ── fallback file list parsed from the diff (before tracked rows exist) ──
	function diffFiles(d: string): { path: string; status: string }[] {
		if (!d) return [];
		const out: { path: string; status: string }[] = [];
		let cur: { path: string; status: string } | null = null;
		for (const line of d.split('\n')) {
			const m = line.match(/^diff --git a\/(.+?) b\/(.+)$/);
			if (m) {
				cur = { path: m[2], status: 'modify' };
				out.push(cur);
			} else if (cur) {
				if (line.startsWith('new file mode')) cur.status = 'create';
				else if (line.startsWith('deleted file mode')) cur.status = 'delete';
			}
		}
		return out;
	}
	$: filesFromDiff = diffFiles(diff);
	$: fileRows = changes.length
		? changes.map((c) => ({ path: c.file_path, status: c.change_type || 'modify' }))
		: filesFromDiff;

	// ── form state — prefilled once per open (never clobbers user edits mid-open) ──
	let prTitle = '';
	let prBody = '';
	let baseBranch = '';
	let testsAck = false;
	let busy = false;
	let error = '';
	let result: { pr_url?: string; pr_number?: number; branch?: string; base?: string } | null = null;

	const prefill = () => {
		prTitle = (session?.title || '').trim();
		baseBranch = (session?.base_branch || 'main').trim();
		const list = fileRows
			.slice(0, 40)
			.map((f) => `- \`${f.path}\` (${f.status})`)
			.join('\n');
		prBody = [
			`Opened from Harvis Build session${session?.title ? ` “${session.title}”` : ''}.`,
			list ? `\nChanged files:\n${list}` : ''
		]
			.join('\n')
			.trim();
	};

	$: if (show && sessionId && loadedFor !== sessionId) {
		loadedFor = sessionId;
		testsAck = false;
		error = '';
		result = null;
		reviewStatusLocal = '';
		reviewError = '';
		reviewModeLocal = '';
		githubReviewPr = null;
		load().then(prefill);
		prefill(); // immediate prefill from the diff; refined once tracked rows load
		if (session?.review_enabled) loadReviewerAgents(); // populate the reviewer picker
	}
	$: if (!show && loadedFor) loadedFor = ''; // fresh reload + prefill next open

	// Base-branch suggestions: the session's base first, then the common defaults.
	$: baseOptions = [...new Set([session?.base_branch, 'main', 'master', 'develop'].filter(Boolean))] as string[];

	// ── readiness checklist — gates the Create-PR button ──
	$: hasChanges = fileRows.length > 0 || diff.trim() !== '';
	$: titleOk = prTitle.trim() !== '';
	$: ready = hasChanges && titleOk && testsAck;

	// ── agent review gate (opt-in per session; review off ⇒ zero behavior change) ──
	// Mirrors the backend gate: review_enabled AND review_status NOT IN ('agreed','off')
	// ⇒ Create-PR refuses, unless the human passes the explicit override.
	let reviewStatusLocal = ''; // optimistic status after a Start-review POST (no session refetch)
	let reviewBusy = false;
	let reviewError = '';
	$: reviewEnabled = session?.review_enabled === true;
	$: reviewStatus = String(reviewStatusLocal || session?.review_status || 'off').toLowerCase();
	$: reviewBlocked = reviewEnabled && reviewStatus !== 'agreed' && reviewStatus !== 'off';

	// github-mode review runs the same loop ON a real draft PR — the backend opens
	// it at review start and persists it to code_pull_requests with status 'draft'.
	// We surface that draft PR (from the persisted list, else the POST response)
	// while the review is running/blocked so the human can follow it on GitHub.
	// ── reviewer roster: extra custom sub-agents that join the coder↔reviewer loop.
	// None selected ⇒ the single built-in reviewer (today's behavior, unchanged).
	let reviewerAgents: SubAgentLite[] = [];
	let selectedReviewerIds: string[] = [];
	let reviewerAgentsLoaded = false;
	const loadReviewerAgents = async () => {
		if (reviewerAgentsLoaded) return;
		reviewerAgentsLoaded = true;
		reviewerAgents = (await listSubagents()).filter((a) => a.enabled !== false);
	};
	const toggleReviewer = (id: string) => {
		selectedReviewerIds = selectedReviewerIds.includes(id)
			? selectedReviewerIds.filter((x) => x !== id)
			: [...selectedReviewerIds, id];
	};

	let reviewModeLocal: '' | 'thread' | 'github' = '';
	let githubReviewPr: { pr_url?: string; pr_number?: number } | null = null;
	$: draftPr = pulls.find((p) => String(p?.status || '').toLowerCase() === 'draft') ?? null;
	$: reviewPrUrl = draftPr?.pr_url || githubReviewPr?.pr_url || '';
	$: githubReviewActive =
		reviewBlocked && (reviewModeLocal === 'github' || (!!draftPr && reviewModeLocal !== 'thread'));

	const startReview = async (mode: 'thread' | 'github' = 'thread') => {
		if (!sessionId || reviewBusy) return;
		reviewBusy = true;
		reviewError = '';
		try {
			const r = await startVibecodeSessionReview(sessionId, mode, selectedReviewerIds);
			reviewStatusLocal = String(r?.review_status || 'pending');
			reviewModeLocal = mode;
			if (mode === 'github') {
				githubReviewPr = r?.pr_url ? { pr_url: r.pr_url, pr_number: r.pr_number } : null;
				await load(); // pick up the persisted draft-PR row
			}
		} catch (e: any) {
			reviewError = String(e?.message ?? e);
		} finally {
			reviewBusy = false;
		}
	};

	const submit = async (override = false) => {
		if (!ready || busy || !sessionId) return;
		if (reviewBlocked && !override) return; // gate mirrors the backend refusal
		busy = true;
		error = '';
		try {
			result = await createPrForVibecodeSession(sessionId, {
				title: prTitle.trim(),
				body: prBody.trim() || undefined,
				base: baseBranch.trim() || undefined,
				...(override ? { override: true } : {})
			});
			await load(); // pick up the persisted code_pull_requests row
		} catch (e: any) {
			error = String(e?.message ?? e);
		} finally {
			busy = false;
		}
	};

	const CHECK_OK = 'text-emerald-600 dark:text-emerald-400';
	const CHECK_NO = 'text-gray-400 dark:text-gray-500';
	const statusChip = (s: string | null) =>
		s === 'merged'
			? 'border-purple-300/40 text-purple-600 dark:text-purple-300'
			: s === 'closed'
				? 'border-red-300/40 text-red-600 dark:text-red-400'
				: s === 'draft'
					? 'border-gray-300/40 text-gray-500 dark:text-gray-400'
					: 'border-emerald-300/40 text-emerald-600 dark:text-emerald-400';
</script>

{#if show}
	<button
		class="fixed inset-0 z-40 bg-black/40 cursor-default"
		aria-label={$i18n.t('Close')}
		on:click={close}
	></button>
	<aside
		class="fixed right-0 top-0 bottom-0 z-50 w-full max-w-lg bg-white dark:bg-gray-950 border-l border-gray-100 dark:border-gray-850 shadow-2xl flex flex-col"
	>
		<div class="shrink-0 flex items-center gap-2 px-4 py-3 border-b border-gray-100 dark:border-gray-850">
			<div class="min-w-0">
				<div class="text-sm font-semibold text-gray-800 dark:text-gray-100">
					{$i18n.t('Create pull request')}
				</div>
				<div class="text-[11px] text-gray-400">
					{$i18n.t('Human-only — pushes a branch and opens the PR when you click')}
				</div>
			</div>
			<button
				class="ml-auto shrink-0 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 p-1"
				aria-label={$i18n.t('Close')}
				on:click={close}
			>
				<svg viewBox="0 0 20 20" fill="currentColor" class="size-4"><path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" /></svg>
			</button>
		</div>

		<div class="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-4">
			{#if !hasGithub}
				<div class="rounded-lg border border-amber-300/40 bg-amber-50 dark:bg-amber-950/30 px-3 py-2 text-[11px] text-amber-700 dark:text-amber-300">
					{$i18n.t('This session has no GitHub origin — Create PR needs a GitHub-backed repo.')}
				</div>
			{/if}

			<!-- agent review — reviewer roster + start/re-run, available in ANY state except while a
			     review is actively running, so you can add agents to the (thread OR GitHub) loop even
			     after a prior review agreed. -->
			{#if reviewEnabled}
				<div
					class="rounded-lg border px-3 py-2 space-y-2 {reviewStatus === 'agreed'
						? 'border-emerald-300/40 bg-emerald-50 dark:bg-emerald-950/30'
						: 'border-amber-300/40 bg-amber-50 dark:bg-amber-950/30'}"
				>
					<div class="flex items-center gap-2">
						<span
							class="min-w-0 flex-1 text-[11px] {reviewStatus === 'agreed'
								? 'text-emerald-700 dark:text-emerald-300'
								: 'text-amber-700 dark:text-amber-300'}"
						>
							{#if reviewStatus === 'agreed'}
								{$i18n.t('Agent review: agreed — PR is unblocked. Re-run to review new changes.')}
							{:else if reviewStatus === 'pending'}
								{$i18n.t("Agents haven't agreed yet — review in progress.")}
							{:else if reviewStatus === 'needs_human'}
								{$i18n.t("Agents couldn't agree after the review rounds — your call.")}
							{:else if reviewStatus === 'stale'}
								{$i18n.t('New changes since the last review — re-run it before creating the PR.')}
							{:else}
								{$i18n.t('Agent review is enabled but has not run yet.')}
							{/if}
						</span>
						{#if reviewStatus !== 'pending'}
							<button
								class="shrink-0 rounded-md border border-amber-400/40 px-2 py-1 text-[10px] text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/40 disabled:opacity-40 transition"
								disabled={reviewBusy || !sessionId}
								on:click={() => startReview('thread')}
							>
								{reviewBusy
									? $i18n.t('Starting…')
									: ['agreed', 'needs_human', 'stale'].includes(reviewStatus)
										? $i18n.t('Re-run review')
										: $i18n.t('Start review')}
							</button>
							<!-- github mode: same loop, but on a real draft PR (needs a GitHub origin) -->
							<button
								class="shrink-0 rounded-md border border-amber-400/40 px-2 py-1 text-[10px] text-amber-700 dark:text-amber-300 hover:bg-amber-100 dark:hover:bg-amber-900/40 disabled:opacity-40 transition"
								disabled={reviewBusy || !sessionId || !hasGithub}
								title={!hasGithub ? $i18n.t('Needs a GitHub-backed repo') : undefined}
								on:click={() => startReview('github')}
							>
								{reviewBusy ? $i18n.t('Starting…') : $i18n.t('Review on GitHub')}
							</button>
						{/if}
					</div>
					<!-- reviewer roster: add custom sub-agents to the coder↔reviewer loop (applies to
					     BOTH thread and GitHub reviews). None ⇒ the built-in reviewer. -->
					{#if reviewStatus !== 'pending' && reviewerAgents.length}
						<div
							class="pt-2 border-t {reviewStatus === 'agreed'
								? 'border-emerald-400/20'
								: 'border-amber-400/20'}"
						>
							<div class="text-[10px] uppercase tracking-wide text-gray-500 dark:text-gray-400 mb-1">
								{$i18n.t('Reviewers')}
							</div>
							<div class="flex flex-wrap gap-1.5">
								{#each reviewerAgents as a (a.id)}
									<button
										type="button"
										class="px-2 py-0.5 rounded-full border text-[10px] transition {selectedReviewerIds.includes(
											a.id
										)
											? 'border-amber-500 bg-amber-500/15 text-amber-800 dark:text-amber-200'
											: 'border-gray-300/50 dark:border-gray-600/50 text-gray-600 dark:text-gray-300 hover:border-amber-400/60'}"
										title={a.description || a.model || ''}
										on:click={() => toggleReviewer(a.id)}
									>
										{selectedReviewerIds.includes(a.id) ? '✓ ' : ''}{a.name}
									</button>
								{/each}
							</div>
							<div class="mt-1 text-[10px] text-gray-500 dark:text-gray-400">
								{#if selectedReviewerIds.length}
									{$i18n.t(
										'Coder ↔ {{count}} custom reviewer(s) — all must approve. Applies to thread + GitHub reviews.',
										{ count: selectedReviewerIds.length }
									)}
								{:else}
									{$i18n.t('None selected — the built-in reviewer runs. Pick agents to add perspectives.')}
								{/if}
							</div>
						</div>
					{/if}
					{#if githubReviewActive}
						<div class="text-[10px] text-amber-700 dark:text-amber-300">
							{$i18n.t('This review is happening on the draft PR — critiques post as PR reviews, fixes as PR comments.')}
							{#if reviewPrUrl}
								<a
									href={reviewPrUrl}
									target="_blank"
									rel="noopener noreferrer"
									class="ml-1 inline-flex items-center gap-1 rounded border border-amber-400/40 px-1.5 py-0.5 font-mono hover:bg-amber-100 dark:hover:bg-amber-900/40 transition"
								>
									{$i18n.t('Draft PR')}{draftPr?.pr_number || githubReviewPr?.pr_number
										? ` #${draftPr?.pr_number ?? githubReviewPr?.pr_number}`
										: ''} ↗
								</a>
							{/if}
						</div>
					{/if}
					{#if reviewError}
						<div class="text-[10px] text-red-600 dark:text-red-400">{reviewError}</div>
					{/if}
				</div>
			{/if}

			<!-- title + body -->
			<div class="space-y-2">
				<label class="block">
					<span class="text-[11px] text-gray-500">{$i18n.t('Title')}</span>
					<input
						class="mt-1 w-full text-xs rounded-lg bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 px-2.5 py-1.5 text-gray-800 dark:text-gray-100 outline-none focus:border-gray-300 dark:focus:border-gray-700"
						placeholder={$i18n.t('What does this PR do?')}
						bind:value={prTitle}
					/>
				</label>
				<label class="block">
					<span class="text-[11px] text-gray-500">{$i18n.t('Description')}</span>
					<textarea
						rows="6"
						class="mt-1 w-full text-xs rounded-lg bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 px-2.5 py-1.5 text-gray-800 dark:text-gray-100 outline-none focus:border-gray-300 dark:focus:border-gray-700 font-mono resize-y"
						bind:value={prBody}
					></textarea>
				</label>
				<label class="block">
					<span class="text-[11px] text-gray-500">{$i18n.t('Target (base) branch')}</span>
					<input
						class="mt-1 w-full text-xs rounded-lg bg-gray-50 dark:bg-gray-900 border border-gray-200 dark:border-gray-800 px-2.5 py-1.5 text-gray-800 dark:text-gray-100 outline-none focus:border-gray-300 dark:focus:border-gray-700 font-mono"
						list="pr-base-branches"
						bind:value={baseBranch}
					/>
					<datalist id="pr-base-branches">
						{#each baseOptions as b}<option value={b}></option>{/each}
					</datalist>
					<span class="mt-1 block text-[10px] text-gray-400">
						{$i18n.t('Head branch')}: <span class="font-mono">harvis/vibecode/{sessionId.slice(0, 8)}…</span> — {$i18n.t('main/master are refused as head.')}
					</span>
				</label>
			</div>

			<!-- readiness checklist — the button unlocks only when all three pass -->
			<div class="rounded-lg border border-gray-200 dark:border-gray-800 divide-y divide-gray-100 dark:divide-gray-850">
				<div class="px-3 py-1.5 text-[10px] uppercase tracking-wide text-gray-400">
					{$i18n.t('Readiness')}
				</div>
				<div class="px-3 py-2 flex items-center gap-2 text-xs {hasChanges ? CHECK_OK : CHECK_NO}">
					<span class="font-mono">{hasChanges ? '✓' : '○'}</span>
					<span class="text-gray-700 dark:text-gray-200">{$i18n.t('Changes exist')}</span>
					<span class="ml-auto text-[10px] text-gray-400">
						{loading ? $i18n.t('Loading…') : `${fileRows.length} ${$i18n.t('file(s)')}`}
					</span>
				</div>
				<label class="px-3 py-2 flex items-center gap-2 text-xs cursor-pointer {testsAck ? CHECK_OK : CHECK_NO}">
					<input type="checkbox" bind:checked={testsAck} class="sr-only" />
					<span class="font-mono">{testsAck ? '✓' : '○'}</span>
					<span class="text-gray-700 dark:text-gray-200">{$i18n.t('Tests were run — or intentionally skipped')}</span>
					<span class="ml-auto text-[10px] text-gray-400">{$i18n.t('click to confirm')}</span>
				</label>
				<div class="px-3 py-2 flex items-center gap-2 text-xs {titleOk ? CHECK_OK : CHECK_NO}">
					<span class="font-mono">{titleOk ? '✓' : '○'}</span>
					<span class="text-gray-700 dark:text-gray-200">{$i18n.t('Title present')}</span>
				</div>
			</div>

			<!-- changed files (tracked apply_patch rows, else diff-parsed) -->
			{#if fileRows.length}
				<div class="rounded-lg border border-gray-200 dark:border-gray-800 overflow-hidden">
					<div class="px-3 py-1.5 text-[10px] uppercase tracking-wide text-gray-400 border-b border-gray-100 dark:border-gray-850">
						{changes.length ? $i18n.t('Tracked edits') : $i18n.t('Changed files (from diff)')}
					</div>
					<div class="max-h-40 overflow-y-auto divide-y divide-gray-50 dark:divide-gray-900">
						{#each fileRows.slice(0, 100) as f}
							<div class="px-3 py-1 flex items-center gap-2 text-[11px]">
								<span
									class="shrink-0 w-4 text-center font-mono {f.status === 'create'
										? 'text-emerald-600 dark:text-emerald-400'
										: f.status === 'delete'
											? 'text-red-600 dark:text-red-400'
											: 'text-amber-600 dark:text-amber-400'}"
									>{f.status === 'create' ? 'A' : f.status === 'delete' ? 'D' : 'M'}</span
								>
								<span class="font-mono truncate text-gray-600 dark:text-gray-300">{f.path}</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}

			<!-- result of THIS click -->
			{#if result?.pr_url}
				<div class="rounded-lg border border-emerald-300/40 bg-emerald-50 dark:bg-emerald-950/30 px-3 py-2 text-xs">
					<a href={result.pr_url} target="_blank" rel="noopener noreferrer" class="text-emerald-700 dark:text-emerald-300 hover:underline">
						{$i18n.t('Pull request opened')}{result.pr_number ? ` #${result.pr_number}` : ''} ↗
					</a>
					{#if result.branch}
						<span class="ml-2 text-[10px] text-gray-400 font-mono">{result.branch} → {result.base}</span>
					{/if}
				</div>
			{/if}
			{#if error}
				<div class="rounded-lg border border-red-300/40 bg-red-50 dark:bg-red-950/30 px-3 py-2 text-[11px] text-red-600 dark:text-red-400">{error}</div>
			{/if}

			<!-- persisted PR history for this session -->
			{#if pulls.length}
				<div class="rounded-lg border border-gray-200 dark:border-gray-800 overflow-hidden">
					<div class="px-3 py-1.5 text-[10px] uppercase tracking-wide text-gray-400 border-b border-gray-100 dark:border-gray-850">
						{$i18n.t('Pull requests from this session')}
					</div>
					<div class="divide-y divide-gray-50 dark:divide-gray-900">
						{#each pulls as pr (pr.id)}
							<div class="px-3 py-1.5 flex items-center gap-2 text-[11px]">
								{#if pr.pr_url}
									<a href={pr.pr_url} target="_blank" rel="noopener noreferrer" class="truncate text-gray-700 dark:text-gray-200 hover:underline">
										{pr.title || pr.pr_url}{pr.pr_number ? ` #${pr.pr_number}` : ''}
									</a>
								{:else}
									<span class="truncate text-gray-700 dark:text-gray-200">{pr.title || pr.id}</span>
								{/if}
								{#if pr.head_branch}
									<span class="hidden sm:inline text-[10px] text-gray-400 font-mono truncate">{pr.head_branch} → {pr.base_branch || 'main'}</span>
								{/if}
								<span class="ml-auto shrink-0 px-1.5 py-0.5 rounded border text-[10px] {statusChip(pr.status)}">{pr.status || 'open'}</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}
		</div>

		<!-- footer: the one human gate -->
		<div class="shrink-0 flex items-center gap-2 px-4 py-3 border-t border-gray-100 dark:border-gray-850">
			<span class="text-[10px] text-gray-400">
				{#if reviewBlocked}
					{$i18n.t("Agents haven't agreed yet — override is your explicit call.")}
				{:else if ready}
					{$i18n.t('Ready — this pushes a branch and opens the PR.')}
				{:else}
					{$i18n.t('Complete the checklist to enable Create PR.')}
				{/if}
			</span>
			<button
				class="ml-auto text-xs px-3 py-1.5 rounded-lg text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 transition"
				disabled={busy}
				on:click={close}>{$i18n.t('Cancel')}</button
			>
			{#if reviewBlocked}
				<!-- explicit human bypass of the agent-review gate — sends override:true -->
				<button
					class="text-xs px-3 py-1.5 rounded-lg border border-amber-400/40 text-amber-700 dark:text-amber-300 hover:bg-amber-50 dark:hover:bg-amber-950/40 disabled:opacity-40 disabled:cursor-not-allowed transition"
					disabled={!ready || !hasGithub || busy}
					on:click={() => submit(true)}
				>
					{busy ? $i18n.t('Opening…') : $i18n.t('Override & create PR')}
				</button>
			{/if}
			<button
				class="text-xs px-3.5 py-1.5 rounded-lg bg-gray-900 text-white hover:bg-gray-800 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white disabled:opacity-40 disabled:cursor-not-allowed transition"
				disabled={!ready || !hasGithub || busy || reviewBlocked}
				on:click={() => submit(false)}
			>
				{busy ? $i18n.t('Opening…') : $i18n.t('Create PR')}
			</button>
		</div>
	</aside>
{/if}
