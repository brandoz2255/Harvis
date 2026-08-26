<script lang="ts">
	// Plugins & Skills — a calm capability marketplace for Harvis (ChatGPT-plugin
	// -directory style, not an admin panel). Two tabs over one shell:
	//   • Plugins  — curated capability catalog (executable integrations/providers)
	//                grouped by category, with an Installed row and a click-through
	//                detail side-panel. States are representative; live status
	//                binding to /api/owui/capabilities is a follow-up.
	//   • Skills   — reusable procedures (real /api/v1/skills), same calm rows,
	//                governance (audit → verdict → enable) behind the detail panel,
	//                plus a starter workflow library.
	// Detail lives behind click — the default directory stays visually simple.
	import { getContext, onMount } from 'svelte';
	import { fly, fade } from 'svelte/transition';
	import { toast } from 'svelte-sonner';
	import ConnectorLogo from './ConnectorLogo.svelte';
	import {
		getSkills,
		createNewSkill,
		toggleSkillById,
		deleteSkillById,
		auditSkill,
		setSkillVerdict
	} from '$lib/apis/skills';

	export let token = '';
	const i18n: any = getContext('i18n');

	let tab: 'plugins' | 'skills' = 'plugins';
	let scope: 'public' | 'personal' = 'public';
	let query = '';
	let createOpen = false;
	let selected: any = null; // detail-panel item (plugin OR skill)
	let selKind: 'plugin' | 'skill' = 'plugin';

	// ── icons ────────────────────────────────────────────────────────────────
	// ConnectorLogo already carries verified brand marks; reuse it for those ids.
	// Everything else gets a calm lucide-style glyph with a subtle accent tint.
	const CL_IDS = new Set([
		'github', 'notion', 'slack', 'git', 'postgres', 'sqlite', 'puppeteer',
		'filesystem', 'fetch', 'memory', 'sequential-thinking', 'custom-url', 'custom-stdio'
	]);
	const GLYPHS: Record<string, { d: string; color: string }> = {
		'computer-use': { d: 'M3 4h18v12H3zM8 20h8M12 16v4', color: 'text-sky-500' },
		chrome: { d: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM3 12h18M12 3c2.4 2.6 2.4 15.4 0 18M12 3c-2.4 2.6-2.4 15.4 0 18', color: 'text-indigo-400' },
		discord: { d: 'M8 12h.01M16 12h.01M18 6a13 13 0 0 0-12 0 16 16 0 0 0-2 11 12 12 0 0 0 4 2l1-2m8 0 1 2a12 12 0 0 0 4-2 16 16 0 0 0-2-11', color: 'text-indigo-400' },
		comfyui: { d: 'M4 5h5v5H4zM15 14h5v5h-5zM9 7.5h4a2 2 0 0 1 2 2v5', color: 'text-fuchsia-400' },
		openclaw: { d: 'M9 3h6M12 3v3M6 6h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2ZM9 12h.01M15 12h.01', color: 'text-amber-400' },
		opencode: { d: 'M8 9l-3 3 3 3M16 9l3 3-3 3M13 6l-2 12', color: 'text-emerald-400' },
		ssh: { d: 'M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1ZM7 9l3 3-3 3M13 15h4', color: 'text-slate-400' },
		'local-shell': { d: 'M4 17l6-6-6-6M12 19h8', color: 'text-slate-400' },
		mcp: { d: 'M9 2v6M15 2v6M12 8v3m0 0a5 5 0 0 1 5 5v2H7v-2a5 5 0 0 1 5-5ZM7 18v2a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2v-2', color: 'text-slate-400' },
		'printer-3d': { d: 'M6 9V4h12v5M4 9h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2v4H6v-4H4a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2ZM9 15h6', color: 'text-cyan-400' },
		octoprint: { d: 'M6 9V4h12v5M4 9h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2v4H6v-4H4a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2ZM9 13h.01M12 13h.01M15 13h.01', color: 'text-teal-400' },
		klipper: { d: 'M6 9V4h12v5M4 9h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2h-2v4H6v-4H4a2 2 0 0 1-2-2v-4a2 2 0 0 1 2-2Z', color: 'text-rose-400' },
		ollama: { d: 'M12 3a4 4 0 0 0-4 4v1a3 3 0 0 0 0 6v2a4 4 0 0 0 8 0v-2a3 3 0 0 0 0-6V7a4 4 0 0 0-4-4Z', color: 'text-orange-400' },
		gdrive: { d: 'M8 4h8l5 9-4 6H7l-4-6zM8 4l5 9M16 4l-5 9M7 19l5-6h9', color: 'text-emerald-400' },
		gmail: { d: 'M3 6h18v12H3zM3 7l9 6 9-6', color: 'text-red-400' },
		gcalendar: { d: 'M4 5h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1ZM3 9h18M8 3v4M16 3v4', color: 'text-sky-500' },
		linear: { d: 'M4 4h16v16H4zM8 16 16 8', color: 'text-indigo-400' },
		clickup: { d: 'M5 15l7-7 7 7M5 10l7-7 7 7', color: 'text-violet-400' },
		dropbox: { d: 'M21 8 12 3 3 8l9 5 9-5zM3 8v8l9 5 9-5V8', color: 'text-sky-400' },
		asana: { d: 'M12 4a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM7 13a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM17 13a3 3 0 1 0 0 6 3 3 0 0 0 0-6z', color: 'text-rose-400' },
		'data-analytics': { d: 'M4 20V10M10 20V4M16 20v-7M2 20h20', color: 'text-violet-400' },
		docs: { d: 'M7 3h7l5 5v13H7zM14 3v5h5M9 13h6M9 17h6', color: 'text-sky-500' },
		sheets: { d: 'M4 4h16v16H4zM4 10h16M4 15h16M10 4v16', color: 'text-emerald-400' },
		slides: { d: 'M3 4h18v11H3zM8 20l4-5 4 5M9 9l3-3 3 3', color: 'text-amber-400' },
		'web-search': { d: 'M11 3a8 8 0 1 0 0 16 8 8 0 0 0 0-16zM3 11h16M11 3c2.4 2.5 2.4 13.5 0 16M11 3c-2.4 2.5-2.4 13.5 0 16M21 21l-3-3', color: 'text-sky-400' },
		knowledge: { d: 'M5 4a2 2 0 0 1 2-2h12v16H7a2 2 0 0 0-2 2zM5 20a2 2 0 0 1 2-2h12', color: 'text-teal-400' },
		routines: { d: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 8v4l3 2', color: 'text-amber-400' },
		skill: { d: 'M12 3l1.9 5.8H20l-4.9 3.6 1.9 5.8L12 14.6 7 18.2l1.9-5.8L4 8.8h6.1L12 3z', color: 'text-violet-400' }
	};

	// ── plugin catalog (curated) ─────────────────────────────────────────────
	type PState = 'install' | 'installed' | 'configure' | 'needs_auth' | 'disabled' | 'ready' | 'error';
	interface Plugin {
		id: string;
		name: string;
		desc: string;
		category: string;
		state: PState;
		scope: 'public' | 'personal';
		caps: string[];
		lane: string;
		auth: string;
		setup: string[];
	}
	const CATEGORY_ORDER = ['Featured', 'Development', 'Productivity', 'Local AI', 'Hardware', 'Automation', 'Research'];

	let plugins: Plugin[] = [
		{ id: 'computer-use', name: 'Computer Use', desc: 'Control desktop apps from Harvis', category: 'Featured', state: 'ready', scope: 'public', caps: ['screen capture', 'mouse & keyboard', 'app control'], lane: 'Lane 4 · elevated', auth: 'Local — no credentials', setup: ['Grant screen-recording permission', 'Approve the apps Harvis may control'] },
		{ id: 'chrome', name: 'Chrome', desc: 'Drive Chrome with Harvis', category: 'Featured', state: 'install', scope: 'public', caps: ['navigate', 'read page', 'fill forms'], lane: 'Lane 3 · sandboxed', auth: 'Browser extension', setup: ['Install the Harvis Chrome extension', 'Pin it and sign in'] },
		{ id: 'github', name: 'GitHub', desc: 'Triage PRs, issues, CI, and publish changes', category: 'Featured', state: 'needs_auth', scope: 'public', caps: ['read repos', 'open PRs', 'read CI'], lane: 'Lane 3 · sandboxed', auth: 'OAuth — not connected', setup: ['Connect your GitHub account', 'Pick which repositories Harvis may access'] },
		{ id: 'discord', name: 'Discord', desc: 'Run Harvis from Discord', category: 'Featured', state: 'ready', scope: 'public', caps: ['read messages', 'reply', 'slash commands'], lane: 'Lane 2 · messaging', auth: 'Bot token — connected', setup: ['Invite the Harvis bot to your server', 'Sync slash commands'] },
		{ id: 'openclaw', name: 'OpenClaw', desc: 'Sandboxed agent runtime', category: 'Featured', state: 'ready', scope: 'public', caps: ['tool loop', 'sub-agents', 'shell (sandboxed)'], lane: 'Lane 3 · sandboxed', auth: 'Internal — no egress', setup: ['Runs on the internal network', 'No public internet access'] },
		{ id: 'comfyui', name: 'ComfyUI', desc: 'Local image generation', category: 'Featured', state: 'ready', scope: 'public', caps: ['txt2img', 'SD 1.5', 'PNG artifacts'], lane: 'Lane 2 · local', auth: 'Local — no credentials', setup: ['Runs at harvis-comfyui:8188', 'Enable HARVIS_OWUI_IMAGE_GENERATION to expose'] },

		{ id: 'local-shell', name: 'Local shell', desc: 'Run commands in the workspace sandbox', category: 'Development', state: 'ready', scope: 'public', caps: ['exec', 'run_code', 'run_tests', 'read/edit files'], lane: 'Lane 3 · sandboxed', auth: 'Local — no credentials', setup: ['Every command is authorized before it runs', 'Bounded to the workspace container'] },
		{ id: 'mcp', name: 'MCP servers', desc: 'Connect Model Context Protocol tools', category: 'Development', state: 'installed', scope: 'public', caps: ['tool discovery', 'stdio & remote'], lane: 'Lane 3 · sandboxed', auth: 'Per-connector', setup: ['Manage servers in Connectors', 'Browse the live MCP registry'] },
		{ id: 'ssh', name: 'SSH targets', desc: 'Run on remote machines', category: 'Development', state: 'configure', scope: 'personal', caps: ['pinned exec', 'probe', 'file transfer'], lane: 'Lane 4 · remote', auth: 'Key-pinned host', setup: ['Register a target host', 'Pin its host key and test'] },

		{ id: 'notion', name: 'Notion', desc: 'Notion workflows for specs and notes', category: 'Productivity', state: 'install', scope: 'public', caps: ['read pages', 'edit pages', 'search'], lane: 'Lane 3 · sandboxed', auth: 'OAuth', setup: ['Connect Notion', 'Choose which workspaces to share'] },
		{ id: 'linear', name: 'Linear', desc: 'Plan and build products', category: 'Productivity', state: 'install', scope: 'public', caps: ['issues', 'projects', 'cycles'], lane: 'Lane 3 · sandboxed', auth: 'OAuth', setup: ['Connect Linear', 'Select a team'] },
		{ id: 'gdrive', name: 'Google Drive', desc: 'Access, save, and share files', category: 'Productivity', state: 'needs_auth', scope: 'public', caps: ['read files', 'upload', 'search'], lane: 'Lane 3 · sandboxed', auth: 'OAuth — not connected', setup: ['Connect Google Drive', 'Grant read/write scope'] },
		{ id: 'gmail', name: 'Gmail', desc: 'Read and draft mail', category: 'Productivity', state: 'needs_auth', scope: 'public', caps: ['read', 'draft', 'label'], lane: 'Lane 3 · sandboxed', auth: 'OAuth — not connected', setup: ['Connect Gmail', 'Drafts require your confirmation to send'] },
		{ id: 'gcalendar', name: 'Google Calendar', desc: 'Read and create events', category: 'Productivity', state: 'needs_auth', scope: 'public', caps: ['read events', 'create events'], lane: 'Lane 3 · sandboxed', auth: 'OAuth — not connected', setup: ['Connect Google Calendar', 'Grant calendar scope'] },
		{ id: 'clickup', name: 'ClickUp', desc: 'Automate projects, docs, reports', category: 'Productivity', state: 'install', scope: 'public', caps: ['tasks', 'docs', 'reports'], lane: 'Lane 3 · sandboxed', auth: 'OAuth', setup: ['Connect ClickUp', 'Pick a workspace'] },
		{ id: 'dropbox', name: 'Dropbox', desc: 'Access, save, and share files', category: 'Productivity', state: 'install', scope: 'public', caps: ['read', 'upload', 'share'], lane: 'Lane 3 · sandboxed', auth: 'OAuth', setup: ['Connect Dropbox', 'Grant file scope'] },
		{ id: 'asana', name: 'Asana', desc: 'Turn chats into actions', category: 'Productivity', state: 'install', scope: 'public', caps: ['tasks', 'projects'], lane: 'Lane 3 · sandboxed', auth: 'OAuth', setup: ['Connect Asana', 'Select a project'] },

		{ id: 'ollama', name: 'Ollama', desc: 'Local model inference', category: 'Local AI', state: 'ready', scope: 'public', caps: ['chat', 'embeddings', 'tool calls'], lane: 'Lane 1 · local', auth: 'Local — no credentials', setup: ['Runs at ollama:11434', 'Pull the models you want'] },

		{ id: 'printer-3d', name: '3D Printer', desc: 'Send prints to your printer', category: 'Hardware', state: 'configure', scope: 'personal', caps: ['slice', 'send print', 'status'], lane: 'Lane 5 · hardware', auth: 'Local network', setup: ['Add your printer', 'Every print is human-approved'] },
		{ id: 'octoprint', name: 'OctoPrint', desc: 'Manage prints via OctoPrint', category: 'Hardware', state: 'install', scope: 'personal', caps: ['upload gcode', 'start/stop', 'temps'], lane: 'Lane 5 · hardware', auth: 'API key', setup: ['Add your OctoPrint URL', 'Paste an application key'] },
		{ id: 'klipper', name: 'Klipper / Moonraker', desc: 'Manage prints via Klipper', category: 'Hardware', state: 'install', scope: 'personal', caps: ['upload gcode', 'start/stop', 'macros'], lane: 'Lane 5 · hardware', auth: 'Moonraker key', setup: ['Add your Moonraker URL', 'Grant an API key'] },

		{ id: 'routines', name: 'Routines & Schedules', desc: 'Run prompts on a timer', category: 'Automation', state: 'ready', scope: 'public', caps: ['cron', 'chat delivery', 'coding runs'], lane: 'Lane 2 · scheduled', auth: 'Internal', setup: ['Create a Routine (coding) or Schedule (chat)', 'It fires on your local time'] },

		{ id: 'web-search', name: 'Web Search', desc: 'Search the web live', category: 'Research', state: 'disabled', scope: 'public', caps: ['search', 'fetch', 'summarize'], lane: 'Lane 3 · sandboxed', auth: 'Off by default', setup: ['Enable Web Research in the composer', 'Requests are proxied and audited'] },
		{ id: 'knowledge', name: 'Knowledge Bases', desc: 'RAG over your documents', category: 'Research', state: 'ready', scope: 'public', caps: ['ingest', 'chunk & embed', 'retrieve'], lane: 'Lane 1 · local', auth: 'Local — no credentials', setup: ['Create a knowledge base', 'Attach a repo or upload docs'] }
	];

	// state → { label, dot }. Buttons vary by state (installed/ready → menu, else pill).
	const STATE_META: Record<PState, { label: string; dot: string }> = {
		install: { label: 'Install', dot: '' },
		installed: { label: 'Installed', dot: 'bg-gray-400' },
		configure: { label: 'Configure', dot: 'bg-amber-500' },
		needs_auth: { label: 'Needs auth', dot: 'bg-amber-500' },
		disabled: { label: 'Disabled', dot: 'bg-slate-400' },
		ready: { label: 'Ready', dot: 'bg-emerald-500' },
		error: { label: 'Error', dot: 'bg-red-500' }
	};
	const isLive = (s: PState) => s === 'ready' || s === 'installed';

	// ── skills (real API) + starter workflow library ──────────────────────────
	let skills: any[] = [];
	let skillsLoaded = false;
	let skillsLoadError = '';
	const loadSkills = async () => {
		skillsLoadError = '';
		const r = await getSkills(token).catch((e) => {
			// Keep whatever list is on screen — a failed refresh must not read as
			// "all skills deleted". The error branch below covers the empty case.
			skillsLoadError = `${e}`;
			if (skills.length) toast.error(`${$i18n.t('Could not refresh skills')} — ${e}`);
			return null;
		});
		if (r) {
			skills = Array.isArray(r) ? r : (r?.skills ?? r?.items ?? []);
			skillsLoaded = true;
		}
	};
	const verdictOf = (s: any): string | null => s?.meta?.audit?.verdict ?? null;

	const WORKFLOW_LIBRARY = [
		{ id: 'repo-setup', name: 'Repo setup', desc: 'Clone, install deps, and boot a project', body: '# Repo setup\n\nGiven a repository, detect the stack, install dependencies, and start the dev server. Report the URL and any failures.' },
		{ id: 'discord-summary', name: 'Discord run summary', desc: 'Summarise an agent run for a Discord reply', body: '# Discord run summary\n\nTurn a completed run into a short, friendly Discord reply: what was done, what changed, and any follow-ups.' },
		{ id: 'image-gen', name: 'Image generation', desc: 'Compose a prompt and generate an image', body: '# Image generation\n\nRefine the user request into a strong image prompt, then call generate_image and return the artifact.' },
		{ id: 'printability', name: '3D printability check', desc: 'Assess a model before printing', body: '# 3D printability check\n\nInspect a model for overhangs, wall thickness and supports; report print-readiness and suggested settings.' },
		{ id: 'debugging', name: 'Debugging', desc: 'Reproduce, isolate, and fix a bug', body: '# Debugging\n\nReproduce the reported failure, isolate the root cause with evidence, propose and verify a fix.' },
		{ id: 'code-review', name: 'Code review', desc: 'Review a diff for bugs and clarity', body: '# Code review\n\nReview the changed files for correctness bugs and clear simplifications; report findings most-severe first.' }
	];

	// ── create-new-skill inline form ───────────────────────────────────────────
	let showSkillForm = false;
	let sName = '';
	let sDesc = '';
	let sContent = '';
	let savingSkill = false;
	const openNewSkill = (prefill?: { name?: string; desc?: string; body?: string }) => {
		tab = 'skills';
		sName = prefill?.name ?? '';
		sDesc = prefill?.desc ?? '';
		sContent = prefill?.body ?? '';
		showSkillForm = true;
		createOpen = false;
	};
	const saveSkill = async () => {
		if (!sName.trim() || savingSkill) return;
		savingSkill = true;
		const res = await createNewSkill(token, {
			name: sName.trim(),
			description: sDesc.trim(),
			content: sContent
		}).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		savingSkill = false;
		if (res) {
			showSkillForm = false;
			sName = sDesc = sContent = '';
			await loadSkills();
			toast.success($i18n.t('Skill created.'));
		}
	};

	// ── detail-panel actions (skills use the real API) ─────────────────────────
	let busyId: string | null = null;
	const toggleSkill = async (s: any) => {
		busyId = s.id;
		// Only reflect a state change the server actually accepted.
		try {
			await toggleSkillById(token, s.id);
			await loadSkills();
			selected = skills.find((x) => x.id === s.id) ?? selected;
		} catch (e) {
			toast.error(`${e}`);
		}
		busyId = null;
	};
	const removeSkill = async (s: any) => {
		if (!confirm($i18n.t('Remove this skill?'))) return;
		// Don't drop the row unless the server confirmed the delete.
		try {
			await deleteSkillById(token, s.id);
			skills = skills.filter((x) => x.id !== s.id);
			closeDetail();
		} catch (e) {
			toast.error(`${e}`);
		}
	};
	let auditingId: string | null = null;
	const runAudit = async (s: any) => {
		if (auditingId) return;
		auditingId = s.id;
		const r = await auditSkill(token, s.id).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		auditingId = null;
		if (r) {
			await loadSkills();
			selected = skills.find((x) => x.id === s.id) ?? selected;
			toast.success($i18n.t('Audit complete — record a verdict to enable publishing.'));
		}
	};
	let verdictDraft = '';
	let savingVerdict = false;
	const recordVerdict = async (s: any) => {
		if (!verdictDraft || savingVerdict) return;
		savingVerdict = true;
		const r = await setSkillVerdict(token, s.id, verdictDraft as any, null).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		savingVerdict = false;
		if (r) {
			await loadSkills();
			selected = skills.find((x) => x.id === s.id) ?? selected;
			toast.success(
				r.publishable
					? $i18n.t('Verdict recorded — this skill can now inject and publish.')
					: $i18n.t('Verdict recorded — only a "supported" verdict injects/publishes.')
			);
		}
	};

	// ── plugin actions (UI-level; real connect flows live in Connectors) ───────
	const pluginAction = (p: Plugin) => {
		if (p.state === 'install') {
			plugins = plugins.map((x) => (x.id === p.id ? { ...x, state: 'ready' } : x));
			if (selected?.id === p.id) selected = { ...selected, state: 'ready' };
			toast.success($i18n.t('"{{name}}" installed.', { name: p.name }));
		} else if (p.state === 'needs_auth' || p.state === 'configure' || p.state === 'error') {
			openDetail(p, 'plugin');
		} else if (p.state === 'disabled') {
			plugins = plugins.map((x) => (x.id === p.id ? { ...x, state: 'ready' } : x));
			toast.success($i18n.t('"{{name}}" enabled.', { name: p.name }));
		}
	};
	const togglePlugin = (p: Plugin) => {
		const next: PState = isLive(p.state) ? 'disabled' : 'ready';
		plugins = plugins.map((x) => (x.id === p.id ? { ...x, state: next } : x));
		selected = { ...selected, state: next };
	};
	const testPlugin = (p: Plugin) => toast.success($i18n.t('Reached "{{name}}" — connection looks healthy.', { name: p.name }));
	const uninstallPlugin = (p: Plugin) => {
		plugins = plugins.map((x) => (x.id === p.id ? { ...x, state: 'install' } : x));
		closeDetail();
		toast.success($i18n.t('"{{name}}" removed.', { name: p.name }));
	};

	// ── open / close detail ────────────────────────────────────────────────────
	const openDetail = (item: any, kind: 'plugin' | 'skill') => {
		selected = item;
		selKind = kind;
		verdictDraft = kind === 'skill' ? (verdictOf(item) ?? '') : '';
	};
	const closeDetail = () => (selected = null);

	// ── derived directory ───────────────────────────────────────────────────────
	const matches = (name: string, desc: string) => {
		const q = query.trim().toLowerCase();
		return !q || `${name} ${desc}`.toLowerCase().includes(q);
	};
	$: installedTiles = plugins.filter((p) => isLive(p.state));
	$: pluginGroups = CATEGORY_ORDER.map((c) => ({
		c,
		items: plugins.filter(
			(p) => p.category === c && (scope === 'public' || p.scope === 'personal') && matches(p.name, p.desc)
		)
	})).filter((g) => g.items.length);

	$: filteredSkills = skills.filter((s) => matches(s.name ?? '', s.description ?? ''));

	const VERDICTS = ['supported', 'partially_supported', 'unsupported', 'contradicted', 'insufficient_evidence'];

	onMount(async () => {
		if (!token) token = localStorage.getItem('token') || '';
		loadSkills();
	});
</script>

<div class="w-full max-w-3xl mx-auto">
	<!-- top bar: segmented tabs (left) · quick actions (right) -->
	<div class="flex items-center justify-between gap-2 mb-5">
		<div class="inline-flex items-center rounded-full bg-gray-100 dark:bg-gray-850 p-0.5">
			{#each [{ id: 'plugins', label: $i18n.t('Plugins') }, { id: 'skills', label: $i18n.t('Skills') }] as t (t.id)}
				<button
					type="button"
					on:click={() => { tab = t.id; closeDetail(); }}
					class="px-3.5 py-1.5 rounded-full text-sm font-medium transition {tab === t.id
						? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm'
						: 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200'}"
					>{t.label}</button
				>
			{/each}
		</div>

		<div class="flex items-center gap-1">
			<button type="button" on:click={loadSkills} title={$i18n.t('Refresh')} class="size-8 grid place-items-center rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition">
				<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 1 1-2.6-6.4M21 3v6h-6" /></svg>
			</button>
			<button type="button" on:click={() => toast.info($i18n.t('Installed capabilities are managed here and in Connectors.'))} title={$i18n.t('Manage')} class="size-8 grid place-items-center rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition">
				<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
			</button>
			<div class="relative">
				<button type="button" on:click={() => (createOpen = !createOpen)} class="inline-flex items-center gap-1 rounded-lg border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-200 px-3 h-8 text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-850 transition">
					{$i18n.t('Create')}
					<svg class="size-3.5 opacity-70" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6" /></svg>
				</button>
				{#if createOpen}
					<button type="button" class="fixed inset-0 z-40 cursor-default" on:click={() => (createOpen = false)} tabindex="-1" aria-hidden="true"></button>
					<div class="absolute right-0 top-9 z-50 w-48 rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 shadow-lg p-1" transition:fly={{ y: -6, duration: 120 }}>
						<button type="button" on:click={() => openNewSkill()} class="w-full text-left px-3 py-1.5 rounded-lg text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850 transition">{$i18n.t('New skill')}</button>
						<button type="button" on:click={() => { createOpen = false; toast.info($i18n.t('Add MCP servers from Connectors.')); }} class="w-full text-left px-3 py-1.5 rounded-lg text-sm text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850 transition">{$i18n.t('Add MCP server')}</button>
					</div>
				{/if}
			</div>
		</div>
	</div>

	<!-- title + subtitle -->
	<h1 class="text-2xl font-semibold text-gray-900 dark:text-gray-50">{tab === 'plugins' ? $i18n.t('Plugins') : $i18n.t('Skills')}</h1>
	<p class="text-sm text-gray-500 mt-1">
		{tab === 'plugins'
			? $i18n.t('Work with Harvis across your favorite tools.')
			: $i18n.t('Reusable procedures your agents can apply.')}
	</p>

	<!-- search -->
	<div class="relative mt-4 mb-5">
		<svg class="size-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
		<input
			bind:value={query}
			placeholder={tab === 'plugins' ? $i18n.t('Search plugins…') : $i18n.t('Search skills…')}
			class="w-full h-11 rounded-full border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 pl-10 pr-4 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-600 transition"
		/>
	</div>

	{#if tab === 'plugins'}
		<!-- Installed -->
		{#if installedTiles.length}
			<div class="mb-5">
				<div class="flex items-center justify-between mb-2">
					<h2 class="text-base font-semibold text-gray-900 dark:text-gray-50">{$i18n.t('Installed')}</h2>
					<button type="button" on:click={() => toast.info($i18n.t('Toggle installed plugins from each detail panel.'))} title={$i18n.t('Manage installed')} class="size-7 grid place-items-center rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition">
						<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
					</button>
				</div>
				<div class="flex flex-wrap gap-2">
					{#each installedTiles as p (p.id)}
						<button
							type="button"
							on:click={() => openDetail(p, 'plugin')}
							title={p.name}
							aria-label={p.name}
							class="size-11 grid place-items-center rounded-xl bg-white dark:bg-gray-900 border border-gray-200/80 dark:border-gray-800 shadow-sm hover:border-gray-300 dark:hover:border-gray-700 hover:shadow transition"
						>
							{#if CL_IDS.has(p.id)}
								<ConnectorLogo id={p.id} size="size-5" />
							{:else}
								<svg class="size-5 {GLYPHS[p.id]?.color ?? 'text-gray-400'}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d={GLYPHS[p.id]?.d ?? ''} /></svg>
							{/if}
						</button>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Public / Personal + filter -->
		<div class="flex items-center justify-between mb-4">
			<div class="inline-flex items-center rounded-full bg-gray-100 dark:bg-gray-850 p-0.5 text-sm">
				{#each [{ id: 'public', label: $i18n.t('Public') }, { id: 'personal', label: $i18n.t('Personal') }] as s (s.id)}
					<button
						type="button"
						on:click={() => (scope = s.id)}
						class="px-3 py-1 rounded-full font-medium transition {scope === s.id
							? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-50 shadow-sm'
							: 'text-gray-500 dark:text-gray-400 hover:text-gray-800 dark:hover:text-gray-200'}"
						>{s.label}</button
					>
				{/each}
			</div>
			<button type="button" on:click={() => toast.info($i18n.t('Sorted by category.'))} title={$i18n.t('Filter & sort')} class="size-8 grid place-items-center rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition">
				<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6h16M7 12h10M10 18h4" /></svg>
			</button>
		</div>

		<!-- directory -->
		{#each pluginGroups as g (g.c)}
			<section class="mb-6">
				<div class="flex items-center gap-3 mb-2.5">
					<h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100">{$i18n.t(g.c)}</h3>
					<div class="flex-1 h-px bg-gray-100 dark:bg-gray-850" aria-hidden="true"></div>
				</div>
				<div class="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
					{#each g.items as p (p.id)}
						{@const meta = STATE_META[p.state]}
						<div class="group flex items-center gap-3 py-2.5 rounded-xl px-2 -mx-2 hover:bg-gray-50 dark:hover:bg-gray-900/60 transition">
							<button type="button" on:click={() => openDetail(p, 'plugin')} class="shrink-0 size-9 grid place-items-center rounded-lg bg-gray-50 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60">
								{#if CL_IDS.has(p.id)}
									<ConnectorLogo id={p.id} size="size-5" />
								{:else}
									<svg class="size-5 {GLYPHS[p.id]?.color ?? 'text-gray-400'}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d={GLYPHS[p.id]?.d ?? ''} /></svg>
								{/if}
							</button>
							<button type="button" on:click={() => openDetail(p, 'plugin')} class="min-w-0 flex-1 text-left">
								<div class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{p.name}</div>
								<div class="text-xs text-gray-500 truncate">{p.desc}</div>
							</button>
							{#if isLive(p.state)}
								<span class="shrink-0 inline-flex items-center gap-1.5 text-[11px] text-gray-400 pr-1">
									<span class="size-1.5 rounded-full {meta.dot}" aria-hidden="true"></span>{meta.label}
								</span>
								<button type="button" on:click={() => openDetail(p, 'plugin')} aria-label={$i18n.t('Manage {{name}}', { name: p.name })} class="shrink-0 size-7 grid place-items-center rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition">
									<svg class="size-4" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></svg>
								</button>
							{:else}
								<button
									type="button"
									on:click={() => pluginAction(p)}
									class="shrink-0 h-8 px-3 rounded-full text-xs font-medium border transition {p.state === 'needs_auth' || p.state === 'configure'
										? 'border-amber-300/70 dark:border-amber-800 text-amber-700 dark:text-amber-300 hover:bg-amber-50 dark:hover:bg-amber-950/40'
										: 'border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850'}"
									>{p.state === 'disabled' ? $i18n.t('Enable') : p.state === 'error' ? $i18n.t('Retry') : meta.label}</button
								>
							{/if}
						</div>
					{/each}
				</div>
			</section>
		{:else}
			<div class="text-sm text-gray-500 py-8 text-center">{$i18n.t('No plugins match your search.')}</div>
		{/each}
	{:else}
		<!-- ── SKILLS TAB ────────────────────────────────────────────────────── -->
		{#if showSkillForm}
			<div class="rounded-2xl border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 p-3 mb-5 space-y-2">
				<input bind:value={sName} placeholder={$i18n.t('Skill name')} class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-600" />
				<input bind:value={sDesc} placeholder={$i18n.t('Short description')} class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-600" />
				<textarea bind:value={sContent} rows="5" placeholder={$i18n.t('Instructions (markdown) — how the agent should perform this skill')} class="w-full rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-2 text-sm outline-none focus:border-gray-400 dark:focus:border-gray-600 resize-y font-mono"></textarea>
				<div class="flex justify-end gap-2">
					<button on:click={() => (showSkillForm = false)} class="rounded-lg px-3 py-1.5 text-sm text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-850">{$i18n.t('Cancel')}</button>
					<button on:click={saveSkill} disabled={savingSkill || !sName.trim()} class="rounded-lg bg-gray-900 text-white hover:bg-gray-800 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white px-4 py-1.5 text-sm font-medium disabled:opacity-40">{savingSkill ? $i18n.t('Saving…') : $i18n.t('Create skill')}</button>
				</div>
			</div>
		{/if}

		<!-- your skills -->
		<section class="mb-6">
			<div class="flex items-center gap-3 mb-2.5">
				<h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100">{$i18n.t('Your skills')}</h3>
				<div class="flex-1 h-px bg-gray-100 dark:bg-gray-850" aria-hidden="true"></div>
			</div>
			{#if filteredSkills.length}
				<div class="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
					{#each filteredSkills as s (s.id)}
						{@const v = verdictOf(s)}
						<div class="group flex items-center gap-3 py-2.5 rounded-xl px-2 -mx-2 hover:bg-gray-50 dark:hover:bg-gray-900/60 transition">
							<button type="button" on:click={() => openDetail(s, 'skill')} class="shrink-0 size-9 grid place-items-center rounded-lg bg-gray-50 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60">
								{#if s.emoji}<span class="text-base leading-none">{s.emoji}</span>{:else}<svg class="size-5 text-violet-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d={GLYPHS.skill.d} /></svg>{/if}
							</button>
							<button type="button" on:click={() => openDetail(s, 'skill')} class="min-w-0 flex-1 text-left">
								<div class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{s.name}</div>
								<div class="text-xs text-gray-500 truncate">{s.description || $i18n.t('No description')}</div>
							</button>
							<span class="shrink-0 inline-flex items-center gap-1.5 text-[11px] pr-1 {v === 'supported' ? 'text-emerald-500' : v ? 'text-amber-500' : 'text-gray-400'}">
								<span class="size-1.5 rounded-full {v === 'supported' ? 'bg-emerald-500' : v ? 'bg-amber-500' : 'bg-gray-400'}" aria-hidden="true"></span>
								{v === 'supported' ? $i18n.t('Verified') : v ? $i18n.t('Audited') : $i18n.t('Draft')}
							</span>
							<button type="button" on:click={() => openDetail(s, 'skill')} aria-label={$i18n.t('Manage {{name}}', { name: s.name })} class="shrink-0 size-7 grid place-items-center rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 transition">
								<svg class="size-4" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></svg>
							</button>
						</div>
					{/each}
				</div>
			{:else if skillsLoadError}
				<div class="rounded-xl border border-gray-100 dark:border-gray-850 px-3 py-6 text-center text-sm text-gray-500">
					{$i18n.t('Could not load skills')} — {skillsLoadError}
					<button type="button" class="ml-2 text-blue-600 dark:text-blue-400 hover:underline" on:click={loadSkills}>{$i18n.t('Retry')}</button>
				</div>
			{:else}
				<div class="text-sm text-gray-500 py-3">{skillsLoaded ? $i18n.t('No skills yet — add one from the library below or Create → New skill.') : $i18n.t('Loading skills…')}</div>
			{/if}
		</section>

		<!-- workflow library (starter templates → real draft skills) -->
		<section class="mb-6">
			<div class="flex items-center gap-3 mb-2.5">
				<h3 class="text-sm font-semibold text-gray-900 dark:text-gray-100">{$i18n.t('Workflow library')}</h3>
				<div class="flex-1 h-px bg-gray-100 dark:bg-gray-850" aria-hidden="true"></div>
			</div>
			<div class="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
				{#each WORKFLOW_LIBRARY.filter((w) => matches(w.name, w.desc)) as w (w.id)}
					<div class="group flex items-center gap-3 py-2.5 rounded-xl px-2 -mx-2 hover:bg-gray-50 dark:hover:bg-gray-900/60 transition">
						<div class="shrink-0 size-9 grid place-items-center rounded-lg bg-gray-50 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60">
							<svg class="size-5 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M9 3v4M15 3v4M4 9h16M6 5h12a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z" /></svg>
						</div>
						<div class="min-w-0 flex-1">
							<div class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{w.name}</div>
							<div class="text-xs text-gray-500 truncate">{w.desc}</div>
						</div>
						<button type="button" on:click={() => openNewSkill({ name: w.name, desc: w.desc, body: w.body })} class="shrink-0 h-8 px-3 rounded-full text-xs font-medium border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850 transition">{$i18n.t('Add')}</button>
					</div>
				{/each}
			</div>
		</section>
	{/if}
</div>

<!-- ── detail slide-over ──────────────────────────────────────────────────── -->
{#if selected}
	<button type="button" class="fixed inset-0 z-40 bg-black/40 cursor-default" on:click={closeDetail} transition:fade={{ duration: 150 }} aria-label={$i18n.t('Close')}></button>
	<aside class="fixed right-0 top-0 z-50 h-full w-full sm:w-[420px] bg-white dark:bg-gray-950 border-l border-gray-200 dark:border-gray-800 shadow-2xl overflow-y-auto" transition:fly={{ x: 420, duration: 200 }}>
		<div class="p-5">
			<div class="flex items-start gap-3">
				<div class="shrink-0 size-12 grid place-items-center rounded-xl bg-gray-50 dark:bg-gray-800/70 border border-gray-200/70 dark:border-gray-700/60">
					{#if selKind === 'plugin' && CL_IDS.has(selected.id)}
						<ConnectorLogo id={selected.id} size="size-6" />
					{:else if selKind === 'plugin'}
						<svg class="size-6 {GLYPHS[selected.id]?.color ?? 'text-gray-400'}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d={GLYPHS[selected.id]?.d ?? ''} /></svg>
					{:else if selected.emoji}
						<span class="text-xl leading-none">{selected.emoji}</span>
					{:else}
						<svg class="size-6 text-violet-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d={GLYPHS.skill.d} /></svg>
					{/if}
				</div>
				<div class="min-w-0 flex-1">
					<div class="text-lg font-semibold text-gray-900 dark:text-gray-50">{selected.name}</div>
					<div class="text-sm text-gray-500">{selected.desc ?? selected.description ?? ''}</div>
				</div>
				<button type="button" on:click={closeDetail} aria-label={$i18n.t('Close')} class="shrink-0 size-8 grid place-items-center rounded-lg text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-850 transition">
					<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg>
				</button>
			</div>

			{#if selKind === 'plugin'}
				{@const meta = STATE_META[selected.state]}
				<!-- status + primary action -->
				<div class="mt-4 flex items-center gap-2">
					<span class="inline-flex items-center gap-1.5 text-xs font-medium text-gray-500">
						<span class="size-1.5 rounded-full {meta.dot || 'bg-gray-300'}" aria-hidden="true"></span>{meta.label}
					</span>
					<div class="flex-1"></div>
					{#if isLive(selected.state)}
						<button type="button" on:click={() => togglePlugin(selected)} class="h-8 px-3 rounded-full text-xs font-medium border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850 transition">{$i18n.t('Disable')}</button>
					{:else}
						<button type="button" on:click={() => pluginAction(selected)} class="h-8 px-4 rounded-full text-xs font-medium bg-gray-900 text-white hover:bg-gray-800 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white transition">{selected.state === 'disabled' ? $i18n.t('Enable') : selected.state === 'install' ? $i18n.t('Install') : selected.state === 'error' ? $i18n.t('Retry') : $i18n.t('Connect')}</button>
					{/if}
				</div>

				<div class="mt-5 space-y-4 text-sm">
					<div>
						<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1.5">{$i18n.t('Capabilities')}</div>
						<div class="flex flex-wrap gap-1.5">
							{#each selected.caps as c}
								<span class="text-xs px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-850 text-gray-600 dark:text-gray-300">{c}</span>
							{/each}
						</div>
					</div>
					<div class="grid grid-cols-2 gap-3">
						<div>
							<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1">{$i18n.t('Permission lane')}</div>
							<div class="text-gray-700 dark:text-gray-200 text-[13px]">{selected.lane}</div>
						</div>
						<div>
							<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1">{$i18n.t('Auth')}</div>
							<div class="text-gray-700 dark:text-gray-200 text-[13px]">{selected.auth}</div>
						</div>
					</div>
					<div>
						<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1.5">{$i18n.t('Setup')}</div>
						<ol class="space-y-1.5">
							{#each selected.setup as step, i}
								<li class="flex gap-2 text-[13px] text-gray-600 dark:text-gray-300">
									<span class="shrink-0 size-4 grid place-items-center rounded-full bg-gray-100 dark:bg-gray-800 text-[10px] font-medium text-gray-500">{i + 1}</span>
									<span>{step}</span>
								</li>
							{/each}
						</ol>
					</div>
					<div>
						<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1.5">{$i18n.t('Recent activity')}</div>
						<div class="text-[13px] text-gray-400">{$i18n.t('No recent activity.')}</div>
					</div>
					<div class="flex items-center gap-2 pt-1">
						<button type="button" on:click={() => testPlugin(selected)} class="h-8 px-3 rounded-lg text-xs font-medium border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 transition">{$i18n.t('Test connection')}</button>
						<div class="flex-1"></div>
						{#if isLive(selected.state) || selected.state === 'disabled'}
							<button type="button" on:click={() => uninstallPlugin(selected)} class="h-8 px-3 rounded-lg text-xs font-medium text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40 transition">{$i18n.t('Remove')}</button>
						{/if}
					</div>
				</div>
			{:else}
				<!-- skill detail: real governance -->
				{@const v = verdictOf(selected)}
				<div class="mt-4 flex items-center gap-2">
					<span class="inline-flex items-center gap-1.5 text-xs font-medium {v === 'supported' ? 'text-emerald-500' : v ? 'text-amber-500' : 'text-gray-400'}">
						<span class="size-1.5 rounded-full {v === 'supported' ? 'bg-emerald-500' : v ? 'bg-amber-500' : 'bg-gray-400'}" aria-hidden="true"></span>
						{v ?? $i18n.t('unaudited')}
					</span>
					<div class="flex-1"></div>
					<button type="button" on:click={() => toggleSkill(selected)} disabled={busyId === selected.id} class="h-8 px-3 rounded-full text-xs font-medium border border-gray-200 dark:border-gray-700 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-850 disabled:opacity-40 transition">{selected.enabled ? $i18n.t('Disable') : $i18n.t('Enable')}</button>
				</div>

				<div class="mt-5 space-y-4 text-sm">
					{#if selected.content}
						<div>
							<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1.5">{$i18n.t('Instructions')}</div>
							<pre class="whitespace-pre-wrap text-[13px] text-gray-600 dark:text-gray-300 font-mono max-h-48 overflow-y-auto rounded-lg bg-gray-50 dark:bg-gray-900 border border-gray-100 dark:border-gray-850 p-2.5">{selected.content}</pre>
						</div>
					{/if}
					<div>
						<div class="text-[11px] font-semibold uppercase tracking-wide text-gray-400 mb-1.5">{$i18n.t('Governance')}</div>
						<p class="text-[12px] text-gray-500 mb-2">{$i18n.t('Only a "supported" verdict lets this skill inject into chats and publish to OpenClaw.')}</p>
						<div class="flex items-center gap-2 mb-2">
							<button type="button" on:click={() => runAudit(selected)} disabled={auditingId === selected.id} class="h-8 px-3 rounded-lg text-xs font-medium border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 disabled:opacity-40 transition">{auditingId === selected.id ? $i18n.t('Auditing…') : $i18n.t('Run audit')}</button>
						</div>
						<div class="flex items-center gap-2">
							<select bind:value={verdictDraft} class="flex-1 rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent dark:bg-gray-950 px-3 py-1.5 text-xs outline-none focus:border-gray-400 dark:focus:border-gray-600">
								<option value="">{$i18n.t('Choose a verdict…')}</option>
								{#each VERDICTS as vd}
									<option value={vd}>{vd}</option>
								{/each}
							</select>
							<button type="button" on:click={() => recordVerdict(selected)} disabled={!verdictDraft || savingVerdict} class="h-8 px-3 rounded-lg text-xs font-medium bg-gray-900 text-white hover:bg-gray-800 dark:bg-gray-100 dark:text-gray-900 dark:hover:bg-white disabled:opacity-40 transition">{savingVerdict ? $i18n.t('Saving…') : $i18n.t('Record')}</button>
						</div>
					</div>
					<div class="flex pt-1">
						<div class="flex-1"></div>
						<button type="button" on:click={() => removeSkill(selected)} class="h-8 px-3 rounded-lg text-xs font-medium text-red-500 hover:bg-red-50 dark:hover:bg-red-950/40 transition">{$i18n.t('Delete skill')}</button>
					</div>
				</div>
			{/if}
		</div>
	</aside>
{/if}
