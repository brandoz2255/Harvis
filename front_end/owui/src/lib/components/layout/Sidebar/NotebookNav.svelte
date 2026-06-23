<script lang="ts">
	// Harvis: the Open Notebook navigation, lifted out of the embedded open-notebook
	// app's right-hand AppSidebar and into the Harvis (OWUI) left sidebar. Each item
	// drives the /harvis/notebooks iframe via the `?onb=` query param, so the iframe
	// content runs full-width (the app's own AppSidebar is no longer rendered).
	// Mirrors AppSidebar's groups/items; colors are Harvis theme tokens.
	import { goto } from '$app/navigation';

	export let activeOnb: string = '';

	const GROUPS = [
		{
			title: 'Collect',
			items: [
				{
					name: 'Sources',
					href: '/sources',
					d: 'M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2zM14 2v6h6M16 13H8M16 17H8M10 9H8'
				}
			]
		},
		{
			title: 'Process',
			items: [
				{
					name: 'Notebooks',
					href: '/notebooks',
					d: 'M4 19.5A2.5 2.5 0 0 1 6.5 17H20M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z'
				},
				{
					name: 'Ask & Search',
					href: '/search',
					d: 'M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.35-4.35'
				}
			]
		},
		{
			title: 'Create',
			items: [
				{
					name: 'Podcasts',
					href: '/podcasts',
					d: 'M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3zM19 10v2a7 7 0 0 1-14 0v-2M12 19v3'
				}
			]
		},
		{
			title: 'Manage',
			items: [
				{
					name: 'Models',
					href: '/settings/api-keys',
					d: 'M4 4h16v16H4zM9 9h6v6H9zM9 2v2M15 2v2M9 20v2M15 20v2M20 9h2M20 14h2M2 9h2M2 14h2'
				},
				{
					name: 'Transformations',
					href: '/transformations',
					d: 'M16 3h5v5M4 20 21 3M21 16v5h-5M15 15l6 6M4 4l5 5'
				},
				{
					name: 'Settings',
					href: '/settings',
					d: 'M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6'
				},
				{
					name: 'Advanced',
					href: '/advanced',
					d: 'M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.83 2.83-2.12-2.12 2.83-2.83z'
				}
			]
		}
	];

	const isActive = (href: string) =>
		href === '/notebooks' ? activeOnb === '' || activeOnb === '/notebooks' : activeOnb === href;

	const open = (href: string) => goto('/harvis/notebooks?onb=' + encodeURIComponent(href));
</script>

<div class="flex flex-col px-[0.4375rem]">
	{#each GROUPS as group}
		<div class="mt-1.5 first:mt-0">
			<div
				class="px-2.5 pt-1 pb-0.5 text-[0.625rem] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500"
			>
				{group.title}
			</div>
			{#each group.items as item}
				<button
					type="button"
					on:click={() => open(item.href)}
					aria-current={isActive(item.href) ? 'page' : undefined}
					class="w-full flex items-center gap-3 rounded-2xl px-2.5 py-2 text-sm transition outline-none {isActive(
						item.href
					)
						? 'bg-gray-100 dark:bg-gray-900 text-gray-900 dark:text-gray-50 font-medium'
						: 'text-gray-700 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-900'}"
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
		</div>
	{/each}
</div>
