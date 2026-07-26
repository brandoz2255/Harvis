<script lang="ts">
	// Harvis Notebook-mode sidebar. Actions (New notebook · Sources · Ask & Search ·
	// Transformations · Customize) + the user's Recent notebooks. The onb sub-nav items
	// drive the /harvis/notebooks iframe via the `?onb=` query param; Customize routes to
	// the Agent Studio Customize surface. Recents open the notebook in the iframe
	// (?onb=/notebooks/{id}). Colors are Harvis theme tokens.
	import { getContext, onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { listNotebooksDetailed, type Notebook } from '$lib/apis/notebooks';

	export let activeOnb: string = '';

	const i18n: any = getContext('i18n');

	let notebooks: Notebook[] = [];
	// Honest failure state for Recents: '' = ok; otherwise a short reason so an
	// expired session / down backend doesn't masquerade as "No notebooks yet."
	let recentsError = '';
	let timer: any = null;
	const load = async () => {
		const res = await listNotebooksDetailed();
		if (res.ok) {
			notebooks = res.notebooks;
			recentsError = '';
		} else {
			recentsError =
				res.status === 401 || res.status === 403
					? $i18n.t('Signed out — sign in to see recents.')
					: `${$i18n.t("Couldn't load recents")} (${res.error ?? 'error'}).`;
		}
	};
	const schedule = () => {
		timer = setTimeout(async () => {
			await load();
			schedule();
		}, 30000);
	};
	onMount(async () => {
		await load();
		schedule();
	});
	onDestroy(() => clearTimeout(timer));

	// Open-Notebook sub-nav (drives the iframe via ?onb=).
	const ONB = [
		{
			name: 'Sources',
			href: '/sources',
			d: 'M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2zM14 2v6h6M16 13H8M16 17H8M10 9H8'
		},
		{
			name: 'Ask & Search',
			href: '/search',
			d: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35'
		},
		{
			name: 'Transformations',
			href: '/transformations',
			d: 'M16 3h5v5M4 20 21 3M21 16v5h-5M15 15l6 6M4 4l5 5'
		}
	];

	const isActive = (href: string) => activeOnb === href;
	const open = (href: string) => goto('/harvis/notebooks?onb=' + encodeURIComponent(href));
	const openNotebook = (id: string) =>
		goto('/harvis/notebooks?onb=' + encodeURIComponent('/notebooks/' + id));
	const isNotebookActive = (id: string) => activeOnb === '/notebooks/' + id;
</script>

<div class="flex flex-col px-[0.4375rem]">
	<!-- New notebook -->
	<button
		type="button"
		on:click={() => open('/notebooks')}
		class="group flex items-center gap-3 rounded-xl px-2.5 py-2 text-blue-600 dark:text-blue-400 font-medium hover:bg-blue-500/10 transition outline-none"
		aria-label={$i18n.t('New notebook')}
	>
		<div class="self-center">
			<svg
				xmlns="http://www.w3.org/2000/svg"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
				class="size-4.5"
			>
				<path d="M12 5v14M5 12h14" />
			</svg>
		</div>
		<div class="flex flex-1 self-center translate-y-[0.5px]">
			<div class="self-center text-sm font-primary">{$i18n.t('New notebook')}</div>
		</div>
	</button>

	<!-- Sources · Ask & Search · Transformations (onb iframe) -->
	{#each ONB as item}
		<button
			type="button"
			on:click={() => open(item.href)}
			aria-current={isActive(item.href) ? 'page' : undefined}
			class="w-full flex items-center gap-3 rounded-xl px-2.5 py-2 text-sm transition outline-none {isActive(
				item.href
			)
				? 'bg-blue-500/10 text-blue-600 dark:text-blue-400 font-medium'
				: 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850'}"
		>
			<svg
				xmlns="http://www.w3.org/2000/svg"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="1.8"
				stroke-linecap="round"
				stroke-linejoin="round"
				class="size-4.5 shrink-0"
			>
				<path d={item.d} />
			</svg>
			<span class="self-center translate-y-[0.5px] truncate">{item.name}</span>
		</button>
	{/each}

	<!-- Recent notebooks -->
	<div
		class="px-2.5 pt-3 pb-1 text-[0.625rem] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500"
	>
		{$i18n.t('Recents')}
	</div>
	{#if recentsError}
		<div class="px-2.5 py-1 text-xs text-gray-500 dark:text-gray-400">
			<span>{recentsError}</span>
			<button
				type="button"
				on:click={load}
				class="ml-1 text-blue-600 dark:text-blue-400 hover:underline"
			>
				{$i18n.t('Retry')}
			</button>
		</div>
	{:else if !notebooks.length}
		<div class="px-2.5 py-1 text-xs text-gray-400">{$i18n.t('No notebooks yet.')}</div>
	{:else}
		{#each notebooks as nb (nb.id)}
			<button
				type="button"
				on:click={() => openNotebook(nb.id)}
				aria-current={isNotebookActive(nb.id) ? 'page' : undefined}
				class="w-full flex items-center gap-3 rounded-xl px-2.5 py-1.5 text-sm transition outline-none {isNotebookActive(
					nb.id
				)
					? 'bg-gray-100 dark:bg-gray-850 text-gray-900 dark:text-gray-50 font-medium'
					: 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850'}"
			>
				<span class="shrink-0 w-4 text-center">{nb.emoji || '📓'}</span>
				<span class="flex-1 overflow-hidden whitespace-nowrap name-fade text-left translate-y-[0.5px]"
					>{nb.title || $i18n.t('Untitled')}</span
				>
			</button>
		{/each}
	{/if}
</div>
