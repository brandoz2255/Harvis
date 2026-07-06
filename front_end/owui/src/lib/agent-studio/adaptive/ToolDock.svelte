<script lang="ts">
	// Tool Dock — the workspace's capability registry, backend-routed (manifest.tools).
	// Each chip shows a tool's honest status (ready/mock/setup/gated/disabled) and its
	// permission lane, so what Harvis CAN and CANNOT do is legible at a glance. Nothing
	// here executes; it renders the registry the backend seeds per method pack.
	import { getContext } from 'svelte';
	const i18n: any = getContext('i18n');

	export let tools: any[] = [];

	const statusColor = (s: string) =>
		({ ready: '#34d399', mock: '#7dd3fc', setup: '#fcd34d', gated: '#fbbf24', disabled: '#64748b' }[s] ?? '#64748b');
	const statusLabel = (s: string) =>
		({ ready: 'Ready', mock: 'Mock', setup: 'Setup', gated: 'Gated', disabled: 'Off' }[s] ?? s);
</script>

<article class="hud-panel">
	<span class="corner tl"></span><span class="corner tr"></span><span class="corner bl"></span><span class="corner br"></span>
	<div class="flex items-center justify-between gap-2">
		<h3 class="text-xs font-semibold text-gray-100">{$i18n.t('Tool dock')}</h3>
		<span class="text-[8px] uppercase tracking-widest text-cyan-300/60">{tools.length} {$i18n.t('capabilities')}</span>
	</div>
	<div class="mt-2 flex flex-wrap gap-1.5">
		{#each tools as t (t.key)}
			<div
				class="tool-chip"
				class:dim={t.status === 'disabled'}
				title="{t.purpose}{t.desc ? ' — ' + t.desc : ''} · {t.lane_label} lane"
			>
				<span class="dot" style="background:{statusColor(t.status)};"></span>
				<span class="lbl">{t.label}</span>
				<span class="tag" style="color:{statusColor(t.status)};">{$i18n.t(statusLabel(t.status))}</span>
				<span class="lane">L{t.lane}</span>
				{#if t.approval}
					<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-2.5 text-amber-300/80" aria-label={$i18n.t('approval required')}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" stroke-linecap="round" stroke-linejoin="round" /></svg>
				{/if}
			</div>
		{/each}
	</div>
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

	.tool-chip {
		display: inline-flex;
		align-items: center;
		gap: 5px;
		padding: 3px 8px;
		border-radius: 8px;
		border: 1px solid rgba(255, 255, 255, 0.08);
		background: rgba(255, 255, 255, 0.02);
		font-size: 10px;
		color: #cbd5e1;
	}
	.tool-chip.dim {
		opacity: 0.5;
	}
	.tool-chip .dot {
		width: 6px;
		height: 6px;
		border-radius: 9999px;
		flex: none;
	}
	.tool-chip .lbl {
		color: #e2e8f0;
	}
	.tool-chip .tag {
		font-size: 8px;
		text-transform: uppercase;
		letter-spacing: 0.08em;
	}
	.tool-chip .lane {
		font-size: 8px;
		color: #64748b;
		border: 1px solid rgba(148, 163, 184, 0.2);
		border-radius: 4px;
		padding: 0 3px;
	}
</style>
