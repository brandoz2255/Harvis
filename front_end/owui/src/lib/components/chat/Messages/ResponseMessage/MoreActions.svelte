<script lang="ts">
	import { getContext } from 'svelte';

	import Dropdown from '$lib/components/common/Dropdown.svelte';
	import Sparkles from '$lib/components/icons/Sparkles.svelte';

	const i18n = getContext('i18n');

	// The four everyday actions stay on the row; everything else lives here, so a
	// response footer is five icons wide instead of a dozen.
	export let items: {
		id: string;
		label: string;
		icon?: string;
		iconUrl?: string;
		onClick: () => void;
	}[] = [];

	let show = false;
</script>

{#if items.length > 0}
	<Dropdown bind:show align="end" sideOffset={-2}>
		<slot></slot>

		<div slot="content">
			<div
				class="min-w-[180px] rounded-xl px-1 py-1 border border-gray-100 dark:border-gray-800 z-50 bg-white dark:bg-gray-850 dark:text-white shadow-lg transition"
			>
				{#each items as item (item.id)}
					<button
						class="select-none flex gap-2 items-center px-3 py-1.5 text-sm cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800 rounded-lg w-full"
						on:click={() => {
							item.onClick();
							show = false;
						}}
					>
						<div class="size-4 shrink-0">
							{#if item.icon === 'edit'}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="2"
									aria-hidden="true"
									stroke="currentColor"
									class="w-4 h-4"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L6.832 19.82a4.5 4.5 0 01-1.897 1.13l-2.685.8.8-2.685a4.5 4.5 0 011.13-1.897L16.863 4.487zm0 0L19.5 7.125"
									/>
								</svg>
							{:else if item.icon === 'branch'}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="2"
									stroke="currentColor"
									aria-hidden="true"
									class="w-4 h-4"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M6.75 3.75a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0ZM6.75 20.25a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0ZM20.25 6.75a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0Z"
									/>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M5.25 5.25v12M6.75 18c4.5 0 6.75-3 6.75-6.75V8.25h3"
									/>
								</svg>
							{:else if item.icon === 'stop-speaking'}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									aria-hidden="true"
									stroke-width="2"
									stroke="currentColor"
									class="w-4 h-4"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M17.25 9.75 19.5 12m0 0 2.25 2.25M19.5 12l2.25-2.25M19.5 12l-2.25 2.25m-10.5-6 4.72-4.72a.75.75 0 0 1 1.28.53v15.88a.75.75 0 0 1-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.009 9.009 0 0 1 2.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75Z"
									/>
								</svg>
							{:else if item.icon === 'speak'}
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									aria-hidden="true"
									stroke-width="2"
									stroke="currentColor"
									class="w-4 h-4"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M19.114 5.636a9 9 0 010 12.728M16.463 8.288a5.25 5.25 0 010 7.424M6.75 8.25l4.72-4.72a.75.75 0 011.28.53v15.88a.75.75 0 01-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.01 9.01 0 012.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75z"
									/>
								</svg>
							{:else if item.icon === 'continue'}
								<svg
									aria-hidden="true"
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="2"
									stroke="currentColor"
									class="w-4 h-4"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
									/>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M15.91 11.672a.375.375 0 0 1 0 .656l-5.603 3.113a.375.375 0 0 1-.557-.328V8.887c0-.286.307-.466.557-.327l5.603 3.112Z"
									/>
								</svg>
							{:else if item.icon === 'info'}
								<svg
									aria-hidden="true"
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="2"
									stroke="currentColor"
									class="w-4 h-4"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										d="M11.25 11.25l.041-.02a.75.75 0 011.063.852l-.708 2.836a.75.75 0 001.063.853l.041-.021M21 12a9 9 0 11-18 0 9 9 0 0118 0zm-9-3.75h.008v.008H12V8.25z"
									/>
								</svg>
							{:else if item.iconUrl}
								<img
									src={item.iconUrl}
									class="w-4 h-4 {item.iconUrl.includes('data:image/svg') ? 'dark:invert-[80%]' : ''}"
									style="fill: currentColor;"
									alt={item.label}
									draggable="false"
								/>
							{:else}
								<Sparkles strokeWidth="2" className="size-4" />
							{/if}
						</div>
						<div class="flex items-center line-clamp-1">{item.label}</div>
					</button>
				{/each}
			</div>
		</div>
	</Dropdown>
{/if}
