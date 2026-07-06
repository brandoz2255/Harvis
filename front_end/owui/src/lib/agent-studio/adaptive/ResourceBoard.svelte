<script lang="ts">
	// Resource Board — what the workspace has gathered or produced, backend-routed
	// (manifest.resources). Surfaces gathered inputs (criteria), uploaded references,
	// and produced outputs (analysis), each carrying its honesty flags: a reference
	// image is "not measured", a generated mesh is "concept" (not structural).
	import { getContext } from 'svelte';
	const i18n: any = getContext('i18n');

	export let resources: any[] = [];

	// small kind → icon (24×24 stroke path)
	const ICONS: Record<string, string> = {
		criteria: 'M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11',
		analysis: 'M3 3v18h18M18 17V9M13 17V5M8 17v-3',
		image: 'M3 3h18v18H3zM3 15l5-5 4 4 3-3 6 6',
		mesh: 'M12 2 3 7v10l9 5 9-5V7l-9-5zM12 22V12M3 7l9 5 9-5',
		step: 'M4 6h16M4 12h16M4 18h10',
		output: 'M4 4h16v16H4zM9 9h6v6H9z'
	};
	const iconFor = (k: string) => ICONS[k] ?? 'M4 4h16v16H4z';
</script>

<article class="hud-panel">
	<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
	<div class="flex items-center justify-between gap-2">
		<h3 class="text-xs font-semibold text-gray-100">{$i18n.t('Resource board')}</h3>
		<span class="text-[8px] uppercase tracking-widest text-cyan-300/60">{resources.length} {$i18n.t('gathered')}</span>
	</div>
	{#if resources.length}
		<ul class="mt-2 space-y-1.5">
			{#each resources as r (r.id)}
				<li class="flex items-center gap-2 text-[11px]">
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" class="size-3 text-cyan-300/70 shrink-0"><path d={iconFor(r.kind)} /></svg>
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
			{$i18n.t('Harvis gathers files, criteria, and outputs here as the task takes shape.')}
		</p>
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
</style>
