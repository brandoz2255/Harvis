<script lang="ts">
	import { getContext, onDestroy, onMount } from 'svelte';
	import { models } from '$lib/stores';
	import { createOpenAITextStream } from '$lib/apis/streaming';
	import {
		saveComparison,
		judgeComparison,
		getComparisons,
		type CmpResult,
		type CmpStat
	} from '$lib/apis/comparisons';
	import { benchScoresForModel } from './benchmarks';
	import { marked } from 'marked';
	import DOMPurify from 'dompurify';

	const i18n: any = getContext('i18n');

	// Dock-ready (later dock-router phase).
	export let mode: 'full' | 'dock' = 'full';

	// Compare mode: one shared prompt → each picked model answers in its own card,
	// as PLAIN chat (harvis_mode:'chat' forces the facade to skip the workspace
	// auto-detector — Compare never fans out to an OpenClaw run). The right-hand
	// Analytics panel charts the picked models' measured performance (tok/s /
	// latency / judge, this run + lifetime avg) against curated open-source
	// benchmark numbers. With >2 models the answer cards collapse to rectangles
	// (click to expand) so the analytics keeps the room.
	type Status = 'idle' | 'streaming' | 'done' | 'error' | 'stopped';
	interface Run {
		status: Status;
		text: string;
		error: string;
		startedAt: number;
		firstAt: number;
		ttftMs: number | null;
		totalMs: number | null;
		chars: number;
		tokens: number | null;
		tokensEstimated: boolean;
		tokPerSec: number | null;
		judgeScore: number | null;
	}

	let picks: string[] = ['', ''];
	let prompt = '';
	let running = false;
	let runs: (Run | undefined)[] = [];
	let controllers: (AbortController | null)[] = [];
	let runId = '';

	// On-demand LLM-as-judge.
	let judging = false;
	let judgeModel = '';
	let judgeError = '';
	$: if (!judgeModel && $models.length) judgeModel = $models[0].id;

	// Lifetime analytics (per-model aggregates across all past runs).
	let stats: CmpStat[] = [];
	const loadStats = async () => {
		stats = (await getComparisons()).stats ?? [];
	};
	onMount(loadStats);
	$: statByModel = new Map(stats.map((s) => [s.model_id, s]));

	// Card expand/collapse — auto-collapse once there are >2 models so the
	// answers condense to rectangles and the analytics panel keeps its room.
	let expandedOverride: Record<number, boolean> = {};
	$: activeCount = picks.filter(Boolean).length;
	$: autoCollapse = activeCount > 2;
	$: expandedMap = picks.map((_, i) => expandedOverride[i] ?? !autoCollapse);
	const toggleExpand = (i: number) => {
		expandedOverride = { ...expandedOverride, [i]: !(expandedOverride[i] ?? !autoCollapse) };
	};

	$: cols = picks.map((id, i) => ({
		id,
		i,
		model: $models.find((m: any) => m.id === id) as any,
		run: runs[i]
	}));

	$: hasPicks = picks.some((id) => !!id);
	$: canJudge = !!runId && !running && cols.some((c) => c.run?.status === 'done' && c.run?.text);

	// Analytics panel rows — one per picked model (live run value preferred, else
	// lifetime average), with a relative tok/s bar + benchmarks.
	$: panelRows = cols
		.filter((c) => c.id)
		.map((c) => {
			const stat = statByModel.get(c.id);
			const liveTps = c.run?.status === 'done' ? c.run.tokPerSec : null;
			return {
				id: c.id,
				name: c.model?.name || c.id,
				run: c.run,
				stat,
				tps: liveTps ?? stat?.avg_tok_per_sec ?? null,
				bench: benchScoresForModel(c.id)
			};
		});
	$: panelMaxTps = Math.max(1, ...panelRows.map((r) => r.tps ?? 0));

	const blankRun = (): Run => ({
		status: 'streaming',
		text: '',
		error: '',
		startedAt: 0,
		firstAt: 0,
		ttftMs: null,
		totalMs: null,
		chars: 0,
		tokens: null,
		tokensEstimated: false,
		tokPerSec: null,
		judgeScore: null
	});

	const addCol = () => {
		picks = [...picks, ''];
	};
	const removeCol = (i: number) => {
		picks = picks.filter((_, idx) => idx !== i);
		runs = runs.filter((_, idx) => idx !== i);
	};
	const onPickChange = (i: number) => {
		runs[i] = undefined;
		runs = runs;
	};

	const stopAll = () => {
		controllers.forEach((c) => {
			try {
				c?.abort();
			} catch (_) {
				/* noop */
			}
		});
		controllers = [];
	};
	onDestroy(stopAll);

	const finalizeRun = (run: Run) => {
		const now = Date.now();
		run.totalMs = now - run.startedAt;
		if (run.tokens == null) {
			run.tokens = Math.max(1, Math.round(run.chars / 4));
			run.tokensEstimated = true;
		}
		// Bursty (non-incremental) delivery makes firstAt ≈ done, so the post-
		// first-token window collapses and tok/s would explode — fall back to
		// total wall time when that window is too small to be real.
		const genMs = run.firstAt && now - run.firstAt > 250 ? now - run.firstAt : run.totalMs;
		run.tokPerSec = genMs > 0 ? run.tokens / (genMs / 1000) : null;
	};

	const streamColumn = async (i: number, modelId: string, p: string) => {
		const run = runs[i]!;
		run.startedAt = Date.now();
		runs = runs;
		const controller = new AbortController();
		controllers[i] = controller;
		try {
			const res = await fetch('/api/chat/completions', {
				method: 'POST',
				headers: {
					Authorization: `Bearer ${localStorage.token}`,
					'Content-Type': 'application/json'
				},
				credentials: 'include',
				signal: controller.signal,
				body: JSON.stringify({
					model: modelId,
					messages: [{ role: 'user', content: p }],
					stream: true,
					stream_options: { include_usage: true },
					harvis_mode: 'chat'
				})
			});
			if (!res.ok || !res.body) {
				let detail = `HTTP ${res.status}`;
				try {
					const j = await res.json();
					detail = j?.detail || j?.error?.message || detail;
				} catch (_) {
					/* noop */
				}
				throw new Error(detail);
			}
			const textStream = await createOpenAITextStream(res.body, false);
			for await (const update of textStream as any) {
				if (update.error) {
					throw new Error(
						typeof update.error === 'string'
							? update.error
							: update.error?.message || 'stream error'
					);
				}
				if (update.usage?.completion_tokens != null) {
					run.tokens = update.usage.completion_tokens;
					run.tokensEstimated = false;
				}
				if (update.value) {
					if (!run.firstAt) {
						run.firstAt = Date.now();
						run.ttftMs = run.firstAt - run.startedAt;
					}
					run.text += update.value;
					run.chars = run.text.length;
					runs = runs;
				}
				if (update.done) break;
			}
			finalizeRun(run);
			run.status = 'done';
		} catch (e: any) {
			if (controller.signal.aborted) {
				run.status = 'stopped';
				finalizeRun(run);
			} else {
				run.status = 'error';
				run.error = String(e?.message || e);
			}
		} finally {
			runs = runs;
		}
	};

	const persistRun = async (p: string) => {
		const results: CmpResult[] = picks
			.map((id, i) => ({ id, i, run: runs[i] }))
			.filter((x) => x.id && x.run)
			.map((x) => ({
				slot: x.i,
				model_id: x.id,
				status: x.run!.status,
				ttft_ms: x.run!.ttftMs,
				total_ms: x.run!.totalMs,
				tokens: x.run!.tokens,
				tokens_estimated: x.run!.tokensEstimated,
				tok_per_sec: x.run!.tokPerSec,
				chars: x.run!.chars,
				answer: x.run!.text
			}));
		if (results.length) {
			await saveComparison(runId, p, results);
			await loadStats();
		}
	};

	const runComparison = async () => {
		const p = (prompt || '').trim();
		if (!p || running || !hasPicks) return;
		stopAll();
		running = true;
		judgeError = '';
		expandedOverride = {};
		runId =
			typeof crypto !== 'undefined' && (crypto as any).randomUUID
				? (crypto as any).randomUUID()
				: `cmp-${Date.now()}`;
		runs = picks.map((id) => (id ? blankRun() : undefined));
		controllers = picks.map(() => null);
		const tasks = picks.map((id, i) => (id ? streamColumn(i, id, p) : Promise.resolve()));
		try {
			await Promise.allSettled(tasks);
		} finally {
			running = false;
		}
		await persistRun(p);
	};

	const stop = () => {
		stopAll();
		running = false;
		runs = runs.map((r) =>
			r && r.status === 'streaming' ? ((r.status = 'stopped'), finalizeRun(r), r) : r
		);
	};

	const streamToText = async (modelId: string, p: string): Promise<string> => {
		const res = await fetch('/api/chat/completions', {
			method: 'POST',
			headers: {
				Authorization: `Bearer ${localStorage.token}`,
				'Content-Type': 'application/json'
			},
			credentials: 'include',
			body: JSON.stringify({
				model: modelId,
				messages: [{ role: 'user', content: p }],
				stream: true,
				harvis_mode: 'chat'
			})
		});
		if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
		const ts = await createOpenAITextStream(res.body, false);
		let out = '';
		for await (const u of ts as any) {
			if (u.error)
				throw new Error(typeof u.error === 'string' ? u.error : u.error?.message || 'stream error');
			if (u.value) out += u.value;
			if (u.done) break;
		}
		return out;
	};

	const judgeAnswers = async () => {
		if (judging || running || !runId || !judgeModel) return;
		const judgeable = cols.filter((c) => c.run && c.run.status === 'done' && c.run.text);
		if (!judgeable.length) return;
		judging = true;
		judgeError = '';
		try {
			const letters = judgeable.map((_, i) => String.fromCharCode(65 + i));
			let body =
				"You are an impartial judge evaluating answers from different AI models to the SAME prompt. Rate each answer's overall quality from 1 to 10 (10 = best), considering correctness, completeness, and clarity.\n\nPROMPT:\n" +
				prompt +
				'\n\n';
			judgeable.forEach((c, i) => {
				body += `--- ANSWER ${letters[i]} (model: ${c.model?.name || c.id}) ---\n${c.run!.text}\n\n`;
			});
			body +=
				'Respond with ONLY a compact JSON object mapping each answer letter to its numeric score, e.g. {"A": 8, "B": 6}. No commentary, no code fence.';

			const content = await streamToText(judgeModel, body);
			const m = content.match(/\{[^{}]*\}/);
			if (!m) throw new Error('judge returned no JSON scores');
			const parsed = JSON.parse(m[0]);
			const scores: Record<string, number> = {};
			judgeable.forEach((c, i) => {
				const raw = parsed[letters[i]] ?? parsed[letters[i].toLowerCase()];
				const num = typeof raw === 'number' ? raw : parseFloat(raw);
				if (!isNaN(num)) {
					runs[c.i]!.judgeScore = num;
					scores[String(c.i)] = num;
				}
			});
			runs = runs;
			if (Object.keys(scores).length) {
				await judgeComparison(runId, judgeModel, scores);
				await loadStats();
			} else throw new Error('could not map judge scores to columns');
		} catch (e: any) {
			judgeError = String(e?.message || e);
			console.error('comparison judge failed', e);
		} finally {
			judging = false;
		}
	};

	const onKey = (e: KeyboardEvent) => {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			runComparison();
		}
	};

	const fmtMs = (ms: number | null) =>
		ms == null ? '—' : ms < 1000 ? `${Math.round(ms)}ms` : `${(ms / 1000).toFixed(1)}s`;
	const fmtTps = (t: number | null) =>
		t == null ? '—' : `${t >= 10 ? Math.round(t) : t.toFixed(1)}`;
	const fmtScore = (s: number | null) => (s == null ? '—' : s % 1 === 0 ? `${s}` : s.toFixed(1));
	const renderMd = (t: string) =>
		DOMPurify.sanitize(marked.parse(t || '', { breaks: true, async: false }) as string);

	const specLine = (m: any) => {
		if (!m) return '';
		const bits: string[] = [];
		if (m.details?.parameter_size) bits.push(m.details.parameter_size);
		if (m.details?.quantization_level) bits.push(m.details.quantization_level);
		if (m.size) bits.push(`${(m.size / 1e9).toFixed(1)} GB`);
		if (m.owned_by && !bits.length) bits.push(m.owned_by);
		return bits.join(' · ');
	};

	const benchChips = (b: any): { label: string; value: number }[] => {
		if (!b) return [];
		const out: { label: string; value: number }[] = [];
		if (b.mmlu != null) out.push({ label: 'MMLU', value: b.mmlu });
		if (b.humaneval != null) out.push({ label: 'HumanEval', value: b.humaneval });
		if (b.gpqa != null) out.push({ label: 'GPQA', value: b.gpqa });
		return out;
	};
</script>

<div class="w-full h-full flex flex-col">
	<!-- header -->
	<div class="flex items-center justify-between px-4 py-3 shrink-0 gap-2">
		<h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wide shrink-0">
			{$i18n.t('Model Comparison')}
		</h2>
		<div class="flex items-center gap-2 min-w-0">
			{#if canJudge}
				<select
					bind:value={judgeModel}
					title={$i18n.t('Judge model')}
					class="text-xs rounded-lg py-1 px-2 bg-gray-100 dark:bg-gray-850 outline-none max-w-[10rem] truncate"
				>
					{#each $models as m}
						<option value={m.id}>{m.name}</option>
					{/each}
				</select>
				<button
					class="text-xs px-2.5 py-1 rounded-lg bg-purple-500/10 text-purple-500 hover:bg-purple-500/20 disabled:opacity-40 transition shrink-0"
					on:click={judgeAnswers}
					disabled={judging}
					>{judging ? $i18n.t('Scoring…') : '★ ' + $i18n.t('Score answers')}</button
				>
			{/if}
			<button
				class="text-xs px-2.5 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition shrink-0"
				on:click={addCol}>+ {$i18n.t('Add model')}</button
			>
		</div>
	</div>

	{#if judgeError}
		<div class="px-4 pb-1 text-[11px] text-red-500 shrink-0">{$i18n.t('Judge')}: {judgeError}</div>
	{/if}

	<!-- body: answers (left) + analytics panel (right) -->
	<div class="flex-1 min-h-0 flex">
		<!-- answer cards -->
		<div class="flex-1 min-w-0 overflow-y-auto px-4 pb-2">
			<div class="flex flex-wrap gap-3 items-start">
				{#each cols as col (col.i)}
					<div
						class="flex flex-col flex-1 min-w-[15rem] max-w-[26rem] rounded-2xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 overflow-hidden self-start"
					>
						<!-- card header -->
						<div class="p-3 border-b border-gray-100 dark:border-gray-850 shrink-0">
							<div class="flex items-center gap-2">
								<select
									bind:value={picks[col.i]}
									on:change={() => onPickChange(col.i)}
									class="flex-1 min-w-0 rounded-lg py-2 px-3 text-sm bg-gray-50 dark:bg-gray-850 outline-none"
								>
									<option value="">{$i18n.t('Select a model')}</option>
									{#each $models as m}
										<option value={m.id}>{m.name}</option>
									{/each}
								</select>
								{#if col.run?.text}
									<button
										class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 shrink-0"
										on:click={() => toggleExpand(col.i)}
										title={expandedMap[col.i] ? $i18n.t('Collapse') : $i18n.t('Expand')}
									>
										<svg
											class="size-4 transition-transform {expandedMap[col.i] ? 'rotate-180' : ''}"
											viewBox="0 0 24 24"
											fill="none"
											stroke="currentColor"
											stroke-width="2"
											stroke-linecap="round"
											stroke-linejoin="round"><path d="M6 9l6 6 6-6" /></svg
										>
									</button>
								{/if}
								{#if picks.length > 1}
									<button
										class="text-xs text-gray-400 hover:text-red-500 shrink-0"
										on:click={() => removeCol(col.i)}
										aria-label={$i18n.t('Remove')}>✕</button
									>
								{/if}
							</div>
							{#if col.model && specLine(col.model)}
								<div class="text-[11px] text-gray-400 mt-1.5 truncate">{specLine(col.model)}</div>
							{/if}

							{#if col.run}
								<!-- metrics strip -->
								<div class="flex flex-wrap items-center gap-1.5 mt-2">
									{#if col.run.status === 'streaming'}
										<span
											class="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-blue-500/10 text-blue-500"
											><span class="size-1.5 rounded-full bg-blue-500 animate-ping"></span>{$i18n.t(
												'Streaming'
											)}</span
										>
									{:else if col.run.status === 'done'}
										<span
											class="text-[11px] px-2 py-0.5 rounded-md bg-green-500/10 text-green-600 dark:text-green-400"
											>✓</span
										>
									{:else if col.run.status === 'error'}
										<span class="text-[11px] px-2 py-0.5 rounded-md bg-red-500/10 text-red-500"
											>{$i18n.t('Error')}</span
										>
									{:else if col.run.status === 'stopped'}
										<span class="text-[11px] px-2 py-0.5 rounded-md bg-amber-500/10 text-amber-500"
											>{$i18n.t('Stopped')}</span
										>
									{/if}
									{#if col.run.judgeScore != null}
										<span
											class="text-[11px] px-2 py-0.5 rounded-md bg-purple-500/10 text-purple-500"
											title={$i18n.t('Judge score')}>★ {fmtScore(col.run.judgeScore)}</span
										>
									{/if}
									<span class="text-[11px] text-gray-400" title={$i18n.t('Generation speed')}
										>{fmtTps(col.run.tokPerSec)} tok/s</span
									>
									<span class="text-[11px] text-gray-400">·</span>
									<span class="text-[11px] text-gray-400" title={$i18n.t('Total latency')}
										>{fmtMs(col.run.totalMs)}</span
									>
								</div>
							{/if}
						</div>

						<!-- card body -->
						<div
							class="p-3 text-sm {expandedMap[col.i] ? 'overflow-y-auto max-h-[26rem]' : ''}"
						>
							{#if col.run}
								{#if col.run.status === 'error'}
									<div class="text-xs text-red-500 break-words">{col.run.error}</div>
								{:else if col.run.text}
									{#if expandedMap[col.i]}
										<div
											class="cmp-md text-gray-800 dark:text-gray-100 leading-relaxed break-words"
										>
											{@html renderMd(col.run.text)}
										</div>
									{:else}
										<button
											class="text-left text-xs text-gray-500 dark:text-gray-400 leading-relaxed"
											on:click={() => toggleExpand(col.i)}
										>
											{col.run.text.slice(0, 140)}{col.run.text.length > 140 ? '…' : ''}
											<span class="text-blue-500 whitespace-nowrap"> · {$i18n.t('View output')}</span>
										</button>
									{/if}
								{:else}
									<div class="text-xs text-gray-400">{$i18n.t('Waiting for response…')}</div>
								{/if}
							{:else if col.model}
								<div class="text-xs text-gray-400 leading-relaxed">
									{$i18n.t('Ready. Enter a prompt below and run to compare.')}
								</div>
							{:else}
								<div class="text-xs text-gray-400">{$i18n.t('Pick a model to compare.')}</div>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		</div>

		<!-- analytics panel -->
		<div
			class="w-[21rem] shrink-0 border-l border-gray-100 dark:border-gray-850 overflow-y-auto bg-gray-50/40 dark:bg-gray-900/40"
		>
			<div class="px-3 py-3">
				<div class="flex items-center justify-between mb-2">
					<h3 class="text-xs font-semibold text-gray-500 uppercase tracking-wide">
						{$i18n.t('Analytics')}
					</h3>
					<button
						class="text-[11px] text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
						on:click={loadStats}>{$i18n.t('Refresh')}</button
					>
				</div>

				{#if !panelRows.length}
					<div class="text-[11px] text-gray-400 leading-relaxed mt-4">
						{$i18n.t('Pick models and run a comparison — measured performance and benchmarks land here.')}
					</div>
				{:else}
					<div class="space-y-2">
						{#each panelRows as r (r.id)}
							<div class="rounded-xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 p-2.5">
								<div class="text-xs font-medium text-gray-800 dark:text-gray-100 truncate" title={r.id}>
									{r.name}
								</div>
								<!-- measured: tok/s bar -->
								<div class="flex items-center gap-2 mt-1.5">
									<div class="flex-1 h-1.5 rounded-full bg-gray-100 dark:bg-gray-800 overflow-hidden">
										<div
											class="h-full bg-blue-500/70 rounded-full"
											style="width: {Math.round(((r.tps ?? 0) / panelMaxTps) * 100)}%"
										></div>
									</div>
									<span class="text-[11px] text-gray-600 dark:text-gray-300 tabular-nums w-12 text-right"
										>{fmtTps(r.tps)} t/s</span
									>
								</div>
								<!-- measured: secondary stats -->
								<div class="flex items-center gap-2 mt-1 text-[11px] text-gray-400">
									{#if r.run?.status === 'done'}
										<span title={$i18n.t('This run latency')}>⏱ {fmtMs(r.run.totalMs)}</span>
									{/if}
									{#if r.run?.judgeScore != null}
										<span class="text-purple-500" title={$i18n.t('Judge score')}>★ {fmtScore(r.run.judgeScore)}</span>
									{:else if r.stat?.avg_judge_score != null}
										<span class="text-purple-500/70" title={$i18n.t('Average judge score')}>★ {fmtScore(r.stat.avg_judge_score)}</span>
									{/if}
									{#if r.stat?.runs}
										<span title={$i18n.t('Lifetime average over N runs')}
											>{fmtTps(r.stat.avg_tok_per_sec)} t/s avg · {r.stat.runs}
											{r.stat.runs === 1 ? $i18n.t('run') : $i18n.t('runs')}</span
										>
									{/if}
								</div>
								<!-- theoretical: benchmark chips -->
								<div class="flex flex-wrap items-center gap-1 mt-1.5">
									{#each benchChips(r.bench) as b}
										<span
											class="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-500"
											title={$i18n.t('Published open-source benchmark')}>{b.label} {b.value}</span
										>
									{:else}
										<span class="text-[10px] text-gray-300 dark:text-gray-700"
											>{$i18n.t('no benchmark data')}</span
										>
									{/each}
								</div>
							</div>
						{/each}
					</div>
					<div class="mt-3 text-[10px] text-gray-400 leading-relaxed">
						<span class="text-blue-400">{$i18n.t('Blue')}</span> = {$i18n.t('measured here')} ·
						<span class="text-purple-400">{$i18n.t('purple')}</span> = {$i18n.t(
							'published benchmarks (curated; "no data" until added).'
						)}
					</div>
				{/if}
			</div>
		</div>
	</div>

	<!-- composer -->
	<div class="shrink-0 border-t border-gray-100 dark:border-gray-850 p-3">
		<div
			class="flex items-end gap-2 rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-850 px-3 py-2"
		>
			<textarea
				bind:value={prompt}
				on:keydown={onKey}
				rows="1"
				placeholder={$i18n.t('Send the same prompt to every model…')}
				class="flex-1 bg-transparent outline-none resize-none text-sm max-h-32 py-1"
			></textarea>
			{#if running}
				<button
					class="px-3 py-1.5 rounded-xl text-sm bg-red-500/10 text-red-500 hover:bg-red-500/20 transition shrink-0"
					on:click={stop}>{$i18n.t('Stop')}</button
				>
			{:else}
				<button
					class="px-3 py-1.5 rounded-xl text-sm bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-40 disabled:cursor-not-allowed transition shrink-0"
					disabled={!prompt.trim() || !hasPicks}
					on:click={runComparison}>{$i18n.t('Run')}</button
				>
			{/if}
		</div>
	</div>
</div>

<style>
	.cmp-md :global(pre) {
		background: rgba(127, 127, 127, 0.12);
		padding: 0.6rem 0.75rem;
		border-radius: 0.5rem;
		overflow-x: auto;
		font-size: 0.78rem;
		margin: 0 0 0.5rem;
	}
	.cmp-md :global(code) {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.82em;
	}
	.cmp-md :global(p) {
		margin: 0 0 0.5rem;
	}
	.cmp-md :global(ul),
	.cmp-md :global(ol) {
		margin: 0 0 0.5rem 1.1rem;
		list-style: revert;
	}
	.cmp-md :global(h1),
	.cmp-md :global(h2),
	.cmp-md :global(h3) {
		font-weight: 600;
		margin: 0.6rem 0 0.3rem;
	}
	.cmp-md :global(a) {
		color: rgb(59, 130, 246);
		text-decoration: underline;
	}
</style>
