<script lang="ts">
	import { getContext, onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { WEBUI_NAME, config, showSidebar, models } from '$lib/stores';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { uploadFile } from '$lib/apis/files';
	import { getCapabilityRegistry } from '$lib/integrations/registry';
	import {
		getAttachedRepos,
		createVibecodeSession,
		getVibecodeSession,
		startVibecodeTurn,
		autonameVibecodeSession,
		getPendingAction,
		resolveAction,
		setVibecodePermission,
		seedVibecodeLocalFolder,
		getVibecodeWriteback,
		getVibecodeSessionDiff,
		getRunArtifacts,
		cancelWorkspaceRun,
		type AttachedRepo,
		type VibecodeSession,
		type VibecodeTurn,
		type PendingAction
	} from '$lib/apis/agent-runs';
	import RunView from '$lib/agent-studio/RunView.svelte';
	import BuildActions from '$lib/agent-studio/BuildActions.svelte';
	import { createWorkspaceStream } from '$lib/apis/streaming/workspace-stream';
	import WorkflowInspector from '$lib/agent-studio/WorkflowInspector.svelte';
	import { humanizeRunTitle } from '$lib/agent-studio/runFormat';
	import PlanPanel from '$lib/agent-studio/PlanPanel.svelte';
	import GitHubRepoModal from '$lib/agent-studio/GitHubRepoModal.svelte';
	import BuildHeader from '$lib/agent-studio/build/BuildHeader.svelte';
	import WorkspaceFileRail from '$lib/agent-studio/build/WorkspaceFileRail.svelte';
	import WorkspaceMainPanel from '$lib/agent-studio/build/WorkspaceMainPanel.svelte';
	import WorkspacePanel from '$lib/agent-studio/build/WorkspacePanel.svelte';
	import BackgroundTaskCard from '$lib/agent-studio/build/BackgroundTaskCard.svelte';
	import ShellTab from '$lib/agent-studio/build/ShellTab.svelte';
	import Customize from '$lib/agent-studio/Customize.svelte';
	import { PaneGroup, Pane, PaneResizer } from 'paneforge';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';
	import {
		supportsLocalFs,
		pickLocalDirectory,
		readFolderSnapshot,
		writeFilesToFolder,
		deleteFilesFromFolder,
		verifyPermission,
		rememberFolder,
		listRecentFolders,
		linkSessionToFolder,
		findFolderForSession,
		type RecentFolder
	} from '$lib/apis/local-fs';
	import { toast } from 'svelte-sonner';

	const i18n: any = getContext('i18n');

	$: enabled = $config?.features?.enable_harvis_vibecode ?? true;
	// P2: manual Shell tab — flag default OFF (stop-gated); backend WS enforces it too.
	$: shellEnabled = $config?.features?.enable_harvis_build_shell ?? false;

	// ── URL-driven: the sidebar session list + New session set ?session. ──
	$: sessionId = $page.url.searchParams.get('session') || '';

	// Settings/Customize opens IN Build (right drawer) instead of bouncing to the
	// Agent Studio hub. URL-synced (?panel=customize) so it deep-links + back-buttons
	// cleanly; /harvis/agent-studio/customize still works for the full-page version.
	$: showCustomize = $page.url.searchParams.get('panel') === 'customize';
	const setCustomize = (open: boolean) => {
		const url = new URL($page.url);
		if (open) url.searchParams.set('panel', 'customize');
		else url.searchParams.delete('panel');
		goto(`${url.pathname}${url.search}`, { replaceState: !open, noScroll: true, keepFocus: true });
	};

	let session: VibecodeSession | null = null;
	let turns: VibecodeTurn[] = [];
	let pollTimer: any = null;
	// Which finished turns have their full run (thought stream + canvas) expanded.
	// Chat-style: a finished turn shows the model's summary as a bubble; the run is
	// one click away. Running turns always show the live run.
	let expandedRuns: Record<string, boolean> = {};
	const toggleRun = (id: string) => {
		expandedRuns = { ...expandedRuns, [id]: !expandedRuns[id] };
	};

	$: anyRunning = turns.some((t) => t.status === 'running');
	$: latestTurnId = turns.length ? turns[turns.length - 1].id : '';
	$: doneTurns = turns.filter((t) => t.status === 'done').length;

	// ── Background-tasks panel (right rail) — THIS session's turns ONLY. Scoped by
	// construction (getVibecodeSession is per-session) → no account-wide leak from
	// other sessions. Running + finished both sorted newest-first so a freshly-
	// launched run lands at the TOP of its section. ──
	let bgHidden: Set<string> = new Set(); // finished tasks the user "Clear"-ed from the panel
	$: runningTasks = turns.filter((t) => t.status === 'running').slice().reverse();
	$: finishedTasks = turns
		.filter((t) => t.status !== 'running' && !bgHidden.has(t.id))
		.slice()
		.reverse();

	// ── BW: customizable rail — collapse/expand each panel, persisted ──
	let railOpen: Record<string, boolean> = (() => {
		const def: Record<string, boolean> = { bg: true, files: true, plan: true, file: true };
		try {
			return { ...def, ...JSON.parse(localStorage.getItem('harvis.vibecode.rail') || '{}') };
		} catch {
			return def;
		}
	})();
	const toggleRail = (k: string) => {
		railOpen = { ...railOpen, [k]: !railOpen[k] };
		try {
			localStorage.setItem('harvis.vibecode.rail', JSON.stringify(railOpen));
		} catch {}
	};

	// ── BW: Files + File panels — the session's changed files, parsed from its diff ──
	let sessionDiff = '';
	let selectedFile = '';
	const loadDiff = async () => {
		if (!sessionId) {
			sessionDiff = '';
			return;
		}
		try {
			const r: any = await getVibecodeSessionDiff(sessionId);
			sessionDiff = r?.diff ?? '';
		} catch {
			sessionDiff = '';
		}
	};
	function parseDiffFiles(diff: string): { path: string; status: 'M' | 'A' | 'D'; lines: string[] }[] {
		if (!diff) return [];
		const files: { path: string; status: 'M' | 'A' | 'D'; lines: string[] }[] = [];
		let cur: { path: string; status: 'M' | 'A' | 'D'; lines: string[] } | null = null;
		for (const line of diff.split('\n')) {
			const m = line.match(/^diff --git a\/(.+?) b\/(.+)$/);
			if (m) {
				cur = { path: m[2], status: 'M', lines: [line] };
				files.push(cur);
			} else if (cur) {
				cur.lines.push(line);
				if (line.startsWith('new file mode')) cur.status = 'A';
				else if (line.startsWith('deleted file mode')) cur.status = 'D';
			}
		}
		return files;
	}
	$: changedFiles = parseDiffFiles(sessionDiff);
	$: selectedFileObj = changedFiles.find((f) => f.path === selectedFile) || changedFiles[0] || null;
	// Refresh the workspace runs + session diff on load and whenever a turn completes.
	$: {
		doneTurns;
		sessionId;
		latestTurnId;
		loadDiff();
		loadArtifacts();
	}
	const clearBg = () => {
		bgHidden = new Set([...bgHidden, ...finishedTasks.map((t) => t.id)]);
	};
	const bgDot = (s?: string) =>
		s === 'running'
			? 'bg-blue-500 animate-pulse'
			: s === 'error'
				? 'bg-red-500'
				: s === 'cancelled'
					? 'bg-amber-500'
					: 'bg-emerald-500';
	const bgStatusLabel = (s?: string) =>
		s === 'running'
			? $i18n.t('Running')
			: s === 'error'
				? $i18n.t('Failed')
				: s === 'cancelled'
					? $i18n.t('Cancelled')
					: $i18n.t('Completed');

	// (BW2 3-region dock helpers removed — superseded by the BW3 dock + ⋯ panel menu)

	// Left-rail tab + main-panel tab + file/artifact selection wiring.
	let fileTab: 'files' | 'changes' | 'artifacts' = 'changes';
	let mainTab: 'chat' | 'diff' | 'logs' | 'editor' | 'preview' = 'chat';
	const onFileSelect = (path: string) => {
		selectedFile = path;
		mainTab = 'diff';
		// Picking a file in the Explorer jumps the dock to the File tab (VS Code flow).
		if (!panelVisible.br) {
			panelVisible = { ...panelVisible, br: true };
			persistPanels();
		}
		dockTab = 'br';
	};
	let artifacts: any[] = [];
	const loadArtifacts = async () => {
		if (!latestTurnId) {
			artifacts = [];
			return;
		}
		try {
			artifacts = await getRunArtifacts(latestTurnId);
		} catch {
			artifacts = [];
		}
	};
	const onArtifactSelect = (_id: string) => {
		mainTab = 'diff';
		if (!panelVisible.br) {
			panelVisible = { ...panelVisible, br: true };
			persistPanels();
		}
		dockTab = 'br';
	};

	// Right-rail "Agents" — a vibecode turn runs one coder agent; surface it.
	$: agents = (() => {
		const t = turns.length ? turns[turns.length - 1] : null;
		if (!t) return [];
		const st =
			t.status === 'running'
				? 'running'
				: t.status === 'done'
					? 'done'
					: t.status === 'error'
						? 'error'
						: 'pending';
		return [{ name: t.model_name || $i18n.t('Coder'), status: st }];
	})();

	// Mirror the pending-action approval into the right rail's Approvals section.
	$: rightApproval = pendingAction
		? {
				tool: pendingAction.tool,
				command:
					pendingAction.args && (pendingAction.args.command || pendingAction.args.cmd)
						? String(pendingAction.args.command || pendingAction.args.cmd)
						: pendingAction.tool,
				risk: pendingAction.risk
			}
		: null;

	// ── BuildHeader props ─────────────────────────────────────────────────────────
	$: hdrHasProject = !!sessionId;
	$: hdrProjectName =
		session?.title ||
		session?.repo_display_path ||
		(session?.repo_path ? session.repo_path.split('/').filter(Boolean).pop() : '') ||
		$i18n.t('Untitled session');
	$: hdrSourceLabel = session?.repo_path ? $i18n.t('Local repo') : $i18n.t('Scratch');
	$: hdrIsoLabel = activeIso === 'inplace' ? $i18n.t('In-place branch') : $i18n.t('Clone');
	// Run-mode label is the permission ladder rung — only meaningful in-place (clone
	// has no ladder), so it's blank for clone to avoid a redundant "Clone · Clone".
	$: hdrModeLabel = activeIso === 'inplace' ? PERM_SHORT[activePerm] || activePerm : '';

	// Header / rail actions.
	const cancelRun = async () => {
		const running = turns.find((t) => t.status === 'running');
		if (running) await cancelWorkspaceRun(running.id);
	};
	const cancelRunId = async (id: string) => {
		if (id) await cancelWorkspaceRun(id);
	};
	// Open run / View logs → slide the Workflow Inspector IN over the page (right→left)
	// instead of navigating away. The inspector shows the run's sub-agents as inspectable
	// chat-like sessions (Overview + one per agent).
	let overlayRunId = '';
	let overlayInitialTab: string = 'overview';
	// The inspector docks into the right workspace pane (pushes the chat, doesn't take over).
	// Remember the dock width and the inspector width SEPARATELY (persisted) so opening a
	// run restores your last inspector width and CLOSING restores your last dock width —
	// no snap-back to a hardcoded size if you'd resized it.
	let rightPane: any = null;
	let _lastOverlayOpen = false;
	const _clampPane = (n: number) => Math.min(62, Math.max(22, n || 0));
	let dockSize = 33;
	let inspectorSize = 50;
	if (typeof localStorage !== 'undefined') {
		dockSize = _clampPane(Number(localStorage.getItem('vibecodeDockSize')) || 33);
		inspectorSize = _clampPane(Number(localStorage.getItem('vibecodeInspectorSize')) || 50);
	}
	$: {
		const _open = !!overlayRunId;
		if (_open !== _lastOverlayOpen && rightPane) {
			try {
				const cur = rightPane.getSize();
				if (_open) {
					if (cur > 0) dockSize = _clampPane(cur); // leaving the dock → remember its width
					rightPane.resize(inspectorSize); // open at your last inspector width
				} else {
					if (cur > 0) inspectorSize = _clampPane(cur); // leaving inspector → remember it
					rightPane.resize(dockSize); // restore your dock width
				}
				if (typeof localStorage !== 'undefined') {
					localStorage.setItem('vibecodeDockSize', String(Math.round(dockSize)));
					localStorage.setItem('vibecodeInspectorSize', String(Math.round(inspectorSize)));
				}
			} catch (_) {
				// pane not ready — defaultSize handles the just-mounted case
			}
		}
		_lastOverlayOpen = _open;
	}
	$: overlayTitle = overlayRunId
		? humanizeRunTitle(turns.find((t) => t.id === overlayRunId) || { task_brief: '' })
		: '';
	const headerOpenRun = () => {
		if (latestTurnId) {
			overlayInitialTab = 'overview';
			overlayRunId = latestTurnId;
		}
	};
	const headerOpenRunId = (id: string) => {
		if (id) {
			overlayInitialTab = 'overview';
			overlayRunId = id;
		}
	};
	const headerCreatePR = () => {
		mainTab = 'chat';
		toast.info($i18n.t('Use “Create PR” in the changes card below the conversation.'));
	};

	// ── BW3: main conversation + resizable workspace dock (the quad lives in the dock) ─
	let dockOpen = (() => {
		try {
			const v = localStorage.getItem('harvis.vibecode.dock');
			return v === null ? true : v === '1';
		} catch {
			return true;
		}
	})();
	const toggleDock = () => {
		dockOpen = !dockOpen;
		try {
			localStorage.setItem('harvis.vibecode.dock', dockOpen ? '1' : '0');
		} catch {
			/* ignore */
		}
	};
	// ── Dock panel visibility (the ⋯ menu) — conditional render so EVERY panel exits
	// reliably. (PaneForge collapse() failed when both panes in a column were collapsed.)
	let panelVisible: Record<string, boolean> = (() => {
		const def = { tl: true, tr: true, bl: false, br: false, sh: true };
		try {
			return { ...def, ...JSON.parse(localStorage.getItem('harvis.vibecode.panels') || '{}') };
		} catch {
			return def;
		}
	})();
	const persistPanels = () => {
		try {
			localStorage.setItem('harvis.vibecode.panels', JSON.stringify(panelVisible));
		} catch {
			/* ignore */
		}
	};
	let blTouched = false; // user manually toggled Plan → stop auto-managing it
	const togglePanel = (k: string) => {
		const turningOn = !panelVisible[k];
		panelVisible = { ...panelVisible, [k]: !panelVisible[k] };
		if (k === 'bl') blTouched = true;
		// Enabling a panel always brings the dock back (so it can't get stuck hidden when
		// the dock was collapsed); when all panels are off the dock yields its space to chat.
		if (turningOn && !dockOpen) {
			dockOpen = true;
			try {
				localStorage.setItem('harvis.vibecode.dock', '1');
			} catch {
				/* ignore */
			}
		}
		persistPanels();
	};
	// Plan auto-opens once a run produces a plan (until the user touches it).
	let planStepCount = 0;
	$: if (planStepCount > 0 && !blTouched && !panelVisible.bl) {
		panelVisible = { ...panelVisible, bl: true };
	}
	$: leftHasAny = panelVisible.tl || panelVisible.bl;
	$: rightHasAny = panelVisible.tr || panelVisible.br;
	// Rows-first dock: top row = tl|tr, bottom row = bl|br. With one column of panels
	// visible they stack top/bottom; with all four it's a 2×2.
	$: topHasAny = panelVisible.tl || panelVisible.bl;
	$: bottomHasAny = panelVisible.tr || panelVisible.br;
	$: panelList = [
		{ key: 'tl', label: $i18n.t('Background tasks'), visible: panelVisible.tl },
		{ key: 'tr', label: $i18n.t('Files'), visible: panelVisible.tr },
		{ key: 'bl', label: $i18n.t('Plan'), visible: panelVisible.bl },
		{ key: 'br', label: $i18n.t('File'), visible: panelVisible.br },
		...(shellEnabled ? [{ key: 'sh', label: $i18n.t('Shell'), visible: panelVisible.sh }] : [])
	];
	// ── Tabbed dock (Claude-Code-Desktop style): ONE panel at a time, a tab strip on
	// top. The ⋯ menu still controls WHICH tabs exist (panelVisible); this picks the
	// active one. Order: Tasks · Plan · Files · File.
	let dockTab: 'tl' | 'bl' | 'tr' | 'br' | 'sh' = (() => {
		try {
			const v = localStorage.getItem('harvis.vibecode.docktab');
			return v === 'tl' || v === 'bl' || v === 'tr' || v === 'br' || v === 'sh' ? v : 'tl';
		} catch {
			return 'tl';
		}
	})();
	const setDockTab = (k: 'tl' | 'bl' | 'tr' | 'br' | 'sh') => {
		dockTab = k;
		try {
			localStorage.setItem('harvis.vibecode.docktab', k);
		} catch {
			/* ignore */
		}
	};
	$: dockTabs = [
		{ key: 'tl' as const, label: $i18n.t('Tasks'), visible: panelVisible.tl },
		{ key: 'bl' as const, label: $i18n.t('Plan'), visible: panelVisible.bl },
		{ key: 'tr' as const, label: $i18n.t('Files'), visible: panelVisible.tr },
		{ key: 'br' as const, label: $i18n.t('File'), visible: panelVisible.br },
		// P2: manual shell — only exists when the HARVIS_BUILD_SHELL flag is on.
		{ key: 'sh' as const, label: $i18n.t('Shell'), visible: shellEnabled && panelVisible.sh }
	].filter((t) => t.visible);
	// If the active tab's panel gets hidden via the ⋯ menu, fall to the first visible one.
	$: if (dockTabs.length && !dockTabs.some((t) => t.key === dockTab)) dockTab = dockTabs[0].key;
	// When a NEW run starts, surface the Background tasks panel automatically (open the
	// dock if it was hidden, show the panel if it was closed). Only on the rising edge —
	// the user can still hide it mid-run.
	let prevRunningCount = 0;
	$: surfaceBackgroundOnRun(runningTasks.length);
	function surfaceBackgroundOnRun(n: number) {
		if (n > prevRunningCount) {
			if (!dockOpen) {
				dockOpen = true;
				try {
					localStorage.setItem('harvis.vibecode.dock', '1');
				} catch {
					/* ignore */
				}
			}
			if (!panelVisible.tl) {
				panelVisible = { ...panelVisible, tl: true };
				persistPanels();
			}
			// Bring the Tasks tab forward so the new run is immediately visible.
			dockTab = 'tl';
		}
		prevRunningCount = n;
	}
	// Finished background tasks stay collapsed by default; show-logs targets one run.
	let showFinished = false;
	let logsRunId = '';
	const viewLogs = (id: string, agentTab: string = '') => {
		// Open the Workflow Inspector. `agentTab` (a sub-agent's run id, from clicking a
		// specific agent row) focuses that agent's tab; otherwise we land on Overview.
		logsRunId = id;
		if (id) {
			overlayInitialTab = agentTab || 'overview';
			overlayRunId = id;
		}
	};
	// Main-panel empty-state actions.
	const connectGithub = () => (showGithubModal = true);
	const setupCli = () =>
		toast.info(
			$i18n.t('Local CLI sessions are coming soon — connect a GitHub or local repo for now.')
		);
	const refreshFiles = () => loadDiff();

	// ── Token / context / COST usage — real per-turn usage, summed across the session, with a
	//    real-time tick while a turn streams. Engine-FLEXIBLE: each model's context window + price
	//    come from its /api/models metadata (info.meta.context_length / price_in / price_out).
	//    Local Ollama models carry no price → shown as Free. No hardcoded per-engine logic. ──
	let showUsageStats = false;
	let showModelMenu = false;
	let selectedModel = ''; // '' ⇒ engine/turn default; set ⇒ sent on every turn
	let liveCompletionTokens = 0; // streamed output tokens for the running turn (live tick)

	// Engine → which model providers are relevant (Claude Code → Claude; OpenCode/Native/Hermes →
	// local Ollama; Codex → GPT or local). Drives the picker + the meter.
	const ENGINE_MODEL_OWNERS: Record<string, string[]> = {
		'claude-code': ['anthropic'],
		codex: ['openai', 'ollama'],
		opencode: ['ollama'],
		'hermes-agent': ['ollama'],
		'hermes-native': ['ollama'],
		native: ['ollama']
	};
	// The model the meter reads window+price from before the first turn lands (so a Claude session
	// shows 200k + Claude pricing immediately).
	const ENGINE_DEFAULT_MODEL: Record<string, string> = {
		'claude-code': 'anthropic/claude-sonnet-4-6',
		codex: 'openai/gpt-5'
	};
	const fmtTok = (n: number) =>
		n >= 10000 ? Math.round(n / 1000) + 'k' : n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n);
	const fmtCost = (n: number) => (n >= 1 ? '$' + n.toFixed(2) : n > 0 ? '$' + n.toFixed(3) : '$0');
	const pickModel = (id: string) => {
		selectedModel = id;
		showModelMenu = false;
	};

	$: usageTurns = turns.filter((t) => (t.prompt_tokens ?? 0) > 0 || (t.completion_tokens ?? 0) > 0);
	$: lastUsage = usageTurns.length ? usageTurns[usageTurns.length - 1] : null;
	$: sessionTokens = usageTurns.reduce((s, t) => s + (t.prompt_tokens || 0) + (t.completion_tokens || 0), 0);

	// Engine-filtered picker list (Claude Code → only Claude, etc.).
	$: modelOptions = ($models || []).filter((m: any) => {
		if (!m || !m.id) return false;
		const owners = ENGINE_MODEL_OWNERS[selectedEngine] || ['ollama'];
		return owners.includes((m.owned_by || 'ollama').toString().toLowerCase());
	});
	// Picked model no longer valid for the current engine (e.g. switched to Claude Code) → default.
	$: if (selectedModel && modelOptions.length && !modelOptions.find((m: any) => m.id === selectedModel)) {
		selectedModel = '';
	}

	// Meter reads window + price from: the picked model → the last turn's → the engine default.
	$: meterModelId = selectedModel || lastUsage?.model_name || ENGINE_DEFAULT_MODEL[selectedEngine] || '';
	$: meterEntry = ($models || []).find((m: any) => m?.id === meterModelId);
	$: meterModelMeta = (meterEntry?.info?.meta as any) || {};
	$: priceIn = Number(meterModelMeta.price_in || 0); // USD / million input tokens
	$: priceOut = Number(meterModelMeta.price_out || 0); // USD / million output tokens
	$: isFreeModel = priceIn === 0 && priceOut === 0; // local Ollama → no cost
	$: isSubscriptionModel = /subscription/i.test(meterEntry?.name || '');
	$: sessionCost = usageTurns.reduce(
		(s, t) => s + ((t.prompt_tokens || 0) * priceIn + (t.completion_tokens || 0) * priceOut) / 1e6,
		0
	);

	$: liveOn = runningTasks.length > 0; // a turn is streaming → tick the completion side live
	$: ctxWindow = Number(meterModelMeta.context_length || lastUsage?.context_window || 24576);
	$: ctxUsed = (lastUsage?.prompt_tokens || 0) + (liveOn ? liveCompletionTokens : 0);
	$: ctxPct = ctxWindow ? Math.min(100, Math.round((ctxUsed / ctxWindow) * 100)) : 0;
	$: ctxAvail = Math.max(0, ctxWindow - ctxUsed);
	$: usageModel = meterModelId || lastUsage?.model_name || 'llama3.1:8b';
	$: displayModel = meterEntry?.name || selectedModel || usageModel;
	$: liveSessionTokens = sessionTokens + (liveOn ? liveCompletionTokens : 0);
	$: liveCost = sessionCost + (liveOn ? (liveCompletionTokens * priceOut) / 1e6 : 0);

	// Live tick: a lightweight 2nd stream consumer counts the running turn's streamed tokens.
	let _liveCtrl: AbortController | null = null;
	let _liveRunId = '';
	$: _watchLive(runningTasks[0]?.id || '');
	function _watchLive(runId: string) {
		if (runId === _liveRunId) return;
		_liveRunId = runId;
		if (_liveCtrl) {
			try { _liveCtrl.abort(); } catch (_) {}
			_liveCtrl = null;
		}
		liveCompletionTokens = 0;
		if (!runId) return;
		const ctrl = new AbortController();
		_liveCtrl = ctrl;
		(async () => {
			try {
				for await (const ev of createWorkspaceStream(runId, localStorage.token, ctrl.signal)) {
					if (ctrl.signal.aborted) break;
					const c = (ev as any)?.content;
					if ((ev as any)?.type === 'token' && c) liveCompletionTokens += Math.ceil(String(c).length / 4);
				}
			} catch (_) {}
		})();
	}
	onDestroy(() => {
		if (_liveCtrl) {
			try { _liveCtrl.abort(); } catch (_) {}
		}
	});

	const loadSession = async () => {
		if (!sessionId) {
			session = null;
			turns = [];
			return;
		}
		const reqId = sessionId;
		const data = await getVibecodeSession(reqId);
		if (reqId !== sessionId) return; // navigated to another session mid-fetch — drop the stale response
		if (data) {
			session = data.session;
			turns = data.turns ?? [];
			maybeAutoname();
		}
	};

	// Auto-name once, after the first turn settles, while the session is still untitled.
	let autonameTriggered = false;
	const maybeAutoname = async () => {
		if (autonameTriggered || !session || session.title) return;
		const first = turns[0];
		if (!first || (first.status !== 'done' && first.status !== 'error')) return;
		autonameTriggered = true;
		const named = await autonameVibecodeSession(sessionId);
		if (named && session) session = { ...session, title: named.title, emoji: named.emoji };
	};

	const schedule = () => {
		clearTimeout(pollTimer);
		if (!sessionId) return;
		pollTimer = setTimeout(
			async () => {
				await loadSession();
				await pollPending();
				await maybeWriteBack();
				schedule();
			},
			anyRunning ? 2000 : 30000
		);
	};

	let loadedFor = '';
	$: if (sessionId !== loadedFor) {
		loadedFor = sessionId;
		autonameTriggered = false;
		// Drop the previous session's folder binding; relink this one from IndexedDB.
		clearLocalFolder();
		lastWriteBackDone = -1;
		(async () => {
			await loadSession();
			await relinkSessionFolder();
			await maybeWriteBack();
			schedule();
		})();
	}

	// ── Compose state ──
	let repos: AttachedRepo[] = [];
	let selectedRepoPath = '';
	let prompt = '';
	let promptEl: HTMLTextAreaElement; // composer textarea (auto-grow)
	const autogrow = () => {
		if (!promptEl) return;
		promptEl.style.height = 'auto';
		promptEl.style.height = Math.min(promptEl.scrollHeight, 160) + 'px';
	};
	// Collapse back to one line once the prompt is cleared (after sending).
	$: if (prompt === '' && promptEl) promptEl.style.height = 'auto';
	let sending = false;
	let sendError = '';
	$: selectedRepo = repos.find((r) => r.path === selectedRepoPath) || null;
	$: composerDisabled = sending || anyRunning;

	// ── Run mode (per turn) = the permission PYRAMID: how much autonomy this turn gets.
	//   plan        — read-only: drafts a step-by-step plan, changes nothing
	//   ask         — pauses for approval before each edit / command
	//   auto-accept — auto-applies edits, pauses on risky ops (delete / push / .env)
	//   full-auto   — runs everything with no prompts
	// Sent per-turn; the agent always works on a CLONE, so the diff/PR is the outer gate.
	type RunRung = 'plan' | 'ask' | 'auto-accept' | 'full-auto';
	let runMode: RunRung = 'full-auto';
	let pendingRunModeAfterAck: RunRung | '' = '';
	// Orchestrate = fan this turn out to N task-delegated sub-agents (the planner picks
	// 3–10, scaling to the task). Off ⇒ a single agent on the session's working copy.
	let orchestrate = false;
	// Phase E1/E2: external Build engine. 'native' = OpenClaw vibecode-turn runner; the others
	// = sidecar CLIs (opencode = local; codex/claude-code = cloud, per-user key). Clone-mode
	// only, flag-gated. Selector shows ONLY ready engines (per the registry engine_readiness).
	let selectedEngine = 'native';
	let engineReadiness: Record<string, { ready: boolean; reason?: string }> = {};
	// Phase E4B: "Hermes Agent" = the REAL NousResearch Hermes Agent app (sidecar, via the
	// engine-adapter). "Hermes Native" = the experimental E4 in-process runner (SubAgentRunner +
	// SOUL persona on a local Hermes model). Each gated by its own backend flag.
	const ENGINE_LABELS: Record<string, string> = {
		opencode: 'OpenCode',
		codex: 'Codex',
		'claude-code': 'Claude Code',
		'hermes-agent': 'Hermes Agent',
		'hermes-native': 'Hermes Native'
	};
	// Display label for a session's engine ('native' / unset → "Native"); used by the
	// Build-analysis card to label "Built with X".
	const engineDisplay = (id?: string | null): string =>
		!id || id === 'native' ? 'Native' : ENGINE_LABELS[id] || id;

	// Some engines (e.g. Claude Code) emit their final summary twice — the assistant text and
	// the result block carry the same sentence. Collapse an exact "X. X." double so the thread
	// narrative reads once.
	const cleanSummary = (s?: string | null): string => {
		const v = (s || '').replace(/\s+/g, ' ').trim();
		if (!v) return v;
		const m = v.match(/^(.{12,}?[.!?])\s*\1\s*$/);
		if (m) return m[1];
		const mid = Math.floor(v.length / 2);
		const a = v.slice(0, mid).trim();
		const b = v.slice(mid).trim();
		return a && a === b ? a : v;
	};
	// The backend engine_readiness ALREADY encodes each engine's flag (a ready entry implies
	// its flag is on), so we gate the selector purely on "≥1 ready engine + clone-mode" — no
	// separate front-end flag check. This lets each Hermes engine show under its own flag
	// without coupling to the external-engines flag, and vice-versa.
	$: readyEngineIds = ['opencode', 'codex', 'claude-code', 'hermes-agent', 'hermes-native'].filter(
		(e) => engineReadiness?.[e]?.ready
	);
	$: showEngineSelector = readyEngineIds.length > 0 && isolationMode === 'session';
	// Surface the Hermes-Native "enabled but no model" reason even when the selector is hidden.
	$: hermesNeedsModel =
		isolationMode === 'session' && engineReadiness?.['hermes-native']?.reason === 'no_hermes_model';
	// Force native whenever the selector isn't applicable (inplace / flag-off) or the selected
	// engine is no longer ready (e.g. key disconnected, sidecar down).
	$: if (!showEngineSelector && selectedEngine !== 'native') selectedEngine = 'native';
	$: if (selectedEngine !== 'native' && !engineReadiness?.[selectedEngine]?.ready) selectedEngine = 'native';
	// Apex → base (rendered top-to-bottom; base = safest = Plan, apex = most autonomy = Auto).
	const RUN_LADDER: { mode: RunRung; label: string; desc: string }[] = [
		{ mode: 'full-auto', label: 'Auto', desc: 'Runs everything automatically — no prompts.' },
		{
			mode: 'auto-accept',
			label: 'Accept edits',
			desc: 'Auto-applies edits; pauses for risky ops (delete, push, .env).'
		},
		{ mode: 'ask', label: 'Ask', desc: 'Pauses for your approval before each edit or command.' },
		{ mode: 'plan', label: 'Plan', desc: 'Read-only — drafts a step-by-step plan, changes nothing.' }
	];
	const setRunMode = (mode: RunRung) => {
		// Full-auto is the loudest rung → one-time acknowledge before arming it.
		if (mode === 'full-auto' && !ackFullAuto) {
			pendingRunModeAfterAck = mode;
			fullAutoAckOpen = true;
			showModeMenu = false;
			return;
		}
		runMode = mode;
		showModeMenu = false;
	};

	// ── Isolation + permission ladder ──
	let isolationMode = 'session'; // 'session' (clone, default+safe) | 'inplace'
	let permissionMode = 'ask';
	const PERM_SHORT: Record<string, string> = {
		ask: 'Ask',
		'auto-accept': 'Accept',
		plan: 'Plan',
		'full-auto': 'Auto'
	};
	const PERM_MENU = [
		{ mode: 'ask', label: 'Ask permissions' },
		{ mode: 'auto-accept', label: 'Accept edits' },
		{ mode: 'plan', label: 'Plan mode' },
		{ mode: 'full-auto', label: 'Auto mode' }
	];
	$: offerRepos = repos.filter((r) => (isolationMode === 'inplace' ? r.writable : !r.writable));
	// Opened folders (browser FS) + RO-browsed server repos are clone-mode only → the in-place
	// toggle is disabled while one is selected. RW-browsed repos (repoBrowsedRw) ARE in-place
	// eligible, so they are deliberately NOT in cloneOnly.
	$: cloneOnly = repoIsBrowsed || !!localFolderHandle || localFolderFiles.length > 0 || !!selectedGithubRepo;
	// A browsed pick lives OUTSIDE the offer list, so the offer-list cleanup must not wipe it —
	// neither an RO-browsed (repoIsBrowsed) nor an RW-browsed (repoBrowsedRw) selection.
	$: if (
		!repoIsBrowsed &&
		!repoBrowsedRw &&
		selectedRepoPath &&
		!offerRepos.some((r) => r.path === selectedRepoPath)
	) {
		selectedRepoPath = '';
	}

	// Active mode reflects the session in-session, the local choice pre-session.
	$: activeIso = sessionId ? session?.isolation_mode || 'session' : isolationMode;
	$: activePerm = sessionId ? session?.permission_mode || 'ask' : permissionMode;
	$: modePillLabel = activeIso === 'inplace' ? PERM_SHORT[activePerm] || activePerm : 'Clone';

	let ackFullAuto = false;
	let fullAutoAckOpen = false;
	let pendingPermAfterAck = '';
	let permError = '';
	const applyPerm = async (mode: string) => {
		if (sessionId && session) {
			// In-session: persist FIRST, then update local state — only if the server
			// accepted it. Avoids leaving permissionMode optimistically ahead of the DB
			// (which would otherwise leak a rejected mode into the next session create).
			try {
				await setVibecodePermission(sessionId, mode);
				permissionMode = mode;
				session = { ...session, permission_mode: mode };
				permError = '';
			} catch (_) {
				permError = $i18n.t('Could not change run mode — try again.');
			}
		} else {
			// Pre-session: local choice only, applied at session-create time.
			permissionMode = mode;
			permError = '';
		}
	};
	const setPerm = async (mode: string) => {
		if (mode === 'full-auto' && !ackFullAuto) {
			pendingPermAfterAck = mode;
			fullAutoAckOpen = true;
			return;
		}
		await applyPerm(mode);
		showModeMenu = false;
	};
	const setIsolation = (m: string) => {
		isolationMode = m;
	};

	// ── Composer menus + image attach ──
	let showModeMenu = false;
	let showRepoMenu = false;
	let showExecMenu = false; // execution-target dropdown (Local live + SSH seam)
	let showEngineMenu = false; // Build-engine dropdown (Native + each ready engine)
	// In-place editing of a BROWSED host folder is gated server-side; the flag is surfaced via
	// /api/config so the picker defaults to clone unless the deployer has enabled it.
	$: inplaceOnBrowsed = $config?.features?.enable_inplace_on_browsed ?? false;
	let showFolderBrowser = false;
	let folderBrowserRw = false; // the folder browser is in WRITABLE mode (in-place eligible)
	let repoIsBrowsed = false; // current pick came from the read-only server browse (clone-only)
	let repoBrowsedRw = false; // current pick came from the read-WRITE browse → in-place eligible
	let showGithubModal = false;
	let selectedGithubRepo: { owner: string; name: string; branch?: string } | null = null;
	let selectedRepoDisplayPath = ''; // host-style label for an allowlisted browsed repo

	// ── Local folder (browser File System Access — edits the user's REAL folder) ──
	let fsSupported = false; // Chromium only (Chrome/Edge/Brave/Arc)
	let recentFolders: RecentFolder[] = []; // persisted handles (IndexedDB)
	let localFolderHandle: any = null; // the picked FileSystemDirectoryHandle (source of truth)
	let localFolderName = ''; // display label (the folder's name)
	let localFolderKey = ''; // IndexedDB key, for session ↔ folder linking
	let pickingFolder = false;
	let seedingStatus = ''; // "Reading folder…" while we snapshot it for the backend
	let writeBackStatus = ''; // "Saving to your folder…" while we write changes back
	let needsRelink = false; // reopened a local-folder session but lost the handle (reload)
	// Read-only fallback for browsers WITHOUT File System Access (Brave default, Firefox,
	// Safari): a hidden <input webkitdirectory> opens the native OS file explorer and yields a
	// one-shot file snapshot (no persistent handle → no live writeback, clone-mode semantics).
	let folderInputEl: HTMLInputElement;
	let localFolderFiles: { path: string; content: string }[] = [];

	const clearLocalFolder = () => {
		localFolderHandle = null;
		localFolderName = '';
		localFolderKey = '';
		localFolderFiles = [];
		needsRelink = false;
	};

	// Pick an allowlisted repo (bind-mounted / browse-root) — clears any local-folder pick.
	const pickRepo = (path: string, displayPath = '') => {
		selectedRepoPath = path;
		repoIsBrowsed = false;
		repoBrowsedRw = false;
		selectedRepoDisplayPath = displayPath;
		selectedGithubRepo = null;
		clearLocalFolder();
		showRepoMenu = false;
	};

	// GitHub-clone source: clone owner/repo into the session (always clone-mode). Mutually
	// exclusive with a local/browsed repo — clear those so the chip + submit are unambiguous.
	const pickGithubRepo = (owner: string, name: string, branch?: string) => {
		selectedGithubRepo = { owner, name, branch };
		selectedRepoPath = '';
		selectedRepoDisplayPath = '';
		repoIsBrowsed = false;
		repoBrowsedRw = false;
		clearLocalFolder();
		isolationMode = 'session';
		showRepoMenu = false;
	};

	// Native OS folder picker (File System Access) → edit YOUR real folder, no server path.
	// When the browser doesn't expose it (Brave with FS-Access off, Firefox, Safari), fall
	// back to the server-side folder browser so the button still lets you point to a repo.
	const openFolder = async () => {
		showRepoMenu = false;
		if (!fsSupported) {
			// No File System Access API (Brave default, Firefox, Safari) → open the native OS
			// file explorer via a webkitdirectory input. Read-only snapshot (no live writeback).
			folderInputEl?.click();
			return;
		}
		pickingFolder = true;
		try {
			const handle = await pickLocalDirectory();
			const rec = await rememberFolder(handle);
			localFolderHandle = handle;
			localFolderName = handle.name;
			localFolderKey = rec.key;
			selectedRepoPath = '';
			selectedGithubRepo = null;
			repoIsBrowsed = false;
			isolationMode = 'session';
			recentFolders = await listRecentFolders();
		} catch (e: any) {
			const msg = String(e?.message ?? e);
			if (!/abort/i.test(msg)) toast.error(msg); // user-cancel = AbortError → silent
		} finally {
			pickingFolder = false;
		}
	};

	// webkitdirectory pick (Brave/Firefox/Safari): read the chosen folder's text files into a
	// one-shot snapshot and select it like a local folder (clone-mode, no live writeback).
	const onFolderPick = async (e: Event) => {
		const input = e.target as HTMLInputElement;
		const list = Array.from(input.files || []);
		input.value = '';
		if (!list.length) return;
		pickingFolder = true;
		seedingStatus = $i18n.t('Reading folder…');
		try {
			const rootName = (list[0].webkitRelativePath || list[0].name).split('/')[0] || 'folder';
			const SKIP = /(^|\/)(\.git|node_modules|\.venv|__pycache__|dist|build|\.next|\.svelte-kit)(\/|$)/;
			const decoder = new TextDecoder('utf-8', { fatal: false });
			const files: { path: string; content: string }[] = [];
			for (const f of list) {
				const rel = (f.webkitRelativePath || f.name).split('/').slice(1).join('/'); // strip root dir
				if (!rel || SKIP.test(rel) || f.size > 512 * 1024) continue;
				const buf = new Uint8Array(await f.arrayBuffer());
				let binary = false;
				for (let i = 0; i < Math.min(buf.length, 8000); i++) if (buf[i] === 0) { binary = true; break; }
				if (binary) continue;
				files.push({ path: rel, content: decoder.decode(buf) });
				seedingStatus = $i18n.t('Reading folder… {{n}} files', { n: files.length });
			}
			if (!files.length) {
				toast.error($i18n.t('That folder had no readable text files.'));
				return;
			}
			clearLocalFolder();
			localFolderFiles = files;
			localFolderName = rootName;
			selectedRepoPath = '';
			selectedRepoDisplayPath = '';
			repoIsBrowsed = false;
			selectedGithubRepo = null;
			isolationMode = 'session';
		} catch (err: any) {
			toast.error(String(err?.message ?? err));
		} finally {
			pickingFolder = false;
			seedingStatus = '';
		}
	};

	// Re-open a Recent folder — re-verify the handle's permission (needs a user gesture).
	const useRecentFolder = async (rec: RecentFolder) => {
		showRepoMenu = false;
		const ok = await verifyPermission(rec.handle, true);
		if (!ok) {
			toast.error($i18n.t('Permission to that folder was denied.'));
			return;
		}
		localFolderHandle = rec.handle;
		localFolderName = rec.name;
		localFolderKey = rec.key;
		selectedRepoPath = '';
		repoIsBrowsed = false;
		selectedGithubRepo = null;
		isolationMode = 'session';
		recentFolders = await listRecentFolders();
	};

	// The single "Open folder…" → the server-side host-folder browser. It lists the host tree the
	// backend can see (HARVIS_FS_BROWSE_ROOT_RW). NOT a native OS dialog — Harvis runs in a
	// container, so "local" = the host Harvis runs on, browsed server-side.
	const openServerBrowse = () => {
		showRepoMenu = false;
		folderBrowserRw = true; // browse the host tree; picks default to clone (see pickBrowsedRepo)
		showFolderBrowser = true;
	};
	const pickBrowsedRepo = (path: string, displayPath?: string, pickedRw = false) => {
		selectedRepoPath = path;
		selectedRepoDisplayPath = displayPath || '';
		// In-place ONLY when the tree is writable AND the deployer enabled it (gated server-side
		// too); otherwise the browsed folder is clone-mode (real files untouched, review the diff).
		const inplace = pickedRw && inplaceOnBrowsed;
		repoBrowsedRw = inplace;
		repoIsBrowsed = !inplace; // cloneOnly true → in-place toggle disabled when not eligible
		selectedGithubRepo = null;
		clearLocalFolder();
		isolationMode = inplace ? 'inplace' : 'session';
	};

	// Repo chip label — local folder name in a local session, else the repo's display path.
	$: repoChipLabel = sessionId
		? session?.repo_display_path ||
			session?.local_folder_name ||
			session?.repo_path?.split('/').filter(Boolean).pop() ||
			$i18n.t('No repo')
		: (selectedGithubRepo ? `${selectedGithubRepo.owner}/${selectedGithubRepo.name}` : '') ||
			localFolderName ||
			selectedRepoDisplayPath ||
			selectedRepo?.name ||
			(selectedRepoPath ? selectedRepoPath.split('/').filter(Boolean).pop() : '') ||
			$i18n.t('No repo');

	// ── Live write-back: after each turn, push the agent's changes to the real folder ──
	let lastWriteBackDone = -1; // doneTurns we last synced (−1 = uninitialised baseline)

	const applyWriteback = async () => {
		const wb = await getVibecodeWriteback(sessionId);
		if (wb.changed?.length) await writeFilesToFolder(localFolderHandle, wb.changed);
		if (wb.deleted?.length) await deleteFilesFromFolder(localFolderHandle, wb.deleted);
		return wb;
	};

	const maybeWriteBack = async () => {
		if (!session?.local_folder_name || !localFolderHandle || anyRunning) return;
		if (lastWriteBackDone === -1) {
			lastWriteBackDone = doneTurns; // baseline on first observation — don't write yet
			return;
		}
		if (doneTurns <= lastWriteBackDone) return;
		lastWriteBackDone = doneTurns;
		writeBackStatus = $i18n.t('Saving to your folder…');
		try {
			const wb = await applyWriteback();
			const n = (wb.changed?.length || 0) + (wb.deleted?.length || 0);
			if (n) toast.success($i18n.t('Saved changes to {{name}}', { name: localFolderName }));
		} catch (e: any) {
			toast.error($i18n.t('Could not write to your folder: {{err}}', { err: String(e?.message ?? e) }));
		} finally {
			writeBackStatus = '';
		}
	};

	// Reconnect a reopened local-folder session to its handle, then sync once.
	const relinkSessionFolder = async () => {
		if (!session?.local_folder_name || localFolderHandle) {
			needsRelink = false;
			return;
		}
		localFolderName = session.local_folder_name;
		const rec = await findFolderForSession(sessionId);
		if (rec && (await verifyPermission(rec.handle, true))) {
			localFolderHandle = rec.handle;
			localFolderName = rec.name;
			localFolderKey = rec.key;
			needsRelink = false;
			lastWriteBackDone = doneTurns; // already in sync — don't replay on reconnect
		} else {
			needsRelink = true;
		}
	};

	// User-triggered reconnect (re-grants permission, then writes accumulated changes back).
	const reconnectFolder = async () => {
		const rec = (await findFolderForSession(sessionId)) || recentFolders[0];
		if (!rec) {
			await openFolder();
			return;
		}
		if (!(await verifyPermission(rec.handle, true))) {
			toast.error($i18n.t('Permission to that folder was denied.'));
			return;
		}
		localFolderHandle = rec.handle;
		localFolderName = rec.name;
		localFolderKey = rec.key;
		needsRelink = false;
		await linkSessionToFolder(rec.key, sessionId);
		writeBackStatus = $i18n.t('Saving to your folder…');
		try {
			await applyWriteback();
			lastWriteBackDone = doneTurns;
			toast.success($i18n.t('Reconnected {{name}}', { name: localFolderName }));
		} catch (_) {
		} finally {
			writeBackStatus = '';
		}
	};

	let attachedImages: { id?: string; name: string; type: string; url: string }[] = [];
	let imageInputEl: HTMLInputElement;
	const onImagePick = async (e: Event) => {
		const input = e.target as HTMLInputElement;
		for (const f of Array.from(input.files || [])) {
			if (!f.type.startsWith('image/')) continue;
			try {
				const up: any = await uploadFile(localStorage.token, f);
				const id = up?.id;
				attachedImages = [
					...attachedImages,
					{ id, name: f.name, type: f.type, url: id ? `${WEBUI_BASE_URL}/api/v1/files/${id}/content` : '' }
				];
			} catch (_) {}
		}
		input.value = '';
	};
	const removeImage = (i: number) => {
		attachedImages = attachedImages.filter((_, idx) => idx !== i);
	};

	// ── Attach menu: the composer + opens a multi-choice popup (Add image / Attach files) ──
	let showAttachMenu = false;
	let fileAttachInputEl: HTMLInputElement;
	// Any-file attach (not just images) → same attachment pipeline; the backend inlines
	// text-like files into the brief and lists the rest for the agent.
	const onFileAttach = async (e: Event) => {
		const input = e.target as HTMLInputElement;
		for (const f of Array.from(input.files || [])) {
			try {
				const up: any = await uploadFile(localStorage.token, f);
				const id = up?.id;
				attachedImages = [
					...attachedImages,
					{ id, name: f.name, type: f.type, url: id ? `${WEBUI_BASE_URL}/api/v1/files/${id}/content` : '' }
				];
			} catch (_) {}
		}
		input.value = '';
	};

	// ── Approval gate: a paused edit/command awaiting your OK ──
	// Fires for any GATING run mode (Ask / Accept-edits) — on the clone lane too, not just
	// in-place. Plan blocks everything silently; Full-auto allows everything → neither pauses.
	let pendingAction: PendingAction | null = null;
	let approvalBusy = false;
	$: isInplace = activeIso === 'inplace';

	const pollPending = async () => {
		if (!anyRunning) {
			pendingAction = null;
			return;
		}
		const running = turns.find((t) => t.status === 'running');
		if (!running) {
			pendingAction = null;
			return;
		}
		pendingAction = await getPendingAction(running.id);
	};

	const resolvePending = async (approve: boolean) => {
		const running = turns.find((t) => t.status === 'running');
		if (!pendingAction || !running) return;
		approvalBusy = true;
		try {
			await resolveAction(running.id, pendingAction.action_id, approve);
			pendingAction = null;
		} catch (_) {
		} finally {
			approvalBusy = false;
		}
	};

	const submit = async () => {
		const text = prompt.trim();
		if (!text || composerDisabled) return;
		sending = true;
		sendError = '';
		stickBottom = true; // a new turn → follow the conversation down
		const attachments = attachedImages.map((im) => ({
			file_id: im.id,
			name: im.name,
			mime_type: im.type,
			url: im.url
		}));
		let createdId = '';
		try {
			if (!sessionId) {
				if (localFolderHandle) {
					// Local-folder session: create empty → snapshot the real folder → seed the
					// backend baseline → first turn. Edits flow back to the folder after each turn.
					const s = await createVibecodeSession({ local_folder_name: localFolderName, engine: selectedEngine });
					createdId = s.id;
					await linkSessionToFolder(localFolderKey, s.id);
					seedingStatus = $i18n.t('Reading folder…');
					const files = await readFolderSnapshot(localFolderHandle, (n) => {
						seedingStatus = $i18n.t('Reading folder… {{n}} files', { n });
					});
					seedingStatus = $i18n.t('Loading into workspace…');
					await seedVibecodeLocalFolder(s.id, files);
					seedingStatus = '';
					lastWriteBackDone = -1;
					await startVibecodeTurn(s.id, { task_brief: text, attachments, model_name: selectedModel || undefined, run_mode: runMode, orchestrate });
					prompt = '';
					attachedImages = [];
					goto(`/harvis/vibecode?session=${s.id}`);
				} else if (localFolderFiles.length) {
					// Read-only local folder (webkitdirectory — Brave/Firefox/Safari): seed the
					// snapshot → clone-mode session. No live writeback (no persistent handle).
					const s = await createVibecodeSession({ local_folder_name: localFolderName, engine: selectedEngine });
					createdId = s.id;
					seedingStatus = $i18n.t('Loading into workspace…');
					await seedVibecodeLocalFolder(s.id, localFolderFiles);
					seedingStatus = '';
					await startVibecodeTurn(s.id, { task_brief: text, attachments, model_name: selectedModel || undefined, run_mode: runMode, orchestrate });
					prompt = '';
					attachedImages = [];
					localFolderFiles = [];
					goto(`/harvis/vibecode?session=${s.id}`);
				} else if (selectedGithubRepo) {
					// GitHub-clone source → clone-mode session (the agent works on a copy; Create-PR
					// pushes back to the GitHub origin). Backend clones with the user's token if
					// connected, else tokenless (public repos).
					const s = await createVibecodeSession({
						github_owner: selectedGithubRepo.owner,
						github_repo: selectedGithubRepo.name,
						github_branch: selectedGithubRepo.branch,
						engine: selectedEngine
					});
					createdId = s.id;
					await startVibecodeTurn(s.id, { task_brief: text, attachments, model_name: selectedModel || undefined, run_mode: runMode, orchestrate });
					prompt = '';
					attachedImages = [];
					goto(`/harvis/vibecode?session=${s.id}`);
				} else {
					const s = await createVibecodeSession({
						repo_path: selectedRepoPath || undefined,
						isolation_mode: isolationMode,
						permission_mode: isolationMode === 'inplace' ? permissionMode : undefined,
						engine: selectedEngine
					});
					createdId = s.id;
					await startVibecodeTurn(s.id, { task_brief: text, attachments, model_name: selectedModel || undefined, run_mode: runMode, orchestrate });
					prompt = '';
					attachedImages = [];
					goto(`/harvis/vibecode?session=${s.id}`);
				}
			} else {
				await startVibecodeTurn(sessionId, { task_brief: text, attachments, model_name: selectedModel || undefined, run_mode: runMode, orchestrate });
				prompt = '';
				attachedImages = [];
				await loadSession();
				schedule();
			}
		} catch (e: any) {
			sendError = String(e?.message ?? e);
			if (createdId) goto(`/harvis/vibecode?session=${createdId}`);
		} finally {
			sending = false;
			seedingStatus = '';
		}
	};

	// ── Auto-follow the conversation: stick to the bottom as content streams in (new
	// turns, the live run card, the typewriter) — unless the user scrolled up to read.
	let threadScrollEl: HTMLDivElement;
	let stickBottom = true;
	const onThreadScroll = () => {
		if (!threadScrollEl) return;
		const { scrollTop, scrollHeight, clientHeight } = threadScrollEl;
		stickBottom = scrollHeight - scrollTop - clientHeight < 80;
	};
	const scrollThreadToBottom = () => {
		if (threadScrollEl) threadScrollEl.scrollTop = threadScrollEl.scrollHeight;
	};
	function autoFollow(node: HTMLElement) {
		const ro = new ResizeObserver(() => {
			if (stickBottom) scrollThreadToBottom();
		});
		ro.observe(node);
		return { destroy: () => ro.disconnect() };
	}

	// ── Type the assistant's answer out (not pasted) when a turn finishes LIVE. Turns that
	// were already done when the page loaded render instantly (no replay-typing on reload).
	const _sawRunning = new Set<string>();
	const _typedTurns = new Set<string>();
	let typingText: Record<string, string> = {};
	const typeOut = (id: string, full: string) => {
		if (!full) return;
		const dur = Math.max(700, Math.min(3600, full.length * 22));
		const start = performance.now();
		typingText = { ...typingText, [id]: '' };
		const step = () => {
			const frac = Math.min(1, (performance.now() - start) / dur);
			const n = Math.max(1, Math.floor(frac * full.length));
			typingText = { ...typingText, [id]: full.slice(0, n) };
			if (stickBottom) scrollThreadToBottom();
			if (frac < 1) {
				requestAnimationFrame(step);
			} else {
				const next = { ...typingText };
				delete next[id];
				typingText = next;
			}
		};
		requestAnimationFrame(step);
	};
	$: {
		for (const t of turns) {
			if (t.status === 'running') _sawRunning.add(t.id);
			else if (_sawRunning.has(t.id) && !_typedTurns.has(t.id)) {
				_typedTurns.add(t.id);
				if (t.status === 'done') typeOut(t.id, (t.final_summary || '').toString());
			}
		}
	}

	onMount(async () => {
		if (!enabled) return;
		// Pre-fill the model picker from the user's saved Integrations default model
		// (Phase C2/C3): localStorage cache → server fallback (cross-device). Only fills
		// when the slot is empty AND the model is actually available, so a default that
		// was removed since can never be sent as an invalid model.
		try {
			let d = localStorage.getItem('harvis.integrations.default_model') || '';
			// Always fetch the registry: we need either the default model OR per-engine readiness
			// (Phase E1/E2/E4 — each engine self-gates by its own flag, so we can't skip this when
			// a default model is cached). One cheap GET on mount.
			const reg = await getCapabilityRegistry(localStorage.token);
			if (!d && reg) {
				d = reg?.default_model || '';
				try {
					if (d) localStorage.setItem('harvis.integrations.default_model', d);
				} catch (_) {}
			}
			if (d && !selectedModel && ($models || []).some((m: any) => m?.id === d)) selectedModel = d;
			// Phase E1/E2/E4: read per-engine readiness whenever the registry loads (each engine
			// gates itself by its own flag, so Hermes surfaces even when the external-engines flag
			// is off). Default to the user's PREFERRED engine ONLY if it's ready (cloud never auto-
			// defaults unless preferred + verified; Hermes has no pref mapping, so it's opt-in).
			if (reg) {
				engineReadiness = (reg as any)?.engine_readiness || {};
				const pref = (reg?.preferences as any)?.code_engine_candidate; // provider id
				const prefEngine =
					pref === 'opencode' ? 'opencode'
					: pref === 'codex-app' ? 'codex'
					: pref === 'claude-code' ? 'claude-code'
					: null;
				selectedEngine = prefEngine && engineReadiness?.[prefEngine]?.ready ? prefEngine : 'native';
			}
		} catch (_) {}
		fsSupported = supportsLocalFs();
		if (fsSupported) recentFolders = await listRecentFolders();
		repos = await getAttachedRepos();
		await loadSession();
		await relinkSessionFolder();
		schedule();
	});
	onDestroy(() => clearTimeout(pollTimer));
</script>

<svelte:window on:keydown={(e) => e.key === 'Escape' && overlayRunId && (overlayRunId = '')} />

<svelte:head>
	<title>{$i18n.t('Vibe Code')} • {$WEBUI_NAME}</title>
</svelte:head>

{#if !enabled}
	<div
		class="w-full h-full flex flex-col items-center justify-center text-center px-4 {$showSidebar
			? 'md:max-w-[calc(100%-var(--sidebar-width))]'
			: ''}"
	>
		<h1 class="text-xl font-medium text-gray-800 dark:text-gray-100 mb-2">{$i18n.t('Vibe Code')}</h1>
		<p class="text-sm text-gray-500 max-w-md">
			{$i18n.t('The Harvis coding IDE is coming here. For now, ask Harvis to write or edit code in chat.')}
		</p>
	</div>
{:else}
	<div
		class="w-full h-full flex flex-col min-h-0 text-sm {$showSidebar
			? 'md:max-w-[calc(100%-var(--sidebar-width))]'
			: ''}"
	>
		<!-- BW2: Build header -->
		<BuildHeader
			projectName={hdrProjectName}
			hasProject={hdrHasProject}
			sourceLabel={hdrSourceLabel}
			isolationLabel={hdrIsoLabel}
			modeLabel={hdrModeLabel}
			model={displayModel}
			isRunning={anyRunning}
			panels={panelList}
			{dockOpen}
			on:stop={cancelRun}
			on:createPR={headerCreatePR}
			on:openRun={headerOpenRun}
			on:togglePanel={(e) => togglePanel(e.detail.key)}
			on:toggleDock={toggleDock}
			on:settings={() => setCustomize(true)}
		/>

		<!-- BW3 dock layout: main conversation (left, dominant) + resizable workspace dock (right) -->
		<div class="flex-1 min-h-0">
			<PaneGroup direction="horizontal" class="w-full h-full">
				<!-- MAIN conversation column (dominant) -->
				<Pane minSize={32} class="min-h-0">
					<div class="h-full flex flex-col min-h-0">
						<div class="flex-1 min-h-0 overflow-y-auto" bind:this={threadScrollEl} on:scroll={onThreadScroll}>
					{#if sessionId}
						<!-- Conversation thread — centered island column (buffered from the sidebar +
						     the right dock; aligns with the composer island below). `autoFollow` keeps
						     the view pinned to the bottom as content streams in. -->
						<div class="px-5 py-4 space-y-3 max-w-4xl mx-auto w-full" use:autoFollow>
					{#if !turns.length}
						<div class="text-xs text-gray-500 text-center pt-8">
							{$i18n.t('No turns yet — send a message to start coding.')}
						</div>
					{/if}
					{#each turns as t (t.id)}
						<div class="flex justify-end">
							<div
								class="max-w-[68%] rounded-2xl rounded-br-md border border-white/8 bg-white/[0.03] px-3.5 py-2 text-gray-100"
							>
								{#if t.attachments && t.attachments.length}
									<!-- The user's attachments stay in the chat: images inline, other files as chips. -->
									<div class="flex flex-wrap gap-2 {t.task_brief ? 'mb-2' : ''}">
										{#each t.attachments as att}
											{#if (att.mime_type || '').startsWith('image/') && att.url}
												<img
													src={att.url}
													alt={att.name || 'attachment'}
													class="max-h-44 max-w-[14rem] rounded-lg border border-gray-200 dark:border-gray-700 object-contain"
												/>
											{:else}
												<span
													class="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-lg border border-white/8 bg-white/6 text-gray-300"
													>📎 {att.name || $i18n.t('file')}</span
												>
											{/if}
										{/each}
									</div>
								{/if}
								{#if t.task_brief}<div class="whitespace-pre-wrap">{t.task_brief}</div>{/if}
							</div>
						</div>
						{#if t.status === 'running'}
							<!-- live run while Harvis works -->
							<div class="rounded-xl border border-white/8 overflow-hidden bg-[#0b101b]">
								{#key t.id}<RunView wsId={t.id} mode="dock" title={t.task_brief} />{/key}
							</div>
						{:else}
							<!-- assistant reply: "the AI's domain" — unbubbled, full-width (matches the main
							     chat). Only the user's message above is bubbled. Full run is one click away. -->
							<div class="flex flex-col items-start gap-1.5 w-full">
								<div
									class="w-full text-sm text-gray-100 markdown-prose markdown-prose-sm"
								>
									{#if t.analysis_md}
										<!-- Build Result Narrator: the full written analysis IS the assistant message. -->
										<Markdown id={`vc-turn-${t.id}`} content={t.analysis_md} />
									{:else if t.status === 'error'}
										<span class="text-red-500 dark:text-red-400"
											>{t.error_message || $i18n.t('This turn failed.')}</span
										>
									{:else if typingText[t.id] !== undefined}
										<!-- typing the answer out (not pasted) — plain text + cursor while it
										     streams, then the full markdown render once it finishes. -->
										<div class="whitespace-pre-wrap break-words">{typingText[t.id]}<span
												class="text-gray-500 animate-pulse">▍</span
											></div>
									{:else}
										<Markdown id={`vc-turn-${t.id}`} content={cleanSummary(t.final_summary) || $i18n.t('Done.')} />
									{/if}
								</div>
								{#if typingText[t.id] === undefined}
									<!-- Actions row below the analysis: View run details · Create PR · Download. -->
									<BuildActions
										run={t}
										{sessionId}
										expanded={!!expandedRuns[t.id]}
										onOpenRun={() => toggleRun(t.id)}
									/>
								{/if}
								{#if expandedRuns[t.id]}
									<div
										class="w-full rounded-xl border border-white/8 overflow-hidden bg-[#0b101b]"
									>
										{#key t.id}<RunView wsId={t.id} mode="dock" title={t.task_brief} />{/key}
									</div>
								{/if}
							</div>
						{/if}
					{/each}
				</div>
					{/if}
							{#if !sessionId}
								<div class="h-full flex flex-col items-center justify-center text-center px-6">
									<div class="text-lg font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Start a coding session')}</div>
									<div class="mt-1.5 max-w-md text-xs text-gray-500">{$i18n.t('Pick a repo and mode below, describe a task, and Harvis works — each follow-up builds on the last.')}</div>
								</div>
							{/if}
						</div>
						<!-- composer under the conversation — a centered floating island (not a
						     full-width bar), buffered from the sidebar + dock to match the thread. -->
		<div class="shrink-0 px-5 pb-4 pt-2">
				<div class="w-full max-w-4xl mx-auto rounded-2xl border border-white/10 bg-[#0c111d] p-2.5 shadow-lg shadow-black/30">
					<!-- attached image chips -->
					{#if attachedImages.length}
						<div class="flex flex-wrap gap-2 mb-2">
							{#each attachedImages as im, i}
								<div class="relative group">
									{#if im.type?.startsWith('image/')}
										<img
											src={im.url}
											alt={im.name}
											class="h-14 w-14 object-cover rounded-lg border border-gray-200 dark:border-gray-800"
										/>
									{:else}
										<div class="h-14 max-w-[11rem] px-3 flex items-center gap-2 rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-850">
											<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" class="size-4 shrink-0 text-gray-400"><path d="M14 3v5h5M14 3l5 5v11a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" stroke-linejoin="round" /></svg>
											<span class="text-[11px] text-gray-600 dark:text-gray-300 truncate">{im.name}</span>
										</div>
									{/if}
									<button
										class="absolute -top-1.5 -right-1.5 size-4 rounded-full bg-gray-700 text-white text-[10px] flex items-center justify-center opacity-0 group-hover:opacity-100 transition"
										on:click={() => removeImage(i)}>×</button
									>
								</div>
							{/each}
						</div>
					{/if}

					<!-- context-chip row -->
					<div class="flex items-center gap-2 mb-2">
						<!-- Execution-target chip → dropdown (Local = live; SSH = coming-soon seam) -->
						<div class="relative">
							<button
								class="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-800"
								on:click={() => (showExecMenu = !showExecMenu)}
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.8"
									class="size-3.5"
									><rect x="2" y="3" width="20" height="14" rx="2" /><path
										d="M8 21h8M12 17v4"
										stroke-linecap="round"
									/></svg
								>
								{$i18n.t('Local')}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 20 20"
									fill="currentColor"
									class="size-3 text-gray-400"
									><path
										fill-rule="evenodd"
										d="M5.23 7.21a.75.75 0 0 1 1.06.02L10 11.17l3.71-3.94a.75.75 0 1 1 1.08 1.04l-4.25 4.5a.75.75 0 0 1-1.08 0l-4.25-4.5a.75.75 0 0 1 .02-1.06z"
										clip-rule="evenodd"
									/></svg
								>
							</button>
							{#if showExecMenu}
								<div
									class="absolute bottom-full mb-1 left-0 z-30 w-56 rounded-xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 shadow-lg py-1 text-xs"
								>
									<div class="px-3 pt-1.5 pb-0.5 text-[10px] uppercase tracking-wide text-gray-400">
										{$i18n.t('Local')}
									</div>
									<button
										class="w-full flex items-center justify-between gap-2 px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
										on:click={() => (showExecMenu = false)}
									>
										<span class="flex items-center gap-2">
											<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-3.5"><rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" stroke-linecap="round" /></svg>
											{$i18n.t('This machine')}
										</span>
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-3.5 shrink-0 text-blue-500"><path d="M20 6 9 17l-5-5" stroke-linecap="round" stroke-linejoin="round" /></svg>
									</button>
									<div class="border-t border-gray-100 dark:border-gray-800 my-1"></div>
									<div class="px-3 pt-1 pb-0.5 text-[10px] uppercase tracking-wide text-gray-400">
										{$i18n.t('SSH')}
									</div>
									<button
										class="w-full flex items-center gap-2 px-3 py-1.5 text-gray-400 cursor-not-allowed"
										disabled
										title={$i18n.t('Code on another machine over SSH — a later phase, gated behind the permission ladder')}
									>
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-3.5"><path d="M12 5v14M5 12h14" stroke-linecap="round" /></svg>
										{$i18n.t('Add SSH host…')}
										<span class="ml-auto text-[10px]">{$i18n.t('soon')}</span>
									</button>
								</div>
							{/if}
						</div>

						<!-- repo chip -->
						<div class="relative">
							<button
								class="inline-flex items-center gap-1.5 text-[11px] px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 text-gray-600 dark:text-gray-300 {sessionId
									? 'cursor-default'
									: 'hover:bg-gray-200 dark:hover:bg-gray-800'}"
								on:click={() => {
									if (!sessionId) showRepoMenu = !showRepoMenu;
								}}
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.8"
									class="size-3.5"
									><path
										d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"
										stroke-linejoin="round"
									/></svg
								>
								{repoChipLabel}
							</button>
							{#if showRepoMenu && !sessionId}
								<div
									class="absolute bottom-full mb-1 left-0 z-30 w-60 rounded-xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 shadow-lg py-1 text-xs"
								>
									{#if offerRepos.length}
										<div class="px-3 pt-2 pb-1 text-[10px] uppercase tracking-wide text-gray-400">
											{$i18n.t('Recent')}
										</div>
										{#each offerRepos as r}
											<button
												class="w-full flex items-center justify-between gap-2 text-left px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
												on:click={() => pickRepo(r.path)}
											>
												<span class="truncate">{r.name}{r.branch ? ` · ${r.branch}` : ''}</span>
												{#if selectedRepoPath === r.path}
													<svg
														xmlns="http://www.w3.org/2000/svg"
														viewBox="0 0 24 24"
														fill="none"
														stroke="currentColor"
														stroke-width="2"
														class="size-3.5 shrink-0"
														><path d="M20 6 9 17l-5-5" stroke-linecap="round" stroke-linejoin="round" /></svg
													>
												{/if}
											</button>
										{/each}
										<div class="border-t border-gray-100 dark:border-gray-800 my-1"></div>
									{/if}

									{#if isolationMode === 'session'}
										<button
											class="w-full flex items-center justify-between gap-2 text-left px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
											on:click={() => pickRepo('')}
										>
											<span>{$i18n.t('None (scratch)')}</span>
											{#if !selectedRepoPath}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													viewBox="0 0 24 24"
													fill="none"
													stroke="currentColor"
													stroke-width="2"
													class="size-3.5 shrink-0"
													><path d="M20 6 9 17l-5-5" stroke-linecap="round" stroke-linejoin="round" /></svg
												>
											{/if}
										</button>
									{/if}
									<!-- GitHub: connect → pick a repo (or clone a public repo by name), clone-mode -->
									<button
										class="w-full text-left px-3 py-1.5 text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-850"
										title={$i18n.t('Clone a GitHub repository into a session')}
										on:click={() => {
											showRepoMenu = false;
											showGithubModal = true;
										}}>{$i18n.t('GitHub repo…')}</button
									>
								</div>
							{/if}
						</div>
					</div>

					<!-- local-folder status / reconnect banner -->
					{#if seedingStatus || writeBackStatus}
						<div
							class="flex items-center gap-2 mb-2 text-[11px] text-gray-500 dark:text-gray-400"
						>
							<svg class="size-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
								<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" />
								<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8V0C5.4 0 0 5.4 0 12h4z" />
							</svg>
							{seedingStatus || writeBackStatus}
						</div>
					{/if}
					{#if sessionId && session?.local_folder_name && needsRelink && !writeBackStatus}
						<div
							class="flex items-center justify-between gap-2 mb-2 text-[11px] px-2.5 py-1.5 border border-amber-500/20 bg-amber-500/10 text-amber-300"
						>
							<span class="truncate"
								>{$i18n.t('Reconnect "{{name}}" so edits save back to your computer.', {
									name: session.local_folder_name
								})}</span
							>
							<button
								class="shrink-0 font-medium underline hover:no-underline"
								on:click={reconnectFolder}>{$i18n.t('Reconnect')}</button
							>
						</div>
					{/if}

					<!-- input — clean single-line bar; subtle ⏎ (Enter sends, Shift+Enter = newline) -->
					<div class="relative">
						<textarea
							bind:this={promptEl}
							class="w-full text-sm bg-transparent py-2 pl-2 pr-10 outline-none resize-none disabled:opacity-50 leading-relaxed text-gray-100 placeholder:text-gray-500"
							style="max-height: 160px"
							rows="1"
							placeholder={sessionId ? $i18n.t('Send a follow-up…') : $i18n.t('Describe a task or ask a question')}
							bind:value={prompt}
							disabled={composerDisabled}
							on:input={autogrow}
							on:keydown={(e) => {
								if (e.key === 'Enter' && !e.shiftKey) {
									e.preventDefault();
									submit();
								}
							}}
						></textarea>
						<button
							class="absolute right-2 bottom-1.5 size-7 rounded-lg flex items-center justify-center transition {composerDisabled || !prompt.trim()
								? 'bg-white/6 text-gray-500 cursor-not-allowed'
								: 'bg-blue-600 hover:bg-blue-500 text-white shadow-sm'}"
							disabled={composerDisabled || !prompt.trim()}
							on:click={submit}
							aria-label={sessionId ? $i18n.t('Send') : $i18n.t('Start')}
							title={sessionId ? $i18n.t('Send') : $i18n.t('Start')}
						>
							{#if sending}
								<svg class="size-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" /><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8V0C5.4 0 0 5.4 0 12h4z" /></svg>
							{:else}
								<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-4"><path d="M12 19V5M5 12l7-7 7 7" stroke-linecap="round" stroke-linejoin="round" /></svg>
							{/if}
						</button>
					</div>

					<!-- toolbar -->
					<div class="flex items-center gap-1.5 mt-2">
						{#if showEngineSelector}
							<!-- Phase E1/E2: external Build engine — Native (OpenClaw) + each ready engine. -->
							<!-- Build-engine chip → dropdown. Defaults to your Integrations preference
							     (Save preference on a card); this is the per-session override. -->
							<div class="relative">
								<button
									type="button"
									class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border border-white/8 bg-white/4 hover:bg-white/8 transition {selectedEngine !==
									'native'
										? 'text-teal-300'
										: 'text-gray-300'}"
									title={$i18n.t('Build engine for this session')}
									on:click={() => (showEngineMenu = !showEngineMenu)}
								>
									<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" class="size-3.5"><path d="M12 2 3 7v10l9 5 9-5V7l-9-5z" stroke-linejoin="round" /><path d="M3 7l9 5 9-5M12 12v10" stroke-linejoin="round" /></svg>
									{selectedEngine === 'native' ? $i18n.t('Native') : ENGINE_LABELS[selectedEngine] || selectedEngine}
									<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="size-3 text-gray-400"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 0 1 1.06.02L10 11.17l3.71-3.94a.75.75 0 1 1 1.08 1.04l-4.25 4.5a.75.75 0 0 1-1.08 0l-4.25-4.5a.75.75 0 0 1 .02-1.06z" clip-rule="evenodd" /></svg>
								</button>
								{#if showEngineMenu}
									<div class="absolute bottom-full mb-1 left-0 z-30 w-56 rounded-xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 shadow-lg py-1 text-xs">
										<div class="px-3 pt-1.5 pb-0.5 text-[10px] uppercase tracking-wide text-gray-400">
											{$i18n.t('Build engine')}
										</div>
										<button
											class="w-full flex items-center justify-between gap-2 px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
											on:click={() => {
												selectedEngine = 'native';
												showEngineMenu = false;
											}}
										>
											<span>{$i18n.t('Native (OpenClaw)')}</span>
											{#if selectedEngine === 'native'}<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-3.5 shrink-0 text-blue-500"><path d="M20 6 9 17l-5-5" stroke-linecap="round" stroke-linejoin="round" /></svg>{/if}
										</button>
										{#each readyEngineIds as eid}
											<button
												class="w-full flex items-center justify-between gap-2 px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-850"
												on:click={() => {
													selectedEngine = eid;
													showEngineMenu = false;
												}}
											>
												<span>{ENGINE_LABELS[eid] || eid}</span>
												{#if selectedEngine === eid}<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-3.5 shrink-0 text-blue-500"><path d="M20 6 9 17l-5-5" stroke-linecap="round" stroke-linejoin="round" /></svg>{/if}
											</button>
										{/each}
										<div class="border-t border-gray-100 dark:border-gray-800 my-1"></div>
										<div class="px-3 py-1 text-[10px] text-gray-400">
											{$i18n.t('Set a default in Integrations → Save preference.')}
										</div>
									</div>
								{/if}
							</div>
						{/if}
						{#if hermesNeedsModel}
							<span class="text-[11px] text-amber-400/80"
								>{$i18n.t('Pull a Hermes model to enable the Hermes engine.')}</span
							>
						{/if}
						{#if selectedEngine !== 'native'}
							<span class="text-[11px] text-gray-500"
								>{ENGINE_LABELS[selectedEngine] || selectedEngine}
								{$i18n.t('runs autonomously on a clone — review the diff.')}</span
							>
						{/if}
						{#if selectedEngine === 'native'}
						<!-- Run-mode = the permission PYRAMID (per turn): Plan ▸ Ask ▸ Accept ▸ Auto.
						     The agent works on a clone; the diff/PR is the outer gate. -->
						<div class="relative">
							<button
								type="button"
								class="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border transition hover:opacity-90 {runMode ===
								'plan'
									? 'border-white/8 bg-white/4 text-gray-300'
									: runMode === 'full-auto'
										? 'border-amber-500/20 bg-amber-500/10 text-amber-300'
										: 'border-sky-500/20 bg-sky-500/10 text-sky-300'}"
								title={$i18n.t('Run mode — how much the agent does on its own this turn')}
								on:click={() => (showModeMenu = !showModeMenu)}
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.8"
									class="size-3.5"
									><path d="M12 4 4 19h16L12 4Z" stroke-linejoin="round" /><path
										d="M8.5 14h7M10 11h4"
										stroke-linecap="round"
									/></svg
								>
								{PERM_SHORT[runMode] || 'Auto'}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="2"
									class="size-3"><path d="M6 9l6 6 6-6" stroke-linecap="round" /></svg
								>
							</button>
							{#if showModeMenu}
								<div
									class="absolute bottom-full mb-1 left-0 z-30 w-64 rounded-xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 shadow-lg p-1.5"
								>
									<div
										class="px-2 pt-1 pb-1.5 flex items-center justify-between text-[10px] uppercase tracking-wider text-gray-400"
									>
										<span>{$i18n.t('Run mode')}</span>
										<span>↑ {$i18n.t('more autonomy')}</span>
									</div>
									{#each RUN_LADDER as rung, i}
										<button
											type="button"
											class="w-full text-left rounded-lg px-2.5 py-1.5 transition flex items-start gap-2 {runMode ===
											rung.mode
												? 'bg-gray-100 dark:bg-gray-850'
												: 'hover:bg-gray-50 dark:hover:bg-gray-850/60'}"
											style="margin-left:{(RUN_LADDER.length - 1 - i) *
												8}px; margin-right:{(RUN_LADDER.length - 1 - i) * 8}px"
											on:click={() => setRunMode(rung.mode)}
										>
											<span
												class="mt-1 size-2 rounded-full shrink-0 {runMode === rung.mode
													? rung.mode === 'full-auto'
														? 'bg-amber-500'
														: rung.mode === 'plan'
															? 'bg-gray-400'
															: 'bg-blue-500'
													: 'border border-gray-300 dark:border-gray-600'}"
											></span>
											<span class="min-w-0">
												<span class="block text-xs font-medium text-gray-800 dark:text-gray-100"
													>{$i18n.t(rung.label)}{#if runMode === rung.mode}<span class="text-gray-400"
															> · {$i18n.t('current')}</span
														>{/if}</span
												>
												<span class="block text-[11px] text-gray-400 leading-snug">{$i18n.t(rung.desc)}</span>
											</span>
										</button>
									{/each}
									<div class="px-2 pt-1 text-[10px] text-gray-400">↓ {$i18n.t('safer · read-only')}</div>
								</div>
							{/if}
						</div>

						<!-- Orchestrate = fan this turn out to N task-delegated sub-agents (the planner
						     picks 3–10). The multi-agent run shows live in Background tasks. -->
						<button
							type="button"
							class="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border transition hover:opacity-90 {orchestrate
								? 'border-violet-500/30 bg-violet-500/12 text-violet-300'
								: 'border-white/8 bg-white/4 text-gray-400 hover:text-gray-200'}"
							title={$i18n.t('Orchestrate — fan this task out to multiple task-delegated agents')}
							on:click={() => (orchestrate = !orchestrate)}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.8"
								class="size-3.5"
								><circle cx="12" cy="5" r="2" /><circle cx="5" cy="19" r="2" /><circle
									cx="19"
									cy="19"
									r="2"
								/><path d="M12 7v3m0 0-5 7m5-7 5 7" stroke-linecap="round" stroke-linejoin="round" /></svg
							>
							{$i18n.t('Agents')}
						</button>
						{/if}

						<!-- attach menu: the + opens a multi-choice popup (Add image / Attach files) -->
						<div class="relative">
							<button
								class="text-gray-500 hover:text-gray-200 p-1.5"
								title={$i18n.t('Add attachment')}
								on:click={() => (showAttachMenu = !showAttachMenu)}
							>
								<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-4"><path d="M12 5v14M5 12h14" stroke-linecap="round" /></svg>
							</button>
							{#if showAttachMenu}
								<div
									class="absolute bottom-full mb-1 left-0 z-30 w-52 rounded-2xl bg-white dark:bg-gray-850 border border-gray-100 dark:border-gray-800 shadow-lg p-1"
								>
								<button
									class="flex w-full gap-2 items-center px-3 py-1.5 text-sm rounded-xl hover:bg-gray-50 dark:hover:bg-gray-800/60 text-gray-700 dark:text-gray-200"
									on:click={() => { showAttachMenu = false; imageInputEl?.click(); }}
								>
									<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-4 shrink-0 text-gray-400"><rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" stroke-linecap="round" stroke-linejoin="round" /></svg>
									<span class="flex-1 text-left">{$i18n.t('Add image')}</span>
									<span class="text-[10px] text-gray-400">{$i18n.t('Ctrl+U')}</span>
								</button>
								<button
									class="flex w-full gap-2 items-center px-3 py-1.5 text-sm rounded-xl hover:bg-gray-50 dark:hover:bg-gray-800/60 text-gray-700 dark:text-gray-200"
									on:click={() => { showAttachMenu = false; fileAttachInputEl?.click(); }}
								>
									<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-4 shrink-0 text-gray-400"><path d="M21.44 11.05l-9.19 9.19a5 5 0 0 1-7.07-7.07l9.19-9.19a3.5 3.5 0 0 1 4.95 4.95l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" stroke-linecap="round" stroke-linejoin="round" /></svg>
									<span class="flex-1 text-left">{$i18n.t('Attach files')}</span>
								</button>
								</div>
							{/if}
						</div>
						<input
							type="file"
							accept="image/*"
							multiple
							class="hidden"
							bind:this={imageInputEl}
							on:change={onImagePick}
						/>
						<!-- generic any-file attach (Attach files menu item) -->
						<input
							type="file"
							multiple
							class="hidden"
							bind:this={fileAttachInputEl}
							on:change={onFileAttach}
						/>
						<!-- hidden native OS folder picker (webkitdirectory) for browsers without File
						     System Access (Brave/Firefox/Safari) — opened by the box-+ / Open-folder button. -->
						<input
							type="file"
							webkitdirectory
							multiple
							class="hidden"
							bind:this={folderInputEl}
							on:change={onFolderPick}
						/>

						<!-- mic (placeholder) -->
						<button
							class="text-gray-600 p-1.5 cursor-default"
							title={$i18n.t('Voice (coming soon)')}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="1.8"
								class="size-4"
								><rect x="9" y="2" width="6" height="12" rx="3" /><path
									d="M5 10a7 7 0 0 0 14 0M12 19v3"
									stroke-linecap="round"
								/></svg
							>
						</button>

						<div class="flex-1"></div>

						<!-- model selector → pick from available models -->
						<div class="relative">
							<button
								class="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-lg border border-white/8 bg-white/4 text-gray-300 hover:bg-white/8 transition max-w-[10rem]"
								on:click={() => (showModelMenu = !showModelMenu)}
								title={$i18n.t('Model')}
							>
								<span class="truncate">{displayModel}</span>
								<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-3 shrink-0"><path d="M6 9l6 6 6-6" stroke-linecap="round" /></svg>
							</button>
							{#if showModelMenu}
								<div class="absolute bottom-full right-0 mb-1 z-40 w-60 max-h-64 overflow-y-auto rounded-xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 shadow-xl py-1 text-xs">
									<div class="px-3 pt-1.5 pb-1 text-[10px] uppercase tracking-wider text-gray-400">{$i18n.t('Model')}</div>
									{#if !modelOptions.length}
										<div class="px-3 py-1.5 text-gray-400">{$i18n.t('No models available.')}</div>
									{/if}
									{#each modelOptions as m}
										<button class="w-full flex items-center justify-between gap-2 text-left px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-850" on:click={() => pickModel(m.id)}>
											<span class="truncate">{m.name || m.id}</span>
											{#if displayModel === m.id}<span class="shrink-0 text-blue-500">✓</span>{/if}
										</button>
									{/each}
								</div>
							{/if}
						</div>

						<!-- model + context/token usage (logs real tokens used vs the context window) -->
						<!-- usage gauge → click for the full context/token breakdown -->
						<div class="relative hidden sm:block">
							<button
								class="flex items-center gap-2 text-[10px] text-gray-500 px-1.5 py-1 hover:bg-white/4 transition"
								on:click={() => (showUsageStats = !showUsageStats)}
								title={$i18n.t('Context & token usage')}
							>
								<div class="flex flex-col items-end leading-tight">
									<span class="tabular-nums text-gray-500 dark:text-gray-400">{fmtTok(ctxUsed)} / {fmtTok(ctxWindow)} · {ctxPct}%</span>
									<span class="text-gray-400 dark:text-gray-500 tabular-nums">{#if isFreeModel}{$i18n.t('Free')}{:else}{fmtCost(liveCost)}{/if} · {fmtTok(liveSessionTokens)} tok</span>
								</div>
								<div class="w-14 h-1.5 rounded-full bg-gray-200 dark:bg-gray-800 overflow-hidden">
									<div class="h-full rounded-full transition-all {liveOn ? 'animate-pulse ' : ''}{ctxPct > 85 ? 'bg-red-500' : 'bg-blue-500'}" style="width: {ctxPct}%"></div>
								</div>
							</button>
							{#if showUsageStats}
								<div class="absolute bottom-full right-0 mb-1 z-40 w-64 rounded-2xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 shadow-xl p-3 text-xs space-y-2">
									<div class="flex items-center justify-between text-gray-700 dark:text-gray-200 font-medium">
										<span>{$i18n.t('Context window')}</span>
										<span class="tabular-nums">{ctxUsed.toLocaleString()} / {ctxWindow.toLocaleString()}</span>
									</div>
									<div class="w-full h-2 rounded-full bg-gray-200 dark:bg-gray-800 overflow-hidden">
										<div class="h-full rounded-full {ctxPct > 85 ? 'bg-red-500' : 'bg-blue-500'}" style="width: {ctxPct}%"></div>
									</div>
									<div class="flex justify-between text-gray-500"><span>{$i18n.t('Used')}</span><span class="tabular-nums">{ctxPct}%</span></div>
									<div class="flex justify-between text-gray-500"><span>{$i18n.t('Available')}</span><span class="tabular-nums">{ctxAvail.toLocaleString()} {$i18n.t('tokens')}</span></div>
									<div class="border-t border-gray-100 dark:border-gray-800"></div>
									<div class="flex justify-between text-gray-500"><span>{$i18n.t('Last turn')}</span><span class="tabular-nums">↑ {(lastUsage?.prompt_tokens || 0).toLocaleString()} · ↓ {(lastUsage?.completion_tokens || 0).toLocaleString()}</span></div>
									<div class="flex justify-between text-gray-500"><span>{$i18n.t('Session total')}</span><span class="tabular-nums">{liveSessionTokens.toLocaleString()} · {usageTurns.length} {$i18n.t('turns')}</span></div>
									<div class="flex justify-between text-gray-500">
										<span>{$i18n.t('Est. cost')}</span>
										<span class="tabular-nums text-gray-700 dark:text-gray-300">
											{#if isFreeModel}{$i18n.t('Free · local')}{:else}{fmtCost(liveCost)}{#if isSubscriptionModel} <span class="text-gray-400">· {$i18n.t('at API rates')}</span>{/if}{/if}
										</span>
									</div>
									<div class="flex justify-between text-gray-500"><span>{$i18n.t('Model')}</span><span class="truncate ml-2 text-gray-700 dark:text-gray-300">{displayModel}</span></div>
								</div>
							{/if}
						</div>
						
						{#if anyRunning}<span class="text-[11px] text-gray-500">{$i18n.t('Working…')}</span>{/if}
					</div>
					{#if sendError}<div class="text-[11px] text-red-500 mt-1">{sendError}</div>{/if}
					</div>
				</div>
					</div>
				</Pane>
				{#if (dockOpen && (topHasAny || bottomHasAny)) || overlayRunId}
					<PaneResizer class="w-1.5 shrink-0 bg-gray-100 dark:bg-gray-850 hover:bg-blue-400 dark:hover:bg-blue-500 transition" />
					<!-- RIGHT PANE: the workspace 2×2 dock, OR the Workflow Inspector when a run is
					     open — the inspector pushes the chat narrower instead of taking over the page. -->
					<Pane bind:pane={rightPane} defaultSize={overlayRunId ? inspectorSize : dockSize} minSize={22} maxSize={72} class="min-h-0 bg-[#070b13]">
						{#if (topHasAny || bottomHasAny) || overlayRunId}
						<!-- When a run is open the inspector sits BESIDE the workspace dock (not over it),
						     so the panels stay usable; the dock shrinks to a side strip. -->
						<div class="flex h-full min-h-0">
						{#if topHasAny || bottomHasAny}
						<div class="h-full min-h-0 min-w-0 overflow-hidden order-last {overlayRunId ? 'border-l border-white/8' : ''}" style={overlayRunId ? 'flex: 0 0 38%' : 'flex: 1 1 100%'}>
							<!-- Tabbed dock (Claude-Code-Desktop style): a tab strip over ONE full-height
							     panel. The ⋯ menu still decides which tabs exist; the strip switches. -->
							<div class="h-full p-1">
							<div class="flex flex-col min-h-0 h-full bg-[#0c111d] rounded-xl border border-white/8 shadow-lg shadow-black/30 overflow-hidden text-gray-200">
								<!-- tab strip -->
								<div class="shrink-0 flex items-center gap-0 px-2 border-b border-white/8 bg-white/[0.015]">
									{#each dockTabs as t (t.key)}
										<button
											type="button"
											class="relative px-3 py-2 text-[11px] font-medium transition {dockTab === t.key
												? 'text-gray-100'
												: 'text-gray-500 hover:text-gray-300'}"
											on:click={() => setDockTab(t.key)}
										>
											<span class="inline-flex items-center gap-1.5">
												{t.label}
												{#if t.key === 'tl' && runningTasks.length}
													<span class="inline-flex items-center justify-center min-w-4 h-4 px-1 rounded-full bg-blue-500/20 text-blue-300 text-[10px] tabular-nums leading-none">{runningTasks.length}</span>
												{/if}
											</span>
											{#if dockTab === t.key}
												<span class="absolute left-2 right-2 -bottom-px h-px bg-sky-400"></span>
											{/if}
										</button>
									{/each}
									<button
										type="button"
										class="ml-auto shrink-0 text-gray-500 hover:text-gray-200 transition p-1.5"
										aria-label={$i18n.t('Hide this panel')}
										title={$i18n.t('Hide this panel')}
										on:click={() => togglePanel(dockTab)}
									>
										<svg viewBox="0 0 20 20" fill="currentColor" class="size-3.5"><path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" /></svg>
									</button>
								</div>
								<!-- active panel -->
								{#if dockTab === 'tl'}
									<div class="flex-1 min-h-0 overflow-y-auto">
										<div class="p-2 space-y-2">
											{#if runningTasks.length}
												<div class="px-1 text-[10px] uppercase tracking-wider text-gray-500">{$i18n.t('Running')}</div>
												{#each runningTasks as t (t.id)}
													<BackgroundTaskCard run={t} live autoExpand={(t.child_count || 0) > 1} on:stop={(e) => cancelRunId(e.detail.id)} on:openRun={(e) => headerOpenRunId(e.detail.id)} on:viewLogs={(e) => viewLogs(e.detail.id, e.detail.agentTab)} />
												{/each}
											{/if}
											{#if finishedTasks.length}
												<div class="flex items-center justify-between px-1 pt-1">
													<button class="flex items-center gap-1 text-[10px] uppercase tracking-wider text-gray-500 hover:text-gray-300 transition" on:click={() => (showFinished = !showFinished)}>
														<svg class="size-3 transition-transform {showFinished ? 'rotate-90' : ''}" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 0 1 .02-1.06L11.168 10 7.23 6.29a.75.75 0 1 1 1.04-1.08l4.5 4.25a.75.75 0 0 1 0 1.08l-4.5 4.25a.75.75 0 0 1-1.06-.02Z" clip-rule="evenodd" /></svg>
														<span>{$i18n.t('Finished')} {finishedTasks.length}</span>
													</button>
													<button class="text-[10px] text-blue-400 hover:underline" on:click={clearBg}>{$i18n.t('Clear')}</button>
												</div>
												{#if showFinished}
													{#each finishedTasks as t (t.id)}
														<BackgroundTaskCard run={t} on:openRun={(e) => headerOpenRunId(e.detail.id)} on:viewLogs={(e) => viewLogs(e.detail.id, e.detail.agentTab)} />
													{/each}
												{/if}
											{/if}
											{#if !runningTasks.length && !finishedTasks.length}
												<div class="text-xs text-gray-500 px-1 py-2">{$i18n.t('Nothing running.')}</div>
											{/if}
										</div>
									</div>
								{:else if dockTab === 'bl'}
									<div class="flex-1 min-h-0 overflow-y-auto">
										{#if latestTurnId}
											<div class="p-2"><PlanPanel wsId={latestTurnId} on:steps={(e) => (planStepCount = e.detail.count)} /></div>
										{:else}
											<div class="p-3 text-[11px] text-gray-500 leading-snug">{$i18n.t('No plan yet. Harvis will outline steps here once an agent starts working.')}</div>
										{/if}
									</div>
								{:else if dockTab === 'tr'}
									<div class="flex-1 min-h-0">
										<WorkspaceFileRail bind:tab={fileTab} {changedFiles} {artifacts} {selectedFile} on:select={(e) => onFileSelect(e.detail.path)} on:selectArtifact={(e) => onArtifactSelect(e.detail.id)} />
									</div>
								{:else if dockTab === 'sh'}
									<div class="flex-1 min-h-0">
										<ShellTab {sessionId} />
									</div>
								{:else}
									<div class="flex-1 min-h-0">
										<WorkspaceMainPanel showChat={false} bind:tab={mainTab} {selectedFile} diffLines={selectedFileObj ? selectedFileObj.lines : []} hasRepo={!!sessionId} hasChanges={changedFiles.length > 0} on:refresh={refreshFiles}>
											<div slot="logs" class="h-full overflow-auto">
												{#if logsRunId || latestTurnId}
													{#key logsRunId || latestTurnId}<RunView wsId={logsRunId || latestTurnId} mode="dock" />{/key}
												{:else}
													<div class="h-full flex items-center justify-center text-xs text-gray-500 px-4 text-center">{$i18n.t('No logs yet. Agent output and command results will appear here once work begins.')}</div>
												{/if}
											</div>
										</WorkspaceMainPanel>
									</div>
								{/if}
							</div>
							</div>
							</div>
						{/if}
						{#if overlayRunId}
						<div class="h-full min-h-0 min-w-0 flex-1 order-first">
							{#key overlayRunId}
								<WorkflowInspector
									wsId={overlayRunId}
									initialTab={overlayInitialTab}
									on:close={() => (overlayRunId = '')}
								/>
							{/key}
						</div>
						{/if}
						</div>
						{:else}
						<div class="h-full flex items-center justify-center text-center px-4">
							<div class="text-xs text-gray-500">{$i18n.t('All panels hidden — use the ⋯ menu in the header to show panels.')}</div>
						</div>
						{/if}
					</Pane>
				{/if}
			</PaneGroup>
		</div>

		<!-- dock toggle (panel visibility lives in the header ⋯ menu) -->
		{#if !dockOpen && (topHasAny || bottomHasAny)}
			<div class="shrink-0 flex items-center gap-1.5 px-3 py-1.5 border-t border-gray-100 dark:border-gray-850">
				<button class="flex items-center gap-1.5 text-[11px] text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 transition" on:click={toggleDock}>
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" class="size-3.5"><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M15 4v16" /></svg>
					{$i18n.t('Show workspace')}
				</button>
			</div>
		{/if}
	</div>

	<!-- click-away backdrop for the composer menus -->
	{#if showModeMenu || showRepoMenu || showExecMenu || showEngineMenu || showAttachMenu || showUsageStats || showModelMenu}
		<button
			class="fixed inset-0 z-20 cursor-default"
			tabindex="-1"
			aria-hidden="true"
			on:click={() => {
				showModeMenu = false;
				showRepoMenu = false;
				showExecMenu = false;
				showEngineMenu = false;
				showAttachMenu = false;
				showUsageStats = false;
				showModelMenu = false;
			}}
		></button>
	{/if}

	<!-- Acknowledge-popup: a gated in-place action awaiting approval. -->
	{#if pendingAction}
		<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
			<div
				class="w-full max-w-md rounded-2xl bg-white dark:bg-gray-900 border shadow-xl p-4 space-y-3 {pendingAction.risk ===
				'high'
					? 'border-red-300 dark:border-red-800'
					: 'border-gray-200 dark:border-gray-800'}"
			>
				<div class="flex items-center gap-2">
					<span class="text-lg">{pendingAction.risk === 'high' ? '⚠️' : '✋'}</span>
					<h3
						class="text-sm font-semibold {pendingAction.risk === 'high'
							? 'text-red-600 dark:text-red-400'
							: 'text-gray-800 dark:text-gray-100'}"
					>
						{pendingAction.risk === 'high'
							? $i18n.t('Confirm a high-risk action')
							: $i18n.t('Approve this action?')}
					</h3>
				</div>
				<div class="text-xs text-gray-600 dark:text-gray-300">
					<div>
						<span class="text-gray-400">{$i18n.t('Tool')}:</span>
						<code class="font-mono">{pendingAction.tool}</code>
						<span
							class="text-[10px] uppercase tracking-wide {pendingAction.risk === 'high'
								? 'text-red-500'
								: 'text-gray-400'}">{pendingAction.risk}</span
						>
					</div>
					{#if pendingAction.args}
						<pre
							class="mt-1 max-h-40 overflow-auto rounded-lg bg-gray-50 dark:bg-gray-850 p-2 text-[11px] font-mono whitespace-pre-wrap">{JSON.stringify(
								pendingAction.args,
								null,
								2
							)}</pre>
					{/if}
				</div>
				{#if pendingAction.risk === 'high'}
					<p class="text-[11px] text-red-600 dark:text-red-400">
						{$i18n.t('This can modify or destroy real files in your repo — review carefully.')}
					</p>
				{/if}
				<div class="flex items-center justify-end gap-2">
					<button
						class="text-xs px-3 py-1.5 rounded-lg text-gray-500 hover:text-gray-700 dark:hover:text-gray-200"
						disabled={approvalBusy}
						on:click={() => resolvePending(false)}>{$i18n.t('Deny')}</button
					>
					<button
						class="text-xs px-3 py-1.5 rounded-lg text-white disabled:opacity-50 transition {pendingAction.risk ===
						'high'
							? 'bg-red-600 hover:bg-red-500'
							: 'bg-blue-600 hover:bg-blue-500'}"
						disabled={approvalBusy}
						on:click={() => resolvePending(true)}
						>{approvalBusy ? $i18n.t('…') : $i18n.t('Approve')}</button
					>
				</div>
			</div>
		</div>
	{/if}

	<!-- Customize IN Build — right drawer hosting the Agent Studio Customize surface
	     (dock mode). Opened by the header ⚙; URL-synced via ?panel=customize. -->
	{#if showCustomize}
		<button
			class="fixed inset-0 z-40 bg-black/40 cursor-default"
			aria-label={$i18n.t('Close')}
			on:click={() => setCustomize(false)}
		></button>
		<aside
			class="fixed right-0 top-0 bottom-0 z-50 w-full max-w-2xl bg-white dark:bg-gray-950 border-l border-gray-100 dark:border-gray-850 shadow-2xl flex flex-col"
		>
			<div class="shrink-0 flex items-center gap-2 px-4 py-3 border-b border-gray-100 dark:border-gray-850">
				<div class="min-w-0">
					<div class="text-sm font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Customize')}</div>
					<div class="text-[11px] text-gray-400">{$i18n.t('Models, presets, skills & MCP — without leaving Build')}</div>
				</div>
				<a
					class="ml-auto shrink-0 text-[11px] text-gray-400 hover:text-blue-500 transition"
					href="/harvis/agent-studio/customize"
					title={$i18n.t('Open as a full page')}>⤢ {$i18n.t('Full page')}</a
				>
				<button
					class="shrink-0 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 p-1"
					aria-label={$i18n.t('Close')}
					on:click={() => setCustomize(false)}
				>
					<svg viewBox="0 0 20 20" fill="currentColor" class="size-4"><path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" /></svg>
				</button>
			</div>
			<div class="flex-1 min-h-0 overflow-y-auto px-4 py-3">
				<Customize mode="dock" />
			</div>
		</aside>
	{/if}

	<!-- GitHub: connect → pick a repo (or clone a public repo by name) → clone-mode session. -->
	<GitHubRepoModal bind:show={showGithubModal} onPick={pickGithubRepo} />

	<!-- The Workflow Inspector is no longer a full-page overlay — it docks into the right
	     workspace pane (see above), so opening a run PUSHES the chat narrower instead of
	     covering the page. Escape still closes it (handled on the window keydown). -->

	<!-- Full-auto entry acknowledge (one-time). -->
	{#if fullAutoAckOpen}
		<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
			<div
				class="w-full max-w-md rounded-2xl bg-white dark:bg-gray-900 border border-red-300 dark:border-red-800 shadow-xl p-4 space-y-3"
			>
				<div class="flex items-center gap-2">
					<span class="text-lg">⚠️</span>
					<h3 class="text-sm font-semibold text-red-600 dark:text-red-400">
						{$i18n.t('Enable Full-auto?')}
					</h3>
				</div>
				<p class="text-xs text-gray-600 dark:text-gray-300">
					{$i18n.t(
						'In Full-auto the agent makes every change and runs every command on the copy WITHOUT asking — including destructive ones. Use it only with a model you trust. The diff/PR is still your review gate, and Create-PR needs your explicit click.'
					)}
				</p>
				<div class="flex items-center justify-end gap-2">
					<button
						class="text-xs px-3 py-1.5 rounded-lg text-gray-500 hover:text-gray-700 dark:hover:text-gray-200"
						on:click={() => {
							fullAutoAckOpen = false;
							pendingRunModeAfterAck = '';
						}}>{$i18n.t('Cancel')}</button
					>
					<button
						class="text-xs px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-500 text-white transition"
						on:click={() => {
							ackFullAuto = true;
							fullAutoAckOpen = false;
							if (pendingRunModeAfterAck) {
								runMode = pendingRunModeAfterAck;
								pendingRunModeAfterAck = '';
							}
							showModeMenu = false;
						}}>{$i18n.t('I understand — enable Full-auto')}</button
					>
				</div>
			</div>
		</div>
	{/if}
{/if}
