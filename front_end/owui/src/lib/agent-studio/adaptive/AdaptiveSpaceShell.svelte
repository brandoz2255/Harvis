<script lang="ts">
	// Adaptive Space SHELL — ONE session workspace (the Build/Vibecode pattern),
	// not stacked pages. Left rail = recent spaces · center canvas = Adaptive Core
	// + task-shaped panels · bottom composer = always present.
	//
	// In-place transitions: selecting/creating a space updates ?s=<id> on the SAME
	// route (goto with keepFocus/noScroll → no remount, no page jump). The
	// /harvis/adaptive/[id] route renders this same shell for direct/share URLs.
	// Panels fade in only when real manifest state exists (escalating density).
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { fade, fly } from 'svelte/transition';
	import { showSidebar } from '$lib/stores';
	import AdaptiveCore from './AdaptiveCore.svelte';
	import PrototypeTestPanel from './PrototypeTestPanel.svelte';
	import RepoRunnerSurface from './RepoRunnerSurface.svelte';
	import ResourceBoard from './ResourceBoard.svelte';
	import ToolDock from './ToolDock.svelte';
	import { methodFor } from './method';
	import { surfaceFor } from './surfaces';
	import { describeMediaError, micUnavailableReason } from '$lib/utils/audio';
	import { toast } from 'svelte-sonner';

	const i18n: any = getContext('i18n');

	export let initialSpaceId = ''; // set by the [id] direct-load route

	// ── Studio identity per template (vector icons; no emoji glyphs) ──
	const STUDIO: Record<string, { label: string; icon: string; mock?: boolean }> = {
		'feature-plan': { label: 'Feature Builder', icon: 'M12 2 3 7v10l9 5 9-5V7l-9-5zM3 7l9 5 9-5M12 12v10' },
		'integration-scaffold': { label: 'Integration Builder', icon: 'M9 2v6m6-6v6M5 8h14a2 2 0 0 1 2 2v2a7 7 0 0 1-7 7h-4a7 7 0 0 1-7-7v-2a2 2 0 0 1 2-2zM12 19v3' },
		'research-notebook': { label: 'Research Notebook', icon: 'M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 19.5A2.5 2.5 0 0 0 6.5 22H20V2H6.5A2.5 2.5 0 0 0 4 4.5v15z' },
		'ssh-workspace': { label: 'Remote Profile (mock)', icon: 'M2 3h20v14H2zM8 21h8M12 17v4m-6-9 3-2.5L6 7M13 12h5' },
		'social-post': { label: 'Action Studio', icon: 'M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z', mock: true },
		fabrication: { label: 'Physical Prototype Test', icon: 'M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18v3h3l6.3-6.3a4 4 0 0 0 5.4-5.4L15 12l-3-3 2.7-2.7z', mock: true },
		'image-to-3d': { label: 'Image → 3D Pipeline', icon: 'M12 2 3 7v10l9 5 9-5V7l-9-5zM12 22V12M3 7l9 5 9-5', mock: true },
		'repo-runner': { label: 'Repo Runner', icon: 'M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1zM7 10l3 2.5L7 15M13 15h4' }
	};

	type FlowStep = { title: string; gate: boolean };
	type Template = { key: string; name: string; description: string; steps: number; gates?: number; panels?: string[]; flow?: FlowStep[] };
	type SpaceRow = { id: string; title: string; intent: string; template_key: string; status: string; updated_at?: string };

	const relTime = (ts?: string) => {
		if (!ts) return '';
		try {
			const s = (Date.now() - new Date(ts).getTime()) / 1000;
			if (s < 90) return 'now';
			if (s < 3600) return `${Math.round(s / 60)}m`;
			if (s < 86400) return `${Math.round(s / 3600)}h`;
			return `${Math.round(s / 86400)}d`;
		} catch {
			return '';
		}
	};

	const hdrs = () => ({ Authorization: `Bearer ${localStorage.token}`, 'Content-Type': 'application/json' });

	// ── Shell state ──
	let templates: Template[] = [];
	let spaces: SpaceRow[] = [];
	let listLoading = true;

	// Active space (null → empty/standby canvas)
	$: spaceId = $page.url.searchParams.get('s') || initialSpaceId || '';
	let loadedId = '';
	let space: any = null;
	let spaceLoading = false;
	let err = '';

	// Composer — chat-first: the workspace SHAPE is inferred automatically on
	// submit ("Detected: X" chip). A focused question popup appears only when
	// inference is ambiguous; there is no selector-first flow.
	let intent = '';
	let creating = false;
	let shapingLabel = ''; // detected template label shown during the shaping transition
	let askShape: { text: string } | null = null; // ambiguous → one-question popup

	// Composer attachments — an image rides into the new space as a REFERENCE
	// resource; the mic records → Harvis Whisper STT → transcript into the intent.
	let pendingImage: File | null = null;
	let pendingImageUrl = '';
	let composerFileInput: HTMLInputElement;
	let recording = false;
	let transcribing = false;
	let mediaRecorder: MediaRecorder | null = null;
	let audioChunks: Blob[] = [];

	// Approval gate + request-in-flight
	let gateStep: any = null;
	let busy = false;
	let statusOpen = false; // anchored-orb status popover (hybrid layout)
	let railOpen = false; // support rail (resource board + tool dock) is secondary — collapsed by default

	onMount(async () => {
		try {
			const [tRes, sRes] = await Promise.all([
				fetch('/api/adaptive/templates', { headers: hdrs(), credentials: 'include' }),
				fetch('/api/adaptive/spaces', { headers: hdrs(), credentials: 'include' })
			]);
			if (tRes.ok) templates = (await tRes.json()).templates ?? [];
			if (sRes.ok) spaces = (await sRes.json()).spaces ?? [];
		} catch (e) {
			console.error('adaptive shell', e);
		}
		listLoading = false;
	});

	const refreshList = async () => {
		try {
			const r = await fetch('/api/adaptive/spaces', { headers: hdrs(), credentials: 'include' });
			if (r.ok) spaces = (await r.json()).spaces ?? [];
		} catch {
			/* ignore */
		}
	};

	// ── Space load (in place; reacts to ?s= changes) ──
	const loadSpace = async (id: string) => {
		spaceLoading = true;
		err = '';
		try {
			const r = await fetch(`/api/adaptive/spaces/${id}`, { headers: hdrs(), credentials: 'include' });
			if (!r.ok) throw new Error((await r.json())?.detail || 'Load failed');
			space = await r.json();
			shapingLabel = ''; // workspace has arrived — end the shaping transition
		} catch (e: any) {
			err = e?.message || 'Load failed';
			space = null;
		}
		spaceLoading = false;
	};
	$: if (spaceId && spaceId !== loadedId) {
		loadedId = spaceId;
		loadSpace(spaceId);
	} else if (!spaceId && loadedId) {
		loadedId = '';
		space = null;
	}

	// Quiet URL updates — same route, no remount, no page jump.
	const openSpace = (id: string) =>
		goto(`/harvis/adaptive?s=${id}`, { noScroll: true, keepFocus: true });
	const goStandby = () => {
		intent = '';
		shapingLabel = '';
		goto('/harvis/adaptive', { noScroll: true, keepFocus: true });
	};

	// ── Automatic workspace inference: suggest ranks; the TOP score is applied
	// automatically. Only an ambiguous result (all zero) asks — one focused
	// question, chip answers, never a wizard.
	const inferShape = async (text: string): Promise<string | null> => {
		try {
			const r = await fetch('/api/adaptive/suggest', {
				method: 'POST', headers: hdrs(), credentials: 'include', body: JSON.stringify({ intent: text })
			});
			if (!r.ok) return null;
			const ranked = ((await r.json()).suggestions ?? []) as { key: string; score: number }[];
			if (ranked.length && ranked[0].score > 0) return ranked[0].key;
			return null; // ambiguous
		} catch {
			return null;
		}
	};

	// ── Composer attachments ──
	const onComposerFile = (e: Event) => {
		const f = (e.target as HTMLInputElement).files?.[0];
		if (!f) return;
		if (pendingImageUrl) URL.revokeObjectURL(pendingImageUrl);
		pendingImage = f;
		pendingImageUrl = URL.createObjectURL(f);
		(e.target as HTMLInputElement).value = '';
	};
	const clearPendingImage = () => {
		if (pendingImageUrl) URL.revokeObjectURL(pendingImageUrl);
		pendingImage = null;
		pendingImageUrl = '';
	};
	const toggleMic = async () => {
		if (recording) {
			mediaRecorder?.stop();
			return;
		}
		const unavailable = micUnavailableReason();
		if (unavailable) {
			toast.error($i18n.t(unavailable.key, unavailable.values ?? {}));
			return;
		}
		try {
			const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
			audioChunks = [];
			mediaRecorder = new MediaRecorder(stream);
			mediaRecorder.ondataavailable = (ev) => {
				if (ev.data.size) audioChunks.push(ev.data);
			};
			mediaRecorder.onstop = async () => {
				stream.getTracks().forEach((t) => t.stop());
				recording = false;
				const blob = new Blob(audioChunks, { type: 'audio/webm' });
				if (!blob.size) return;
				transcribing = true;
				try {
					const fd = new FormData();
					fd.append('file', blob, 'speech.webm');
					const r = await fetch('/api/v1/audio/transcriptions', {
						method: 'POST', headers: { Authorization: `Bearer ${localStorage.token}` }, credentials: 'include', body: fd
					});
					if (r.ok) {
						const t = ((await r.json()).text || '').trim();
						if (t) intent = intent ? `${intent} ${t}` : t;
					}
				} catch {
					/* transcription unavailable — leave intent as-is */
				}
				transcribing = false;
			};
			mediaRecorder.start();
			recording = true;
		} catch (err) {
			const info = describeMediaError(err);
			toast.error($i18n.t(info.key, info.values ?? {}));
			recording = false;
		}
	};

	// ── Create (composer submit) — infers the shape, transitions the SAME canvas ──
	const create = async () => {
		let text = intent.trim();
		if (creating || (!text && !pendingImage)) return;
		if (!text) text = 'Work with this reference image'; // image-only → sensible default intent
		creating = true;
		err = '';
		const key = await inferShape(text);
		if (!key) {
			// ambiguous → one-question popup (with a safe default escape)
			askShape = { text };
			creating = false;
			return;
		}
		await createWith(key, text);
	};

	const createWith = async (templateKey: string, text: string) => {
		creating = true;
		shapingLabel = STUDIO[templateKey]?.label ?? '';
		err = '';
		try {
			const r = await fetch('/api/adaptive/spaces', {
				method: 'POST', headers: hdrs(), credentials: 'include',
				body: JSON.stringify({ template_key: templateKey, intent: text, title: text.slice(0, 80) })
			});
			if (!r.ok) throw new Error((await r.json())?.detail || 'Create failed');
			const { id } = await r.json();
			// Carry a composer-attached image into the new space as a reference resource.
			if (pendingImage) {
				try {
					const fd = new FormData();
					fd.append('file', pendingImage);
					await fetch(`/api/adaptive/spaces/${id}/resource`, {
						method: 'POST', headers: { Authorization: `Bearer ${localStorage.token}` }, credentials: 'include', body: fd
					});
				} catch {
					/* image is optional — the space is created regardless */
				}
				clearPendingImage();
			}
			intent = '';
			askShape = null;
			await refreshList();
			openSpace(id);
		} catch (e: any) {
			err = e?.message || 'Create failed';
		}
		creating = false;
	};

	// ── Space mutations (same as before; manifest is the source of truth) ──
	const post = async (path: string, body: any) => {
		busy = true;
		try {
			const r = await fetch(`/api/adaptive/spaces/${spaceId}${path}`, {
				method: 'POST', headers: hdrs(), credentials: 'include', body: JSON.stringify(body)
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
	const confirmGate = async () => {
		if (!gateStep) return;
		await post('/step', { step_id: gateStep.id, status: 'done', approved: true });
		gateStep = null;
	};
	const isExecStep = (s: any) => ['execute', 'export'].includes(s?.id);
	const runMock = (s: any) => post('/mock-execute', { stage: s.id });
	const setSpaceStatus = async (status: string) => {
		await post('/status', { status });
		space = { ...space, status };
		refreshList();
	};

	// ── Derived core state (manifest-driven; no timers) ──
	$: manifest = space?.manifest ?? {};
	$: steps = manifest.steps ?? [];
	$: linkedRuns = manifest.linked_runs ?? [];
	$: tools = manifest.tools ?? []; // method layer — backend-routed capability registry
	$: resources = manifest.resources ?? [];
	$: cues = manifest.cues ?? [];
	$: doneSteps = steps.filter((s: any) => s.status === 'done').length;
	$: activeStep = steps.find((s: any) => s.status === 'active') ?? null;
	$: coreProgress = steps.length ? doneSteps / steps.length : 0;
	$: coreState = (() => {
		if (!space) return 'idle';
		if (space?.status === 'done' || (steps.length && doneSteps === steps.length)) return 'done';
		if (steps.some((s: any) => s.status === 'blocked')) return 'error';
		if (activeStep?.gate === 'approval') return 'waiting';
		if (activeStep) return 'executing';
		return 'idle';
	})();
	$: method = space ? methodFor(space.template_key) : null;
	$: surface = space ? surfaceFor(space.template_key) : 'generic_output';
	$: surfaceLabel = surface === 'repo_runner' ? $i18n.t('Repo runner') : $i18n.t('Output & preview');
	$: execStep = steps.find((s: any) => s.status === 'active' && isExecStep(s)) ?? null;

	const rowDot = (s: string) => (s === 'done' ? 'bg-emerald-400' : s === 'abandoned' ? 'bg-gray-500' : 'bg-cyan-400');
	const fmtAt = (ts?: string) => {
		if (!ts) return '';
		try { return new Date(ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); } catch { return ts; }
	};
</script>

<!-- SHELL: rail · canvas · composer — one page, transforms in place.
     The app sidebar is an overlay; pages self-offset (vibecode/chat recipe). -->
<div
	class="w-full h-full flex text-gray-200 {$showSidebar
		? 'md:max-w-[calc(100%-var(--sidebar-width))]'
		: ''}"
	style="background-color:#070b14;background-image:linear-gradient(rgba(56,189,248,0.04) 1px,transparent 1px),linear-gradient(90deg,rgba(56,189,248,0.04) 1px,transparent 1px);background-size:44px 44px;"
>
	<!-- LEFT RAIL: recent spaces -->
	<aside class="w-56 shrink-0 border-r border-white/6 bg-[#0a101d]/70 backdrop-blur flex flex-col min-h-0">
		<button
			class="mx-2 mt-3 mb-1 shrink-0 flex items-center justify-center gap-1.5 text-xs px-2 py-1.5 rounded-xl border border-cyan-400/25 text-cyan-300 hover:bg-cyan-400/10 transition"
			on:click={goStandby}
		>
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-3.5"><path d="M12 5v14M5 12h14" stroke-linecap="round" /></svg>
			{$i18n.t('New adaptive session')}
		</button>
		<div class="flex-1 min-h-0 overflow-y-auto px-2 pb-3">
			{#if listLoading}
				<div class="text-xs text-gray-500 px-2 py-1">{$i18n.t('Loading…')}</div>
			{:else if !spaces.length}
				<div class="text-[11px] text-gray-500 px-2 py-1 leading-snug">{$i18n.t('No sessions yet — describe a task below.')}</div>
			{:else}
				{#each [{ label: 'Active', rows: spaces.filter((x) => x.status === 'active') }, { label: 'Recent', rows: spaces.filter((x) => x.status !== 'active') }] as sec (sec.label)}
					{#if sec.rows.length}
						<div class="px-2 pt-2 pb-1 text-[9px] uppercase tracking-widest text-gray-500">{$i18n.t(sec.label)}</div>
						<div class="space-y-0.5">
							{#each sec.rows as s (s.id)}
								<button
									type="button"
									class="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg text-left transition group {spaceId === s.id
										? 'bg-cyan-400/10 border border-cyan-400/25'
										: 'border border-transparent hover:bg-white/4'}"
									on:click={() => openSpace(s.id)}
								>
									<span class="size-1.5 rounded-full shrink-0 {rowDot(s.status)}"></span>
									<span class="min-w-0 flex-1">
										<span class="block truncate text-xs {spaceId === s.id ? 'text-cyan-100' : 'text-gray-300 group-hover:text-gray-100'}">{s.title || s.intent || $i18n.t('Space')}</span>
										<span class="block truncate text-[9px] uppercase tracking-wide text-gray-500">{STUDIO[s.template_key]?.label ?? s.template_key}</span>
									</span>
									<span class="shrink-0 text-[9px] text-gray-600 tabular-nums">{relTime(s.updated_at)}</span>
								</button>
							{/each}
						</div>
					{/if}
				{/each}
			{/if}
		</div>
		<div class="shrink-0 px-3 py-2 border-t border-white/6 flex flex-wrap gap-1 text-[8.5px] uppercase tracking-wider text-cyan-300/60">
			<span>{$i18n.t('Mock-safe')}</span>·<span>{$i18n.t('Approval-gated')}</span>·<span>{$i18n.t('No live hardware')}</span>
		</div>
	</aside>

	<!-- CENTER: canvas + composer -->
	<div class="flex-1 min-w-0 flex flex-col min-h-0">
		<!-- CANVAS -->
		<div class="flex-1 min-h-0 overflow-y-auto">
			{#if creating || (spaceId && spaceLoading && !space)}
				<!-- SHAPING TRANSITION: the gap between submit and the workspace. The
				     orb keeps its planning/busy readout and crossfades into the result,
				     so arriving at a session feels formed, not like a page swap. -->
				<div class="h-full flex flex-col items-center justify-center px-6 text-center" in:fade={{ duration: 150 }} out:fade={{ duration: 150 }}>
					<AdaptiveCore state="planning" busy={true} progress={0} steps={0} gates={0} size={230} />
					<div class="mt-6 flex items-center justify-center gap-2 text-sm text-cyan-100">
						<span>{creating || shapingLabel ? $i18n.t('Shaping your workspace') : $i18n.t('Opening workspace')}</span>
						<span class="shaping-dots" aria-hidden="true"><i></i><i></i><i></i></span>
					</div>
					{#if shapingLabel}
						<div class="mt-2 inline-flex items-center gap-1.5 text-[9px] uppercase tracking-widest text-cyan-300/80 px-2 py-0.5 rounded-md border border-cyan-400/20 bg-cyan-400/5" in:fade={{ duration: 200 }}>
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-2.5"><path d="M20 6 9 17l-5-5" stroke-linecap="round" stroke-linejoin="round" /></svg>
							{$i18n.t('Detected')}: {shapingLabel}
						</div>
					{/if}
					<p class="mt-2 text-xs text-gray-500 max-w-xs">{$i18n.t('Gathering resources and forming the task environment…')}</p>
				</div>
			{:else if !spaceId}
				<!-- STANDBY: chat-first — the core is the interface. Typing = Listening
				     (an honest readiness state), nothing else competes for attention. -->
				<div class="h-full flex flex-col items-center justify-center px-6 text-center" in:fade={{ duration: 200 }}>
					<AdaptiveCore
						state={intent.trim() ? 'listening' : 'idle'}
						busy={false}
						progress={0}
						steps={0}
						gates={0}
						size={280}
					/>
					<h1 class="mt-6 text-xl font-semibold text-gray-100">{$i18n.t('What should Harvis shape?')}</h1>
					<p class="mt-1 text-sm text-gray-500 max-w-md">
						{$i18n.t('Describe the task — the workspace forms around it automatically.')}
					</p>
					<div class="mt-4 flex flex-wrap justify-center gap-1.5 max-w-lg">
						{#each ['Clone and run a GitHub repo', 'Test this helmet hanger', 'Turn this image into a printable 3D model', 'Build a new Harvis integration'] as ex}
							<button
								type="button"
								class="text-[11px] px-2.5 py-1 rounded-lg border border-white/8 text-gray-400 hover:text-cyan-200 hover:border-cyan-400/30 transition"
								on:click={() => (intent = ex)}>{ex}</button
							>
						{/each}
					</div>
				</div>
			{:else if space}
				<!-- HYBRID WORKSPACE: the orb docks to a compact top-left STATUS ANCHOR
				     (was the centered hero in standby); the result gets the main stage.
				     Cinematic in the chrome (the live orb), legible in the content. -->
				<div class="relative max-w-6xl mx-auto px-5 pt-5 pb-6" in:fade={{ duration: 220 }}>
					<!-- TOP STATUS BAR: anchored orb + detected chip + title -->
					<header class="flex items-start gap-3.5">
						<div class="relative shrink-0">
							<button
								type="button"
								class="block rounded-lg transition hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-400/50"
								aria-label="{$i18n.t('Adaptive core')}: {$i18n.t('status')}"
								aria-expanded={statusOpen}
								on:click={() => (statusOpen = !statusOpen)}
							>
								<AdaptiveCore
									state={coreState}
									progress={coreProgress}
									steps={steps.length}
									gates={steps.filter((s) => s.gate === 'approval').length}
									size={72}
									busy={creating || busy}
								/>
							</button>
							{#if statusOpen}
								<div class="absolute z-30 mt-1 left-0 w-56 rounded-xl border border-cyan-400/25 bg-[#0c111d]/95 backdrop-blur p-3 shadow-xl text-xs" transition:fade={{ duration: 120 }}>
									<div class="flex items-center justify-between">
										<span class="uppercase tracking-widest text-[9px] text-cyan-300/80">{$i18n.t('Adaptive core')}</span>
										<button class="text-gray-500 hover:text-gray-300" on:click={() => (statusOpen = false)} aria-label={$i18n.t('Close')}>✕</button>
									</div>
									<div class="mt-1.5 text-gray-200 capitalize">{coreState}</div>
									{#if steps.length}
										<div class="mt-1 text-gray-500">{doneSteps}/{steps.length} {$i18n.t('steps')} · {steps.filter((s) => s.gate === 'approval').length} {$i18n.t('gates')}</div>
									{/if}
								</div>
							{/if}
						</div>
						<div class="min-w-0 flex-1 pt-1.5">
							<div class="inline-flex items-center gap-1.5 text-[9px] uppercase tracking-widest text-cyan-300/80 px-2 py-0.5 rounded-md border border-cyan-400/20 bg-cyan-400/5">
								<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" class="size-2.5"><path d={method?.icon} /></svg>
								{$i18n.t('Detected')}: {method?.label}{#if method?.mock}&nbsp;· {$i18n.t('Mock Mode')}{/if}
							</div>
							<div class="mt-1 flex items-center gap-2">
								<h1 class="text-lg font-semibold text-gray-50 truncate">{space?.title || $i18n.t('Space')}</h1>
								{#if space?.status === 'active'}
									<button class="shrink-0 text-[10px] px-2 py-0.5 rounded-lg border border-white/10 text-gray-500 hover:text-gray-200 transition" on:click={() => setSpaceStatus('done')}>{$i18n.t('Mark done')}</button>
								{:else}
									<span class="shrink-0 text-[9px] uppercase px-1.5 py-0.5 rounded-md {space?.status === 'done' ? 'bg-emerald-500/15 text-emerald-400' : 'bg-white/8 text-gray-400'}">{space?.status}</span>
									<button class="shrink-0 text-[10px] px-2 py-0.5 rounded-lg border border-white/10 text-gray-500 hover:text-gray-200 transition" on:click={() => setSpaceStatus('active')}>{$i18n.t('Reopen')}</button>
								{/if}
							</div>
						</div>
					</header>

					{#if err}<div class="relative mt-3 text-xs text-red-400">{err}</div>{/if}

					<!-- approval gate — the ONE action that interrupts the workspace -->
					{#if coreState === 'waiting' && activeStep}
						<button
							class="relative mt-4 inline-flex items-center gap-2 text-xs px-3.5 py-2 rounded-xl border border-amber-400/40 bg-amber-400/10 text-amber-200 hover:bg-amber-400/15 transition"
							in:fly={{ y: 8, duration: 250 }}
							on:click={() => (gateStep = activeStep)}
						>
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-3.5"><path d="M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" stroke-linecap="round" stroke-linejoin="round" /></svg>
							{$i18n.t('Waiting on your approval')} — {activeStep.title} · <span class="underline underline-offset-2">{$i18n.t('Review')}</span>
						</button>
					{/if}

					<!-- PRIMARY SURFACE — the canvas reshapes into the task's workbench.
					     Resource Board + Tool Dock are demoted to a support rail below. -->
					<section class="relative w-full mt-5">
						<div class="flex items-center gap-2 text-[9px] uppercase tracking-[0.25em] text-cyan-300/70">
							<span class="h-px w-6 bg-cyan-400/40"></span>
							{surfaceLabel}
							<span class="h-px flex-1 bg-cyan-400/15"></span>
							{#if execStep && space?.status === 'active'}
								<button
									class="normal-case tracking-normal text-[10px] px-2.5 py-1 rounded-lg border border-cyan-400/30 text-cyan-200 hover:bg-cyan-400/10 transition disabled:opacity-50"
									disabled={busy}
									on:click={() => runMock(execStep)}>{$i18n.t('Run (mock)')}</button
								>
							{/if}
						</div>
						<div class="mt-3">
							{#if surface === 'repo_runner'}
								{#key space.id}
									<RepoRunnerSurface {space} on:updated={(e) => (space = { ...space, manifest: e.detail })} />
								{/key}
							{:else if surface === 'physical_3d_stage'}
								{#key space.id}
									<PrototypeTestPanel {space} />
								{/key}
							{:else}
								<div class="grid sm:grid-cols-2 gap-3">
									{#each method?.outputs ?? [] as o, oi (o.title)}
										<article class="hud-panel {o.tone === 'amber' ? 'amber' : ''}" in:fly={{ y: 14, duration: 300, delay: 120 + oi * 70 }}>
											<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
											<div class="flex items-center justify-between gap-2">
												<h3 class="text-xs font-semibold {o.tone === 'amber' ? 'text-amber-200' : 'text-gray-100'}">{o.title}</h3>
												<span class="text-[8px] uppercase tracking-widest {o.tone === 'amber' ? 'text-amber-300/80' : 'text-cyan-300/60'}">{o.tone === 'amber' ? $i18n.t('Gated') : $i18n.t('Mock')}</span>
											</div>
											<p class="mt-1.5 text-[11px] text-gray-400 leading-relaxed">{o.body}</p>
										</article>
									{/each}
								</div>
							{/if}
						</div>
						{#if linkedRuns.length}
							<article class="hud-panel mt-3" in:fly={{ y: 14, duration: 300, delay: 120 }}>
								<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
								<h3 class="text-xs font-semibold text-gray-100">{$i18n.t('Activity')}</h3>
								<div class="mt-1.5 space-y-1">
									{#each linkedRuns.slice(-3).reverse() as r, ri (ri)}
										<div class="flex items-center gap-2 text-[11px] text-gray-400">
											<span class="size-1 rounded-full bg-cyan-400/70 shrink-0"></span>
											<span class="min-w-0 truncate">{r.message ?? r.stage ?? r.kind ?? 'event'}</span>
											{#if r.mock}<span class="shrink-0 text-[8px] uppercase tracking-widest text-cyan-300/60">{$i18n.t('Mock')}</span>{/if}
											<span class="ml-auto shrink-0 text-[9px] text-gray-600 tabular-nums">{fmtAt(r.at)}</span>
										</div>
									{/each}
								</div>
							</article>
						{/if}
					</section>

					<!-- SUPPORT RAIL — resource board + tool dock, secondary (collapsed by default) -->
					{#if resources.length || tools.length}
						<section class="relative w-full mt-4">
							<button
								class="w-full flex items-center gap-2 text-[9px] uppercase tracking-[0.25em] text-gray-500 hover:text-gray-300 transition"
								aria-expanded={railOpen}
								on:click={() => (railOpen = !railOpen)}
							>
								<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-2.5 transition-transform {railOpen ? 'rotate-90' : ''}"><path d="M9 6l6 6-6 6" stroke-linecap="round" stroke-linejoin="round" /></svg>
								{$i18n.t('Resources & tools')} <span class="text-gray-600">({resources.length + tools.length})</span>
								<span class="h-px flex-1 bg-white/6"></span>
							</button>
							{#if railOpen}
								<div class="mt-3 grid lg:grid-cols-2 gap-3" transition:fade={{ duration: 150 }}>
									<ResourceBoard {resources} {cues} spaceId={space.id} on:updated={(e) => (space = { ...space, manifest: e.detail })} />
									<ToolDock {tools} />
								</div>
							{/if}
						</section>
					{/if}
				</div>
			{:else}
				<div class="h-full flex flex-col items-center justify-center text-xs text-gray-500 gap-2">
					<span>{err || $i18n.t('Space unavailable.')}</span>
					<button class="text-[11px] px-2.5 py-1 rounded-lg border border-white/10 text-gray-400 hover:text-gray-200" on:click={goStandby}>{$i18n.t('Back to standby')}</button>
				</div>
			{/if}
		</div>

		<!-- COMPOSER — always present, chat-first: submit → shape is inferred, the
		     same canvas transforms. No selector; a popup asks only if ambiguous. -->
		<div class="shrink-0 px-5 pb-4 pt-2">
			<div class="max-w-3xl mx-auto rounded-2xl border border-white/10 bg-[#0c111d]/95 backdrop-blur p-2 shadow-lg shadow-black/40">
				{#if pendingImageUrl}
					<div class="flex items-center gap-2 mb-1.5 px-1" in:fade={{ duration: 150 }}>
						<img src={pendingImageUrl} alt={$i18n.t('Attached reference')} class="size-9 rounded-lg object-cover border border-white/10" />
						<span class="text-[10px] text-gray-400">{$i18n.t('Reference image')} · <span class="text-cyan-300/70">{$i18n.t('attached — not measured')}</span></span>
						<button class="ml-auto text-gray-500 hover:text-gray-200 transition" on:click={clearPendingImage} aria-label={$i18n.t('Remove attachment')}>
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-3.5"><path d="M18 6 6 18M6 6l12 12" stroke-linecap="round" /></svg>
						</button>
					</div>
				{/if}
				<div class="flex items-end gap-1.5">
					<button
						class="shrink-0 size-8 rounded-xl flex items-center justify-center text-gray-400 hover:text-cyan-200 hover:bg-white/5 transition"
						aria-label={$i18n.t('Attach reference image')}
						title={$i18n.t('Attach reference image')}
						on:click={() => composerFileInput?.click()}
					>
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-4"><path d="M3 3h18v18H3z" /><path d="M3 15l5-5 4 4 3-3 6 6" stroke-linecap="round" stroke-linejoin="round" /><circle cx="8.5" cy="8.5" r="1.5" fill="currentColor" stroke="none" /></svg>
					</button>
					<input bind:this={composerFileInput} type="file" accept="image/png,image/jpeg,image/webp" class="hidden" on:change={onComposerFile} />
					<button
						class="shrink-0 size-8 rounded-xl flex items-center justify-center transition {recording ? 'bg-red-500/20 text-red-300' : transcribing ? 'text-cyan-300' : 'text-gray-400 hover:text-cyan-200 hover:bg-white/5'}"
						aria-label={recording ? $i18n.t('Stop recording') : $i18n.t('Voice input')}
						title={$i18n.t('Voice input')}
						on:click={toggleMic}
					>
						{#if transcribing}
							<svg class="size-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" /><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8V0C5.4 0 0 5.4 0 12h4z" /></svg>
						{:else}
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-4 {recording ? 'mic-live' : ''}"><path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z" /><path d="M19 10v1a7 7 0 0 1-14 0v-1M12 18v4M8 22h8" stroke-linecap="round" stroke-linejoin="round" /></svg>
						{/if}
					</button>
					<textarea
						rows="1"
						class="flex-1 text-sm bg-transparent px-2 py-1.5 outline-none resize-none text-gray-100 placeholder:text-gray-500 leading-relaxed max-h-32"
						placeholder={recording ? $i18n.t('Listening…') : space ? $i18n.t('Describe the next task — a new space forms around it…') : $i18n.t('What should Harvis shape?')}
						bind:value={intent}
						on:keydown={(e) => {
							if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); create(); }
						}}
					></textarea>
					<button
						class="shrink-0 size-8 rounded-xl flex items-center justify-center transition {(intent.trim() || pendingImage) && !creating
							? 'bg-cyan-600 hover:bg-cyan-500 text-white'
							: 'bg-white/6 text-gray-500 cursor-not-allowed'}"
						disabled={(!intent.trim() && !pendingImage) || creating}
						aria-label={$i18n.t('Shape workspace')}
						on:click={create}
					>
						{#if creating}
							<svg class="size-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" /><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 0 1 8-8V0C5.4 0 0 5.4 0 12h4z" /></svg>
						{:else}
							<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-4"><path d="M12 19V5M5 12l7-7 7 7" stroke-linecap="round" stroke-linejoin="round" /></svg>
						{/if}
					</button>
				</div>
			</div>
			<div class="max-w-3xl mx-auto mt-1 text-center text-[9px] text-gray-500">
				{$i18n.t('Attach a reference image or speak · workspace shape is detected automatically · mock-first')}
			</div>
		</div>
	</div>
</div>

<!-- Ambiguous shape → ONE focused question (chip answers + safe default; not a wizard) -->
{#if askShape}
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" transition:fade={{ duration: 150 }}>
		<div class="w-full max-w-md rounded-2xl bg-[#0c111d] border border-cyan-400/25 shadow-xl p-4 space-y-3">
			<h3 class="text-sm font-semibold text-gray-100">{$i18n.t('What kind of task is this?')}</h3>
			<p class="text-[11px] text-gray-500">
				{$i18n.t('Harvis couldn’t infer the workspace shape from the description — pick one:')}
			</p>
			<div class="flex flex-wrap gap-1.5">
				{#each templates as t (t.key)}
					<button
						type="button"
						class="inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1.5 rounded-lg border border-white/10 text-gray-300 hover:text-cyan-200 hover:border-cyan-400/30 transition disabled:opacity-50"
						disabled={creating}
						on:click={() => createWith(t.key, askShape?.text ?? '')}
					>
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" class="size-3"><path d={STUDIO[t.key]?.icon ?? ''} /></svg>
						{STUDIO[t.key]?.label ?? t.name}
					</button>
				{/each}
			</div>
			<div class="flex items-center justify-end gap-2 pt-1">
				<button class="text-xs px-3 py-1.5 rounded-lg text-gray-400 hover:text-gray-200" disabled={creating} on:click={() => (askShape = null)}>{$i18n.t('Cancel')}</button>
				<button
					class="text-xs px-3 py-1.5 rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white transition disabled:opacity-50"
					disabled={creating}
					on:click={() => createWith('feature-plan', askShape?.text ?? '')}
					>{creating ? $i18n.t('Shaping…') : $i18n.t('Use default (Feature Builder)')}</button
				>
			</div>
		</div>
	</div>
{/if}

<!-- Approval gate confirm (server enforces approved:true) -->
{#if gateStep}
	<div class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" transition:fade={{ duration: 150 }}>
		<div class="w-full max-w-md rounded-2xl bg-[#0c111d] border border-amber-400/30 shadow-xl p-4 space-y-3">
			<div class="flex items-center gap-2">
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-5 text-amber-300"><path d="M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" stroke-linecap="round" stroke-linejoin="round" /></svg>
				<h3 class="text-sm font-semibold text-gray-100">{$i18n.t('Approve this step?')}</h3>
			</div>
			<div class="text-xs text-gray-300">
				<div class="font-medium">{gateStep.title}</div>
				{#if gateStep.detail}<div class="mt-1 text-gray-500">{gateStep.detail}</div>{/if}
			</div>
			<p class="text-[11px] text-amber-300/90">{$i18n.t('Human gate — your approval is recorded in the space’s audit trail.')}</p>
			<div class="flex items-center justify-end gap-2">
				<button class="text-xs px-3 py-1.5 rounded-lg text-gray-400 hover:text-gray-200" on:click={() => (gateStep = null)}>{$i18n.t('Cancel')}</button>
				<button class="text-xs px-3 py-1.5 rounded-lg bg-amber-600 hover:bg-amber-500 text-white transition" disabled={busy} on:click={confirmGate}>{$i18n.t('Approve')}</button>
			</div>
		</div>
	</div>
{/if}

<style>
	/* Mic recording — gentle live pulse on the icon while capturing audio. */
	.mic-live {
		animation: hv-mic 1.1s ease-in-out infinite;
	}
	@keyframes hv-mic {
		0%,
		100% {
			opacity: 0.6;
		}
		50% {
			opacity: 1;
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.mic-live {
			animation: none;
		}
	}

	/* Shaping-transition dots — a quiet "forming" pulse while the session loads. */
	.shaping-dots {
		display: inline-flex;
		gap: 3px;
	}
	.shaping-dots i {
		width: 4px;
		height: 4px;
		border-radius: 9999px;
		background: rgba(125, 211, 252, 0.85);
		animation: hv-shaping-dot 1.1s ease-in-out infinite;
	}
	.shaping-dots i:nth-child(2) {
		animation-delay: 0.18s;
	}
	.shaping-dots i:nth-child(3) {
		animation-delay: 0.36s;
	}
	@keyframes hv-shaping-dot {
		0%,
		100% {
			opacity: 0.25;
			transform: translateY(0);
		}
		50% {
			opacity: 1;
			transform: translateY(-2px);
		}
	}
	@media (prefers-reduced-motion: reduce) {
		.shaping-dots i {
			animation: none;
			opacity: 0.7;
		}
	}

	/* HUD panels — instrument cards with corner brackets (Output & Preview only). */
	.hud-panel {
		position: relative;
		padding: 0.85rem 1rem;
		background: linear-gradient(180deg, rgba(13, 21, 36, 0.92), rgba(8, 13, 24, 0.92));
		border: 1px solid rgba(56, 189, 248, 0.16);
		transition: border-color 200ms ease;
	}
	.hud-panel:hover {
		border-color: rgba(56, 189, 248, 0.35);
	}
	.hud-panel.amber {
		border-color: rgba(252, 211, 77, 0.22);
	}
	.hud-panel.amber:hover {
		border-color: rgba(252, 211, 77, 0.4);
	}
	.corner {
		position: absolute;
		width: 10px;
		height: 10px;
		border: 0 solid rgba(125, 211, 252, 0.55);
		pointer-events: none;
	}
	.hud-panel.amber .corner {
		border-color: rgba(252, 211, 77, 0.55);
	}
	.corner.tl {
		top: -1px;
		left: -1px;
		border-top-width: 1.5px;
		border-left-width: 1.5px;
	}
	.corner.tr {
		top: -1px;
		right: -1px;
		border-top-width: 1.5px;
		border-right-width: 1.5px;
	}
	.corner.bl {
		bottom: -1px;
		left: -1px;
		border-bottom-width: 1.5px;
		border-left-width: 1.5px;
	}
	.corner.br {
		bottom: -1px;
		right: -1px;
		border-bottom-width: 1.5px;
		border-right-width: 1.5px;
	}
</style>
