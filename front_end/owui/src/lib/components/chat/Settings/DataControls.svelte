<script lang="ts">
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import {
		chatId,
		chats,
		user,
		settings,
		scrollPaginationEnabled,
		currentChatPage,
		pinnedChats
	} from '$lib/stores';

	import {
		archiveAllChats,
		deleteAllChats,
		getAllChats,
		getChatList,
		getPinnedChatList,
		importChats
	} from '$lib/apis/chats';
	import { getImportOrigin, convertOpenAIChats } from '$lib/utils';
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import ArchivedChatsModal from '$lib/components/layout/ArchivedChatsModal.svelte';
	import SharedChatsModal from '$lib/components/layout/SharedChatsModal.svelte';
	import FilesModal from '$lib/components/layout/FilesModal.svelte';
	import ConfirmDialog from '$lib/components/common/ConfirmDialog.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import SettingRow from './SettingRow.svelte';

	const i18n = getContext('i18n');

	// HONESTY GATES: the Harvis owui_compat facade does not implement these
	// routes yet (see python_back_end/owui_compat/router.py):
	//   POST   /api/v1/chats/import       → Import Chats
	//   GET    /api/v1/chats/all          → Export Chats (falls into /chats/{chat_id} → 404)
	//   GET    /api/v1/chats/shared       → Shared Chats list
	//   POST   /api/v1/chats/archive/all  → Archive All Chats
	//   DELETE /api/v1/chats/             → Delete All Chats
	//   GET    /api/v1/files/search       → Manage Files (FilesModal listing)
	// Those controls would fail (some silently) on every click, so they are
	// disabled with a note until the routes land. GET /api/v1/chats/archived
	// exists, so Archived Chats stays enabled.
	const CHAT_IMPORT_AVAILABLE = false;
	const CHAT_EXPORT_AVAILABLE = false;
	const SHARED_CHATS_AVAILABLE = false;
	const ARCHIVE_ALL_AVAILABLE = false;
	const DELETE_ALL_AVAILABLE = false;
	const FILES_MODAL_AVAILABLE = false;

	export let saveSettings: Function;

	// Chats
	let importFiles;

	let showArchiveConfirmDialog = false;
	let showDeleteConfirmDialog = false;
	let showArchivedChatsModal = false;
	let showSharedChatsModal = false;
	let showFilesModal = false;

	let chatImportInputElement: HTMLInputElement;

	$: if (importFiles) {
		console.log(importFiles);

		let reader = new FileReader();
		reader.onload = (event) => {
			let chats = JSON.parse(event.target.result);
			console.log(chats);
			if (getImportOrigin(chats) == 'openai') {
				try {
					chats = convertOpenAIChats(chats);
				} catch (error) {
					console.log('Unable to import chats:', error);
				}
			}
			importChatsHandler(chats);
		};

		if (importFiles.length > 0) {
			reader.readAsText(importFiles[0]);
		}
	}

	const importChatsHandler = async (_chats) => {
		const res = await importChats(
			localStorage.token,
			_chats.map((chat) => {
				if (chat.chat) {
					return {
						chat: chat.chat,
						meta: chat.meta ?? {},
						pinned: false,
						folder_id: chat?.folder_id ?? null,
						created_at: chat?.created_at ?? null,
						updated_at: chat?.updated_at ?? null
					};
				} else {
					// Legacy format
					return {
						chat: chat,
						meta: {},
						pinned: false,
						folder_id: null,
						created_at: chat?.created_at ?? null,
						updated_at: chat?.updated_at ?? null
					};
				}
			})
		);
		if (res) {
			toast.success(`Successfully imported ${res.length} chats.`);
		}

		currentChatPage.set(1);
		await chats.set(await getChatList(localStorage.token, $currentChatPage));
		pinnedChats.set(await getPinnedChatList(localStorage.token));
		scrollPaginationEnabled.set(true);
	};

	const exportChats = async () => {
		let blob = new Blob([JSON.stringify(await getAllChats(localStorage.token))], {
			type: 'application/json'
		});
		saveAs(blob, `chat-export-${Date.now()}.json`);
	};

	const archiveAllChatsHandler = async () => {
		await goto('/');
		await archiveAllChats(localStorage.token).catch((error) => {
			toast.error(`${error}`);
		});

		currentChatPage.set(1);
		await chats.set(await getChatList(localStorage.token, $currentChatPage));
		pinnedChats.set([]);
		scrollPaginationEnabled.set(true);
	};

	const deleteAllChatsHandler = async () => {
		await goto('/');
		await deleteAllChats(localStorage.token).catch((error) => {
			toast.error(`${error}`);
		});

		currentChatPage.set(1);
		await chats.set(await getChatList(localStorage.token, $currentChatPage));
		scrollPaginationEnabled.set(true);
	};

	const handleArchivedChatsChange = async () => {
		currentChatPage.set(1);
		await chats.set(await getChatList(localStorage.token, $currentChatPage));

		scrollPaginationEnabled.set(true);
	};
</script>

<ArchivedChatsModal
	bind:show={showArchivedChatsModal}
	onUpdate={handleArchivedChatsChange}
	onDelete={(id) => {
		if ($chatId === id) {
			goto('/');
			chatId.set('');
		}
	}}
/>
<SharedChatsModal bind:show={showSharedChatsModal} />
<FilesModal bind:show={showFilesModal} />

<ConfirmDialog
	title={$i18n.t('Archive All Chats')}
	message={$i18n.t('Are you sure you want to archive all chats? This action cannot be undone.')}
	bind:show={showArchiveConfirmDialog}
	on:confirm={archiveAllChatsHandler}
	on:cancel={() => {
		showArchiveConfirmDialog = false;
	}}
/>

<ConfirmDialog
	title={$i18n.t('Delete All Chats')}
	message={$i18n.t('Are you sure you want to delete all chats? This action cannot be undone.')}
	bind:show={showDeleteConfirmDialog}
	on:confirm={deleteAllChatsHandler}
	on:cancel={() => {
		showDeleteConfirmDialog = false;
	}}
/>

<div id="tab-chats" class="flex flex-col h-full justify-between text-sm">
	<div class="space-y-3 overflow-y-scroll max-h-[28rem] md:max-h-full">
		<input
			id="chat-import-input"
			bind:this={chatImportInputElement}
			bind:files={importFiles}
			type="file"
			accept=".json"
			hidden
		/>

		<div>
			<div class="pb-1 text-lg font-semibold text-gray-900 dark:text-gray-100">{$i18n.t('Chats')}</div>

			<SettingRow description={$i18n.t('Restore chats from a previously exported JSON file.')}>
				<svelte:fragment slot="title">
					<div>{$i18n.t('Import Chats')}</div>
				</svelte:fragment>
				<Tooltip
					content={CHAT_IMPORT_AVAILABLE ? '' : $i18n.t('Not available in this deployment')}
				>
					<button
						class="px-3 py-1.5 text-sm font-medium rounded-[10px] bg-gray-100 hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800 text-gray-800 dark:text-gray-100 flex transition {CHAT_IMPORT_AVAILABLE
							? ''
							: 'opacity-50 cursor-not-allowed'}"
						disabled={!CHAT_IMPORT_AVAILABLE}
						on:click={() => {
							chatImportInputElement.click();
						}}
						type="button"
					>
						<span class="self-center">{$i18n.t('Import')}</span>
					</button>
				</Tooltip>
			</SettingRow>

			{#if $user?.role === 'admin' || ($user.permissions?.chat?.export ?? true)}
				<SettingRow description={$i18n.t('Download all of your chats as a JSON file.')}>
					<svelte:fragment slot="title">
						<div>{$i18n.t('Export Chats')}</div>
					</svelte:fragment>
					<Tooltip
						content={CHAT_EXPORT_AVAILABLE ? '' : $i18n.t('Not available in this deployment')}
					>
						<button
							class="px-3 py-1.5 text-sm font-medium rounded-[10px] bg-gray-100 hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800 text-gray-800 dark:text-gray-100 flex transition {CHAT_EXPORT_AVAILABLE
								? ''
								: 'opacity-50 cursor-not-allowed'}"
							disabled={!CHAT_EXPORT_AVAILABLE}
							on:click={() => {
								exportChats();
							}}
							type="button"
						>
							<span class="self-center">{$i18n.t('Export')}</span>
						</button>
					</Tooltip>
				</SettingRow>
			{/if}

			<SettingRow description={$i18n.t('View and manage the chats you have archived.')}>
				<svelte:fragment slot="title">
					<div>{$i18n.t('Archived Chats')}</div>
				</svelte:fragment>
				<button
					class="px-3 py-1.5 text-sm font-medium rounded-[10px] bg-gray-100 hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800 text-gray-800 dark:text-gray-100 flex transition"
					on:click={() => {
						showArchivedChatsModal = true;
					}}
					type="button"
				>
					<span class="self-center">{$i18n.t('Manage')}</span>
				</button>
			</SettingRow>

			<SettingRow description={$i18n.t('Manage your shared chats.')}>
				<svelte:fragment slot="title">
					<div>{$i18n.t('Shared Chats')}</div>
				</svelte:fragment>
				<Tooltip
					content={SHARED_CHATS_AVAILABLE ? '' : $i18n.t('Not available in this deployment')}
				>
					<button
						class="px-3 py-1.5 text-sm font-medium rounded-[10px] bg-gray-100 hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800 text-gray-800 dark:text-gray-100 flex transition {SHARED_CHATS_AVAILABLE
							? ''
							: 'opacity-50 cursor-not-allowed'}"
						disabled={!SHARED_CHATS_AVAILABLE}
						on:click={() => {
							showSharedChatsModal = true;
						}}
						type="button"
					>
						<span class="self-center">{$i18n.t('Manage')}</span>
					</button>
				</Tooltip>
			</SettingRow>

			<SettingRow description={$i18n.t('Move every chat to the archive.')}>
				<svelte:fragment slot="title">
					<div>{$i18n.t('Archive All Chats')}</div>
				</svelte:fragment>
				<Tooltip
					content={ARCHIVE_ALL_AVAILABLE ? '' : $i18n.t('Not available in this deployment')}
				>
					<button
						class="px-3 py-1.5 text-sm font-medium rounded-[10px] bg-gray-100 hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800 text-gray-800 dark:text-gray-100 flex transition {ARCHIVE_ALL_AVAILABLE
							? ''
							: 'opacity-50 cursor-not-allowed'}"
						disabled={!ARCHIVE_ALL_AVAILABLE}
						on:click={() => {
							showArchiveConfirmDialog = true;
						}}
						type="button"
					>
						<span class="self-center">{$i18n.t('Archive All')}</span>
					</button>
				</Tooltip>
			</SettingRow>

			<SettingRow description={$i18n.t('Permanently delete every chat. This cannot be undone.')}>
				<svelte:fragment slot="title">
					<div>{$i18n.t('Delete All Chats')}</div>
				</svelte:fragment>
				<Tooltip
					content={DELETE_ALL_AVAILABLE ? '' : $i18n.t('Not available in this deployment')}
				>
					<button
						class="px-3 py-1.5 text-sm font-medium rounded-[10px] bg-gray-100 hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800 text-gray-800 dark:text-gray-100 flex transition {DELETE_ALL_AVAILABLE
							? ''
							: 'opacity-50 cursor-not-allowed'}"
						disabled={!DELETE_ALL_AVAILABLE}
						on:click={() => {
							showDeleteConfirmDialog = true;
						}}
						type="button"
					>
						<span class="self-center">{$i18n.t('Delete All')}</span>
					</button>
				</Tooltip>
			</SettingRow>
		</div>

		<div>
			<div class="pt-6 pb-1 text-lg font-semibold text-gray-900 dark:text-gray-100">{$i18n.t('Files')}</div>

			<SettingRow description={$i18n.t('Browse and manage your uploaded files.')}>
				<svelte:fragment slot="title">
					<div>{$i18n.t('Manage Files')}</div>
				</svelte:fragment>
				<Tooltip
					content={FILES_MODAL_AVAILABLE ? '' : $i18n.t('Not available in this deployment')}
				>
					<button
						class="px-3 py-1.5 text-sm font-medium rounded-[10px] bg-gray-100 hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800 text-gray-800 dark:text-gray-100 flex transition {FILES_MODAL_AVAILABLE
							? ''
							: 'opacity-50 cursor-not-allowed'}"
						disabled={!FILES_MODAL_AVAILABLE}
						on:click={() => {
							showFilesModal = true;
						}}
						type="button"
					>
						<span class="self-center">{$i18n.t('Manage')}</span>
					</button>
				</Tooltip>
			</SettingRow>
		</div>
	</div>
</div>
