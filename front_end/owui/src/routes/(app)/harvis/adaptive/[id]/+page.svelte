<script lang="ts">
	// Adaptive Space (marathon P8) — the SpaceView: renders the manifest — steps
	// (approval gates enforced server-side, confirmed here), to-do, notes.
	// Scaffold/preview/guide only: nothing on this page executes anything.
	import { getContext, onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { WEBUI_NAME } from '$lib/stores';

	const i18n: any = getContext('i18n');

	$: spaceId = $page.params.id;

	let space: any = null;
	let loading = true;
	let err = '';
	let notesDraft = '';
	let notesSaved = true;
	let newTodo = '';
	let gateStep: any = null; // step awaiting the user's explicit approval confirm
	let busy = false;

	const hdrs = () => ({
		Authorization: `Bearer ${localStorage.token}`,
		'Content-Type': 'application/json'
	});

	const load = async () => {
		loading = true;
		err = '';
		try {
			const r = await fetch(`/api/adaptive/spaces/${spaceId}`, {
				headers: hdrs(),
				credentials: 'include'
			});
			if (!r.ok) throw new Error((await r.json())?.detail || 'Load failed');
			space = await r.json();
			notesDraft = space?.manifest?.notes ?? '';
			notesSaved = true;
		} catch (e: any) {
			err = e?.message || 'Load failed';
		}
		loading = false;
	};
	onMount(load);

	const post = async (path: string, body: any) => {
		busy = true;
		try {
			const r = await fetch(`/api/adaptive/spaces/${spaceId}${path}`, {
				method: 'POST',
				headers: hdrs(),
				credentials: 'include',
				body: JSON.stringify(body)
			});
			if (!r.ok) throw new Error((await r.json())?.detail || 'Request failed');
			const data = await r.json();
			if (data.manifest) space = { ...space, manifest: data.manifest };
			else if (data.todo) space = { ...space, manifest: { ...space.manifest, todo: data.todo } };
			return data;
		} catch (e: any) {
			err = e?.message || 'Request failed';
			setTimeout(() => (err = ''), 4000);
		} finally {
			busy = false;
		}
	};

	const completeStep = (s: any) => {
		if (s.gate === 'approval') {
			gateStep = s; // explicit confirm modal — the server rejects without approved:true
			return;
		}
		post('/step', { step_id: s.id, status: 'done' });
	};
	const confirmGate = async () => {
		if (!gateStep) return;
		await post('/step', { step_id: gateStep.id, status: 'done', approved: true });
		gateStep = null;
	};
	const reopenStep = (s: any) => post('/step', { step_id: s.id, status: 'active' });

	const toggleTodo = (i: number, done: boolean) => post('/todo', { index: i, done });

	// Execute-class steps run the MOCK adapter — records "no real action taken".
	const isExecStep = (s: any) => ['execute', 'export'].includes(s?.id);
	const runMock = async (s: any) => {
		await post('/mock-execute', { stage: s.id });
	};
	const addTodo = async () => {
		const t = newTodo.trim();
		if (!t) return;
		newTodo = '';
		await post('/todo', { add: t });
	};

	let notesTimer: ReturnType<typeof setTimeout> | null = null;
	const onNotes = () => {
		notesSaved = false;
		if (notesTimer) clearTimeout(notesTimer);
		notesTimer = setTimeout(async () => {
			await post('/notes', { text: notesDraft });
			notesSaved = true;
		}, 800);
	};

	const setSpaceStatus = async (status: string) => {
		await post('/status', { status });
		space = { ...space, status };
	};

	const stepDot = (s: any) =>
		s.status === 'done'
			? 'bg-emerald-500'
			: s.status === 'active'
				? 'bg-blue-500 animate-pulse'
				: s.status === 'blocked'
					? 'bg-red-500'
					: 'bg-gray-300 dark:bg-gray-600';

	$: manifest = space?.manifest ?? {};
	$: steps = manifest.steps ?? [];
	$: todo = manifest.todo ?? [];
	$: linkedRuns = manifest.linked_runs ?? [];
	$: doneSteps = steps.filter((s: any) => s.status === 'done').length;

	const fmtAt = (ts?: string) => {
		if (!ts) return '';
		try {
			return new Date(ts).toLocaleString(undefined, {
				month: 'short',
				day: 'numeric',
				hour: '2-digit',
				minute: '2-digit'
			});
		} catch {
			return ts;
		}
	};
</script>

<svelte:head>
	<title>{space?.title || $i18n.t('Space')} • {$WEBUI_NAME}</title>
</svelte:head>

<div class="w-full h-full overflow-y-auto">
	<div class="max-w-5xl mx-auto px-5 py-5 space-y-4">
		<!-- header -->
		<header class="flex items-start gap-3">
			<div class="min-w-0 flex-1">
				<button
					class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
					on:click={() => goto('/harvis/adaptive')}>← {$i18n.t('Adaptive Space')}</button
				>
				<h1 class="text-xl font-semibold text-gray-800 dark:text-gray-100 truncate mt-1">
					{space?.title || $i18n.t('Space')}
				</h1>
				{#if space?.intent}
					<p class="text-xs text-gray-500 mt-0.5 line-clamp-2">{space.intent}</p>
				{/if}
			</div>
			<div class="shrink-0 flex items-center gap-2 pt-5">
				<span class="text-[11px] text-gray-400 tabular-nums"
					>{doneSteps}/{steps.length} {$i18n.t('steps')}</span
				>
				{#if space?.status === 'active'}
					<button
						class="text-xs px-2.5 py-1 rounded-lg border border-gray-200 dark:border-gray-800 text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 transition"
						on:click={() => setSpaceStatus('done')}>{$i18n.t('Mark done')}</button
					>
				{:else}
					<span
						class="text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full {space?.status ===
						'done'
							? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
							: 'bg-gray-200 dark:bg-gray-800 text-gray-500'}">{space?.status}</span
					>
					<button
						class="text-xs px-2.5 py-1 rounded-lg border border-gray-200 dark:border-gray-800 text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 transition"
						on:click={() => setSpaceStatus('active')}>{$i18n.t('Reopen')}</button
					>
				{/if}
			</div>
		</header>

		{#if err}<div class="text-xs text-red-500">{err}</div>{/if}

		{#if loading}
			<div class="text-xs text-gray-500 py-6">{$i18n.t('Loading…')}</div>
		{:else if space}
			<div class="grid grid-cols-1 lg:grid-cols-5 gap-3">
				<!-- STEPS (checklist panel) -->
				<section
					class="lg:col-span-3 rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4"
				>
					<div class="text-sm font-medium text-gray-800 dark:text-gray-100 mb-3">
						{$i18n.t('Steps')}
					</div>
					<ol class="space-y-1.5">
						{#each steps as s (s.id)}
							<li
								class="flex items-start gap-2.5 rounded-xl px-2 py-2 {s.status === 'active'
									? 'bg-blue-500/5 border border-blue-500/15'
									: 'border border-transparent'}"
							>
								<span class="mt-1.5 size-2 rounded-full shrink-0 {stepDot(s)}"></span>
								<div class="min-w-0 flex-1">
									<div class="flex items-center gap-2">
										<span
											class="text-sm {s.status === 'done'
												? 'text-gray-400 line-through'
												: 'text-gray-800 dark:text-gray-100'}">{s.title}</span
										>
										{#if s.gate === 'approval'}
											<span
												class="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-600 dark:text-amber-400"
												title={$i18n.t('Requires your explicit approval')}
												>✋ {$i18n.t('gate')}</span
											>
										{/if}
									</div>
									{#if s.detail}
										<div class="text-[11px] text-gray-500 leading-snug mt-0.5">{s.detail}</div>
									{/if}
								</div>
								<div class="shrink-0 pt-0.5 flex items-center gap-1.5">
									{#if s.status === 'done'}
										<button
											class="text-[11px] text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
											disabled={busy}
											on:click={() => reopenStep(s)}>{$i18n.t('Reopen')}</button
										>
									{:else}
										{#if isExecStep(s)}
											<button
												class="text-[11px] px-2 py-1 rounded-lg border border-blue-500/30 text-blue-600 dark:text-blue-400 hover:bg-blue-500/10 transition disabled:opacity-50"
												disabled={busy}
												title={$i18n.t('Runs the mock adapter — no real action is taken')}
												on:click={() => runMock(s)}>{$i18n.t('Run (mock)')}</button
											>
										{/if}
										<button
											class="text-[11px] px-2 py-1 rounded-lg transition disabled:opacity-50 {s.gate ===
											'approval'
												? 'border border-amber-500/30 text-amber-600 dark:text-amber-400 hover:bg-amber-500/10'
												: 'border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850'}"
											disabled={busy}
											on:click={() => completeStep(s)}
											>{s.gate === 'approval' ? $i18n.t('Approve…') : $i18n.t('Done')}</button
										>
									{/if}
								</div>
							</li>
						{/each}
					</ol>
				</section>

				<!-- RIGHT: to-do + notes -->
				<div class="lg:col-span-2 space-y-3">
					<section
						class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4"
					>
						<div class="text-sm font-medium text-gray-800 dark:text-gray-100 mb-2">
							{$i18n.t('To-do — the parts only you can do')}
						</div>
						{#if !todo.length}
							<div class="text-[11px] text-gray-400">{$i18n.t('Nothing yet.')}</div>
						{/if}
						<ul class="space-y-1">
							{#each todo as t, i}
								<li class="flex items-start gap-2">
									<input
										type="checkbox"
										class="mt-0.5 accent-blue-600"
										checked={t.done}
										disabled={busy}
										on:change={(e) => toggleTodo(i, (e.target as HTMLInputElement).checked)}
									/>
									<span
										class="text-xs leading-snug {t.done
											? 'text-gray-400 line-through'
											: 'text-gray-700 dark:text-gray-200'}">{t.text}</span
									>
								</li>
							{/each}
						</ul>
						<div class="flex items-center gap-1.5 mt-2">
							<input
								class="flex-1 text-xs bg-transparent border border-gray-200 dark:border-gray-800 rounded-lg px-2 py-1 outline-none focus:border-blue-500/50 text-gray-800 dark:text-gray-100 placeholder:text-gray-400"
								placeholder={$i18n.t('Add an item…')}
								bind:value={newTodo}
								on:keydown={(e) => e.key === 'Enter' && addTodo()}
							/>
							<button
								class="text-[11px] px-2 py-1 rounded-lg border border-gray-200 dark:border-gray-800 text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 transition"
								disabled={busy || !newTodo.trim()}
								on:click={addTodo}>{$i18n.t('Add')}</button
							>
						</div>
					</section>

					<!-- Activity / output — every (mock) execution and audit entry lands here -->
					<section
						class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4"
					>
						<div class="text-sm font-medium text-gray-800 dark:text-gray-100 mb-2">
							{$i18n.t('Activity & output')}
						</div>
						{#if !linkedRuns.length}
							<div class="text-[11px] text-gray-400">
								{$i18n.t('Nothing executed yet — runs and exports will appear here.')}
							</div>
						{:else}
							<ol class="space-y-1.5">
								{#each linkedRuns as r, i (i)}
									<li class="flex items-start gap-2">
										<span
											class="mt-1 size-1.5 rounded-full shrink-0 {r.mock
												? 'bg-blue-400'
												: 'bg-emerald-500'}"
										></span>
										<div class="min-w-0 flex-1">
											<div class="flex items-baseline gap-2">
												<span class="text-xs text-gray-700 dark:text-gray-200 truncate"
													>{r.stage || $i18n.t('run')}{#if r.mock}
														<span class="text-[10px] text-blue-500/80">· {$i18n.t('mock')}</span
														>{/if}</span
												>
												<span class="ml-auto text-[10px] text-gray-400 tabular-nums shrink-0"
													>{fmtAt(r.at)}</span
												>
											</div>
											{#if r.message}
												<div class="text-[11px] text-gray-500 leading-snug">{r.message}</div>
											{/if}
										</div>
									</li>
								{/each}
							</ol>
						{/if}
					</section>

					<section
						class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4"
					>
						<div class="flex items-center gap-2 mb-2">
							<span class="text-sm font-medium text-gray-800 dark:text-gray-100"
								>{$i18n.t('Notes')}</span
							>
							<span class="ml-auto text-[10px] text-gray-400"
								>{notesSaved ? $i18n.t('saved') : $i18n.t('saving…')}</span
							>
						</div>
						<textarea
							class="w-full min-h-40 text-xs bg-transparent border border-gray-200 dark:border-gray-800 rounded-xl px-2.5 py-2 outline-none focus:border-blue-500/50 resize-y text-gray-800 dark:text-gray-100 placeholder:text-gray-400 leading-relaxed"
							placeholder={$i18n.t('Plan, findings, decisions…')}
							bind:value={notesDraft}
							on:input={onNotes}
						></textarea>
					</section>
				</div>
			</div>
		{/if}
	</div>
</div>

<!-- Approval-gate confirm (server also enforces approved:true) -->
{#if gateStep}
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
		<div
			class="w-full max-w-md rounded-2xl bg-white dark:bg-gray-900 border border-amber-300 dark:border-amber-500/40 shadow-xl p-4 space-y-3"
		>
			<div class="flex items-center gap-2">
				<span class="text-lg">✋</span>
				<h3 class="text-sm font-semibold text-gray-800 dark:text-gray-100">
					{$i18n.t('Approve this step?')}
				</h3>
			</div>
			<div class="text-xs text-gray-600 dark:text-gray-300">
				<div class="font-medium">{gateStep.title}</div>
				{#if gateStep.detail}<div class="mt-1 text-gray-500">{gateStep.detail}</div>{/if}
			</div>
			<p class="text-[11px] text-amber-600 dark:text-amber-400">
				{$i18n.t('This step is a human gate — approving it is recorded in the space’s audit trail.')}
			</p>
			<div class="flex items-center justify-end gap-2">
				<button
					class="text-xs px-3 py-1.5 rounded-lg text-gray-500 hover:text-gray-700 dark:hover:text-gray-200"
					on:click={() => (gateStep = null)}>{$i18n.t('Cancel')}</button
				>
				<button
					class="text-xs px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white transition"
					disabled={busy}
					on:click={confirmGate}>{$i18n.t('Approve')}</button
				>
			</div>
		</div>
	</div>
{/if}
