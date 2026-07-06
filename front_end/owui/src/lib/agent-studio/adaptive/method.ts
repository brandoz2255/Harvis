// Adaptive Space METHOD MAP — what each workspace type needs (criteria with
// safe defaults), which tools it uses (with HONEST availability), and which
// output slots it renders. Pure frontend data over mocked/gated capabilities:
// nothing here enables live services, devices, publishing, or credentials.

export type Criterion = {
	key: string;
	label: string;
	why: string; // shown in the question popup — why this matters
	suggested: string[]; // chip answers
	fallback: string; // safe default
	userMust?: boolean; // only the user can provide (file, host, media…)
};

export type Tool = {
	label: string;
	status: 'ready' | 'mock' | 'setup' | 'gated';
	desc: string;
	href?: string; // ready tools may deep-link (e.g. Build handoff)
};

export type OutputSlot = { title: string; body: string; tone?: 'cyan' | 'amber' };

export type Method = {
	label: string;
	icon: string; // svg path (24×24 stroke)
	mock?: boolean;
	criteria: Criterion[];
	tools: Tool[];
	outputs: OutputSlot[];
};

export const METHODS: Record<string, Method> = {
	'feature-plan': {
		label: 'Feature Builder',
		icon: 'M12 2 3 7v10l9 5 9-5V7l-9-5zM3 7l9 5 9-5M12 12v10',
		criteria: [
			{ key: 'repo', label: 'Target repo/context', why: 'Scopes which codebase the feature lands in.', suggested: ['Harvis (this app)', 'Another repo'], fallback: 'Harvis (this app)' },
			{ key: 'scope', label: 'Scope', why: 'Keeps the plan sized to what you actually want.', suggested: ['Small tweak', 'Full feature', 'Refactor'], fallback: 'Full feature' }
		],
		tools: [
			{ label: 'Repo context', status: 'ready', desc: 'Recon via Build (Code mode).', href: '/harvis/vibecode' },
			{ label: 'Design notes', status: 'ready', desc: 'Capture the plan in this space.' },
			{ label: 'Build handoff', status: 'ready', desc: 'Run the implementation in Build on an isolated clone.', href: '/harvis/vibecode' },
			{ label: 'Diff review', status: 'gated', desc: 'Create-PR stays your outer gate.' }
		],
		outputs: [
			{ title: 'Plan summary', body: 'The implementation plan drafts here from your notes.' },
			{ title: 'Review', body: 'Diff review before merge — the human gate.', tone: 'amber' }
		]
	},
	'integration-scaffold': {
		label: 'Integration Builder',
		icon: 'M9 2v6m6-6v6M5 8h14a2 2 0 0 1 2 2v2a7 7 0 0 1-7 7h-4a7 7 0 0 1-7-7v-2a2 2 0 0 1 2-2zM12 19v3',
		criteria: [
			{ key: 'target', label: 'Target device/service', why: 'Determines which adapter gets scaffolded.', suggested: ['OctoPrint', 'Klipper/Moonraker', 'Prusa Connect', 'Other'], fallback: 'Decide during scaffold' },
			{ key: 'bridge', label: 'Local bridge available?', why: 'Hardware needs the CLI lane — Web Harvis never touches devices.', suggested: ['Yes, CLI on host', 'Not yet'], fallback: 'Check during setup' }
		],
		tools: [
			{ label: 'Scaffold via Build', status: 'ready', desc: 'Generate candidate code on an isolated clone.', href: '/harvis/vibecode' },
			{ label: 'Connector', status: 'setup', desc: 'Real connector requires local setup — surfaced as manual steps.' },
			{ label: 'Mock test', status: 'mock', desc: 'Exercise the candidate against a mock endpoint.' },
			{ label: 'Merge gate', status: 'gated', desc: 'Review-before-merge; never self-installed.' }
		],
		outputs: [
			{ title: 'Candidate integration', body: 'Scaffolded adapter/UI code appears here for review.' },
			{ title: 'Review gate', body: 'Diff review before merge — the human gate for anything generated.', tone: 'amber' }
		]
	},
	fabrication: {
		label: 'Physical Prototype Test',
		icon: 'M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4L15 12l-3-3 2.7-2.7z',
		mock: true,
		criteria: [
			{ key: 'dimensions', label: 'Approx. dimensions', why: 'Bounds the concept geometry and build volume.', suggested: ['Small (~10 cm)', 'Medium (~20 cm)', 'Large (~30 cm+)'], fallback: 'Medium (~20 cm)' },
			{ key: 'load', label: 'Expected load/weight', why: 'Drives wall thickness and support assumptions.', suggested: ['< 1 kg', '1–3 kg', '3 kg+'], fallback: '1–3 kg' },
			{ key: 'material', label: 'Material', why: 'Prototype checks assume a material class.', suggested: ['PLA', 'PETG', 'ABS'], fallback: 'PLA (prototype)' },
			{ key: 'mounting', label: 'Mounting', why: 'Wall vs desk changes the whole load path.', suggested: ['Desk/freestanding', 'Wall-mounted'], fallback: 'Desk/freestanding' }
		],
		tools: [
			{ label: 'Reference lookup', status: 'mock', desc: 'Design references — placeholder until research tools attach.' },
			{ label: 'Concept preview', status: 'mock', desc: 'CAD concept mock; real geometry arrives with the CAD adapter.' },
			{ label: 'Validation', status: 'mock', desc: 'Simulation hook pending — assumptions only, not certified engineering.' },
			{ label: 'Export', status: 'gated', desc: 'STL/3MF export is approval-gated; nothing is fabricated from here.' }
		],
		outputs: [
			{ title: 'Concept preview', body: 'CAD concept mock — real geometry arrives with the CAD adapter.' },
			{ title: 'Validation', body: 'Simulation hook pending — assisted prototype, not certified engineering.', tone: 'amber' }
		]
	},
	'image-to-3d': {
		label: 'Image → Object',
		icon: 'M12 2 3 7v10l9 5 9-5V7l-9-5zM12 22V12M3 7l9 5 9-5',
		mock: true,
		criteria: [
			{ key: 'image', label: 'Source image', why: 'Generation starts from your image.', suggested: [], fallback: '', userMust: true },
			{ key: 'size', label: 'Target size', why: 'Sets scale for printability checks.', suggested: ['Desk-size (~15 cm)', 'Miniature (~5 cm)'], fallback: 'Desk-size (~15 cm)' }
		],
		tools: [
			{ label: 'Image intake', status: 'ready', desc: 'Attach the source image as a resource.' },
			{ label: 'Generation', status: 'mock', desc: 'Image-to-3D runs on the dev rig when the adapter lands.' },
			{ label: 'Repair & checks', status: 'mock', desc: 'Watertight/manifold checks — placeholder.' },
			{ label: 'Export', status: 'gated', desc: 'Slicer dry-run + export stay approval-gated.' }
		],
		outputs: [
			{ title: 'Generated object', body: 'Mesh preview appears when the generation adapter is wired.' },
			{ title: 'Printability', body: 'Checks + export remain approval-gated.', tone: 'amber' }
		]
	},
	'social-post': {
		label: 'Action Studio',
		icon: 'M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z',
		mock: true,
		criteria: [
			{ key: 'media', label: 'Media asset', why: 'The post composes around your file.', suggested: [], fallback: '', userMust: true },
			{ key: 'platform', label: 'Platform', why: 'Formats the preview; publishing stays mock.', suggested: ['Instagram', 'YouTube', 'X'], fallback: 'Preview-only' },
			{ key: 'tone', label: 'Tone', why: 'Guides caption drafts.', suggested: ['Casual', 'Hype', 'Technical'], fallback: 'Casual' }
		],
		tools: [
			{ label: 'Asset intake', status: 'ready', desc: 'Reference the media as a resource.' },
			{ label: 'Caption drafts', status: 'ready', desc: 'Draft options in notes/output.' },
			{ label: 'Preview', status: 'mock', desc: 'Composes exactly what WOULD publish.' },
			{ label: 'Publish', status: 'gated', desc: 'Mock adapter only — nothing posts, ever, without approval.' }
		],
		outputs: [
			{ title: 'Post preview', body: 'Asset + caption exactly as it would publish — mock adapter only.' },
			{ title: 'Approval', body: 'Publishing gated on your explicit approval; mock execute logs "no real action taken".', tone: 'amber' }
		]
	},
	'research-notebook': {
		label: 'Research Notebook',
		icon: 'M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 19.5A2.5 2.5 0 0 0 6.5 22H20V2H6.5A2.5 2.5 0 0 0 4 4.5v15z',
		criteria: [
			{ key: 'question', label: 'Research question', why: 'One sentence keeps the space focused.', suggested: [], fallback: 'Derived from your task description' },
			{ key: 'sources', label: 'Sources', why: 'Grounded answers need documents.', suggested: [], fallback: '', userMust: true }
		],
		tools: [
			{ label: 'Notebook', status: 'ready', desc: 'Sources + grounded chat live in Notebooks.', href: '/harvis/notebooks' },
			{ label: 'Findings notes', status: 'ready', desc: 'Capture what you learn here.' },
			{ label: 'Report kinds', status: 'ready', desc: 'Briefing / FAQ / study guide via the Notebook Studio.', href: '/harvis/notebooks' }
		],
		outputs: [{ title: 'Summary', body: 'Findings and exports collect here.' }]
	},
	'ssh-workspace': {
		label: 'Remote Profile (mock)',
		icon: 'M2 3h20v14H2zM8 21h8M12 17v4m-6-9 3-2.5L6 7M13 12h5',
		mock: true,
		criteria: [
			{ key: 'host', label: 'Host profile', why: 'Names the target machine — no connection is made.', suggested: [], fallback: '', userMust: true }
		],
		tools: [
			{ label: 'Profile setup', status: 'setup', desc: 'Placeholder — remote access disabled pending security review.' },
			{ label: 'Connection', status: 'gated', desc: 'No sockets, no SSH libs, no credentials. Disabled.' }
		],
		outputs: [{ title: 'Status preview', body: 'Non-network status placeholder; live connect stays disabled.', tone: 'amber' }]
	},
	'repo-runner': {
		label: 'Repo Runner',
		icon: 'M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM7 10l3 2.5L7 15M13 15h4',
		criteria: [], // the Repo Runner surface handles the URL intake itself
		tools: [
			{ label: 'Fetch repo', status: 'ready', desc: 'Clone a public repo into an isolated per-space checkout.' },
			{ label: 'Read setup', status: 'ready', desc: 'Read the README + manifests and detect the stack.' },
			{ label: 'Install / run', status: 'gated', desc: 'Sandbox execution — approval-gated, off until the toolchain sandbox lands.' },
			{ label: 'App preview', status: 'setup', desc: 'Port-forward preview arrives with the sandbox run wiring.' }
		],
		outputs: [
			{ title: 'Workbench', body: 'File tree, real clone log, and detected setup render in the terminal surface.' },
			{ title: 'Run gate', body: 'Install/build/start stay approval-gated — nothing from the repo runs until you approve it.', tone: 'amber' }
		]
	}
};

export const methodFor = (key: string): Method =>
	METHODS[key] ?? {
		label: key || 'Workspace',
		icon: 'M12 2 3 7v10l9 5 9-5V7l-9-5z',
		criteria: [],
		tools: [{ label: 'Notes', status: 'ready', desc: 'Capture context here.' }],
		outputs: [{ title: 'Output', body: 'Results collect here.' }]
	};
