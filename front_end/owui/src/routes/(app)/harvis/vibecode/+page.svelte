<script lang="ts">
	import { getContext, onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { WEBUI_NAME, config, settings, showSidebar, models, showReviewMirror } from '$lib/stores';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { getModels } from '$lib/apis';
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
		getVibecodeSessionFiles,
		getVibecodeSessionFile,
		getRunArtifacts,
		cancelWorkspaceRun,
		getActiveDiscordSession,
		getWorkspaceModel,
		setWorkspaceModel,
		type AttachedRepo,
		type VibecodeSession,
		type VibecodeTurn,
		type VibecodeFileEntry,
		type PendingAction
	} from '$lib/apis/agent-runs';
	import RunView from '$lib/agent-studio/RunView.svelte';
	import BrowserPanel from '$lib/agent-studio/build/BrowserPanel.svelte';
	import BuildActions from '$lib/agent-studio/BuildActions.svelte';
	import WorkflowInspector from '$lib/agent-studio/WorkflowInspector.svelte';
	import { humanizeRunTitle } from '$lib/agent-studio/runFormat';
	import PlanPanel from '$lib/agent-studio/PlanPanel.svelte';
	import GitHubRepoModal from '$lib/agent-studio/GitHubRepoModal.svelte';
	import BuildHeader from '$lib/agent-studio/build/BuildHeader.svelte';
	import PrDrawer from '$lib/agent-studio/build/PrDrawer.svelte';
	import WorkspaceFileRail from '$lib/agent-studio/build/WorkspaceFileRail.svelte';
	import WorkspaceMainPanel from '$lib/agent-studio/build/WorkspaceMainPanel.svelte';
	import WorkspacePanel from '$lib/agent-studio/build/WorkspacePanel.svelte';
	import BackgroundTaskCard from '$lib/agent-studio/build/BackgroundTaskCard.svelte';
	import ShellTab from '$lib/agent-studio/build/ShellTab.svelte';
	import Customize from '$lib/agent-studio/Customize.svelte';
	import Automations from '$lib/agent-studio/Automations.svelte';
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

	// Routines opens IN Build (right drawer) too — the coding lens of the cron store,
	// no longer bouncing out to the Agent Studio hub. URL-synced (?panel=routines).
	$: showRoutines = $page.url.searchParams.get('panel') === 'routines';
	const setRoutines = (open: boolean) => {
		const url = new URL($page.url);
		if (open) url.searchParams.set('panel', 'routines');
		else url.searchParams.delete('panel');
		goto(`${url.pathname}${url.search}`, { replaceState: !open, noScroll: true, keepFocus: true });
	};

	let session: VibecodeSession | null = null;
	let turns: VibecodeTurn[] = [];
	let pollTimer: any = null;
	// Discord ↔ Build mirror: an actively-running #harvis-code session (or null) →
	// the header chip; and the shared model's last-adopted updated_at epoch so we
	// only adopt a change newer than our own last pick/write (recency-wins).
	let discordSession: any = null;
	let discordPollTimer: any = null;
	let lastModelSyncEpoch = 0;
	// Set in onDestroy so the async onMount tail below (which runs after several awaits) can
	// bail before registering background timers/listeners on an already-unmounted component.
	let destroyed = false;
	// Which finished turns have their full run (thought stream + canvas) expanded.
	// Chat-style: a finished turn shows the model's summary as a bubble; the run is
	// one click away. Running turns always show the live run.
	let expandedRuns: Record<string, boolean> = {};
	const toggleRun = (id: string) => {
		// Touching it by hand makes it the user's panel, not ours — see _autoExpanded.
		_autoExpanded.delete(id);
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
	let showPrDrawer = false;
	let sessionHasGithub = false;
	let diffError = false; // last diff fetch failed → surface it (don't clobber the last-known diff)
	const loadDiff = async () => {
		if (!sessionId) {
			sessionDiff = '';
			diffError = false;
			return;
		}
		// The API is fail-soft: null = fetch failed. Keep the last-known diff on failure
		// (wiping it would silently hide real changes) and show an inline error + Retry.
		const r: any = await getVibecodeSessionDiff(sessionId);
		if (r === null) {
			diffError = true;
			return;
		}
		diffError = false;
		sessionDiff = r?.diff ?? '';
		sessionHasGithub = !!r?.has_github;
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

	// ── Phase 2: the WHOLE workspace tree (read-only), not just touched files. Feeds
	// the rail's Files sub-tab; the Changes sub-tab keeps its diff-parsed list. ──
	let sessionFileEntries: VibecodeFileEntry[] = [];
	let sessionFilesLoading = false;
	let sessionFilesError = false; // listing fetch failed (≠ genuinely empty tree)
	const loadSessionFiles = async () => {
		if (!sessionId) {
			sessionFileEntries = [];
			sessionFilesError = false;
			return;
		}
		const reqId = sessionId;
		sessionFilesLoading = true;
		try {
			const r = await getVibecodeSessionFiles(reqId);
			if (reqId !== sessionId) return; // switched sessions mid-fetch → drop
			if (r === null) {
				// fetch failed — keep the last-known listing, surface an error + Retry
				sessionFilesError = true;
				return;
			}
			sessionFilesError = false;
			sessionFileEntries = r.entries;
		} finally {
			if (reqId === sessionId) sessionFilesLoading = false;
		}
	};
	// The rail's tree builder takes flat FILE paths (dirs are implied by the paths).
	$: sessionFilePaths = sessionFileEntries.filter((e) => e.type === 'file').map((e) => e.path);
	// Re-fetch when the user opens the Files sub-tab (cheap listing; keeps it fresh).
	$: if (fileTab === 'files' && sessionId) loadSessionFiles();

	// ── Phase 2: real read-only file content for the main panel's Editor tab ──
	let fileContent: string | null = null;
	let fileLoading = false;
	let fileBinary = false;
	let fileTruncated = false;
	let fileError = false; // content fetch failed (API returns null) → honest state, not a blank editor
	const loadFileContent = async (path: string) => {
		fileContent = null;
		fileBinary = false;
		fileTruncated = false;
		fileError = false;
		if (!sessionId || !path) return;
		fileLoading = true;
		const req = path;
		const r = await getVibecodeSessionFile(sessionId, path);
		if (req !== selectedFile) return; // user clicked another file mid-fetch → drop
		fileLoading = false;
		if (r) {
			fileContent = r.binary ? '' : (r.content ?? '');
			fileBinary = !!r.binary;
			fileTruncated = !!r.truncated;
		} else {
			fileError = true;
		}
	};

	// Refresh the workspace runs + session diff on load and whenever a turn completes.
	$: {
		doneTurns;
		sessionId;
		latestTurnId;
		loadDiff();
		loadArtifacts();
		loadSessionFiles();
	}
	const clearBg = () => {
		bgHidden = new Set([...bgHidden, ...finishedTasks.map((t) => t.id)]);
	};
	// (bgDot/bgStatusLabel removed — dead since the shared runFormat helpers landed, and
	//  they carried a stale cancelled=amber mapping. Use statusDot/statusLabel instead.)
	// (BW2 3-region dock helpers removed — superseded by the BW3 dock + ⋯ panel menu)

	// Left-rail tab + main-panel tab + file/artifact selection wiring.
	let fileTab: 'files' | 'changes' | 'artifacts' = 'changes';
	let mainTab: 'chat' | 'diff' | 'logs' | 'editor' | 'preview' = 'chat';
	const onFileSelect = (path: string) => {
		selectedFile = path;
		// Files sub-tab = browsing the repo → open the read-only Editor view; the
		// Changes sub-tab keeps landing on the Diff view. Content is fetched either
		// way so the Editor tab is ready.
		mainTab = fileTab === 'files' ? 'editor' : 'diff';
		loadFileContent(path);
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
		if (latestTurnId) headerOpenRunId(latestTurnId);
	};
	const headerOpenRunId = (id: string) => {
		if (!id) return;
		// The run inspector still pegs the main thread when opened on a LIVE run (the shared stream
		// store fixed the connection budget but NOT this freeze — its cause is elsewhere in the
		// inspector-on-live-run render path, still under investigation). Keep it gated to FINISHED
		// runs; while running, follow the live view / mirror instead.
		const t = turns.find((x) => x.id === id);
		if (t && t.status === 'running') {
			toast.info(
				$i18n.t('The run inspector opens once the run finishes — follow it live in the panel for now.')
			);
			return;
		}
		overlayInitialTab = 'overview';
		overlayRunId = id;
		showReviewMirror.set(null);
	};
	const headerCreatePR = () => {
		showPrDrawer = true;
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
		const def = { tl: true, tr: true, bl: false, br: false, sh: true, bw: false };
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
		...(shellEnabled ? [{ key: 'sh', label: $i18n.t('Shell'), visible: panelVisible.sh }] : []),
		{ key: 'bw', label: $i18n.t('Browser'), visible: panelVisible.bw }
	];
	// ── Tabbed dock (Claude-Code-Desktop style): ONE panel at a time, a tab strip on
	// top. The ⋯ menu still controls WHICH tabs exist (panelVisible); this picks the
	// active one. Order: Tasks · Plan · Files · File.
	let dockTab: string = (() => {
		try {
			return localStorage.getItem('harvis.vibecode.docktab') || 'tl';
		} catch {
			return 'tl';
		}
	})();
	const setDockTab = (k: string) => {
		dockTab = k;
		try {
			localStorage.setItem('harvis.vibecode.docktab', k);
		} catch {
			/* ignore */
		}
	};
	// User-rearrangeable tab order (drag the tab strip). Persisted; unknown/new keys are folded
	// in at the end so adding a panel key later never strands it.
	const DOCK_TAB_KEYS = ['tl', 'bl', 'tr', 'br', 'sh', 'bw'];
	let dockOrder: string[] = (() => {
		try {
			const saved = JSON.parse(localStorage.getItem('harvis.vibecode.dockorder') || 'null');
			if (Array.isArray(saved) && saved.length) {
				const known = new Set(DOCK_TAB_KEYS);
				const ordered = saved.filter((k: string) => known.has(k));
				for (const k of DOCK_TAB_KEYS) if (!ordered.includes(k)) ordered.push(k);
				return ordered;
			}
		} catch {
			/* ignore */
		}
		return [...DOCK_TAB_KEYS];
	})();
	const persistDockOrder = () => {
		try {
			localStorage.setItem('harvis.vibecode.dockorder', JSON.stringify(dockOrder));
		} catch {
			/* ignore */
		}
	};
	let dragKey: string | null = null;
	const onTabDrop = (target: string) => {
		if (!dragKey || dragKey === target) {
			dragKey = null;
			return;
		}
		const next = dockOrder.filter((k) => k !== dragKey);
		const at = next.indexOf(target);
		next.splice(at < 0 ? next.length : at, 0, dragKey);
		dockOrder = next;
		dragKey = null;
		persistDockOrder();
	};
	$: dockTabDefs = {
		tl: { label: $i18n.t('Tasks'), visible: panelVisible.tl },
		bl: { label: $i18n.t('Plan'), visible: panelVisible.bl },
		tr: { label: $i18n.t('Files'), visible: panelVisible.tr },
		br: { label: $i18n.t('File'), visible: panelVisible.br },
		// P2: manual shell — only exists when the HARVIS_BUILD_SHELL flag is on.
		sh: { label: $i18n.t('Shell'), visible: shellEnabled && panelVisible.sh },
		bw: { label: $i18n.t('Browse & verify'), visible: panelVisible.bw }
	} as Record<string, { label: string; visible: boolean }>;
	$: dockTabs = dockOrder
		.filter((k) => dockTabDefs[k]?.visible)
		.map((k) => ({ key: k, label: dockTabDefs[k].label }));
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
	const refreshFiles = () => {
		loadDiff();
		if (selectedFile) loadFileContent(selectedFile); // re-try the selected file's content too
	};

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
		kimi: ['moonshot'],
		'kimi-code': ['kimi-code'],
		native: ['ollama']
	};
	// The model the meter reads window+price from before the first turn lands (so a Claude session
	// shows 200k + Claude pricing immediately).
	const ENGINE_DEFAULT_MODEL: Record<string, string> = {
		'claude-code': 'anthropic/claude-sonnet-4-6',
		codex: 'openai/gpt-5',
		kimi: 'moonshot/kimi-k3',
		// The one model every Kimi Code membership tier can use (k3/k3-256k/highspeed need higher
		// tiers), so it can't show a window/price the user isn't entitled to.
		'kimi-code': 'kimi-code/kimi-for-coding'
	};
	const fmtTok = (n: number) =>
		n >= 10000 ? Math.round(n / 1000) + 'k' : n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n);
	const fmtCost = (n: number) => (n >= 1 ? '$' + n.toFixed(2) : n > 0 ? '$' + n.toFixed(3) : '$0');
	// A model's provider → the Build engine (lane) that can actually run it. Local Ollama
	// models use the native OpenClaw loop; Claude/Hermes/OpenAI need their own engine.
	const engineForOwner = (owner: string): string => {
		const o = (owner || '').toLowerCase();
		if (o.startsWith('anthropic')) return 'claude-code';
		if (o.startsWith('hermes')) return 'hermes-agent';
		if (o === 'openai') return 'codex';
		// 'kimi-code' MUST be tested before the generic kimi/moonshot arm below — it also starts
		// with "kimi", and falling through would run a MEMBERSHIP model on the pay-as-you-go
		// Moonshot lane: wrong credential, wrong bill, and no tool loop.
		if (o === 'kimi-code') return 'kimi-code';
		if (o.startsWith('moonshot') || o.startsWith('kimi')) return 'kimi';
		return 'native';
	};

	const pickModel = (id: string) => {
		selectedModel = id;
		showModelMenu = false;
		// The Build engine follows the picked model automatically (see the selectedEngine reactive
		// below) — there is no separate engine pill. Picking a Claude model routes the run to the
		// Claude Code lane; a local model runs on native.
		// Push the pick to the shared workspace model so Discord /set-model (and any other
		// Build tab) reflects it. Record the returned epoch so our own write isn't re-adopted
		// on the next sync poll.
		if (id) {
			setWorkspaceModel(id)
				.then((r) => {
					if (r && r.updated_at) lastModelSyncEpoch = r.updated_at;
				})
				.catch(() => {});
		}
	};

	// Independent poller (runs whenever Build is mounted, even with no session open):
	// (a) surface a running Discord session as the header chip; (b) adopt the shared
	// model when it changed more recently than our last pick — last-write-wins with Discord.
	const pollDiscordAndModel = async () => {
		try {
			discordSession = await getActiveDiscordSession();
		} catch (_) {
			discordSession = null;
		}
		try {
			const wm = await getWorkspaceModel();
			if (wm && wm.updated_at > lastModelSyncEpoch) {
				if (!wm.model_id) {
					lastModelSyncEpoch = wm.updated_at; // shared model cleared — nothing to adopt
				} else if ((modelOptions || []).some((m: any) => m?.id === wm.model_id)) {
					// Adopt (and consume the epoch) ONLY if the model is valid for the CURRENT
					// engine — checking the engine-filtered modelOptions, not the raw store. If it
					// isn't (e.g. Discord picked an Ollama model while Build is on Claude Code), the
					// reactive engine-filter would immediately wipe it, so we DON'T advance the epoch
					// and instead retry after the user switches to a compatible engine.
					if (wm.model_id !== selectedModel) selectedModel = wm.model_id;
					lastModelSyncEpoch = wm.updated_at;
				}
				// else: model not loaded yet OR not valid for this engine — leave epoch, retry later
			}
		} catch (_) {}
	};

	// Chip click → jump into the live Discord session so the web thread mirrors it.
	const openDiscordSession = () => {
		if (discordSession?.session_id) goto(`/harvis/vibecode?session=${discordSession.session_id}`);
	};

	// Keep the picker current: the global `$models` store is loaded once at app mount and
	// never refreshed in-browser, so a model pulled / connected after load wouldn't appear
	// here. Re-fetch it on the triggers that matter — mount, a gentle 30s interval, window
	// focus, and (forced, cache-busting) whenever the picker menu opens. `force` passes
	// refresh=true so the backend bypasses its 60s model cache and returns a truly current
	// list. Guarded so a transient empty/failed fetch never blanks the existing list.
	let modelsRefreshTimer: any = null;
	const refreshModels = async (force = false) => {
		try {
			const dc = $config?.features?.enable_direct_connections
				? ($settings?.directConnections ?? null)
				: null;
			const next = await getModels(localStorage.token, dc, false, force);
			if (Array.isArray(next) && next.length) {
				// Only replace the store when the list actually changed (id/name/owner signature),
				// so identical 30s refreshes don't churn store identity — which would re-render the
				// open dropdown and reset a mid-selection hover/scroll.
				const sig = (arr: any[]) =>
					(arr || []).map((m: any) => `${m?.id}:${m?.name || ''}:${m?.owned_by || ''}`).join('|');
				if (sig(next) !== sig($models)) models.set(next);
			}
		} catch (_) {
			// leave the current list in place on a transient failure
		}
	};
	const onWindowFocus = () => refreshModels(true);

	// Toggle the model dropdown; force a fresh, cache-busting model fetch on the opening edge
	// so the list the user is about to pick from is genuinely current.
	const toggleModelMenu = () => {
		openMenu(showModelMenu ? '' : 'model');
		if (showModelMenu) refreshModels(true);
	};

	$: usageTurns = turns.filter((t) => (t.prompt_tokens ?? 0) > 0 || (t.completion_tokens ?? 0) > 0);
	$: lastUsage = usageTurns.length ? usageTurns[usageTurns.length - 1] : null;
	$: sessionTokens = usageTurns.reduce((s, t) => s + (t.prompt_tokens || 0) + (t.completion_tokens || 0), 0);

	// Engine-filtered picker list (Claude Code → only Claude, etc.).
	// The picker shows ALL available models (local + Claude + Hermes + OpenAI) — same list the
	// main chat has — because the ENGINE now follows the model (see pickModel), so a cross-engine
	// pick routes to the right lane instead of being hidden. Making this the full set also makes
	// the engine-filter wipe reactive below inert (a picked model is always present).
	$: modelOptions = ($models || []).filter((m: any) => m && m.id);
	// Provider groups for the picker menu (Local Ollama incl. 'ollama-desktop' rig-routed).
	const OWNER_GROUPS: { label: string; test: (o: string) => boolean }[] = [
		{ label: 'Local', test: (o) => o.startsWith('ollama') || o === '' },
		{ label: 'Claude', test: (o) => o.startsWith('anthropic') },
		{ label: 'Hermes', test: (o) => o.startsWith('hermes') },
		{ label: 'OpenAI', test: (o) => o === 'openai' },
		// Ordered BEFORE 'Kimi': the generic Kimi test below also matches 'kimi-code', so the
		// membership group has to claim those models first. Two groups because they are two
		// products on two bills — the membership models must be pickable as such, not blended
		// into the Moonshot list.
		{ label: 'Kimi Code (membership)', test: (o) => o === 'kimi-code' },
		{ label: 'Kimi (Moonshot)', test: (o) => o.startsWith('moonshot') || o.startsWith('kimi') }
	];
	$: modelGroups = (() => {
		// First match wins. Skipping already-claimed ids is what makes that true: without it
		// every kimi-code model ALSO fell into the broader 'Kimi' group below and the picker
		// listed each one twice — under a Moonshot header, for an account with no Moonshot key.
		// The backend only ships a provider's models once its credential is connected, so a
		// group with nothing left to claim is dropped rather than shown empty.
		const used = new Set<string>();
		const groups: { label: string; models: any[] }[] = [];
		for (const g of OWNER_GROUPS) {
			const ms = modelOptions.filter(
				(m: any) => !used.has(m.id) && g.test((m.owned_by || 'ollama').toString().toLowerCase())
			);
			ms.forEach((m: any) => used.add(m.id));
			if (ms.length) groups.push({ label: g.label, models: ms });
		}
		const rest = modelOptions.filter((m: any) => !used.has(m.id));
		if (rest.length) groups.push({ label: 'Other', models: rest });
		return groups;
	})();
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

	// (Removed the live token-tick 2nd SSE: it was a redundant per-run stream consumer that,
	// stacked on the inline run view + the review mirror, pushed toward the browser's ~6-
	// connection-per-host cap and could stall the run when a 3rd/4th view was opened. The cost
	// meter now reflects the persisted per-turn totals; `liveCompletionTokens` stays 0.)

	let sessionLoadError = false; // last session fetch failed (API returns null on any failure)
	const loadSession = async () => {
		if (!sessionId) {
			session = null;
			turns = [];
			sessionLoadError = false;
			return;
		}
		const reqId = sessionId;
		const data = await getVibecodeSession(reqId);
		if (reqId !== sessionId) return; // navigated to another session mid-fetch — drop the stale response
		if (data) {
			sessionLoadError = false;
			session = data.session;
			turns = data.turns ?? [];
			maybeAutoname();
		} else {
			// Fetch failed: keep whatever we already have (a transient poll failure must not
			// blank a visible session) and surface the failure honestly in the thread/strip.
			sessionLoadError = true;
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
				try {
					await loadSession();
					await pollPending();
					await maybeWriteBack();
				} finally {
					// One failed poll must never silently kill the loop — always re-arm.
					schedule();
				}
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
	// Agents mode — fan this turn out to N task-delegated sub-agents (planner picks 3–10):
	//   'off'  ⇒ a single agent (default)
	//   'on'   ⇒ always fan out
	//   'auto' ⇒ a cheap classifier proposes fanning out; the user confirms (no surprise cost)
	let agentsMode: 'off' | 'auto' | 'on' = 'off';
	const cycleAgentsMode = () => {
		agentsMode = agentsMode === 'off' ? 'auto' : agentsMode === 'auto' ? 'on' : 'off';
	};
	// Auto-mode: classify + confirm before the (expensive) fan-out.
	let orchestrateSizing = false;
	let orchestratePrompt: { agents: number; reason: string; resolve: (v: boolean | null) => void } | null = null;
	const askSplit = (agents: number, reason: string) =>
		new Promise<boolean | null>((resolve) => {
			orchestratePrompt = { agents, reason, resolve };
		});
	const answerSplit = (v: boolean | null) => {
		orchestratePrompt?.resolve(v);
		orchestratePrompt = null;
	};
	const suggestOrchestrate = async (
		brief: string
	): Promise<{ suggest: boolean; agents: number; reason: string } | null> => {
		try {
			const r = await fetch('/api/vibecode/orchestrate-suggest', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json', authorization: `Bearer ${localStorage.getItem('token')}` },
				body: JSON.stringify({ task_brief: brief })
			});
			return r.ok ? await r.json() : null;
		} catch (_) {
			return null;
		}
	};
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
		'hermes-native': 'Hermes Native',
		kimi: 'Kimi',
		'kimi-code': 'Kimi Code'
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
	$: readyEngineIds = [
		'opencode',
		'codex',
		'claude-code',
		'hermes-agent',
		'hermes-native',
		'kimi',
		'kimi-code'
	].filter((e) => engineReadiness?.[e]?.ready);
	$: showEngineSelector = readyEngineIds.length > 0 && isolationMode === 'session';
	// Surface the Hermes-Native "enabled but no model" reason even when the selector is hidden.
	$: hermesNeedsModel =
		isolationMode === 'session' && engineReadiness?.['hermes-native']?.reason === 'no_hermes_model';
	// Engine follows the MODEL (there is no separate engine pill): the selected model's provider
	// decides the Build lane — Claude→claude-code, Hermes→hermes-agent, OpenAI→codex, local→native —
	// but only if that engine is READY, else fall back to native. Derived reactively so it tracks
	// both an explicit pick AND a model adopted from the shared/Discord state.
	$: {
		const _pm = ($models || []).find((m: any) => m?.id === selectedModel);
		const _eng = engineForOwner((_pm?.owned_by || '').toString());
		const _target = _eng !== 'native' && engineReadiness?.[_eng]?.ready ? _eng : 'native';
		if (selectedEngine !== _target) selectedEngine = _target;
	}
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

	// ── Toolbar menus: exactly one open at a time ──
	// Each toggle used to be an independent `!x`, and the full-screen click-outside backdrop
	// closed the rest, which hid that they don't coordinate. The stacking fix below lifts the
	// composer strip ABOVE that backdrop while a menu is open, so the invariant has to be
	// stated here instead of falling out of the click order.
	type ToolbarMenu = '' | 'mode' | 'repo' | 'exec' | 'attach' | 'model' | 'usage';
	const openMenu = (which: ToolbarMenu) => {
		showModeMenu = which === 'mode';
		showRepoMenu = which === 'repo';
		showExecMenu = which === 'exec';
		showAttachMenu = which === 'attach';
		showModelMenu = which === 'model';
		showUsageStats = which === 'usage';
	};
	// The four menus that live INSIDE the `relative z-10` composer strip. Their z-30/z-40 is
	// capped by that stacking context, so the strip itself has to clear the z-20 backdrop —
	// see the class binding on the control strip. The other two (repo, exec) sit outside it
	// and already paint above the backdrop.
	$: composerMenuOpen = showModeMenu || showAttachMenu || showModelMenu || showUsageStats;
	$: anyToolbarMenuOpen = composerMenuOpen || showRepoMenu || showExecMenu || showEngineMenu;
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
	// Phase 2 backends can queue MULTIPLE gated actions; the modal shows the head
	// as the active card and the rest as a small queue underneath.
	let pendingQueue: PendingAction[] = [];
	let approvalBusy = false;
	$: isInplace = activeIso === 'inplace';

	const pollPending = async () => {
		if (!anyRunning) {
			pendingAction = null;
			pendingQueue = [];
			return;
		}
		const running = turns.find((t) => t.status === 'running');
		if (!running) {
			pendingAction = null;
			pendingQueue = [];
			return;
		}
		const p = await getPendingAction(running.id);
		pendingQueue = Array.isArray(p) ? p : p ? [p] : [];
		pendingAction = pendingQueue[0] ?? null;
	};

	// scope 'session' = approve AND stop gating matching actions for this session.
	const resolvePending = async (approve: boolean, scope?: 'once' | 'session') => {
		const running = turns.find((t) => t.status === 'running');
		if (!pendingAction || !running) return;
		approvalBusy = true;
		try {
			await resolveAction(running.id, pendingAction.action_id, approve, scope);
			// Advance to the next queued action locally; the poll re-syncs shortly.
			pendingQueue = pendingQueue.slice(1);
			pendingAction = pendingQueue[0] ?? null;
		} catch (_) {
		} finally {
			approvalBusy = false;
		}
	};

	const submit = async () => {
		const text = prompt.trim();
		if (!text || composerDisabled) return;

		// Resolve whether THIS turn fans out. 'on' = always; 'off' = never; 'auto' =
		// a cheap classifier proposes, the user confirms — the expensive fan-out is
		// gated behind that confirm, never silent. Done BEFORE sending=true so the
		// confirm bar stays interactive.
		let orchestrate = agentsMode === 'on';
		if (agentsMode === 'auto') {
			orchestrateSizing = true;
			const sug = await suggestOrchestrate(text);
			orchestrateSizing = false;
			if (sug?.suggest) {
				const ok = await askSplit(sug.agents || 3, sug.reason || '');
				if (ok === null) return; // dismissed → cancel the submit
				orchestrate = !!ok;
			} else {
				orchestrate = false;
			}
		}

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
	// Turns whose details this code opened (as opposed to the user clicking "View run
	// details"). Only these get folded again when the next run starts — a panel the user
	// opened by hand stays open.
	const _autoExpanded = new Set<string>();
	$: {
		// `next` stays null until something actually changes, so the assignment below — and
		// with it this block's own re-run — only happens on a real transition.
		let next: Record<string, boolean> | null = null;
		for (const t of turns) {
			if (t.status === 'running') {
				_sawRunning.add(t.id);
				if (_autoExpanded.size) {
					next = next ?? { ...expandedRuns };
					for (const id of _autoExpanded) if (id !== t.id) next[id] = false;
					_autoExpanded.clear();
				}
			} else if (_sawRunning.has(t.id) && !_typedTurns.has(t.id)) {
				_typedTurns.add(t.id);
				if (t.status === 'done') typeOut(t.id, (t.final_summary || '').toString());
				// Open the diff + logs without a click: a finished turn that shows only a one-line
				// summary reads as if nothing happened. Guarded by _sawRunning, so turns already
				// terminal at page load stay collapsed — otherwise reloading a long session would
				// mount a RunView (and its fetches) for every turn at once.
				next = next ?? { ...expandedRuns };
				next[t.id] = true;
				_autoExpanded.add(t.id);
			}
		}
		if (next) expandedRuns = next;
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
		// Discord chip + shared-model sync — independent of the per-session poll so the
		// chip shows and the model stays in sync even on the Build landing page.
		await pollDiscordAndModel();
		// Keep the model picker current (see refreshModels): the store is otherwise load-once.
		await refreshModels(false);
		// Guard: if the component unmounted during the awaits above, onDestroy already ran
		// (against null timers) — don't register orphan timers/listeners that would leak.
		if (destroyed) return;
		discordPollTimer = setInterval(pollDiscordAndModel, 5000);
		modelsRefreshTimer = setInterval(() => refreshModels(false), 30000);
		if (typeof window !== 'undefined') window.addEventListener('focus', onWindowFocus);
	});
	onDestroy(() => {
		destroyed = true;
		clearTimeout(pollTimer);
		clearInterval(discordPollTimer);
		clearInterval(modelsRefreshTimer);
		if (typeof window !== 'undefined') window.removeEventListener('focus', onWindowFocus);
	});
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
			repoLabel={session?.repo_display_path ?? null}
			baseBranch={session?.base_branch ?? null}
			workBranch={session?.work_branch ?? null}
			headSha={session?.head_sha ?? null}
			lifecycle={session?.lifecycle ?? ''}
			preflight={session?.preflight ?? null}
			panels={panelList}
			{dockOpen}
			{discordSession}
			on:stop={cancelRun}
			on:createPR={headerCreatePR}
			on:openRun={headerOpenRun}
			on:openDiscord={openDiscordSession}
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
					{#if sessionLoadError && !session}
						<!-- Initial session load FAILED — say so instead of a fake "no turns" empty state. -->
						<div class="text-xs text-center pt-8 space-y-2">
							<div class="text-red-500 dark:text-red-400">
								{$i18n.t("Couldn't load this session — check your connection.")}
							</div>
							<button
								class="text-[11px] px-2.5 py-1 rounded-lg border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-black/[0.04] dark:hover:bg-white/[0.06] transition"
								on:click={() => loadSession()}>{$i18n.t('Retry')}</button
							>
						</div>
					{:else if !turns.length}
						<div class="text-xs text-gray-500 text-center pt-8">
							{$i18n.t('No turns yet — send a message to start coding.')}
						</div>
					{/if}
					{#each turns as t (t.id)}
						<div class="flex justify-end">
							<div
								class="max-w-[68%] rounded-2xl rounded-br-md border border-gray-200 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05] px-3.5 py-2 text-gray-800 dark:text-gray-100"
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
													class="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-lg border border-gray-200 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05] text-gray-600 dark:text-gray-300"
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
							<!-- live run while Harvis works: a lean Cursor-style step lineup (Editing
							     hello.txt / Running: npm test …) that stays in the chat, not a blank
							     canvas. Fixed height so the feed renders + scrolls; full run one click away. -->
							<div class="h-80 rounded-xl border border-gray-200 dark:border-white/10 overflow-hidden bg-gray-50 dark:bg-gray-900">
								{#key t.id}<RunView wsId={t.id} mode="stream" title={t.task_brief} onOpenFull={() => headerOpenRunId(t.id)} />{/key}
							</div>
						{:else}
							<!-- assistant reply: "the AI's domain" — unbubbled, full-width (matches the main
							     chat). Only the user's message above is bubbled. Full run is one click away. -->
							<div class="flex flex-col items-start gap-1.5 w-full">
								<div
									class="w-full text-sm text-gray-800 dark:text-gray-100 markdown-prose markdown-prose-sm"
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
										onCreatePr={() => (showPrDrawer = true)}
									/>
								{/if}
								{#if expandedRuns[t.id] && typingText[t.id] === undefined}
									<!-- Same typing guard as the actions row above: the dock and the row appear
									     together, so nothing shifts underneath the answer while it types out. -->
									<div
										class="w-full rounded-xl border border-gray-200 dark:border-white/10 overflow-hidden bg-gray-50 dark:bg-gray-900"
									>
										{#key t.id}<RunView wsId={t.id} mode="dock" title={t.task_brief} onOpenFull={() => headerOpenRunId(t.id)} />{/key}
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
				<!-- A. chat card — raised, a step BRIGHTER than the page bg -->
				<div class="w-full max-w-4xl mx-auto rounded-2xl border border-gray-200 dark:border-white/10 bg-white dark:bg-gray-850 p-2.5 shadow-lg shadow-black/20">
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
										<div class="h-14 max-w-[11rem] px-3 flex items-center gap-2 rounded-lg border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-800">
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
								class="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700"
								on:click={() => openMenu(showExecMenu ? '' : 'exec')}
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
								</div>
							{/if}
						</div>

						<!-- repo chip -->
						<div class="relative">
							<button
								class="inline-flex items-center gap-1.5 text-[11px] px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 {sessionId
									? 'cursor-default'
									: 'hover:bg-gray-200 dark:hover:bg-gray-700'}"
								on:click={() => {
									if (!sessionId) openMenu(showRepoMenu ? '' : 'repo');
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

					<!-- Agents · Auto — the classifier proposes a fan-out; the user confirms here. -->
					{#if orchestrateSizing}
						<div class="flex items-center gap-2 mb-2 px-2.5 py-1.5 rounded-lg bg-amber-500/8 border border-amber-500/20 text-[11px] text-amber-300">
							<svg class="size-3.5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-6.2-8.5" stroke-linecap="round" /></svg>
							{$i18n.t('Sizing the task…')}
						</div>
					{:else if orchestratePrompt}
						<div class="flex items-start gap-2 mb-2 px-3 py-2 rounded-lg bg-violet-500/8 border border-violet-500/25">
							<svg class="size-4 shrink-0 mt-0.5 text-violet-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="5" r="2" /><circle cx="5" cy="19" r="2" /><circle cx="19" cy="19" r="2" /><path d="M12 7v3m0 0-5 7m5-7 5 7" stroke-linecap="round" stroke-linejoin="round" /></svg>
							<div class="min-w-0 flex-1">
								<div class="text-xs font-medium text-gray-800 dark:text-gray-100">{$i18n.t('Split across ~{{n}} agents?', { n: orchestratePrompt.agents })}</div>
								{#if orchestratePrompt.reason}<div class="text-[11px] text-gray-400 mt-0.5 leading-snug">{orchestratePrompt.reason}</div>{/if}
							</div>
							<div class="shrink-0 flex items-center gap-1.5">
								<button type="button" class="text-[11px] px-2.5 py-1 rounded-md text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 transition" on:click={() => answerSplit(false)}>{$i18n.t('Keep single')}</button>
								<button type="button" class="text-[11px] px-2.5 py-1 rounded-md border border-violet-500/30 bg-violet-500/15 text-violet-200 hover:bg-violet-500/25 transition" on:click={() => answerSplit(true)}>{$i18n.t('Split')}</button>
							</div>
						</div>
					{/if}

					<!-- input — clean single-line bar; subtle ⏎ (Enter sends, Shift+Enter = newline) -->
					<div class="relative">
						<textarea
							bind:this={promptEl}
							class="w-full text-sm bg-transparent py-2 pl-2 pr-10 outline-none resize-none disabled:opacity-50 leading-relaxed text-gray-800 dark:text-gray-100 placeholder:text-gray-500"
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
								? 'bg-black/[0.03] dark:bg-white/[0.05] text-gray-500 cursor-not-allowed'
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
				</div>

				<!-- B. control strip — BELOW the chat card, blended into the page bg:
				     no card, no border, no shadow. relative+z keeps the upward menus
				     stacking above the chat card.
				     That z-index also opens a stacking context, which CAPS every menu inside
				     it at this level — so at z-10 the z-40 model dropdown still painted under
				     the z-20 click-outside backdrop, and nothing in it could be clicked or
				     scrolled. While one of its own menus is open the strip clears the
				     backdrop; otherwise it stays at z-10 and doesn't float over page chrome. -->
				<div
					class="relative {composerMenuOpen ? 'z-30' : 'z-10'} w-full max-w-4xl mx-auto bg-transparent px-1.5 pt-2"
				>
					<!-- toolbar -->
					<div class="flex items-center gap-1.5">
						<!-- Engine pill removed — the Build engine now follows the model dropdown
						     (see the selectedEngine reactive); the model IS the single control. -->
						{#if hermesNeedsModel}
							<span class="text-[11px] text-amber-400/80"
								>{$i18n.t('Pull a Hermes model to enable the Hermes engine.')}</span
							>
						{/if}
						{#if selectedEngine === 'kimi'}
							<span class="text-[11px] text-gray-500"
								>{ENGINE_LABELS['kimi']}
								{$i18n.t('reasons and responds in the thread (Moonshot) — no clone or diff.')}</span
							>
						{:else if selectedEngine !== 'native'}
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
									? 'border-gray-200 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05] text-gray-600 dark:text-gray-300'
									: runMode === 'full-auto'
										? 'border-amber-500/20 bg-amber-500/10 text-amber-300'
										: 'border-sky-500/20 bg-sky-500/10 text-sky-300'}"
								title={$i18n.t('Run mode — how much the agent does on its own this turn')}
								on:click={() => openMenu(showModeMenu ? '' : 'mode')}
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

						<!-- Agents — 3-state: Off (single agent) → Auto (classifier proposes, you
						     confirm) → On (always fan out to N planner-picked sub-agents). Off is
						     the default so a swarm is never a surprise; Auto lets the AI ask. -->
						<button
							type="button"
							class="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-full border transition hover:opacity-90 {agentsMode === 'on'
								? 'border-violet-500/30 bg-violet-500/12 text-violet-300'
								: agentsMode === 'auto'
									? 'border-amber-500/30 bg-amber-500/12 text-amber-300'
									: 'border-gray-200 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05] text-gray-400 hover:text-gray-700 dark:hover:text-gray-200'}"
							title={agentsMode === 'auto'
								? $i18n.t('Agents · Auto — Harvis proposes splitting multi-part tasks; you confirm')
								: agentsMode === 'on'
									? $i18n.t('Agents · On — always fan this task out to multiple agents')
									: $i18n.t('Agents — click to cycle Off → Auto → On')}
							on:click={cycleAgentsMode}
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
							{$i18n.t('Agents')}{#if agentsMode === 'auto'}<span class="opacity-80">· {$i18n.t('Auto')}</span>{:else if agentsMode === 'on'}<span class="opacity-80">· {$i18n.t('On')}</span>{/if}
						</button>
						{/if}

						<!-- attach menu: the + opens a multi-choice popup (Add image / Attach files) -->
						<div class="relative">
							<button
								class="text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 p-1.5"
								title={$i18n.t('Add attachment')}
								aria-label={$i18n.t('Add attachment')}
								on:click={() => openMenu(showAttachMenu ? '' : 'attach')}
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

						<div class="flex-1"></div>

						<!-- model selector → pick from available models -->
						<div class="relative">
							<button
								class="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-lg border border-gray-200 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05] text-gray-500 dark:text-gray-400 hover:bg-black/[0.06] dark:hover:bg-white/10 hover:text-gray-700 dark:hover:text-gray-200 transition max-w-[10rem]"
								on:click={toggleModelMenu}
								title={$i18n.t('Model')}
							>
								<span class="truncate">{displayModel}</span>
								<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-3 shrink-0"><path d="M6 9l6 6 6-6" stroke-linecap="round" /></svg>
							</button>
							{#if showModelMenu}
								<div class="absolute bottom-full right-0 mb-1 z-40 w-64 max-h-72 overflow-y-auto rounded-xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-800 shadow-xl py-1 text-xs">
									{#if !modelOptions.length}
										<div class="px-3 py-1.5 text-gray-400">{$i18n.t('No models available.')}</div>
									{/if}
									{#each modelGroups as g}
										<div class="px-3 pt-1.5 pb-1 text-[10px] uppercase tracking-wider text-gray-400">{g.label}</div>
										{#each g.models as m}
											<button class="w-full flex items-center justify-between gap-2 text-left px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-850" on:click={() => pickModel(m.id)}>
												<span class="truncate">{m.name || m.id}</span>
												{#if displayModel === m.id}<span class="shrink-0 text-blue-500">✓</span>{/if}
											</button>
										{/each}
									{/each}
								</div>
							{/if}
						</div>

						<!-- model + context/token usage (logs real tokens used vs the context window) -->
						<!-- usage gauge → click for the full context/token breakdown -->
						<div class="relative hidden sm:block">
							<button
								class="flex items-center gap-2 text-[10px] text-gray-500 px-1.5 py-1 hover:bg-black/[0.04] dark:hover:bg-white/[0.06] transition"
								on:click={() => openMenu(showUsageStats ? '' : 'usage')}
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
						{#if sessionLoadError && session}
							<!-- background refresh failing; the poll loop keeps retrying on its own -->
							<span class="text-[11px] text-amber-500"
								>{$i18n.t('Connection lost — retrying…')}</span
							>
						{/if}
					</div>
					{#if sendError}<div class="text-[11px] text-red-500 mt-1">{sendError}</div>{/if}
					{#if permError}<div class="text-[11px] text-red-500 mt-1">{permError}</div>{/if}
					</div>
				</div>
					</div>
				</Pane>
				{#if (dockOpen && (topHasAny || bottomHasAny)) || overlayRunId}
					<PaneResizer class="w-1.5 shrink-0 bg-gray-100 dark:bg-gray-850 hover:bg-blue-400 dark:hover:bg-blue-500 transition" />
					<!-- RIGHT PANE: the workspace 2×2 dock, OR the Workflow Inspector when a run is
					     open — the inspector pushes the chat narrower instead of taking over the page. -->
					<Pane bind:pane={rightPane} defaultSize={overlayRunId ? inspectorSize : dockSize} minSize={22} maxSize={72} class="min-h-0 bg-gray-100 dark:bg-gray-950">
						{#if (topHasAny || bottomHasAny) || overlayRunId}
						<!-- When a run is open the inspector sits BESIDE the workspace dock (not over it),
						     so the panels stay usable; the dock shrinks to a side strip. -->
						<div class="flex h-full min-h-0">
						{#if topHasAny || bottomHasAny}
						<div class="h-full min-h-0 min-w-0 overflow-hidden order-last {overlayRunId ? 'border-l border-gray-200 dark:border-white/10' : ''}" style={overlayRunId ? 'flex: 0 0 38%' : 'flex: 1 1 100%'}>
							<!-- Tabbed dock (Claude-Code-Desktop style): a tab strip over ONE full-height
							     panel. The ⋯ menu still decides which tabs exist; the strip switches. -->
							<div class="h-full p-1">
							<div class="flex flex-col min-h-0 h-full bg-gray-50 dark:bg-gray-900 rounded-xl border border-gray-200 dark:border-white/10 shadow-lg shadow-black/30 overflow-hidden text-gray-700 dark:text-gray-200">
								<!-- tab strip -->
								<div class="shrink-0 flex items-center gap-0 px-2 border-b border-gray-200 dark:border-white/10 bg-black/[0.03] dark:bg-white/[0.05]">
									{#each dockTabs as t (t.key)}
										<button
											type="button"
											draggable="true"
											on:dragstart={() => (dragKey = t.key)}
											on:dragover|preventDefault
											on:drop|preventDefault={() => onTabDrop(t.key)}
											class="relative px-3 py-2 text-[11px] font-medium transition cursor-grab active:cursor-grabbing {dockTab ===
											t.key
												? 'text-gray-800 dark:text-gray-100'
												: 'text-gray-500 hover:text-gray-600 dark:hover:text-gray-300'}"
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
										class="ml-auto shrink-0 text-gray-500 hover:text-gray-700 dark:hover:text-gray-200 transition p-1.5"
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
													<button class="flex items-center gap-1 text-[10px] uppercase tracking-wider text-gray-500 hover:text-gray-600 dark:hover:text-gray-300 transition" on:click={() => (showFinished = !showFinished)}>
														<svg class="size-3 transition-transform {showFinished ? 'rotate-90' : ''}" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M7.21 14.77a.75.75 0 0 1 .02-1.06L11.168 10 7.23 6.29a.75.75 0 1 1 1.04-1.08l4.5 4.25a.75.75 0 0 1 0 1.08l-4.5 4.25a.75.75 0 0 1-1.06-.02Z" clip-rule="evenodd" /></svg>
														<span>{$i18n.t('Finished')} {finishedTasks.length}</span>
													</button>
													<button class="text-[10px] text-blue-400 hover:underline" on:click={clearBg}>{$i18n.t('Clear')}</button>
												</div>
												{#if showFinished}
													{#each finishedTasks as t (t.id)}
														<BackgroundTaskCard run={t} on:openRun={(e) => headerOpenRunId(e.detail.id)} on:viewLogs={(e) => viewLogs(e.detail.id, e.detail.agentTab)} on:retried={() => loadSession()} />
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
									<div class="flex-1 min-h-0 flex flex-col">
										{#if diffError || sessionFilesError}
											<!-- honest degraded state: the diff / file-listing fetch failed -->
											<div class="shrink-0 flex items-center gap-2 px-3 py-1.5 text-[11px] text-red-500 dark:text-red-400 bg-red-500/5 border-b border-red-500/15">
												<span class="truncate"
													>{diffError
														? $i18n.t("Couldn't load the changes.")
														: $i18n.t("Couldn't load the file list.")}</span
												>
												<button
													class="ml-auto shrink-0 underline hover:no-underline"
													on:click={() => {
														if (diffError) loadDiff();
														if (sessionFilesError) loadSessionFiles();
													}}>{$i18n.t('Retry')}</button
												>
											</div>
										{/if}
										<div class="flex-1 min-h-0">
											<WorkspaceFileRail bind:tab={fileTab} {changedFiles} {artifacts} {selectedFile} sessionFiles={sessionFilePaths} {sessionFilesLoading} on:select={(e) => onFileSelect(e.detail.path)} on:selectArtifact={(e) => onArtifactSelect(e.detail.id)} />
										</div>
									</div>
								{:else if dockTab === 'sh'}
									<div class="flex-1 min-h-0">
										<ShellTab {sessionId} />
									</div>
								{:else if dockTab === 'bw'}
									<div class="flex-1 min-h-0">
										<BrowserPanel />
									</div>
								{:else}
									<div class="flex-1 min-h-0">
										<WorkspaceMainPanel showChat={false} bind:tab={mainTab} {selectedFile} diffLines={selectedFileObj ? selectedFileObj.lines : []} {fileContent} {fileLoading} {fileBinary} {fileTruncated} {fileError} hasRepo={!!sessionId} hasChanges={changedFiles.length > 0} on:refresh={refreshFiles}>
											<div slot="logs" class="h-full overflow-auto">
												{#if logsRunId || latestTurnId}
													{#key logsRunId || latestTurnId}<RunView wsId={logsRunId || latestTurnId} mode="dock" onOpenFull={() => headerOpenRunId(logsRunId || latestTurnId)} />{/key}
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
	{#if anyToolbarMenuOpen}
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
					{#if pendingAction.reason}
						<p class="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
							<span class="text-gray-400 dark:text-gray-500">{$i18n.t('Why')}:</span>
							{pendingAction.reason}
						</p>
					{/if}
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
				{#if pendingQueue.length > 1}
					<div class="rounded-lg border border-gray-200 dark:border-gray-800 divide-y divide-gray-100 dark:divide-gray-850">
						<div class="px-2 py-1 text-[10px] uppercase tracking-wide text-gray-400">
							{$i18n.t('Waiting behind this one')} · {pendingQueue.length - 1}
						</div>
						{#each pendingQueue.slice(1) as q (q.action_id)}
							<div class="flex items-center gap-2 px-2 py-1 text-[11px] text-gray-500 dark:text-gray-400">
								<code class="font-mono truncate">{q.tool || $i18n.t('action')}</code>
								<span
									class="ml-auto shrink-0 text-[10px] uppercase tracking-wide {q.risk === 'high'
										? 'text-red-500'
										: 'text-gray-400'}">{q.risk || ''}</span
								>
							</div>
						{/each}
					</div>
				{/if}
				<div class="flex items-center justify-end gap-2">
					<button
						class="text-xs px-3 py-1.5 rounded-lg text-gray-500 hover:text-gray-700 dark:hover:text-gray-200"
						disabled={approvalBusy}
						on:click={() => resolvePending(false)}>{$i18n.t('Deny')}</button
					>
					<button
						class="text-xs px-3 py-1.5 rounded-lg border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-850 disabled:opacity-50 transition"
						disabled={approvalBusy}
						title={$i18n.t('Approve and stop asking for matching actions this session')}
						on:click={() => resolvePending(true, 'session')}
						>{$i18n.t('Approve for this session')}</button
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
	<PrDrawer
		bind:show={showPrDrawer}
		{sessionId}
		{session}
		diff={sessionDiff}
		hasGithub={sessionHasGithub}
	/>

	{#if showCustomize}
		<button
			class="fixed inset-0 z-40 bg-black/50 cursor-default"
			aria-label={$i18n.t('Close')}
			on:click={() => setCustomize(false)}
		></button>
		<!-- Customize IN Build — CENTERED MODAL (popup in the middle), not a right drawer. -->
		<div class="fixed inset-0 z-50 flex items-center justify-center p-4 pointer-events-none">
			<div
				class="pointer-events-auto w-full max-w-3xl max-h-[85vh] rounded-2xl bg-white dark:bg-gray-950 border border-gray-100 dark:border-gray-850 shadow-2xl flex flex-col overflow-hidden"
			>
				<div class="shrink-0 flex items-center gap-2 px-4 py-3 border-b border-gray-100 dark:border-gray-850">
					<div class="min-w-0">
						<div class="text-sm font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Tune')}</div>
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
			</div>
		</div>
	{/if}

	<!-- Routines IN Build — FULL-PAGE inside Build (fills the content area to the right of
	     the main sidebar, not a right drawer). ?panel=routines. -->
	{#if showRoutines}
		<div
			class="fixed top-0 right-0 bottom-0 left-0 z-50 flex flex-col bg-white dark:bg-gray-950 {$showSidebar
				? 'md:left-[var(--sidebar-width)]'
				: ''}"
		>
			<div class="shrink-0 flex items-center gap-2 px-5 py-3 border-b border-gray-100 dark:border-white/8">
				<div class="min-w-0">
					<div class="text-sm font-semibold text-gray-800 dark:text-gray-100">{$i18n.t('Routines')}</div>
					<div class="text-[11px] text-gray-400">{$i18n.t('Schedule agent tasks — without leaving Build')}</div>
				</div>
				<button
					class="ml-auto shrink-0 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 p-1"
					aria-label={$i18n.t('Close')}
					on:click={() => setRoutines(false)}
				>
					<svg viewBox="0 0 20 20" fill="currentColor" class="size-4"><path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" /></svg>
				</button>
			</div>
			<div class="flex-1 min-h-0 overflow-y-auto px-5 py-4">
				<div class="max-w-5xl mx-auto w-full">
					<Automations mode="dock" embed context="coding" />
				</div>
			</div>
		</div>
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
