<script lang="ts">
	// Project detail — a project's chats, its custom instructions, and a
	// "New chat in this project" action that attaches the next chat to it.
	import { getContext, onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import { WEBUI_NAME, selectedFolder } from '$lib/stores';
	import { getFolderById, updateFolderById, deleteFolderById } from '$lib/apis/folders';
	import { getChatsByFolderId } from '$lib/apis/chats';
	import FolderModal from '$lib/components/layout/Sidebar/Folders/FolderModal.svelte';

	const i18n: any = getContext('i18n');

	let token = '';
	let folder: any = null;
	let chats: any[] = [];
	let loading = true;
	let showEdit = false;

	$: folderId = $page.params.id;

	const rel = (iso?: string | number) => {
		if (iso == null) return '';
		const t = typeof iso === 'number' ? iso * (iso < 1e12 ? 1000 : 1) : Date.parse(iso);
		if (isNaN(t)) return '';
		const s = Math.max(1, Math.floor((Date.now() - t) / 1000));
		if (s < 60) return $i18n.t('just now');
		const m = Math.floor(s / 60);
		if (m < 60) return $i18n.t('{{n}}m ago', { n: m });
		const h = Math.floor(m / 60);
		if (h < 24) return $i18n.t('{{n}}h ago', { n: h });
		const d = Math.floor(h / 24);
		if (d < 7) return $i18n.t('{{n}}d ago', { n: d });
		return $i18n.t('{{n}}w ago', { n: Math.floor(d / 7) });
	};

	const load = async () => {
		loading = true;
		folder = await getFolderById(token, folderId).catch(() => null);
		chats = (await getChatsByFolderId(token, folderId).catch(() => [])) ?? [];
		chats = chats.sort((a, b) => (b.updated_at ?? 0) - (a.updated_at ?? 0));
		loading = false;
	};

	const newChatInProject = () => {
		if (folder) selectedFolder.set(folder);
		goto('/');
	};

	const saveEdit = async (form: any) => {
		const res = await updateFolderById(token, folderId, {
			name: form?.name,
			data: form?.data,
			meta: form?.meta
		}).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		if (res) {
			showEdit = false;
			await load();
		}
	};

	let deleting = false;
	const deleteProject = async () => {
		if (deleting) return;
		if (
			!confirm(
				$i18n.t('Delete this project? Its chats are kept and moved out of the project.')
			)
		)
			return;
		deleting = true;
		await deleteFolderById(token, folderId, false).catch((e) => toast.error(`${e}`));
		goto('/harvis/projects');
	};

	onMount(async () => {
		token = localStorage.getItem('token') || '';
		load();
	});
</script>

<svelte:head>
	<title>{folder?.name ?? $i18n.t('Project')} • {$WEBUI_NAME}</title>
</svelte:head>

{#if showEdit}
	<FolderModal bind:show={showEdit} {folderId} edit={true} onSubmit={saveEdit} />
{/if}

<div class="w-full h-full overflow-y-auto">
	<div class="max-w-4xl mx-auto px-5 py-6 space-y-6">
		<!-- Header -->
		<header>
			<button
				class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
				on:click={() => goto('/harvis/projects')}>← {$i18n.t('Projects')}</button
			>
			<div class="flex items-center justify-between gap-3 mt-2">
				<div class="flex items-center gap-2.5 min-w-0">
					<svg class="size-6 text-blue-500 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" /></svg>
					<h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-100 truncate">
						{folder?.name ?? $i18n.t('Project')}
					</h1>
				</div>
				<div class="flex items-center gap-2 shrink-0">
					<button
						on:click={deleteProject}
						disabled={deleting}
						class="rounded-lg border border-gray-200 dark:border-gray-800 px-3 py-1.5 text-sm text-gray-500 hover:text-red-500 hover:border-red-300 dark:hover:border-red-800 transition disabled:opacity-40"
						>{$i18n.t('Delete')}</button
					>
					<button
						on:click={() => (showEdit = true)}
						class="rounded-lg border border-gray-200 dark:border-gray-800 px-3 py-1.5 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
						>{$i18n.t('Edit')}</button
					>
					<button
						on:click={newChatInProject}
						class="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 text-white px-3.5 py-1.5 text-sm font-medium hover:bg-blue-700 transition"
					>
						<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
						{$i18n.t('New chat')}
					</button>
				</div>
			</div>
		</header>

		<!-- Custom instructions -->
		{#if folder?.data?.system_prompt}
			<section class="rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4">
				<div class="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-1.5">
					{$i18n.t('Custom instructions')}
				</div>
				<p class="text-sm text-gray-700 dark:text-gray-200 whitespace-pre-wrap">{folder.data.system_prompt}</p>
			</section>
		{/if}

		<!-- Chats -->
		<section>
			<div class="text-sm font-medium text-gray-800 dark:text-gray-100 mb-2">
				{$i18n.t('Chats')} <span class="text-gray-400">({chats.length})</span>
			</div>
			{#if loading}
				<div class="py-10 flex justify-center text-gray-400">
					<svg class="size-5 animate-spin" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2.5" opacity="0.25" /><path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" /></svg>
				</div>
			{:else if chats.length === 0}
				<div class="rounded-xl border border-dashed border-gray-200 dark:border-gray-800 p-6 text-center text-sm text-gray-500">
					{$i18n.t('No chats in this project yet.')}
					<button on:click={newChatInProject} class="block mx-auto mt-2 text-blue-600 dark:text-blue-400 hover:underline">{$i18n.t('Start one')} →</button>
				</div>
			{:else}
				<div class="rounded-2xl border border-gray-100 dark:border-gray-850 divide-y divide-gray-100 dark:divide-gray-850 overflow-hidden">
					{#each chats as c (c.id)}
						<a
							href={`/c/${c.id}`}
							class="flex items-center justify-between gap-3 px-4 py-2.5 hover:bg-gray-50 dark:hover:bg-gray-900 transition group"
						>
							<span class="truncate text-sm text-gray-700 dark:text-gray-200 group-hover:text-blue-600 dark:group-hover:text-blue-400 transition">{c.title || $i18n.t('Untitled')}</span>
							<span class="text-xs text-gray-400 shrink-0">{rel(c.updated_at)}</span>
						</a>
					{/each}
				</div>
			{/if}
		</section>
	</div>
</div>
