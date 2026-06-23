<script lang="ts">
	import { getContext } from 'svelte';
	import { page } from '$app/stores';
	import { WEBUI_NAME, showSidebar } from '$lib/stores';

	const i18n: any = getContext('i18n');

	// Open Notebook is the vendored open-notebook Next.js app served at /onb. We embed
	// it in an iframe INSIDE the Harvis shell. Same-origin → it shares the Harvis JWT
	// (localStorage.token) and talks to the onb_compat facade at /onb-api.
	//
	// The open-notebook nav now lives in the Harvis left sidebar (NotebookNav), which
	// drives this iframe via the `?onb=` query param (e.g. ?onb=/sources → /onb/sources).
	// Default (no param) = the notebooks home. The app's own AppSidebar is not rendered,
	// so the iframe content runs full-width.
	$: onbPath = $page.url.searchParams.get('onb') ?? '';
	$: iframeSrc = `/onb${onbPath}`;
</script>

<svelte:head>
	<title>{$i18n.t('Open Notebook')} • {$WEBUI_NAME}</title>
</svelte:head>

<div class="w-full h-full {$showSidebar ? 'md:max-w-[calc(100%-var(--sidebar-width))]' : ''}">
	<iframe
		src={iframeSrc}
		title={$i18n.t('Open Notebook')}
		class="w-full h-full border-0 block"
		allow="clipboard-read; clipboard-write; microphone"
	></iframe>
</div>
