<script lang="ts">
	import dayjs from 'dayjs';
	import relativeTime from 'dayjs/plugin/relativeTime';
	dayjs.extend(relativeTime);

	import { toast } from 'svelte-sonner';
	import { onMount, getContext, tick, onDestroy } from 'svelte';
	const i18n = getContext('i18n');

	import { WEBUI_NAME, knowledge, user } from '$lib/stores';
	import {
		deleteKnowledgeById,
		searchKnowledgeBases,
		exportKnowledgeById
	} from '$lib/apis/knowledge';

	import { goto } from '$app/navigation';
	import { capitalizeFirstLetter } from '$lib/utils';

	import DeleteConfirmDialog from '../common/ConfirmDialog.svelte';
	import ItemMenu from './Knowledge/ItemMenu.svelte';
	import Badge from '../common/Badge.svelte';
	import Search from '../icons/Search.svelte';
	import Plus from '../icons/Plus.svelte';
	import Spinner from '../common/Spinner.svelte';
	import Skeleton from '../common/Skeleton.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import XMark from '../icons/XMark.svelte';
	import ViewSelector from './common/ViewSelector.svelte';
	import Loader from '../common/Loader.svelte';

	let loaded = false;
	let showDeleteConfirm = false;
	let tagsContainerElement: HTMLDivElement;

	let selectedItem = null;

	let page = 1;
	let query = '';
	let searchDebounceTimer: ReturnType<typeof setTimeout>;
	let viewOption = '';

	let items = null;
	let total = null;

	let allItemsLoaded = false;
	let itemsLoading = false;
	let loadError = ''; // list fetch failure — error branch with Retry, so the skeleton can't loop forever

	$: if (query !== undefined) {
		clearTimeout(searchDebounceTimer);
		searchDebounceTimer = setTimeout(() => {
			init();
		}, 300);
	}

	onDestroy(() => {
		clearTimeout(searchDebounceTimer);
	});

	$: if (viewOption !== undefined) {
		init();
	}

	const reset = () => {
		page = 1;
		items = null;
		total = null;
		allItemsLoaded = false;
		itemsLoading = false;
	};

	const loadMoreItems = async () => {
		if (allItemsLoaded) return;
		page += 1;
		const res = await getItemsPage();
		if (!res) {
			page -= 1; // failed page — retry it next time instead of silently skipping it
		}
	};

	const init = async () => {
		if (!loaded) return;

		reset();
		await getItemsPage();
	};

	const getItemsPage = async () => {
		itemsLoading = true;
		loadError = '';

		// Robust to both helper behaviors: a thrown error (has detail) and a
		// silent null return (network-level failure with no detail).
		let res = null;
		try {
			res = await searchKnowledgeBases(localStorage.token, query, viewOption, page);
		} catch (e) {
			console.error(e);
			loadError = `${e}`;
		}

		if (res && Array.isArray(res.items)) {
			console.log(res);
			total = res.total;
			const pageItems = res.items;

			if ((pageItems ?? []).length === 0) {
				allItemsLoaded = true;
			} else {
				allItemsLoaded = false;
			}

			if (items) {
				const existingIds = new Set(items.map((item) => item.id));
				const newItems = pageItems.filter((item) => !existingIds.has(item.id));
				items = [...items, ...newItems];
			} else {
				items = pageItems;
			}
		} else if (!loadError) {
			loadError = $i18n.t('Server connection failed');
		}

		itemsLoading = false;
		return loadError ? null : res;
	};

	const deleteHandler = async (item) => {
		const res = await deleteKnowledgeById(localStorage.token, item.id).catch((e) => {
			toast.error(`${e}`);
		});

		if (res) {
			toast.success($i18n.t('Knowledge deleted successfully.'));
			init();
		}
	};

	const exportHandler = async (item) => {
		try {
			const blob = await exportKnowledgeById(localStorage.token, item.id);
			if (blob) {
				const url = URL.createObjectURL(blob);
				const a = document.createElement('a');
				a.href = url;
				a.download = `${item.name}.zip`;
				document.body.appendChild(a);
				a.click();
				document.body.removeChild(a);
				URL.revokeObjectURL(url);
				toast.success($i18n.t('Knowledge exported successfully'));
			}
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	onMount(async () => {
		viewOption = localStorage?.workspaceViewOption || '';
		loaded = true;
	});
</script>

<svelte:head>
	<title>
		{$i18n.t('Knowledge')} • {$WEBUI_NAME}
	</title>
</svelte:head>

{#if loaded}
	<DeleteConfirmDialog
		bind:show={showDeleteConfirm}
		on:confirm={() => {
			deleteHandler(selectedItem);
		}}
	/>

	<div class="flex flex-col gap-1 px-1 mt-1.5 mb-3">
		<div class="flex justify-between items-center">
			<div class="flex items-center md:self-center text-xl font-medium px-0.5 gap-2 shrink-0">
				<div>
					{$i18n.t('Knowledge')}
				</div>

				<div class="text-lg font-medium text-gray-500 dark:text-gray-500">
					{total}
				</div>
			</div>

			<div class="flex w-full justify-end gap-1.5">
				<a
					class=" px-2 py-1.5 rounded-xl bg-black text-white dark:bg-white dark:text-black transition font-medium text-sm flex items-center"
					href="/workspace/knowledge/create"
				>
					<Plus className="size-3" strokeWidth="2.5" />

					<div class=" hidden md:block md:ml-1 text-xs">{$i18n.t('New Knowledge')}</div>
				</a>
			</div>
		</div>
	</div>

	<div
		class="py-2 bg-white dark:bg-gray-900 rounded-3xl border border-gray-100/30 dark:border-gray-850/30"
	>
		<div class=" flex w-full space-x-2 py-0.5 px-3.5 pb-2">
			<div class="flex flex-1">
				<div class=" self-center ml-1 mr-3">
					<Search className="size-3.5" />
				</div>
				<input
					class=" w-full text-sm py-1 rounded-r-xl outline-hidden bg-transparent"
					bind:value={query}
					aria-label={$i18n.t('Search Knowledge')}
					placeholder={$i18n.t('Search Knowledge')}
				/>
				{#if query}
					<div class="self-center pl-1.5 translate-y-[0.5px] rounded-l-xl bg-transparent">
						<button
							class="p-0.5 rounded-full hover:bg-gray-100 dark:hover:bg-gray-900 transition"
							aria-label={$i18n.t('Clear search')}
							on:click={() => {
								query = '';
							}}
						>
							<XMark className="size-3" strokeWidth="2" />
						</button>
					</div>
				{/if}
			</div>
		</div>

		<div
			class="px-3 flex w-full bg-transparent overflow-x-auto scrollbar-none -mx-1"
			on:wheel={(e) => {
				if (e.deltaY !== 0) {
					e.preventDefault();
					e.currentTarget.scrollLeft += e.deltaY;
				}
			}}
		>
			<div
				class="flex gap-0.5 w-fit text-center text-sm rounded-full bg-transparent px-1.5 whitespace-nowrap"
				bind:this={tagsContainerElement}
			>
				<ViewSelector
					bind:value={viewOption}
					onChange={async (value) => {
						localStorage.workspaceViewOption = value;

						await tick();
					}}
				/>
			</div>
		</div>

		{#if items !== null && total !== null}
			{#if (items ?? []).length !== 0}
				<div class=" my-2 px-3 grid grid-cols-1 lg:grid-cols-2 gap-2">
					{#each items as item}
						<button
							class=" flex space-x-4 cursor-pointer text-left w-full px-3 py-2.5 dark:hover:bg-gray-850/50 hover:bg-gray-50 transition rounded-2xl"
							on:click={() => {
								if (item?.meta?.document) {
									toast.error(
										$i18n.t(
											'Only collections can be edited, create a new knowledge base to edit/add documents.'
										)
									);
								} else {
									goto(`/workspace/knowledge/${item.id}`);
								}
							}}
						>
							<div class=" w-full">
								<div class=" self-center flex-1 justify-between">
									<div class="flex items-center justify-between -my-1 h-8">
										<div class=" flex gap-2 items-center justify-between w-full">
											<div>
												<Badge type="success" content={$i18n.t('Collection')} />
											</div>

											{#if !item?.write_access}
												<div>
													<Badge type="muted" content={$i18n.t('Read Only')} />
												</div>
											{/if}
										</div>

										{#if item?.write_access || $user?.role === 'admin'}
											<div class="flex items-center gap-2">
												<div class=" flex self-center">
													<ItemMenu
														onExport={$user.role === 'admin'
															? () => {
																	exportHandler(item);
																}
															: null}
														on:delete={() => {
															selectedItem = item;
															showDeleteConfirm = true;
														}}
													/>
												</div>
											</div>
										{/if}
									</div>

									<div class=" flex items-center gap-1 justify-between px-1.5">
										<Tooltip content={item?.description ?? item.name}>
											<div class=" flex items-center gap-2">
												<div class=" text-sm font-medium line-clamp-1 capitalize">{item.name}</div>
											</div>
										</Tooltip>

										<div class="flex items-center gap-2 shrink-0">
											<Tooltip content={dayjs(item.updated_at * 1000).format('LLLL')}>
												<div class=" text-xs text-gray-500 line-clamp-1 hidden sm:block">
													{$i18n.t('Updated')}
													{dayjs(item.updated_at * 1000).fromNow()}
												</div>
											</Tooltip>

											<div class="text-xs text-gray-500 shrink-0">
												<Tooltip
													content={item?.user?.email ?? $i18n.t('Deleted User')}
													className="flex shrink-0"
													placement="top-start"
												>
													{$i18n.t('By {{name}}', {
														name: capitalizeFirstLetter(
															item?.user?.name ?? item?.user?.email ?? $i18n.t('Deleted User')
														)
													})}
												</Tooltip>
											</div>
										</div>
									</div>
								</div>
							</div>
						</button>
					{/each}
				</div>

				{#if !allItemsLoaded}
					{#if loadError}
						<!-- Load-more failure: an idle "Loading..." spinner here would be a lie,
						     and the Loader would auto-retry against a broken server on scroll. -->
						<div class="w-full flex justify-center py-4 text-xs items-center gap-2 text-gray-500">
							{$i18n.t('Could not load more')}
							<button
								class="text-blue-600 dark:text-blue-400 hover:underline"
								on:click={() => {
									loadMoreItems();
								}}>{$i18n.t('Retry')}</button
							>
						</div>
					{:else}
						<Loader
							on:visible={(e) => {
								if (!itemsLoading) {
									loadMoreItems();
								}
							}}
						>
							<div class="w-full flex justify-center py-4 text-xs animate-pulse items-center gap-2">
								<Spinner className=" size-4" />
								<div class=" ">{$i18n.t('Loading...')}</div>
							</div>
						</Loader>
					{/if}
				{/if}
			{:else}
				<div class=" w-full h-full flex flex-col justify-center items-center my-16 mb-24">
					<div class="max-w-md text-center">
						<div class=" text-3xl mb-3">😕</div>
						<div class=" text-lg font-medium mb-1">{$i18n.t('No knowledge found')}</div>
						<div class=" text-gray-500 text-center text-xs">
							{$i18n.t('Try adjusting your search or filter to find what you are looking for.')}
						</div>
					</div>
				</div>
			{/if}
		{:else if loadError}
			<!-- Honest list-fetch failure: without this, `items` stays null and the
			     skeleton below would shimmer forever. -->
			<div class="px-3 my-2">
				<div
					class="rounded-xl border border-gray-100 dark:border-gray-850 px-3 py-6 text-center text-sm text-gray-500"
				>
					{$i18n.t('Could not load knowledge')} — {loadError}
					<button
						class="ml-2 text-blue-600 dark:text-blue-400 hover:underline"
						on:click={() => {
							init();
						}}>{$i18n.t('Retry')}</button
					>
				</div>
			</div>
		{:else}
			<!-- Skeleton mirrors the knowledge card grid: 2-col rounded-2xl cards with a
			     Collection badge row, name line, and updated/by meta line. -->
			<div class="my-2 px-3 grid grid-cols-1 lg:grid-cols-2 gap-2" aria-busy="true">
				<div aria-hidden="true" class="contents">
					{#each Array.from({ length: 4 }) as _, i}
						<div class="w-full px-3 py-2.5 rounded-2xl">
							<div class="flex items-center h-8 -my-1">
								<Skeleton width="4.5rem" height="1.125rem" rounded="rounded-full" delay={i * 90} />
							</div>
							<div class="flex items-center justify-between px-1.5 mt-1">
								<Skeleton width={['38%', '52%', '30%', '44%'][i]} height="0.875rem" delay={i * 90} />
								<Skeleton width="7rem" height="0.625rem" delay={i * 90} />
							</div>
						</div>
					{/each}
				</div>
				<span class="sr-only" role="status">{$i18n.t('Loading knowledge…')}</span>
			</div>
		{/if}
	</div>

	<div class=" text-gray-500 text-xs m-2">
		ⓘ {$i18n.t("Use '#' in the prompt input to load and include your knowledge.")}
	</div>
{:else}
	<!-- Cold-load skeleton for the whole page: title bar, then the same card grid. -->
	<div class="px-1 mt-1.5" aria-busy="true">
		<div aria-hidden="true">
			<div class="flex items-center justify-between mb-3 px-0.5">
				<Skeleton width="8rem" height="1.25rem" />
				<Skeleton width="6.5rem" height="1.75rem" rounded="rounded-xl" />
			</div>
			<div class="grid grid-cols-1 lg:grid-cols-2 gap-2 px-2">
				{#each Array.from({ length: 6 }) as _, i}
					<div class="w-full px-3 py-2.5 rounded-2xl">
						<div class="flex items-center h-8 -my-1">
							<Skeleton width="4.5rem" height="1.125rem" rounded="rounded-full" delay={i * 90} />
						</div>
						<div class="flex items-center justify-between px-1.5 mt-1">
							<Skeleton width={['38%', '52%', '30%', '44%', '48%', '34%'][i]} height="0.875rem" delay={i * 90} />
							<Skeleton width="7rem" height="0.625rem" delay={i * 90} />
						</div>
					</div>
				{/each}
			</div>
		</div>
		<span class="sr-only" role="status">{$i18n.t('Loading knowledge…')}</span>
	</div>
{/if}
