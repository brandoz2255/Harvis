<script lang="ts">
	// Projects homepage — lists every project (OWUI folder) by its given name.
	// Replaces the old collapsible Projects section in the sidebar. Click a
	// project → its detail page; New Project → the shared FolderModal.
	import { getContext, onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import { WEBUI_NAME, chatId } from '$lib/stores';
	import { getFolders, createNewFolder } from '$lib/apis/folders';
	import { getChatsByFolderId } from '$lib/apis/chats';
	import FolderModal from '$lib/components/layout/Sidebar/Folders/FolderModal.svelte';

	const i18n: any = getContext('i18n');
	const backToChat = () => goto($chatId ? `/c/${$chatId}` : '/');

	let token = '';
	let projects: any[] = [];
	let counts: Record<string, number> = {};
	let loading = true;
	let showCreate = false;

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
		const f = await getFolders(token).catch(() => []);
		projects = (f ?? [])
			.filter((x: any) => !x.parent_id)
			.sort((a: any, b: any) => (b.updated_at ?? 0) - (a.updated_at ?? 0));
		loading = false;
		for (const p of projects) {
			getChatsByFolderId(token, p.id)
				.then((c) => (counts = { ...counts, [p.id]: (c ?? []).length }))
				.catch(() => {});
		}
	};

	const createProject = async (form: any) => {
		const res = await createNewFolder(token, {
			name: form?.name,
			data: form?.data,
			meta: form?.meta,
			parent_id: form?.parent_id ?? null
		}).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		if (res) {
			showCreate = false;
			await load();
		}
	};

	onMount(async () => {
		token = localStorage.getItem('token') || '';
		load();
	});
</script>

<svelte:head>
	<title>{$i18n.t('Projects')} • {$WEBUI_NAME}</title>
</svelte:head>

<FolderModal bind:show={showCreate} onSubmit={createProject} />

<div class="w-full h-full overflow-y-auto">
	<div class="max-w-5xl mx-auto px-5 py-6 space-y-6">
		<!-- Header -->
		<header class="flex items-end justify-between gap-3">
			<div>
				<button
					class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
					on:click={backToChat}>← {$i18n.t('Back to chat')}</button
				>
				<h1 class="text-2xl font-semibold text-gray-800 dark:text-gray-100 mt-2">
					{$i18n.t('Projects')}
				</h1>
				<p class="text-sm text-gray-500 mt-1">
					{$i18n.t('Group chats with shared instructions and knowledge. Each project keeps its own context.')}
				</p>
			</div>
			<button
				on:click={() => (showCreate = true)}
				class="inline-flex items-center gap-1.5 rounded-full bg-blue-600 text-white px-3.5 py-2 text-sm font-medium hover:bg-blue-700 transition shrink-0"
			>
				<svg class="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg>
				{$i18n.t('New Project')}
			</button>
		</header>

		{#if loading}
			<div class="py-16 flex justify-center text-gray-400">
				<svg class="size-6 animate-spin" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="9" stroke="currentColor" stroke-width="2.5" opacity="0.25" /><path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" /></svg>
			</div>
		{:else if projects.length === 0}
			<div
				class="rounded-2xl border border-dashed border-gray-200 dark:border-gray-800 p-10 text-center"
			>
				<div class="text-sm text-gray-500">{$i18n.t('No projects yet.')}</div>
				<button
					on:click={() => (showCreate = true)}
					class="mt-3 text-sm text-blue-600 dark:text-blue-400 hover:underline"
					>{$i18n.t('Create your first project')} →</button
				>
			</div>
		{:else}
			<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
				{#each projects as p (p.id)}
					<button
						type="button"
						on:click={() => goto(`/harvis/projects/${p.id}`)}
						class="text-left rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900 p-4 hover:border-blue-500/40 transition flex flex-col gap-2 min-h-[7rem]"
					>
						<div class="flex items-center gap-2 min-w-0">
							<svg class="size-5 text-blue-500 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" /></svg>
							<div class="truncate text-sm font-semibold text-gray-800 dark:text-gray-100">{p.name}</div>
						</div>
						{#if p.data?.system_prompt}
							<div class="text-xs text-gray-500 line-clamp-2 flex-1">{p.data.system_prompt}</div>
						{:else}
							<div class="text-xs text-gray-400 italic flex-1">{$i18n.t('No custom instructions yet.')}</div>
						{/if}
						<div class="flex items-center gap-2 text-[11px] text-gray-400">
							<span>{counts[p.id] ?? 0} {$i18n.t('chats')}</span>
							{#if p.updated_at}<span>· {rel(p.updated_at)}</span>{/if}
						</div>
					</button>
				{/each}
			</div>
		{/if}
	</div>
</div>
