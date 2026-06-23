<script lang="ts">
	import { getContext } from 'svelte';
	import {
		getGithubStatus,
		getGithubStartUrl,
		disconnectGithub,
		listUserGithubRepos,
		type GitHubStatus,
		type GitHubRepoItem
	} from '$lib/apis/agent-runs';

	const i18n: any = getContext('i18n');

	export let show = false;
	// owner, repo, optional branch → create a clone-mode session from this GitHub repo.
	export let onPick: (owner: string, name: string, branch?: string) => void = () => {};

	let status: GitHubStatus = { connected: false };
	let repos: GitHubRepoItem[] = [];
	let loadingRepos = false;
	let search = '';
	let connectError = '';
	let pollTimer: any = null;

	// manual public-repo entry (works without connecting)
	let owner = '';
	let name = '';
	let branch = '';

	const refreshStatus = async () => {
		status = await getGithubStatus();
		if (status.connected) loadRepos();
	};
	const loadRepos = async () => {
		loadingRepos = true;
		repos = await listUserGithubRepos();
		loadingRepos = false;
	};

	let openedFor = false;
	$: if (show && !openedFor) {
		openedFor = true;
		connectError = '';
		refreshStatus();
	}
	$: if (!show) {
		openedFor = false;
		if (pollTimer) {
			clearInterval(pollTimer);
			pollTimer = null;
		}
	}

	const connect = async () => {
		connectError = '';
		const res = await getGithubStartUrl();
		if (!res.ok || !res.redirect) {
			connectError =
				res.error ||
				$i18n.t('GitHub OAuth is not configured on this server. You can still clone a public repo below.');
			return;
		}
		window.open(res.redirect, '_blank', 'noopener');
		if (pollTimer) clearInterval(pollTimer);
		let tries = 0;
		pollTimer = setInterval(async () => {
			tries++;
			const s = await getGithubStatus();
			if (s.connected || tries > 60) {
				status = s;
				if (pollTimer) {
					clearInterval(pollTimer);
					pollTimer = null;
				}
				if (s.connected) loadRepos();
			}
		}, 2000);
	};

	const disconnect = async () => {
		await disconnectGithub();
		repos = [];
		status = { connected: false };
	};

	const close = () => (show = false);
	const pick = (o: string, n: string, b?: string) => {
		if (!o.trim() || !n.trim()) return;
		onPick(o.trim(), n.trim(), (b || '').trim() || undefined);
		show = false;
	};

	$: filtered = search.trim()
		? repos.filter((r) => r.full_name.toLowerCase().includes(search.trim().toLowerCase()))
		: repos;
</script>

{#if show}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
		role="presentation"
		on:click|self={close}
	>
		<div
			class="w-full max-w-lg max-h-[80vh] flex flex-col rounded-2xl bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 shadow-xl"
		>
			<!-- header -->
			<div
				class="flex items-center gap-2 px-4 py-3 border-b border-gray-100 dark:border-gray-850 shrink-0"
			>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="size-4 text-gray-700 dark:text-gray-200"><path d="M12 2C6.48 2 2 6.48 2 12c0 4.42 2.87 8.17 6.84 9.5.5.09.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.45-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.6.07-.6 1 .07 1.53 1.03 1.53 1.03.89 1.52 2.34 1.08 2.91.83.09-.65.35-1.08.63-1.33-2.22-.25-4.55-1.11-4.55-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02a9.56 9.56 0 0 1 5 0c1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.69-4.57 4.94.36.31.68.92.68 1.85v2.74c0 .27.18.58.69.48A10 10 0 0 0 22 12c0-5.52-4.48-10-10-10z" /></svg>
				<span class="text-sm font-semibold text-gray-800 dark:text-gray-100"
					>{$i18n.t('Clone a GitHub repository')}</span
				>
				<div class="flex-1"></div>
				{#if status.connected}
					<span class="text-[11px] text-gray-500 dark:text-gray-400 flex items-center gap-1.5">
						{#if status.avatar_url}<img src={status.avatar_url} alt="" class="size-4 rounded-full" />{/if}
						{status.login}
						<button class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 underline" on:click={disconnect}
							>{$i18n.t('Disconnect')}</button
						>
					</span>
				{/if}
				<button
					class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
					on:click={close}
					aria-label="Close"
				>
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-4"><path d="M6 6l12 12M18 6L6 18" stroke-linecap="round" /></svg>
				</button>
			</div>

			<div class="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
				{#if status.connected}
					<input
						bind:value={search}
						placeholder={$i18n.t('Search your repositories…')}
						class="w-full px-3 py-2 text-xs rounded-lg border border-gray-200 dark:border-gray-700 dark:bg-gray-850"
					/>
					{#if loadingRepos}
						<div class="text-xs text-gray-400 text-center py-4">{$i18n.t('Loading…')}</div>
					{:else if !filtered.length}
						<div class="text-xs text-gray-400 text-center py-4">{$i18n.t('No repositories found.')}</div>
					{:else}
						{#each filtered.slice(0, 100) as r (r.full_name)}
							<button
								class="w-full flex items-center gap-2 px-2 py-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 text-left"
								on:click={() => pick(r.owner, r.name, r.default_branch)}
							>
								<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-4 shrink-0 text-gray-400"><path d="M6 3v12a3 3 0 0 0 3 3h9M6 15a3 3 0 0 0 3 3h9M6 3a3 3 0 0 0 0 6h12" stroke-linecap="round" stroke-linejoin="round" /></svg>
								<span class="text-xs text-gray-700 dark:text-gray-200 truncate flex-1">{r.full_name}</span>
								{#if r.private}
									<span class="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-500 shrink-0">private</span>
								{/if}
							</button>
						{/each}
					{/if}
				{:else}
					<div class="rounded-lg border border-gray-100 dark:border-gray-800 p-3 text-center space-y-2">
						<p class="text-xs text-gray-500 dark:text-gray-400">
							{$i18n.t('Connect GitHub to browse + clone your private repos and open pull requests.')}
						</p>
						<button
							class="px-3 py-1.5 text-xs rounded-lg bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 hover:opacity-90"
							on:click={connect}>{$i18n.t('Connect GitHub')}</button
						>
						{#if connectError}
							<p class="text-[11px] text-amber-600 dark:text-amber-400">{connectError}</p>
						{/if}
					</div>
				{/if}

				<!-- always available: clone a public repo by name (no connection needed) -->
				<div class="border-t border-gray-100 dark:border-gray-850 pt-3">
					<div class="text-[10px] uppercase tracking-wide text-gray-400 mb-1.5">
						{$i18n.t('Or clone a public repo')}
					</div>
					<div class="flex items-center gap-1.5">
						<input
							bind:value={owner}
							placeholder="owner"
							class="w-1/4 px-2 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-700 dark:bg-gray-850"
						/>
						<span class="text-gray-400 text-xs">/</span>
						<input
							bind:value={name}
							placeholder="repo"
							class="flex-1 px-2 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-700 dark:bg-gray-850"
						/>
						<input
							bind:value={branch}
							placeholder={$i18n.t('branch')}
							class="w-24 px-2 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-700 dark:bg-gray-850"
						/>
					</div>
					<div class="text-[10px] text-gray-400 mt-1.5 leading-relaxed">
						{$i18n.t('Clone-mode: the agent works on a copy; review the diff or open a PR. Your repo is untouched.')}
					</div>
				</div>
			</div>

			<!-- footer -->
			<div
				class="flex items-center gap-2 px-4 py-3 border-t border-gray-100 dark:border-gray-850 shrink-0"
			>
				<div class="flex-1"></div>
				<button
					class="text-xs px-3 py-1.5 rounded-lg text-gray-500 hover:text-gray-700 dark:hover:text-gray-200"
					on:click={close}>{$i18n.t('Cancel')}</button
				>
				<button
					class="text-xs px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 transition"
					disabled={!owner.trim() || !name.trim()}
					on:click={() => pick(owner, name, branch)}>{$i18n.t('Clone repo')}</button
				>
			</div>
		</div>
	</div>
{/if}
