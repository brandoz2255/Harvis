<script lang="ts">
	// Resource Board — what the workspace has gathered or produced, backend-routed
	// (manifest.resources). Surfaces gathered inputs (criteria), uploaded REFERENCE
	// images, and produced outputs (analysis), each carrying its honesty flags: a
	// reference image is "not measured", the analysis is "analytical" (not certified),
	// a generated mesh would be "concept" (not structural). Also lets the user attach
	// a reference photo and shows the visual cues Harvis would ESTIMATE from it.
	import { getContext, createEventDispatcher, onDestroy } from 'svelte';
	const i18n: any = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let resources: any[] = [];
	export let cues: any[] = [];
	export let spaceId = '';

	const authHdr = () => ({ Authorization: `Bearer ${localStorage.token}` });

	const ICONS: Record<string, string> = {
		criteria: 'M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11',
		analysis: 'M3 3v18h18M18 17V9M13 17V5M8 17v-3',
		image: 'M3 3h18v18H3zM3 15l5-5 4 4 3-3 6 6',
		mesh: 'M12 2 3 7v10l9 5 9-5V7l-9-5zM12 22V12M3 7l9 5 9-5',
		output: 'M4 4h16v16H4zM9 9h6v6H9z'
	};
	const iconFor = (k: string) => ICONS[k] ?? 'M4 4h16v16H4z';

	// Thumbnails: <img> can't send a Bearer token, so fetch the blob with auth and
	// render an object URL. Cached per resource id; revoked on destroy.
	let thumbs: Record<string, string> = {};
	const loadThumb = async (rid: string) => {
		if (!rid || !spaceId || rid in thumbs) return;
		thumbs = { ...thumbs, [rid]: '' }; // reserve rid first — blocks a concurrent double-fetch
		try {
			const r = await fetch(`/api/adaptive/spaces/${spaceId}/resource/${rid}`, { headers: authHdr(), credentials: 'include' });
			if (r.ok) thumbs = { ...thumbs, [rid]: URL.createObjectURL(await r.blob()) };
			else { const t = { ...thumbs }; delete t[rid]; thumbs = t; }
		} catch {
			const t = { ...thumbs }; delete t[rid]; thumbs = t; // free the reservation to allow a retry
		}
	};
	$: resources.filter((r) => r.kind === 'image').forEach((r) => loadThumb(r.id));

	let uploading = false;
	let err = '';
	let fileInput: HTMLInputElement;
	const onFile = async (e: Event) => {
		const f = (e.target as HTMLInputElement).files?.[0];
		if (!f || !spaceId) return;
		uploading = true;
		err = '';
		try {
			const fd = new FormData();
			fd.append('file', f);
			const r = await fetch(`/api/adaptive/spaces/${spaceId}/resource`, { method: 'POST', headers: authHdr(), credentials: 'include', body: fd });
			if (r.ok) dispatch('updated', (await r.json()).manifest);
			else err = (await r.json().catch(() => null))?.detail || 'Upload failed';
		} catch {
			err = 'Upload failed';
		}
		uploading = false;
		if (fileInput) fileInput.value = '';
		if (err) setTimeout(() => (err = ''), 4000); // auto-clear on every error path
	};

	onDestroy(() => {
		for (const u of Object.values(thumbs)) if (u) URL.revokeObjectURL(u);
	});
</script>

<article class="hud-panel">
	<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
	<div class="flex items-center justify-between gap-2">
		<h3 class="text-xs font-semibold text-gray-100">{$i18n.t('Resource board')}</h3>
		<div class="flex items-center gap-2">
			<span class="text-[8px] uppercase tracking-widest text-cyan-300/60">{resources.length} {$i18n.t('gathered')}</span>
			<button
				class="text-[10px] px-2 py-0.5 rounded-lg border border-cyan-400/25 text-cyan-200 hover:bg-cyan-400/10 transition disabled:opacity-50 inline-flex items-center gap-1"
				disabled={uploading || !spaceId}
				on:click={() => fileInput?.click()}
			>
				<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-2.5"><path d="M12 5v14M5 12h14" stroke-linecap="round" /></svg>
				{uploading ? $i18n.t('Uploading…') : $i18n.t('Image')}
			</button>
			<input bind:this={fileInput} type="file" accept="image/png,image/jpeg,image/webp" class="hidden" on:change={onFile} />
		</div>
	</div>

	{#if err}<div class="mt-1 text-[10px] text-red-400">{err}</div>{/if}

	{#if resources.length}
		<ul class="mt-2 space-y-1.5">
			{#each resources as r (r.id)}
				<li class="flex items-center gap-2 text-[11px]">
					{#if r.kind === 'image' && thumbs[r.id]}
						<img src={thumbs[r.id]} alt={r.label} class="size-6 rounded object-cover border border-white/10 shrink-0" />
					{:else}
						<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" class="size-3 text-cyan-300/70 shrink-0"><path d={iconFor(r.kind)} /></svg>
					{/if}
					<span class="text-gray-200 min-w-0 truncate">{r.label}</span>
					{#if r.role}<span class="shrink-0 text-[8px] uppercase tracking-widest text-gray-500">{r.role}</span>{/if}
					{#if r.measured === false}<span class="badge cyan">{$i18n.t('reference')}</span>{/if}
					{#if r.kind === 'analysis'}<span class="badge amber">{$i18n.t('analytical')}</span>{/if}
					{#if r.structural === false}<span class="badge violet">{$i18n.t('concept')}</span>{/if}
					{#if r.structural === true}<span class="badge emerald">{$i18n.t('structural')}</span>{/if}
				</li>
			{/each}
		</ul>
	{:else}
		<p class="mt-2 text-[11px] text-gray-500 leading-relaxed">
			{$i18n.t('Harvis gathers files, criteria, and outputs here as the task takes shape. Attach a reference photo to start.')}
		</p>
	{/if}

	<!-- Reference checklist — appears once an image is attached. HONEST: this is a
	     static list of what Harvis WOULD look for, NOT read from the actual photo. -->
	{#if cues.length}
		<div class="mt-3 pt-2 border-t border-white/6">
			<div class="flex items-center justify-between gap-2">
				<span class="text-[9px] uppercase tracking-widest text-gray-500">{$i18n.t('What Harvis would look for')}</span>
				<span class="badge amber">{$i18n.t('not read from your photo')}</span>
			</div>
			<div class="mt-1.5 flex flex-wrap gap-1.5">
				{#each cues as c (c.label)}
					<span class="cue-chip">{c.label}</span>
				{/each}
			</div>
			<p class="mt-1.5 text-[9px] text-gray-600 leading-relaxed">{$i18n.t('A static reference checklist — a future vision model fills these in per image.')}</p>
		</div>
	{/if}
</article>

<style>
	.hud-panel {
		position: relative;
		padding: 0.85rem 1rem;
		background: linear-gradient(180deg, rgba(13, 21, 36, 0.92), rgba(8, 13, 24, 0.92));
		border: 1px solid rgba(56, 189, 248, 0.16);
	}
	.corner {
		position: absolute;
		width: 10px;
		height: 10px;
		border: 0 solid rgba(125, 211, 252, 0.55);
		pointer-events: none;
	}
	.corner.tl { top: -1px; left: -1px; border-top-width: 1.5px; border-left-width: 1.5px; }
	.corner.tr { top: -1px; right: -1px; border-top-width: 1.5px; border-right-width: 1.5px; }
	.corner.bl { bottom: -1px; left: -1px; border-bottom-width: 1.5px; border-left-width: 1.5px; }
	.corner.br { bottom: -1px; right: -1px; border-bottom-width: 1.5px; border-right-width: 1.5px; }

	.badge {
		flex: none;
		font-size: 8px;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		padding: 1px 5px;
		border-radius: 4px;
	}
	.badge.cyan { background: rgba(56, 189, 248, 0.14); color: #7dd3fc; }
	.badge.amber { background: rgba(252, 211, 77, 0.14); color: #fcd34d; }
	.badge.violet { background: rgba(167, 139, 250, 0.16); color: #c4b5fd; }
	.badge.emerald { background: rgba(52, 211, 153, 0.14); color: #34d399; }

	.cue-chip {
		font-size: 10px;
		padding: 2px 8px;
		border-radius: 9999px;
		border: 1px dashed rgba(252, 211, 77, 0.3);
		color: #cbd5e1;
	}
</style>
