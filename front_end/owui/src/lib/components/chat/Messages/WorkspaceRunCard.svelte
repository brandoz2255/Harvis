<script lang="ts">
	import { onMount, onDestroy, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import {
		showControls,
		workspaceControlsTab,
		dockedRunId,
		models,
		workspaceRunMetrics,
		workspaceRunAnswers
	} from '$lib/stores';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import {
		createWorkspaceStream,
		WORKSPACE_TERMINAL,
		type WorkspaceEvent
	} from '$lib/apis/streaming/workspace-stream';
	import Markdown from './Markdown.svelte';
	import HarvisClawMascot from '$lib/components/common/HarvisClawMascot.svelte';
	import BrandGlyph from '$lib/integrations/BrandGlyph.svelte';
	import RunFileCards from './RunFileCards.svelte';
	import WorkflowInspector from '$lib/agent-studio/WorkflowInspector.svelte';
	import {
		buildRunActivity,
		projectTerminalRuns
	} from '$lib/agent-studio/runEventProjection';
	import RunActivitySummary from './RunActivitySummary.svelte';
	import TerminalRunCard from './TerminalRunCard.svelte';
	import { getRunArtifacts } from '$lib/apis/agent-runs';
	import { saveRunAsSkill } from '$lib/apis/skills';
	import { toast } from 'svelte-sonner';
	import { trailingText } from '$lib/utils/trailingText';

	const i18n: any = getContext('i18n');

	// Inspector overview overlay — pops in-place over the chat so the user can browse
	// each agent's posts/responses without navigating away to the full run page.
	let showInspector = false;
	const onInspectorKey = (e: KeyboardEvent) => {
		if (e.key === 'Escape' && showInspector) showInspector = false;
	};
	// Portal the overlay to <body> — the chat message column is a transformed/clipped
	// ancestor, so a `fixed inset-0` nested inside it is scoped + clipped (the inspector's
	// top tab bar gets cut off). Re-parenting to body makes `fixed` span the real viewport.
	const portal = (node: HTMLElement) => {
		document.body.appendChild(node);
		return {
			destroy() {
				if (node.parentNode) node.parentNode.removeChild(node);
			}
		};
	};

	// Props come from the marked `<details type="workspace_run" …>` token.
	export let id = '';
	export let attributes: Record<string, string> = {};
	export let className = 'w-full';

	$: workspaceId = attributes?.workspaceid ?? '';
	$: taskLabel = attributes?.tasklabel ?? 'Workspace task';
	// Engine chip: the marker's engine hint (e.g. "Kimi") shows the instant the card
	// pops; the stream-parsed `executor` refines it once the run connects (and is the
	// only thing that can report a mid-run fallback, e.g. Kimi → local with no key).
	$: engineLabel = executor || (attributes?.engine ?? '');
	// Brand mark for the engine actually running this task. Keyed off the label the
	// backend resolved from the picked model, so the glyph tracks the real lane instead
	// of being a fixed OpenClaw mark. Unknown engines fall back to the generic pack box.
	const ENGINE_BRAND: Record<string, string> = {
		openclaw: 'openclaw',
		kimi: 'kimi',
		claude: 'claude',
		'claude code': 'claude',
		// Kimi Code runs IN the Claude Code sidecar but the brand shown is whose model answered.
		'kimi code': 'kimi',
		'nvidia kimi': 'kimi',
		'cloud ollama': 'ollama',
		local: 'ollama',
		'local model': 'ollama',
		hermes: 'hermes',
		'hermes agent': 'hermes',
		orchestrator: 'harvis',
		codex: 'openai',
		'gpt-oss': 'openai'
	};
	$: engineBrand = ENGINE_BRAND[(engineLabel || '').trim().toLowerCase()] ?? 'pack';
	// Launch-mode chip ("Auto" / "Agent" / "Orchestrate") — set by the bridge marker.
	$: launchMode = attributes?.launchmode ?? '';
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
	let toolCount = 0;
	let summary = '';
	let analysis = ''; // Build Result Narrator: full written analysis (Build-like runs)
	let errorMessage = '';
	let fixHint = '';
	let elapsed = 0;
	// Orchestrated completion moment: one entry per sub-agent, collected from its
	// agent_end (label + its OWN finish() summary + ok + runtime). STITCHED, never
	// model-generated. changedFiles drives the inline artifact.
	let agents: { label: string; summary: string; ok: boolean; durationMs: number }[] = [];
	let changedFiles: string[] = [];
	// Token accounting. The runner reports these after every model call (a `usage`
	// event) and again on agent_end, so the meter moves while the run is going instead
	// of appearing only once it is over.
	let usage: {
		prompt: number;
		completion: number;
		total: number;
		contextWindow: number;
		durationMs: number;
		model: string;
	} | null = null;

	let executor = ''; // "OpenClaw" — proves who's actually executing the task
	let execModel = ''; // the model behind it
	let liveFile: { path: string; content: string; lang: string } | null = null;

	const extLang = (path: string) => {
		const ext = (path.split('.').pop() || '').toLowerCase();
		const map: Record<string, string> = {
			py: 'python',
			js: 'javascript',
			ts: 'typescript',
			sh: 'bash',
			md: 'markdown',
			html: 'html',
			css: 'css',
			json: 'json'
		};
		return map[ext] || ext || 'text';
	};

	// The first five names are the Claude Code CLI's. The last three are Harvis's OWN
	// workspace tools — and their absence here is why a run on the Harvis agent lane
	// (every local model and every free cloud provider) wrote a real file and showed
	// the user nothing: the preview was watching for tool names that lane never emits.
	const _WRITE_TOOLS = [
		'write',
		'file_write',
		'edit',
		'multiedit',
		'notebookedit',
		'edit_file',
		'str_replace',
		'apply_patch'
	];

	const maybeLiveFile = (tool?: string, args?: unknown) => {
		const name = (tool || '').toLowerCase();
		if (!_WRITE_TOOLS.includes(name)) return;
		const a = args && typeof args === 'object' ? (args as Record<string, unknown>) : {};
		const path = String(a.file_path || a.path || a.file || '').trim();
		// `new_str` is str_replace/apply_patch's replacement text; the rest are the
		// whole-file spellings.
		const content = String(a.content || a.new_string || a.new_str || a.contents || '');
		if (!path || !content) return;
		liveFile = { path, content, lang: extLang(path) };
	};

	const takeUsage = (evt: any) => {
		if (!(evt?.prompt_tokens || evt?.completion_tokens || evt?.total_tokens)) return;
		const prompt = Number(evt.prompt_tokens) || 0;
		const completion = Number(evt.completion_tokens) || 0;
		usage = {
			prompt,
			completion,
			total: Number(evt.total_tokens) || prompt + completion,
			contextWindow: Number(evt.context_window) || 0,
			durationMs: Number(evt.duration_ms) || 0,
			model: String(evt.model || usage?.model || '')
		};
	};

	// ── Inline activity + terminal projection ──
	// rawEvents = the unfolded event stream the projectors read (pure → reload
	// replay reconstructs the same final timeline).
	let rawEvents: WorkspaceEvent[] = [];
	let lastEventAt = Date.now();
	let nowTick = Date.now();
	$: terminalRuns = projectTerminalRuns(rawEvents, workspaceId || id || 'workspace');
	$: runActivity = buildRunActivity(rawEvents, phase, workspaceId || id || 'workspace');

	// Terminal output can arrive in very small chunks. Fold it into the view at a
	// bounded cadence instead of invalidating the whole chat tree for every fragment.
	const TERMINAL_FLUSH_MS = 75;
	let pendingTerminalEvents: WorkspaceEvent[] = [];
	let terminalFlushTimer: ReturnType<typeof setTimeout> | null = null;

	const flushTerminalEvents = () => {
		if (terminalFlushTimer) {
			clearTimeout(terminalFlushTimer);
			terminalFlushTimer = null;
		}
		if (!pendingTerminalEvents.length) return;
		rawEvents = [...rawEvents, ...pendingTerminalEvents];
		pendingTerminalEvents = [];
	};

	const recordEvent = (evt: WorkspaceEvent) => {
		if (evt.type === 'terminal_output') {
			pendingTerminalEvents.push(evt);
			if (!terminalFlushTimer) {
				terminalFlushTimer = setTimeout(flushTerminalEvents, TERMINAL_FLUSH_MS);
			}
			return;
		}
		// Preserve event order: output queued before a result must paint first.
		flushTerminalEvents();
		rawEvents = [...rawEvents, evt];
	};

	let controller: AbortController | null = null;
	let timer: ReturnType<typeof setInterval> | null = null;
	// Persist the run's start so the elapsed timer stays consistent when the card
	// remounts (you click off the running workspace and come back).
	const _startKey = `harvis.ws-start.${attributes?.workspaceid ?? ''}`;
	let startedAt = (() => {
		try {
			const s = parseInt(localStorage.getItem(_startKey) || '');
			if (s) return s;
		} catch (e) {
			/* ignore */
		}
		const now = Date.now();
		try {
			localStorage.setItem(_startKey, String(now));
		} catch (e) {
			/* ignore */
		}
		return now;
	})();

	$: running = phase === 'connecting' || phase === 'thinking' || phase === 'executing';
	$: stalled = running && nowTick - lastEventAt > 20000;
	// Orchestrated runs are the ones whose sub-agents emit a parent_run_id-tagged
	// agent_end → that's the gate for the rich completion block (single-agent runs
	// never populate `agents`, so they keep the plain summary path).
	$: isOrchestrated = agents.length > 0;
	// An agent's finish() summary and the Build Result Narrator's analysis are often the
	// same sentence. Showing both prints the answer twice, which reads as two different
	// answers you have to reconcile — the same trap the duplicate token rows fell into.
	const _norm = (s: string) => (s ?? '').replace(/\s+/g, ' ').trim().toLowerCase();
	$: _narrativeNorm = _norm(narrative);
	$: agentPosts = agents.filter((a) => {
		const s = _norm(a.summary);
		if (!s || s === _narrativeNorm) return false;
		// Equality alone was not enough: the Build Result Narrator EMBEDS the agent's
		// summary inside its own "**What I did**" section rather than repeating it
		// verbatim, so the two strings are never equal — they are nested — and the
		// whole answer rendered twice, once under "Harvis Agent" and once below it.
		// The length floor keeps a one-word summary ("Done.") from matching by accident.
		return !(s.length >= 24 && _narrativeNorm.includes(s));
	});
	// Live wall-clock (elapsed); on a reloaded finished run elapsed is 0, so fall
	// back to the longest sub-agent runtime (replay-safe, from agent_end).
	$: doneDuration = elapsed > 0 ? elapsed : Math.max(0, ...agents.map((a) => a.durationMs));

	// The window the model ACTUALLY has. The runner fills context_window from
	// HARVIS_OLLAMA_NUM_CTX, which is right for a local tag and badly wrong for a cloud
	// model — it reported 24,576 for a Gemini model with a million-token window, so the
	// occupancy figure was off by a factor of forty. The catalogue is already loaded for
	// the model picker, so prefer its number and keep the run's own as the fallback.
	$: realContextWindow = (() => {
		const fromCatalog = Number(
			($models ?? []).find((m: any) => m?.id === usage?.model)?.info?.meta?.context_length || 0
		);
		return fromCatalog || usage?.contextWindow || 0;
	})();

	const compact = (n: number) =>
		n >= 1_000_000
			? `${(n / 1_000_000).toFixed(n < 10_000_000 ? 1 : 0)}M`
			: n >= 1000
				? `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}k`
				: String(n);

	// Throughput is completion tokens over the run's wall clock. That includes tool time
	// and the model's thinking, which is exactly what the user waited through — dividing
	// by generation time alone would quote a number nobody experienced.
	$: tokensPerSecond =
		usage && usage.durationMs > 0 ? (usage.completion / (usage.durationMs / 1000)) : 0;
	$: contextPct =
		usage && realContextWindow > 0
			? Math.min(100, (usage.prompt / realContextWindow) * 100)
			: 0;

	// Hand the run's numbers to the assistant message that hosts this card. Its own
	// chat stream closed seconds after the run started and carried no usage at all,
	// which is why the footer under a finished workspace run showed dashes.
	$: if (workspaceId && usage) {
		const snapshot = {
			context_tokens: { value: usage.prompt, quality: 'confirmed', source: 'provider', scope: 'model_request' },
			output_tokens: { value: usage.completion, quality: 'confirmed', source: 'provider', scope: 'run' },
			...(usage.durationMs > 0
				? {
						wall_ms: { value: usage.durationMs, quality: 'measured', source: 'harvis' },
						// Throughput over the whole run, tool time included — the same number
						// this card shows, so the two never disagree.
						generation_ms: { value: usage.durationMs, quality: 'measured', source: 'harvis' }
					}
				: {})
		};
		workspaceRunMetrics.update((m) => ({ ...m, [workspaceId]: snapshot }));
	}

	// A run this tab watched live gets typed out; a run being replayed from the event
	// log on page load already happened, so it shows whole.
	let sawRunning = false;
	$: if (running) sawRunning = true;

	// The written result and the file the agent is writing both arrive in whole chunks.
	// Trailing them is what makes the card read as something being written rather than
	// something being pasted.
	const typedNarrative = trailingText();
	const typedFile = trailingText(70);
	$: narrative = analysis || summary || '';
	$: typedNarrative.feed(narrative, true, !sawRunning);
	$: typedFile.feed(liveFile?.content ?? '', !running, !sawRunning);
	onDestroy(() => {
		typedNarrative.stop();
		typedFile.stop();
	});

	const fmt = (ms: number) => {
		const s = Math.floor(ms / 1000);
		return s < 60 ? `${s}s` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
	};

	// Parse executor/model from system logs without exposing internal reasoning or
	// duplicating tool output (the terminal cards consume terminal_output directly).
	const noteLog = (msg: string) => {
		// A lane can fall back mid-run (e.g. the Kimi lane with no Moonshot key drops to
		// local Ollama). The marker chip still says "Kimi" at that point, so correct it —
		// the chip must name what's ACTUALLY executing, not what was dispatched.
		if (/falling back to local/i.test(msg)) {
			executor = 'Local';
			return;
		}
		if (/Connected to OpenClaw gateway/i.test(msg)) {
			executor = 'OpenClaw'; // shown as the chip — verifies who's running it
			return;
		}
		const lm = msg.match(/(?:local model|Auto-selected[^:]*model):\s*(.+)/i);
		if (lm) {
			if (!executor) executor = 'local model';
			execModel = lm[1].trim();
			return;
		}
		// Public activity is derived from typed events below. Raw log narration can
		// contain private model reasoning, so it is intentionally not rendered.
	};

	const handle = (evt: WorkspaceEvent) => {
		// Feed the progress timeline (every event, incl. replayed ones on reload).
		recordEvent(evt);
		lastEventAt = Date.now();
		if (evt.model) execModel = evt.model;
		switch (evt.type) {
			case 'agent_start':
				if (phase === 'connecting' || phase === 'thinking') phase = 'thinking';
				break;
			case 'token': {
				if (phase === 'connecting') phase = 'thinking';
				break;
			}
			case 'log':
				if (evt.message) noteLog(String(evt.message));
				break;
			case 'tool_call':
				phase = 'executing';
				toolCount += 1;
				maybeLiveFile(evt.tool, evt.args);
				break;
			case 'tool_result':
				break;
			case 'stream_end':
				if (running) {
					phase = 'error';
					errorMessage = 'Activity stream ended before the workspace reported completion.';
					fixHint = 'Reconnect to restore the persisted run timeline.';
					// Close any queued/running projected commands instead of leaving
					// terminal cards permanently active after the SSE sentinel.
					recordEvent({ type: 'error', message: errorMessage });
				}
				break;
			case 'usage':
				// Mid-run token report, one per model call. Same fields as agent_end.
				takeUsage(evt);
				break;
			case 'agent_end': {
				// Only orchestrated sub-agents (the native runner) carry parent_run_id
				// AND their own finish() summary; OpenClaw's root agent_end has neither,
				// so single-agent runs fall through to the plain summary path.
				// Read usage before the parent_run_id gate below — a single-agent run is
				// still a sub-agent, and its numbers are the run's numbers.
				takeUsage(evt);
				if (!evt.parent_run_id) break;
				agents = [
					...agents,
					{
						label: evt.agent_label || evt.label || $i18n.t('Agent'),
						summary: (evt.summary || 'Done.').trim(),
						ok: evt.success !== false,
						durationMs: Number(evt.duration_ms) || 0
					}
				];
				break;
			}
			case 'done':
				phase = 'done';
				summary = evt.summary ?? '';
				// Build Result Narrator: the full written analysis (Build-like runs). When present
				// it IS the assistant message in this chat card. Reload-safe — the persisted done
				// event (saved after enrichment) carries it on stream replay.
				analysis = (evt as any).analysis_md ?? '';
				// Publish it for Chat.svelte to fold into the assistant message. Until
				// this line the answer lived only in the replayed event stream: visible
				// on screen, invisible to the next turn's prompt, which is how a chat
				// could research a topic in a run card and then deny knowing it.
				{
					const answer = (analysis || summary || '').trim();
					if (answer)
						workspaceRunAnswers.update((m) => ({
							...m,
							[workspaceId]: { text: answer, label: taskLabel }
						}));
				}
				if (Array.isArray(evt.changed_files)) changedFiles = evt.changed_files;
				// The artifact now renders inline in this card's completion block, so we
				// no longer force-open the dock Artifacts tab on finish (it was intrusive
				// and raced the dock state). Click "View" to dock the run.
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
				recordEvent({ type: 'error', message: errorMessage });
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
		// Instant feedback: stop listening locally + flip the card to cancelled
		// right away, THEN tell the backend to abort the agent + model server-side.
		controller?.abort();
		if (running) {
			phase = 'cancelled';
			recordEvent({ type: 'cancelled' });
		}
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

	// Pop the inspector overview over the chat (agents + their posts/responses).
	const openStudio = () => (showInspector = true);
	// Dock THIS run's live workspace (Processes / Map / Changes) into the Overview
	// tab of the right-rail pane. Resize the pane to taste.
	const dockRun = () => {
		dockedRunId.set(workspaceId);
		workspaceControlsTab.set('overview');
		showControls.set(true);
	};

	// "Preview" — open the run's rendered output (HTML/MD/SVG) in the Artifacts dock so the
	// user can SEE what the agents built, not just read the code/diffs. Only offered when the
	// run actually produced a renderable file.
	let hasPreview = false;
	let _checkedPreview = false;
	let _wasRunning = false;
	// Renderable OUTPUT types worth auto-surfacing — NOT source code (.py/.ts/.js etc.).
	const _PREVIEWABLE = /\.(html?|pdf|png|jpe?g|gif|webp|svg|markdown|md|csv)$/i;
	// Track whether THIS card saw the run live (so we don't auto-pop historical runs on chat load).
	$: if (running) _wasRunning = true;
	const checkPreview = async () => {
		try {
			const arts = await getRunArtifacts(workspaceId);
			hasPreview = (arts ?? []).some(
				(a) => a.artifact_type === 'file' && _PREVIEWABLE.test(a.path || '')
			);
		} catch (_) {}
	};
	$: if (phase === 'done' && workspaceId && !_checkedPreview) {
		_checkedPreview = true;
		checkPreview();
	}
	const previewRun = () => {
		dockedRunId.set(workspaceId);
		workspaceControlsTab.set('activity');
		showControls.set(true);
	};

	// Phase F: distill THIS finished run into a DRAFT skill (disabled + unaudited — it
	// won't apply in chat until the user audits it to 'supported' in Customize → Skills).
	let _savingSkill = false;
	const saveAsSkill = async () => {
		if (_savingSkill) return;
		_savingSkill = true;
		try {
			await saveRunAsSkill(localStorage.token, workspaceId);
			toast.success(
				$i18n.t('Draft skill created — review it in Customize → Skills, then mark it supported to enable.')
			);
		} catch (e) {
			toast.error(`${e}`);
		}
		_savingSkill = false;
	};

	const startTimerAndStream = () => {
		// startedAt is the persisted run start (above) — do NOT reset it here, or
		// re-entering a running workspace restarts the counter from 0.
		timer = setInterval(() => {
			nowTick = Date.now();
			if (running) elapsed = nowTick - startedAt;
		}, 1000);
		consume();
	};

	// Drop a quiet connection and replay the persisted event stream. The event
	// projector rebuilds the same cards and stable fallback ids from that replay.
	const retryStream = () => {
		controller?.abort();
		if (terminalFlushTimer) clearTimeout(terminalFlushTimer);
		terminalFlushTimer = null;
		pendingTerminalEvents = [];
		rawEvents = [];
		toolCount = 0;
		agents = [];
		executor = '';
		lastEventAt = Date.now();
		if (phase !== 'done' && phase !== 'error') phase = 'connecting';
		consume();
	};

	const approve = async () => {
		phase = 'connecting';
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
		if (terminalFlushTimer) clearTimeout(terminalFlushTimer);
	});
</script>

<div
	class="{className} relative my-2 min-w-0 max-w-full overflow-hidden rounded-2xl border border-gray-100 bg-gray-50 px-3.5 py-3 text-sm dark:border-gray-850 dark:bg-gray-900"
>
	<div class="flex items-center gap-2">
		<HarvisClawMascot
			size={40}
			state={running ? 'working' : phase === 'error' ? 'angry' : 'idle'}
			idleCycle={running}
			className="shrink-0 -my-1.5"
		/>
		{#if running}
			<span class="inline-flex size-2.5 rounded-full bg-blue-500"></span>
		{:else if phase === 'done'}
			<span class="text-blue-500 font-semibold">✓</span>
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
			<div class="ml-auto flex items-center gap-1.5 min-w-0">
				{#if engineLabel}
					<span
						class="shrink-0 flex items-center gap-1 max-w-[170px] text-xs px-1.5 py-0.5 rounded-md bg-blue-500/10 text-blue-600 dark:text-blue-300 font-medium"
						title={engineLabel + (execModel ? ' · ' + execModel : '')}
					>
						<BrandGlyph name={engineBrand} className="size-3 shrink-0" />
						<span class="truncate"
							>{engineLabel}{#if execModel} · {execModel}{/if}</span
						>
					</span>
				{/if}
				<span class="shrink-0 text-xs text-gray-400 tabular-nums">
					{fmt(elapsed)}{#if toolCount > 0} · {toolCount}
						{toolCount === 1 ? $i18n.t('tool') : $i18n.t('tools')}{/if}
				</span>
			</div>
		{/if}
	</div>

	<!-- Cursor-style compact activity sentence. It advances only from real typed
	     events and expands into the complete public tool history on demand. -->
	{#if phase !== 'awaiting'}
		<RunActivitySummary activity={runActivity} {phase} {stalled} onRetry={retryStream} />
		{#each terminalRuns as terminalRun, terminalIndex (terminalRun.id)}
			<TerminalRunCard
				run={terminalRun}
				autoCompact={terminalIndex < terminalRuns.length - 1}
			/>
		{/each}
	{/if}

	{#if phase === 'error'}
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
	{:else}
		<!-- Live file content is concrete workspace output, not model chain-of-thought.
		     It is the run TYPING: the box only exists while the run does. Once it ends the
		     file becomes a pill below, which is a thing you can open — a finished run should
		     hand you the file, not leave you scrolling inside a fixed-height code panel. -->
		{#if liveFile && running}
			<div
				class="mt-2 overflow-hidden rounded-lg border border-gray-200/80 dark:border-white/10 lms-codeblock"
			>
				<div
					class="flex items-center justify-between px-3 py-1 text-[11px] font-mono uppercase tracking-wide text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-[#1a1a1a] border-b border-gray-200/80 dark:border-white/10"
				>
					<span class="truncate">{liveFile.path}</span>
					<span class="normal-case tracking-normal text-blue-500">{$i18n.t('typing…')}</span>
				</div>
				<pre
					class="hljs lms-code-pre p-3.5 px-4 overflow-x-auto max-h-64 text-[13px] leading-6 bg-gray-50 dark:bg-[#1e1e1e] mb-0 whitespace-pre-wrap">{$typedFile}<span
						class="lms-caret"
						aria-hidden="true"
					/></pre>
			</div>
		{/if}
		<!-- Tool details and Bash output live in the activity summary + terminal cards above. -->

		{#if phase === 'done'}
			<!-- One completion block, not three competing ones. The written result, the files
			     the run produced and its token numbers are separate facts about the same run;
			     the branch that showed the analysis used to shadow the other two, so exactly
			     the runs that wrote a file were the ones that never showed it. -->
			<div class="mt-2 pt-2 border-t border-gray-100 dark:border-gray-850 space-y-2">
				{#if isOrchestrated}
					<!-- Per-agent finish() summaries. Nothing generated. The elapsed time and the
					     tool count used to be repeated here; they are already in the header two
					     inches above, and a card that says the same number twice reads as two
					     different numbers you have to reconcile. -->
					{#if agentPosts.length > 1}
						<div class="text-xs font-medium text-gray-600 dark:text-gray-300 tabular-nums">
							{agentPosts.length}
							{$i18n.t('agents')}
						</div>
					{/if}
					<div class="space-y-4">
						{#each agentPosts as a, i}
							<div class="min-w-0">
								<!-- Who is speaking, then what they said. This used to be one 12px row —
								     "✓ Harvis Agent: <the entire answer>" in gray-500, raw text, no
								     markdown. The agent's finish() summary IS its reply to the reader,
								     so it gets the same `markdown-prose` every other assistant message
								     in this chat gets; only the attribution line stays compact. -->
								<div class="flex items-center gap-1.5 mb-1">
									<span class="shrink-0 {a.ok ? 'text-blue-500' : 'text-red-500'}"
										>{a.ok ? '✓' : '✗'}</span
									>
									<span class="text-sm font-medium text-gray-700 dark:text-gray-200"
										>{a.label}</span
									>
								</div>
								<div class="markdown-prose">
									<Markdown id={`ws-agent-${workspaceId}-${i}`} content={a.summary} />
								</div>
							</div>
						{/each}
					</div>
				{/if}

				{#if $typedNarrative}
					<!-- Build Result Narrator, or the agent's own closing summary when there is
					     no narrator. Typed out rather than pasted in.

					     This is the agent talking to the reader, so it gets the SAME typography as
					     any other assistant message — plain `markdown-prose`. The `-sm` variant it
					     used to carry zeroes every margin (prose-p:my-0, prose-li:-my-0), which
					     turned a perfectly good markdown answer into one unbroken block that read
					     as unformatted next to the rest of the chat. -->
					<div class="markdown-prose">
						<Markdown id={`ws-narrative-${workspaceId}`} content={$typedNarrative} />
					</div>
				{/if}

				<RunFileCards wsId={workspaceId} done={phase === 'done'} revealOnFinish={_wasRunning} />

			</div>
		{/if}
	{/if}

	<div class="mt-2.5 flex items-center gap-2">
		{#if phase === 'awaiting'}
			<button
				class="text-xs px-3 py-1 rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition"
				on:click={approve}>{$i18n.t('Approve')}</button
			>
			<button
				class="text-xs px-3 py-1 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-950 transition"
				on:click={deny}>{$i18n.t('Deny')}</button
			>
		{:else if running}
			<button
				class="text-xs px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition"
				on:click={dockRun}>{$i18n.t('View')}</button
			>
			<button
				class="text-xs px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition"
				on:click={openStudio}>{$i18n.t('Open run')}</button
			>
			<button
				class="text-xs px-2 py-1 rounded-lg text-red-600 hover:bg-red-50 dark:hover:bg-red-950 transition ml-auto"
				on:click={stop}>{$i18n.t('Stop')}</button
			>
		{:else}
			{#if hasPreview}
				<button
					class="text-xs px-2.5 py-1 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-medium transition flex items-center gap-1.5"
					on:click={previewRun}
				>
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="size-3.5"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>
					{$i18n.t('Preview')}
				</button>
			{/if}
			<button
				class="text-xs px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition"
				on:click={dockRun}>{$i18n.t('View')}</button
			>
			<button
				class="text-xs px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition"
				on:click={openStudio}>{$i18n.t('Open run')}</button
			>
			{#if phase === 'done'}
				<button
					class="text-xs px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition disabled:opacity-40"
					title={$i18n.t('Distill this run into a draft skill (disabled until you audit it)')}
					disabled={_savingSkill}
					on:click={saveAsSkill}>{_savingSkill ? $i18n.t('Saving…') : $i18n.t('Save as skill')}</button
				>
			{/if}
		{/if}
	</div>
</div>

<svelte:window on:keydown={onInspectorKey} />

{#if showInspector}
	<!-- Inspector overview overlay — agents + their posts/responses, in-place over the chat.
	     Portaled to <body> so `fixed inset-0` spans the real viewport (not a clipped ancestor). -->
	<div use:portal class="fixed inset-0 z-[9998]">
		<div
			class="absolute inset-0 bg-black/50 backdrop-blur-sm"
			on:click={() => (showInspector = false)}
			role="presentation"
		></div>
		<div class="absolute inset-0 flex items-center justify-center p-4 pointer-events-none">
			<div
				class="dark-surface pointer-events-auto w-full max-w-5xl h-[85vh] flex flex-col rounded-2xl border border-white/10 bg-[#0c111d] shadow-2xl shadow-black/50 overflow-hidden"
			>
				<WorkflowInspector wsId={workspaceId} on:close={() => (showInspector = false)} />
			</div>
		</div>
	</div>
{/if}
