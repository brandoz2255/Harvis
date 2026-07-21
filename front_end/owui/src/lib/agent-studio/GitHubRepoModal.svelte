<script lang="ts">
	import { getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import {
		getGithubStatus,
		getGithubStartUrl,
		disconnectGithub,
		listUserGithubRepos,
		getRepoBranches,
		type GitHubStatus,
		type GitHubRepoItem
	} from '$lib/apis/agent-runs';

	const i18n: any = getContext('i18n');

	export let show = false;
	// owner, repo, chosen branch → create a clone-mode session from this GitHub repo on that branch.
	export let onPick: (owner: string, name: string, branch?: string) => void = () => {};

	let status: GitHubStatus = { connected: false };
	let statusUnknown = false; // the status check failed — don't claim "not connected"
	let repos: GitHubRepoItem[] = [];
	let loadingRepos = false;
	let search = '';
	let connectError = '';
	let pollTimer: any = null;

	// manual public-repo entry (works without connecting)
	let owner = '';
	let name = '';

	// Phase 2: branch selection. After picking a repo we fetch its DETECTED branches and let the
	// user choose which one (worktree) to work in, instead of silently using the default.
	let selectedRepo: { owner: string; name: string } | null = null;
	let branchList: string[] = [];
	let chosenBranch = '';
	let loadingBranches = false;

	// null = couldn't check. Keep the last known status rather than silently downgrading
	// the user to "not connected" because a request failed.
	const refreshStatus = async () => {
		const s = await getGithubStatus();
		statusUnknown = !s;
		if (s) {
			status = s;
			if (s.connected) loadRepos();
		}
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
		selectedRepo = null;
		refreshStatus();
	}
	$: if (!show) {
		openedFor = false;
		selectedRepo = null;
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
			// s === null means the check failed; keep polling (the attempt cap bounds it)
			// rather than concluding "still not connected".
			const s = await getGithubStatus();
			if (s?.connected || tries > 60) {
				if (s) {
					status = s;
					statusUnknown = false;
				}
				if (pollTimer) {
					clearInterval(pollTimer);
					pollTimer = null;
				}
				if (s?.connected) loadRepos();
			}
		}, 2000);
	};

	const disconnect = async () => {
		const ok = await disconnectGithub();
		if (ok) {
			repos = [];
			status = { connected: false };
		} else {
			// Honest failure: the credential may still be live server-side — keep the
			// connected state rather than claiming a disconnect that didn't happen.
			toast.error($i18n.t("Couldn't disconnect GitHub — the connection is still active. Try again."));
			refreshStatus();
		}
	};

	const close = () => (show = false);

	// Phase 1 → 2: pick a repo, then detect its branches so the user can choose the worktree.
	const openBranchPicker = async (o: string, n: string, preferred = '') => {
		if (!o.trim() || !n.trim()) return;
		selectedRepo = { owner: o.trim(), name: n.trim() };
		branchList = [];
		chosenBranch = '';
		loadingBranches = true;
		const res = await getRepoBranches(selectedRepo.owner, selectedRepo.name);
		branchList = res.branches || [];
		chosenBranch = preferred || res.default_branch || branchList[0] || '';
		loadingBranches = false;
	};
	const backToRepos = () => {
		selectedRepo = null;
		branchList = [];
		chosenBranch = '';
	};
	const confirmBranch = () => {
		if (!selectedRepo) return;
		onPick(selectedRepo.owner, selectedRepo.name, (chosenBranch || '').trim() || undefined);
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
				<span class="text-sm font-semibold text-gray-800 dark:text-gray-100">
					{selectedRepo ? $i18n.t('Choose a branch') : $i18n.t('Clone a GitHub repository')}
				</span>
				<div class="flex-1"></div>
				{#if status.connected && !selectedRepo}
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
				{#if selectedRepo}
					<!-- Phase 2: branch (worktree) selection -->
					<button
						class="text-[11px] text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 flex items-center gap-1"
						on:click={backToRepos}
					>
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="size-3"><path d="M15 18l-6-6 6-6" stroke-linecap="round" stroke-linejoin="round" /></svg>
						{$i18n.t('Back to repos')}
					</button>
					<div class="flex items-center gap-2 text-sm text-gray-700 dark:text-gray-200">
						<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" class="size-4 shrink-0 text-gray-400"><path d="M6 3v12a3 3 0 0 0 3 3h9M6 15a3 3 0 0 0 3 3h9M6 3a3 3 0 0 0 0 6h12" stroke-linecap="round" stroke-linejoin="round" /></svg>
						<span class="font-medium truncate">{selectedRepo.owner}/{selectedRepo.name}</span>
					</div>
					<div>
						<div class="text-[10px] uppercase tracking-wide text-gray-400 mb-1.5">{$i18n.t('Branch')}</div>
						{#if loadingBranches}
							<div class="text-xs text-gray-400 py-2">{$i18n.t('Detecting branches…')}</div>
						{:else if branchList.length}
							<select
								bind:value={chosenBranch}
								class="w-full px-3 py-2 text-xs rounded-lg border border-gray-200 dark:border-gray-700 dark:bg-gray-850 text-gray-700 dark:text-gray-200 outline-none"
							>
								{#each branchList as b}
									<option value={b}>{b}</option>
								{/each}
							</select>
							<div class="text-[10px] text-gray-400 mt-1.5">
								{branchList.length}
								{branchList.length === 1 ? $i18n.t('branch detected') : $i18n.t('branches detected')} · {$i18n.t('the agent works on a copy of this branch')}
							</div>
						{:else}
							<!-- Fallback: no branches detected (private repo w/o token, or API blocked) → type one. -->
							<input
								bind:value={chosenBranch}
								placeholder={$i18n.t('branch (e.g. main)')}
								class="w-full px-3 py-2 text-xs rounded-lg border border-gray-200 dark:border-gray-700 dark:bg-gray-850"
							/>
							<div class="text-[10px] text-amber-600 dark:text-amber-400 mt-1.5">
								{$i18n.t("Couldn't detect branches — connect GitHub for private repos, or type the branch name.")}
							</div>
						{/if}
					</div>
				{:else}
					<!-- Phase 1: repo selection -->
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
									on:click={() => openBranchPicker(r.owner, r.name, r.default_branch)}
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
								{#if statusUnknown}
									<!-- Failed check ≠ not connected. Offer Retry before pushing them to re-connect. -->
									{$i18n.t("Couldn't check your GitHub connection.")}
									<button
										type="button"
										class="ml-1 text-blue-600 dark:text-blue-400 hover:underline"
										on:click={refreshStatus}>{$i18n.t('Retry')}</button
									>
								{:else}
									{$i18n.t('Connect GitHub to browse + clone your private repos and open pull requests.')}
								{/if}
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
								class="w-1/3 px-2 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-700 dark:bg-gray-850"
							/>
							<span class="text-gray-400 text-xs">/</span>
							<input
								bind:value={name}
								placeholder="repo"
								class="flex-1 px-2 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-700 dark:bg-gray-850"
							/>
						</div>
						<div class="text-[10px] text-gray-400 mt-1.5 leading-relaxed">
							{$i18n.t('Clone-mode: the agent works on a copy; review the diff or open a PR. Your repo is untouched.')}
						</div>
					</div>
				{/if}
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
				{#if selectedRepo}
					<button
						class="text-xs px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 transition"
						disabled={loadingBranches || !chosenBranch.trim()}
						on:click={confirmBranch}
						>{$i18n.t('Clone')} · {chosenBranch || '…'}</button
					>
				{:else}
					<button
						class="text-xs px-3 py-1.5 rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 transition"
						disabled={!owner.trim() || !name.trim()}
						on:click={() => openBranchPicker(owner, name)}>{$i18n.t('Next: choose branch')}</button
					>
				{/if}
			</div>
		</div>
	</div>
{/if}
