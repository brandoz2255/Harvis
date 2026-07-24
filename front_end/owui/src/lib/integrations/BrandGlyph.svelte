<script lang="ts">
	// Brand mark renderer for Integrations.
	// Real product logos are VENDORED locally as SVG at static/integrations/<key>.svg
	// (no runtime remote fetch). Internal / protocol / future entries (OpenClaw, Hermes,
	// SSH, Harvis, packs) stay as local inline glyphs.
	export let name: string = 'pack';
	export let className: string = 'size-5';

	// brands with a vendored official logo at /integrations/<name>.svg
	const LOGOS = new Set(['claude', 'openai', 'ollama', 'github', 'discord', 'mcp', 'opencode', 'openclaw', 'hermes']);
	$: hasLogo = LOGOS.has(name);
</script>

{#if hasLogo}
	<img src="/integrations/{name}.svg" alt="" class="{className} object-contain" loading="lazy" draggable="false" />
{:else if name === 'ssh'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" class={className} aria-hidden="true">
		<rect x="3" y="4.5" width="18" height="15" rx="2" />
		<path d="M7 10l3 2.5-3 2.5M13 15h4" />
	</svg>
{:else if name === 'kimi'}
	<!-- Moonshot / Kimi — crescent moon + spark -->
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" class={className} aria-hidden="true">
		<path d="M20 14.5A7.5 7.5 0 1 1 10.5 4a6 6 0 0 0 9.5 10.5z" />
		<path d="M18.2 3l.5 1.6 1.6.5-1.6.5-.5 1.6-.5-1.6-1.6-.5 1.6-.5z" fill="currentColor" stroke="none" />
	</svg>
{:else if name === 'harvis'}
	<!-- CLI prompt + spark -->
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" class={className} aria-hidden="true">
		<path d="M4 7l6 5.5L4 18" />
		<path d="M12 18h7" />
		<path d="M18.5 2.6l.7 2.2 2.2.7-2.2.7-.7 2.2-.7-2.2-2.2-.7 2.2-.7z" fill="currentColor" stroke="none" />
	</svg>
{:else}
	<!-- pack / default — isometric box -->
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" class={className} aria-hidden="true">
		<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z" />
		<path d="M12 12v9M4 7.5l8 4.5 8-4.5" />
	</svg>
{/if}
