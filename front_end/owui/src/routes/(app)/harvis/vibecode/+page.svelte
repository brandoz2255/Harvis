<script lang="ts">
	import { getContext, onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { WEBUI_NAME, config, showSidebar, models } from '$lib/stores';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { uploadFile } from '$lib/apis/files';
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
		type AttachedRepo,
		type VibecodeSession,
		type VibecodeTurn,
		type PendingAction
	} from '$lib/apis/agent-runs';
	import RunView from '$lib/agent-studio/RunView.svelte';
	import PlanPanel from '$lib/agent-studio/PlanPanel.svelte';
	import VibecodeSessionDiff from '$lib/agent-studio/VibecodeSessionDiff.svelte';
	import GitHubRepoModal from '$lib/agent-studio/GitHubRepoModal.svelte';
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

	// ── URL-driven: the sidebar session list + New session set ?session. ──
	$: sessionId = $page.url.searchParams.get('session') || '';

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

	// ── Background-tasks panel (right rail) — this session's turns as task chips. ──
	let bgHidden: Set<string> = new Set(); // finished tasks the user "Clear"-ed from the panel
	$: runningTasks = turns.filter((t) => t.status === 'running');
	$: finishedTasks = turns.filter((t) => t.status !== 'running' && !bgHidden.has(t.id));
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

	// ── Token / context usage — real per-turn OpenAI usage, summed across the session.
	// prompt_tokens of the latest turn ≈ current context occupancy vs the model's window. ──
	$: usageTurns = turns.filter((t) => (t.prompt_tokens ?? 0) > 0 || (t.completion_tokens ?? 0) > 0);
	$: lastUsage = usageTurns.length ? usageTurns[usageTurns.length - 1] : null;
	$: sessionTokens = usageTurns.reduce(
		(s, t) => s + (t.prompt_tokens || 0) + (t.completion_tokens || 0),
		0
	);
	$: ctxUsed = lastUsage?.prompt_tokens || 0;
	$: ctxWindow = lastUsage?.context_window || 24576;
	$: ctxPct = ctxWindow ? Math.min(100, Math.round((ctxUsed / ctxWindow) * 100)) : 0;
	$: usageModel = lastUsage?.model_name || 'llama3.1:8b';
	const fmtTok = (n: number) =>
		n >= 10000 ? Math.round(n / 1000) + 'k' : n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n);

	// The gauge is interactive: click the bar → full usage stats; click the model → a picker.
	let showUsageStats = false;
	let showModelMenu = false;
	let selectedModel = ''; // '' ⇒ use the turn/session default; set ⇒ sent on every turn
	$: displayModel = selectedModel || usageModel;
	$: ctxAvail = Math.max(0, ctxWindow - ctxUsed);
	$: modelOptions = ($models || []).filter((m: any) => m && m.id);
	const pickModel = (id: string) => {
		selectedModel = id;
		showModelMenu = false;
	};

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
					const s = await createVibecodeSession({ local_folder_name: localFolderName });
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
					await startVibecodeTurn(s.id, { task_brief: text, attachments, model_name: selectedModel || undefined, run_mode: runMode });
					prompt = '';
					attachedImages = [];
					goto(`/harvis/vibecode?session=${s.id}`);
				} else if (localFolderFiles.length) {
					// Read-only local folder (webkitdirectory — Brave/Firefox/Safari): seed the
					// snapshot → clone-mode session. No live writeback (no persistent handle).
					const s = await createVibecodeSession({ local_folder_name: localFolderName });
					createdId = s.id;
					seedingStatus = $i18n.t('Loading into workspace…');
					await seedVibecodeLocalFolder(s.id, localFolderFiles);
					seedingStatus = '';
					await startVibecodeTurn(s.id, { task_brief: text, attachments, model_name: selectedModel || undefined, run_mode: runMode });
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
						github_branch: selectedGithubRepo.branch
					});
					createdId = s.id;
					await startVibecodeTurn(s.id, { task_brief: text, attachments, model_name: selectedModel || undefined, run_mode: runMode });
					prompt = '';
					attachedImages = [];
					goto(`/harvis/vibecode?session=${s.id}`);
				} else {
					const s = await createVibecodeSession({
						repo_path: selectedRepoPath || undefined,
						isolation_mode: isolationMode,
						permission_mode: isolationMode === 'inplace' ? permissionMode : undefined
					});
					createdId = s.id;
					await startVibecodeTurn(s.id, { task_brief: text, attachments, model_name: selectedModel || undefined, run_mode: runMode });
					prompt = '';
					attachedImages = [];
					goto(`/harvis/vibecode?session=${s.id}`);
				}
			} else {
				await startVibecodeTurn(sessionId, { task_brief: text, attachments, model_name: selectedModel || undefined, run_mode: runMode });
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

	onMount(async () => {
		if (!enabled) return;
		fsSupported = supportsLocalFs();
		if (fsSupported) recentFolders = await listRecentFolders();
		repos = await getAttachedRepos();
		await loadSession();
		await relinkSessionFolder();
		schedule();
	});
	onDestroy(() => clearTimeout(pollTimer));
</script>

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
		class="w-full h-full flex min-h-0 text-sm {$showSidebar
			? 'md:max-w-[calc(100%-var(--sidebar-width))]'
			: ''}"
	>
		<!-- CENTER -->
		<div class="flex-1 min-w-0 flex flex-col min-h-0">
			{#if sessionId}
				<!-- Session header bar -->
				<div
					class="flex items-center gap-2 px-4 py-2.5 border-b border-gray-100 dark:border-gray-850 shrink-0"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="1.8"
						class="size-4 text-gray-400 shrink-0"
					>
						<path d="M16 18l6-6-6-6M8 6l-6 6 6 6" stroke-linecap="round" stroke-linejoin="round" />
					</svg>
					<span class="font-medium text-gray-800 dark:text-gray-100 truncate">
						{session?.emoji ? session.emoji + ' ' : ''}{session?.title || $i18n.t('Untitled session')}
					</span>
					{#if session?.repo_path}
						<span
							class="text-[11px] px-1.5 py-0.5 rounded-md bg-gray-100 dark:bg-gray-850 text-gray-500 font-mono shrink-0"
						>
							{session.repo_display_path ||
								session.repo_path.split('/').filter(Boolean).pop()}{session.base_branch
								? ` · ${session.base_branch}`
								: ''}
						</span>
					{/if}
				</div>

				<!-- Conversation thread -->
				<div class="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-4">
					{#if !turns.length}
						<div class="text-xs text-gray-400 text-center pt-8">
							{$i18n.t('No turns yet — send a message to start coding.')}
						</div>
					{/if}
					{#each turns as t (t.id)}
						<div class="flex justify-end">
							<div
								class="max-w-[60%] rounded-2xl bg-gray-100 dark:bg-gray-850 px-3.5 py-2 text-gray-800 dark:text-gray-100"
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
													class="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-gray-200 dark:bg-gray-800 text-gray-600 dark:text-gray-300"
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
							<div class="rounded-2xl border border-gray-100 dark:border-gray-850 overflow-hidden">
								{#key t.id}<RunView wsId={t.id} mode="dock" />{/key}
							</div>
						{:else}
							<!-- assistant reply (left): the model's explanation; full run is one click away -->
							<div class="flex flex-col items-start gap-1.5">
								<div
									class="max-w-[85%] rounded-2xl bg-white dark:bg-gray-900 border border-gray-100 dark:border-gray-850 px-3.5 py-2 text-sm text-gray-800 dark:text-gray-100 markdown-prose markdown-prose-sm"
								>
									{#if t.status === 'error'}
										<span class="text-red-500 dark:text-red-400"
											>{t.error_message || $i18n.t('This turn failed.')}</span
										>
									{:else}
										<Markdown id={`vc-turn-${t.id}`} content={t.final_summary || $i18n.t('Done.')} />
									{/if}
								</div>
								<button
									class="inline-flex items-center gap-1 text-[11px] text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
									on:click={() => toggleRun(t.id)}
								>
									<svg
										xmlns="http://www.w3.org/2000/svg"
										viewBox="0 0 20 20"
										fill="currentColor"
										class="size-3 transition-transform {expandedRuns[t.id] ? 'rotate-90' : ''}"
										><path
											fill-rule="evenodd"
											d="M7.21 14.77a.75.75 0 01.02-1.06L11.168 10 7.23 6.29a.75.75 0 111.04-1.08l4.5 4.25a.75.75 0 010 1.08l-4.5 4.25a.75.75 0 01-1.06-.02z"
											clip-rule="evenodd"
										/></svg
									>
									{expandedRuns[t.id] ? $i18n.t('Hide run') : $i18n.t('View run')}
								</button>
								{#if expandedRuns[t.id]}
									<div
										class="w-full rounded-2xl border border-gray-100 dark:border-gray-850 overflow-hidden"
									>
										{#key t.id}<RunView wsId={t.id} mode="dock" />{/key}
									</div>
								{/if}
							</div>
						{/if}
					{/each}
				</div>
			{:else}
				<!-- No-session: empty-state hint (controls live in the composer below). -->
				<div class="flex-1 min-h-0 flex flex-col items-center justify-center px-6">
					<div class="w-full max-w-xl text-center">
						<h2 class="text-base font-medium text-gray-800 dark:text-gray-100 mb-1">
							{$i18n.t('Start a coding session')}
						</h2>
						<p class="text-xs text-gray-400">
							{$i18n.t(
								'Pick a repo and mode below, describe a task, and Harvis works — each follow-up builds on the last.'
							)}
						</p>
					</div>
				</div>
			{/if}

			{#if sessionId && turns.length}
				<!-- Session changes — pinned at the bottom of the chat, above the composer line -->
				<div class="shrink-0 px-3 pt-2 max-w-3xl w-full mx-auto">
					<VibecodeSessionDiff {sessionId} refreshKey={doneTurns} />
				</div>
			{/if}

			<!-- Composer cluster (pinned bottom) -->
			<div class="shrink-0 border-t border-gray-100 dark:border-gray-850 p-3">
				<div class="w-full max-w-3xl mx-auto">
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
							class="flex items-center justify-between gap-2 mb-2 text-[11px] px-2.5 py-1.5 rounded-lg bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300"
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
							class="w-full text-sm rounded-xl bg-gray-50 dark:bg-gray-850 border border-gray-100 dark:border-gray-800 py-2.5 pl-3.5 pr-10 outline-none resize-none disabled:opacity-50 leading-relaxed"
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
							class="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 disabled:opacity-40 disabled:hover:text-gray-400 transition"
							disabled={composerDisabled || !prompt.trim()}
							on:click={submit}
							aria-label={sessionId ? $i18n.t('Send') : $i18n.t('Start')}
							title={sessionId ? $i18n.t('Send') : $i18n.t('Start')}
						>
							{#if sending}
								<svg class="size-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" /><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8V0C5.4 0 0 5.4 0 12h4z" /></svg>
							{:else}
								<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-4"><path d="M20 5v6a3 3 0 0 1-3 3H5" stroke-linecap="round" stroke-linejoin="round" /><path d="M9 10l-4 4 4 4" stroke-linecap="round" stroke-linejoin="round" /></svg>
							{/if}
						</button>
					</div>

					<!-- toolbar -->
					<div class="flex items-center gap-1.5 mt-2">
						<!-- Run-mode = the permission PYRAMID (per turn): Plan ▸ Ask ▸ Accept ▸ Auto.
						     The agent works on a clone; the diff/PR is the outer gate. -->
						<div class="relative">
							<button
								type="button"
								class="inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg transition hover:opacity-90 {runMode ===
								'plan'
									? 'bg-gray-100 dark:bg-gray-850 text-gray-600 dark:text-gray-300'
									: runMode === 'full-auto'
										? 'bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300'
										: 'bg-blue-50 dark:bg-blue-950/50 text-blue-700 dark:text-blue-300'}"
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

						<!-- attach menu: the + opens a multi-choice popup (Add image / Attach files) -->
						<div class="relative">
							<button
								class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 p-1.5 rounded-md"
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
							class="text-gray-300 dark:text-gray-600 p-1.5 rounded-md cursor-default"
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
								class="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-800 transition max-w-[10rem]"
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
								class="flex items-center gap-2 text-[10px] text-gray-400 px-1.5 py-1 rounded-md hover:bg-gray-100 dark:hover:bg-gray-850 transition"
								on:click={() => (showUsageStats = !showUsageStats)}
								title={$i18n.t('Context & token usage')}
							>
								<div class="flex flex-col items-end leading-tight">
									<span class="tabular-nums text-gray-500 dark:text-gray-400">{fmtTok(ctxUsed)} / {fmtTok(ctxWindow)} · {ctxPct}%</span>
									<span class="text-gray-400 dark:text-gray-500">{fmtTok(sessionTokens)} tok</span>
								</div>
								<div class="w-14 h-1.5 rounded-full bg-gray-200 dark:bg-gray-800 overflow-hidden">
									<div class="h-full rounded-full transition-all {ctxPct > 85 ? 'bg-red-500' : 'bg-blue-500'}" style="width: {ctxPct}%"></div>
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
									<div class="flex justify-between text-gray-500"><span>{$i18n.t('Session total')}</span><span class="tabular-nums">{sessionTokens.toLocaleString()} · {usageTurns.length} {$i18n.t('turns')}</span></div>
									<div class="flex justify-between text-gray-500"><span>{$i18n.t('Model')}</span><span class="truncate ml-2 text-gray-700 dark:text-gray-300">{displayModel}</span></div>
								</div>
							{/if}
						</div>
						
						{#if anyRunning}<span class="text-[11px] text-gray-400">{$i18n.t('Working…')}</span>{/if}
					</div>
					{#if sendError}<div class="text-[11px] text-red-500 mt-1">{sendError}</div>{/if}
				</div>
			</div>
		</div>

		<!-- RIGHT rail: Run mode + Background tasks (top) + Plan (bottom) -->
		<div class="w-80 shrink-0 border-l border-gray-100 dark:border-gray-850 flex flex-col min-h-0">
			<!-- Mode note: Auto executes on a copy (diff/PR); Plan is read-only and fills this panel -->
			<div class="shrink-0 px-3 py-2 border-b border-gray-100 dark:border-gray-850">
				<div class="text-[10px] uppercase tracking-wider text-gray-400 mb-1.5">{$i18n.t('Mode')}</div>
				<div class="text-[11px] text-gray-400 leading-relaxed">
					{#if runMode === 'plan'}
						{$i18n.t('Plan — read-only. The agent reads the repo and drafts a step-by-step plan below; it changes nothing. Pick a higher rung to carry it out.')}
					{:else if runMode === 'ask'}
						{$i18n.t('Ask — the agent works on a copy and pauses for your approval before each edit or command.')}
					{:else if runMode === 'auto-accept'}
						{$i18n.t('Accept edits — edits auto-apply on the copy; risky ops (delete, push, .env) pause for approval. Review the diff or open a PR.')}
					{:else}
						{$i18n.t('Auto — the agent makes every change on a copy with no prompts; your originals stay untouched. Review the diff or open a pull request.')}
					{/if}
				</div>
			</div>
			<!-- Background tasks: this session's runs as task chips (running + finished) -->
			<div class="flex-1 min-h-0 flex flex-col border-b border-gray-100 dark:border-gray-850">
				<div class="px-3 py-2 text-xs font-medium text-gray-700 dark:text-gray-200 shrink-0">
					{$i18n.t('Background tasks')}
				</div>
				<div class="flex-1 min-h-0 overflow-y-auto px-2 pb-2 space-y-3">
					{#if runningTasks.length}
						<div class="space-y-1.5">
							<div class="px-1 text-[10px] uppercase tracking-wider text-gray-400">{$i18n.t('Running')}</div>
							{#each runningTasks as t (t.id)}
								<button
									class="w-full text-left rounded-xl bg-gray-50 dark:bg-gray-850/60 hover:bg-gray-100 dark:hover:bg-gray-800 transition px-3 py-2"
									on:click={() => toggleRun(t.id)}
								>
									<div class="flex items-center gap-2">
										<span class="size-2 rounded-full shrink-0 {bgDot(t.status)}"></span>
										<span class="truncate text-xs font-medium text-gray-700 dark:text-gray-200">{t.task_brief || $i18n.t('Run')}</span>
									</div>
									<div class="mt-0.5 pl-4 text-[11px] text-gray-400 truncate">{t.model_name || 'VibeCode'} · {bgStatusLabel(t.status)}</div>
								</button>
							{/each}
						</div>
					{/if}
					{#if finishedTasks.length}
						<div class="space-y-1.5">
							<div class="flex items-center justify-between px-1">
								<span class="text-[10px] uppercase tracking-wider text-gray-400">{$i18n.t('Finished')}</span>
								<button class="text-[11px] text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition" on:click={clearBg}>{$i18n.t('Clear')}</button>
							</div>
							{#each finishedTasks as t (t.id)}
								<button
									class="w-full text-left rounded-xl bg-gray-50 dark:bg-gray-850/60 hover:bg-gray-100 dark:hover:bg-gray-800 transition px-3 py-2"
									on:click={() => toggleRun(t.id)}
								>
									<div class="flex items-center gap-2">
										<span class="size-2 rounded-full shrink-0 {bgDot(t.status)}"></span>
										<span class="truncate text-xs font-medium text-gray-700 dark:text-gray-200">{t.task_brief || $i18n.t('Run')}</span>
									</div>
									<div class="mt-0.5 pl-4 text-[11px] text-gray-400 truncate">{t.model_name || 'VibeCode'} · {bgStatusLabel(t.status)}</div>
								</button>
							{/each}
						</div>
					{/if}
					{#if !runningTasks.length && !finishedTasks.length}
						<div class="text-xs text-gray-400 px-2 pt-3">{$i18n.t('Nothing running.')}</div>
					{/if}
				</div>
			</div>
			<div class="flex-1 min-h-0 flex flex-col">
				<div class="px-3 py-2 text-xs font-medium text-gray-700 dark:text-gray-200 shrink-0">
					{$i18n.t('Plan')}
				</div>
				<div class="flex-1 min-h-0 overflow-y-auto px-2 pb-2">
					<PlanPanel wsId={latestTurnId} />
				</div>
			</div>
		</div>
	</div>

	<!-- click-away backdrop for the composer menus -->
	{#if showModeMenu || showRepoMenu || showExecMenu || showAttachMenu || showUsageStats || showModelMenu}
		<button
			class="fixed inset-0 z-20 cursor-default"
			tabindex="-1"
			aria-hidden="true"
			on:click={() => {
				showModeMenu = false;
				showRepoMenu = false;
				showExecMenu = false;
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

	<!-- GitHub: connect → pick a repo (or clone a public repo by name) → clone-mode session. -->
	<GitHubRepoModal bind:show={showGithubModal} onPick={pickGithubRepo} />

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
