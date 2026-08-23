<script lang="ts">
	// Brand mark renderer for Integrations. Nothing here is fetched at runtime — every mark ships
	// in the bundle. Three kinds, in the order they're checked:
	//   1. vendored files at static/integrations/<key>.svg, rendered as <img> (fixed fill);
	//   2. inline vendor marks painted with currentColor, so they take the tile's brand tint
	//      (BRAND_TONE) — required whenever the official mark is near-black or the tile is
	//      coloured, because an <img> can't be recoloured;
	//   3. Harvis-drawn glyphs for internal / protocol entries (OpenClaw, SSH, Harvis, packs)
	//      and as the generic fallback — never an approximation of a vendor's real logo.
	export let name: string = 'pack';
	export let className: string = 'size-5';

	// brands with a vendored official logo at /integrations/<name>.svg
	const LOGOS = new Set(['claude', 'openai', 'ollama', 'github', 'discord', 'mcp', 'opencode', 'openclaw', 'hermes']);
	$: hasLogo = LOGOS.has(name);

	// Free-tier cloud providers carry their own official marks (below), single-path where the
	// vendor's logo allows it. 'cloud-api' stays as the generic fallback for a future provider
	// whose mark we don't have — it is no longer what the five actually render.
	const CLOUD_MARKS: Record<string, string[]> = {
		groq: [
			'M12.036 2c-3.853-.035-7 3-7.036 6.781-.035 3.782 3.055 6.872 6.908 6.907h2.42v-2.566h-2.292c-2.407.028-4.38-1.866-4.408-4.23-.029-2.362 1.901-4.298 4.308-4.326h.1c2.407 0 4.358 1.915 4.365 4.278v6.305c0 2.342-1.944 4.25-4.323 4.279a4.375 4.375 0 01-3.033-1.252l-1.851 1.818A7 7 0 0012.029 22h.092c3.803-.056 6.858-3.083 6.879-6.816v-6.5C18.907 4.963 15.817 2 12.036 2z'
		],
		cerebras: [
			'M14.121 2.701a9.299 9.299 0 000 18.598V22.7c-5.91 0-10.7-4.791-10.7-10.701S8.21 1.299 14.12 1.299V2.7zm4.752 3.677A7.353 7.353 0 109.42 17.643l-.901 1.074a8.754 8.754 0 01-1.08-12.334 8.755 8.755 0 0112.335-1.08l-.901 1.075zm-2.255.844a5.407 5.407 0 00-5.048 9.563l-.656 1.24a6.81 6.81 0 016.358-12.043l-.654 1.24zM14.12 8.539a3.46 3.46 0 100 6.922v1.402a4.863 4.863 0 010-9.726v1.402z',
			'M15.407 10.836a2.24 2.24 0 00-.51-.409 1.084 1.084 0 00-.544-.152c-.255 0-.483.047-.684.14a1.58 1.58 0 00-.84.912c-.074.203-.11.416-.11.631 0 .218.036.43.11.631a1.594 1.594 0 00.84.913c.2.093.43.14.684.14.216 0 .417-.046.602-.135.188-.09.35-.225.475-.392l.928 1.006c-.14.14-.3.261-.482.363a3.367 3.367 0 01-1.083.38c-.17.026-.317.04-.44.04a3.315 3.315 0 01-1.182-.21 2.825 2.825 0 01-.961-.597 2.816 2.816 0 01-.644-.929 2.987 2.987 0 01-.238-1.21c0-.444.08-.847.238-1.21.15-.35.368-.666.643-.929.278-.261.605-.464.962-.596a3.315 3.315 0 011.182-.21c.355 0 .712.068 1.072.204.361.138.685.36.944.649l-.962.97z'
		],
		gemini: [
			'M20.616 10.835a14.147 14.147 0 01-4.45-3.001 14.111 14.111 0 01-3.678-6.452.503.503 0 00-.975 0 14.134 14.134 0 01-3.679 6.452 14.155 14.155 0 01-4.45 3.001c-.65.28-1.318.505-2.002.678a.502.502 0 000 .975c.684.172 1.35.397 2.002.677a14.147 14.147 0 014.45 3.001 14.112 14.112 0 013.679 6.453.502.502 0 00.975 0c.172-.685.397-1.351.677-2.003a14.145 14.145 0 013.001-4.45 14.113 14.113 0 016.453-3.678.503.503 0 000-.975 13.245 13.245 0 01-2.003-.678z'
		],
		nvidia: [
			'M10.212 8.976V7.62c.127-.01.256-.017.388-.021 3.596-.117 5.957 3.184 5.957 3.184s-2.548 3.647-5.282 3.647a3.227 3.227 0 01-1.063-.175v-4.109c1.4.174 1.681.812 2.523 2.258l1.873-1.627a4.905 4.905 0 00-3.67-1.846 6.594 6.594 0 00-.729.044m0-4.476v2.025c.13-.01.259-.019.388-.024 5.002-.174 8.261 4.226 8.261 4.226s-3.743 4.69-7.643 4.69c-.338 0-.675-.031-1.007-.092v1.25c.278.038.558.057.838.057 3.629 0 6.253-1.91 8.794-4.169.421.347 2.146 1.193 2.501 1.564-2.416 2.083-8.048 3.763-11.24 3.763-.308 0-.603-.02-.894-.048V19.5H24v-15H10.21zm0 9.756v1.068c-3.356-.616-4.287-4.21-4.287-4.21a7.173 7.173 0 014.287-2.138v1.172h-.005a3.182 3.182 0 00-2.502 1.178s.615 2.276 2.507 2.931m-5.961-3.3c1.436-1.935 3.604-3.148 5.961-3.336V6.523C5.81 6.887 2 10.723 2 10.723s2.158 6.427 8.21 7.015v-1.166C5.77 16 4.25 10.958 4.25 10.958h-.002z'
		],
		mistral: [
			'M3.428 3.4h3.429v3.428h3.429v3.429h-.002 3.431V6.828h3.427V3.4h3.43v13.714H24v3.429H13.714v-3.428h-3.428v-3.429h-3.43v3.428h3.43v3.429H0v-3.429h3.428V3.4zm10.286 13.715h3.428v-3.429h-3.427v3.429z'
		]
	};
	$: cloudMark = CLOUD_MARKS[name];
</script>

{#if hasLogo}
	<img src="/integrations/{name}.svg" alt="" class="{className} object-contain" loading="lazy" draggable="false" />
{:else if name === 'ssh'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" class={className} aria-hidden="true">
		<rect x="3" y="4.5" width="18" height="15" rx="2" />
		<path d="M7 10l3 2.5-3 2.5M13 15h4" />
	</svg>
{:else if name === 'kimi'}
	<!-- Kimi (Moonshot AI) — the official wordmark glyph, from simple-icons (CC0-1.0).
	     Inline rather than vendored as a file because the official mark is solid #000: as an
	     <img> it would vanish on a dark tile, while `fill="currentColor"` inherits the tile's
	     brand tint and reads in both themes. -->
	<svg viewBox="0 0 24 24" fill="currentColor" class={className} aria-hidden="true">
		<path
			d="M21.765.351C22.998.351 24 1.353 24 2.586S22.998 4.82 21.765 4.82h-1.974c-.15 0-.26-.12-.26-.26V2.586A2.237 2.237 0 0 1 21.765.35M9.41 13.388l8.447-8.377c.16-.16.07-.471-.14-.471h-4.55s-.1.02-.14.06l-9.099 9.029c-.14.14-.35.02-.35-.21V4.81c0-.15-.1-.27-.221-.27H.22c-.12 0-.22.12-.22.27v18.57c0 .15.1.27.22.27h3.137c.12 0 .22-.12.22-.27v-3.79c0-.08.03-.16.08-.21l2.826-2.796c.07-.07.16-.08.241-.03l7.546 5.551a8.9 8.9 0 0 0 4.018 1.493c.12.01.23-.11.23-.27V19.76c0-.14-.08-.25-.19-.26a5.8 5.8 0 0 1-2.355-.942l-6.533-4.73c-.14-.09-.15-.32-.03-.441"
		/>
	</svg>
{:else if cloudMark}
	<!-- Groq / Cerebras / Gemini / NVIDIA / Mistral — the vendors' own marks, from
	     @lobehub/icons-static-svg (MIT), the same set static/integrations/openai.svg came from.
	     Inline rather than vendored as files for the reason the kimi mark is: these are painted
	     with `fill="currentColor"` so each inherits its tile's brand tint (BRAND_TONE) and reads
	     in both themes, which an <img> with a baked fill cannot do. -->
	<svg viewBox="0 0 24 24" fill="currentColor" fill-rule="evenodd" clip-rule="evenodd" class={className} aria-hidden="true">
		{#each cloudMark as d}
			<path {d} />
		{/each}
	</svg>
{:else if name === 'cloud-api' || name === 'openrouter'}
	<!-- Generic cloud-API fallback: a cloud + key, drawn by us. Used for a provider whose own
	     mark we don't have — never an approximated lookalike of a vendor logo. OpenRouter lands
	     here deliberately: no official mark ships with this repo, and it keeps its own tile tint
	     (BRAND_TONE.openrouter) so it stays distinguishable in the list. Move it up into
	     CLOUD_MARKS the day the real path is vendored in. -->
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" class={className} aria-hidden="true">
		<path d="M7 15.5a3.5 3.5 0 0 1 .3-6.99A5 5 0 0 1 17 8.6a3.45 3.45 0 0 1 2.2 5.6" />
		<circle cx="10.5" cy="18" r="2.2" />
		<path d="M12.6 17.4H19M17.4 17.4v1.9M19 17.4v2.4" />
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
