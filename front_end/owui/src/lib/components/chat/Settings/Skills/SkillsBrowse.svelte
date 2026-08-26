<script lang="ts" context="module">
	// Module-level session caches — collections are re-visited within a settings
	// session without re-hitting the unauthenticated GitHub API (60 req/hr).
	const repoCache = new Map<string, any>(); // "owner/repo" → { branch, license, truncated, entries }
	const mdCache = new Map<string, string>(); // raw SKILL.md URL → text
</script>

<script lang="ts">
	// Browse skills — in-panel multi-source browse + import surface
	// (Settings › Customize › Skills › Browse). Everything is fetched live and
	// client-side from the GitHub API + raw.githubusercontent.com (both send
	// CORS headers); nothing here fabricates skills, counts, or licenses.
	//
	// SAFETY CONTRACT: browsing is free, but installing imports ONLY the
	// SKILL.md text as a DRAFT via createNewSkill — scripts in a skill bundle
	// are never downloaded or executed, and the backend strips client-sent
	// meta.audit on create, so an import can never arrive pre-"supported".
	import { getContext, tick } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { parseFrontmatter, formatSkillName } from '$lib/utils';
	import { createNewSkill } from '$lib/apis/skills';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Markdown from '$lib/components/chat/Messages/Markdown.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import XMark from '$lib/components/icons/XMark.svelte';
	import Github from '$lib/components/icons/Github.svelte';
	import Document from '$lib/components/icons/Document.svelte';
	import SkillsBrowseSection from './SkillsBrowseSection.svelte';

	export let token = '';
	export let onBack: () => void = () => {};
	// Mounts that already provide their own way back (the Skills surface's
	// Your skills | Directory tabs) hide this to avoid duplicate navigation.
	export let showBack = true;
	export let onInstalled: (skill: any) => void = () => {};

	const i18n: any = getContext('i18n');

	// The five real seed collections — loaded lazily, one pill at a time.
	const COLLECTIONS = [
		{ label: 'Anthropic', owner: 'anthropics', repo: 'skills' },
		{ label: 'Block / Goose', owner: 'block', repo: 'agent-skills' },
		{ label: 'Hugging Face', owner: 'huggingface', repo: 'skills' },
		{ label: 'Microsoft', owner: 'MicrosoftDocs', repo: 'Agent-Skills' },
		{ label: 'NVIDIA', owner: 'NVIDIA', repo: 'skills' }
	];
	const PAGE = 10; // rows revealed per "Load more" (frontmatter fetched per visible row)

	let tab: 'collections' | 'url' = 'collections';
	let searchQuery = '';

	// Per-repo UI state: "owner/repo" → { status, error, rateLimited, truncated, entries }
	let repoStates: Record<string, any> = {};
	let openKeys: string[] = []; // collections the user opened, in click order
	let visibleCounts: Record<string, number> = {};

	// ── URL tab ─────────────────────────────────────────────────────────────
	let urlInput = '';
	let urlLoading = false;
	let urlError = '';
	let urlRepoKey = ''; // set when a plain repo URL was loaded → section in URL tab

	// ── Preview ─────────────────────────────────────────────────────────────
	let preview: any = null; // { entry, content, loading, error, viewMode, fm }
	let previewTriggerEl: HTMLElement | null = null;
	let installing = false;

	const keyOf = (owner: string, repo: string) => `${owner}/${repo}`;
	const rawUrlOf = (e: any) =>
		`https://raw.githubusercontent.com/${e.owner}/${e.repo}/${encodeURIComponent(e.branch)}/` +
		(e.dir ? e.dir.split('/').map(encodeURIComponent).join('/') + '/' : '') +
		'SKILL.md';
	const canonicalUrl = (e: any) =>
		`https://github.com/${e.owner}/${e.repo}/tree/${e.branch}${e.dir ? `/${e.dir}` : ''}`;

	const ghJson = async (url: string) => {
		const res = await fetch(url, { headers: { Accept: 'application/vnd.github+json' } });
		if (!res.ok) {
			if (res.status === 403 || res.status === 429) {
				const err: any = new Error('GitHub API rate limit');
				err.rateLimit = true;
				throw err;
			}
			throw new Error(`GitHub API ${res.status}`);
		}
		return res.json();
	};

	// Load a repo: repo API (default_branch + license) → recursive tree →
	// "skill" = any directory containing a SKILL.md. Cached per session.
	const loadRepo = async (owner: string, repo: string) => {
		const key = keyOf(owner, repo);
		if (repoCache.has(key)) {
			repoStates = { ...repoStates, [key]: { status: 'ready', ...repoCache.get(key) } };
			return repoStates[key];
		}
		repoStates = { ...repoStates, [key]: { status: 'loading', entries: [] } };
		try {
			const info = await ghJson(`https://api.github.com/repos/${owner}/${repo}`);
			const branch = info.default_branch || 'main';
			const spdx = info?.license?.spdx_id;
			const license = spdx && spdx !== 'NOASSERTION' ? spdx : null;
			const tree = await ghJson(
				`https://api.github.com/repos/${owner}/${repo}/git/trees/${encodeURIComponent(branch)}?recursive=1`
			);
			const blobs = (tree.tree ?? []).filter((t: any) => t.type === 'blob');
			const dirs = blobs
				.filter((b: any) => b.path === 'SKILL.md' || b.path.endsWith('/SKILL.md'))
				.map((b: any) => (b.path === 'SKILL.md' ? '' : b.path.slice(0, -'/SKILL.md'.length)))
				.sort();
			const entries = dirs.map((dir: string) => {
				const prefix = dir ? `${dir}/` : '';
				const files = blobs
					.filter((b: any) => (dir ? b.path.startsWith(prefix) : true))
					.map((b: any) => (dir ? b.path.slice(prefix.length) : b.path));
				const extras = files.filter(
					(rel: string) => rel !== 'SKILL.md' && !rel.startsWith('references/')
				).length;
				return {
					key: `${key}/${dir}`,
					owner,
					repo,
					branch,
					dir,
					files,
					extras,
					license,
					fm: null,
					fmState: 'idle'
				};
			});
			const loaded = { branch, license, truncated: !!tree.truncated, entries };
			repoCache.set(key, loaded);
			repoStates = { ...repoStates, [key]: { status: 'ready', ...loaded } };
			return repoStates[key];
		} catch (e: any) {
			repoStates = {
				...repoStates,
				[key]: {
					status: 'error',
					rateLimited: !!e?.rateLimit,
					error: e?.message ?? `${e}`,
					entries: []
				}
			};
			throw e;
		}
	};

	const toggleCollection = (owner: string, repo: string) => {
		const key = keyOf(owner, repo);
		if (openKeys.includes(key)) {
			openKeys = openKeys.filter((k) => k !== key);
			return;
		}
		openKeys = [...openKeys, key];
		visibleCounts = { ...visibleCounts, [key]: visibleCounts[key] ?? PAGE };
		loadRepo(owner, repo).catch(() => {}); // error surfaced in the section
	};

	// Frontmatter (name/description) fetched on demand for visible rows only —
	// raw.githubusercontent.com fetches don't spend the API rate limit.
	const ensureFrontmatter = (entry: any) => {
		if (entry.fmState !== 'idle') return;
		entry.fmState = 'loading';
		const url = rawUrlOf(entry);
		(mdCache.has(url)
			? Promise.resolve(mdCache.get(url) as string)
			: fetch(url).then((r) => {
					if (!r.ok) throw new Error(`raw fetch ${r.status}`);
					return r.text();
				})
		)
			.then((text) => {
				mdCache.set(url, text);
				const fm: any = parseFrontmatter(text);
				entry.fm = { name: fm.name || '', description: fm.description || '' };
				entry.fmState = 'done';
			})
			.catch(() => {
				entry.fmState = 'error';
			})
			.finally(() => {
				repoStates = repoStates; // reflect the mutation
			});
	};

	const matchesSearch = (entry: any, q: string) =>
		!q ||
		entry.dir.toLowerCase().includes(q) ||
		(entry.fm?.name ?? '').toLowerCase().includes(q) ||
		(entry.fm?.description ?? '').toLowerCase().includes(q);

	const sectionFor = (key: string) => {
		const state = repoStates[key] ?? { status: 'idle', entries: [] };
		const q = searchQuery.trim().toLowerCase();
		const filtered = (state.entries ?? []).filter((e: any) => matchesSearch(e, q));
		const limit = visibleCounts[key] ?? PAGE;
		return {
			state,
			visible: filtered.slice(0, limit),
			hiddenCount: Math.max(0, filtered.length - limit)
		};
	};

	// Recompute sections when data / search / paging changes, and lazily fetch
	// frontmatter for whatever just became visible (fmState guard terminates it).
	$: sections = (searchQuery, visibleCounts, repoStates, openKeys.map((k) => [k, sectionFor(k)]));
	$: urlSection = (searchQuery, visibleCounts, repoStates, urlRepoKey ? sectionFor(urlRepoKey) : null);
	$: {
		for (const [, s] of sections) s.visible.forEach(ensureFrontmatter);
		urlSection?.visible.forEach(ensureFrontmatter);
	}

	// ── URL tab: repo URL · /tree/ · /blob/…SKILL.md · raw SKILL.md ────────
	const parseGithubUrl = (input: string): any => {
		let u: URL;
		try {
			u = new URL(input.trim());
		} catch {
			return { error: $i18n.t('That does not look like a URL.') };
		}
		const parts = u.pathname.split('/').filter(Boolean);
		if (u.hostname === 'github.com' || u.hostname === 'www.github.com') {
			if (parts.length < 2) return { error: $i18n.t('Expected a github.com/{owner}/{repo} URL.') };
			const [owner, repo] = parts;
			if (parts.length === 2) return { kind: 'repo', owner, repo: repo.replace(/\.git$/, '') };
			if ((parts[2] === 'tree' || parts[2] === 'blob') && parts.length >= 4) {
				const branch = decodeURIComponent(parts[3]);
				let rest = parts.slice(4).map(decodeURIComponent).join('/');
				if (parts[2] === 'blob') {
					if (!rest.endsWith('SKILL.md'))
						return { error: $i18n.t('A /blob/ URL must point at a SKILL.md file.') };
					rest = rest === 'SKILL.md' ? '' : rest.slice(0, -'/SKILL.md'.length);
				}
				return { kind: 'dir', owner, repo, branch, dir: rest };
			}
			return { error: $i18n.t('Unsupported github.com URL — use a repo, /tree/, or /blob/…SKILL.md link.') };
		}
		if (u.hostname === 'raw.githubusercontent.com') {
			if (parts.length >= 4) {
				const [owner, repo] = parts;
				let branch: string, rest: string;
				if (parts[2] === 'refs' && parts[3] === 'heads' && parts.length >= 6) {
					branch = decodeURIComponent(parts[4]);
					rest = parts.slice(5).map(decodeURIComponent).join('/');
				} else {
					branch = decodeURIComponent(parts[2]);
					rest = parts.slice(3).map(decodeURIComponent).join('/');
				}
				if (!rest.endsWith('SKILL.md'))
					return { error: $i18n.t('A raw URL must point at a SKILL.md file.') };
				const dir = rest === 'SKILL.md' ? '' : rest.slice(0, -'/SKILL.md'.length);
				return { kind: 'dir', owner, repo, branch, dir };
			}
			return { error: $i18n.t('Expected raw.githubusercontent.com/{owner}/{repo}/{branch}/…/SKILL.md.') };
		}
		return {
			error: $i18n.t(
				'Only github.com and raw.githubusercontent.com URLs are supported — other hosts would be blocked by the browser (CORS).'
			)
		};
	};

	const fetchFromUrl = async () => {
		if (urlLoading || !urlInput.trim()) return;
		urlError = '';
		urlRepoKey = '';
		const parsed = parseGithubUrl(urlInput);
		if (parsed.error) {
			urlError = parsed.error;
			return;
		}
		urlLoading = true;
		try {
			if (parsed.kind === 'repo') {
				await loadRepo(parsed.owner, parsed.repo);
				urlRepoKey = keyOf(parsed.owner, parsed.repo);
				visibleCounts = { ...visibleCounts, [urlRepoKey]: visibleCounts[urlRepoKey] ?? PAGE };
			} else {
				try {
					const state = await loadRepo(parsed.owner, parsed.repo);
					const entry = (state.entries ?? []).find((e: any) => e.dir === parsed.dir);
					if (!entry) {
						urlError = $i18n.t('No SKILL.md was found at that path in the repository.');
					} else {
						openPreview(entry, null);
					}
				} catch (e: any) {
					if (!e?.rateLimit) throw e;
					// API rate-limited, but raw fetches still work — degrade honestly:
					// preview the SKILL.md alone, with the file list marked unavailable.
					const synthetic = {
						key: `${keyOf(parsed.owner, parsed.repo)}/${parsed.dir}`,
						owner: parsed.owner,
						repo: parsed.repo,
						branch: parsed.branch,
						dir: parsed.dir,
						files: ['SKILL.md'],
						extras: 0,
						filesUnknown: true,
						license: null
					};
					const res = await fetch(rawUrlOf(synthetic));
					if (!res.ok) {
						urlError = $i18n.t('GitHub API rate limit reached — try again later or paste a URL.');
					} else {
						mdCache.set(rawUrlOf(synthetic), await res.text());
						openPreview(synthetic, null);
					}
				}
			}
		} catch (e: any) {
			urlError = e?.rateLimit
				? $i18n.t('GitHub API rate limit reached — try again later or paste a URL.')
				: `${e?.message ?? e}`;
		}
		urlLoading = false;
	};

	// ── Preview + install ───────────────────────────────────────────────────
	const openPreview = (entry: any, el: HTMLElement | null) => {
		previewTriggerEl = el;
		preview = { entry, content: null, loading: true, error: '', viewMode: 'rendered', fm: null };
		const url = rawUrlOf(entry);
		(mdCache.has(url)
			? Promise.resolve(mdCache.get(url) as string)
			: fetch(url).then((r) => {
					if (!r.ok) throw new Error(`SKILL.md fetch failed (${r.status})`);
					return r.text();
				})
		)
			.then((text) => {
				mdCache.set(url, text);
				if (!preview || preview.entry !== entry) return;
				preview = { ...preview, content: text, loading: false, fm: parseFrontmatter(text) };
			})
			.catch((e) => {
				if (!preview || preview.entry !== entry) return;
				preview = { ...preview, loading: false, error: `${e?.message ?? e}` };
			});
	};

	const closePreview = async () => {
		preview = null;
		installing = false;
		await tick();
		previewTriggerEl?.focus?.();
		previewTriggerEl = null;
	};

	const installDraft = async () => {
		if (!preview?.content || installing) return;
		installing = true;
		const fm: any = parseFrontmatter(preview.content);
		const fallback = preview.entry.dir ? preview.entry.dir.split('/').pop() : preview.entry.repo;
		// Import ONLY the SKILL.md text; meta.source = canonical GitHub URL as
		// provenance for the audit surface. Never audit/verdict fields (the
		// backend strips them on create anyway — imports are always unaudited).
		const res = await createNewSkill(token, {
			name: formatSkillName(fm.name || fallback || 'imported-skill'),
			description: fm.description || '',
			content: preview.content,
			meta: { source: canonicalUrl(preview.entry) }
		}).catch((e) => {
			toast.error(`${e}`);
			return null;
		});
		installing = false;
		if (res) {
			toast.success($i18n.t('Installed as draft — audit it before it can inject.'));
			onInstalled(res);
		}
	};

	const previewTitle = (): string => {
		const e = preview?.entry;
		return formatSkillName(
			preview?.fm?.name || (e?.dir ? e.dir.split('/').pop() : e?.repo) || ''
		);
	};
</script>

<!-- capture phase: runs before Modal.svelte's bubble-phase window Escape handler,
     and stopPropagation() from capture prevents it firing — so Escape closes ONLY
     the preview, not the whole Settings modal. -->
<svelte:window
	on:keydown|capture={(e) => {
		if (e.key === 'Escape' && preview) {
			e.stopPropagation();
			closePreview();
		}
	}}
/>

{#if preview}
	<!-- ── Preview: everything shown before anything is installed ── -->
	<div class="pt-1">
		<button
			class="-ml-1.5 inline-flex items-center gap-1 rounded-lg px-1.5 py-1 text-sm text-gray-500 hover:text-gray-800 dark:hover:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-900 transition"
			on:click={closePreview}
		>
			<ChevronLeft className="size-4" strokeWidth="2" />
			{$i18n.t('Browse')}
		</button>

		<div class="mt-2 flex items-start gap-2">
			<div class="min-w-0 flex-1">
				<h3 class="truncate text-xl font-semibold text-gray-800 dark:text-gray-100">
					{previewTitle()}
				</h3>
				<div class="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-gray-500">
					<a
						href={canonicalUrl(preview.entry)}
						target="_blank"
						rel="noopener noreferrer"
						class="inline-flex items-center gap-1 hover:text-gray-700 dark:hover:text-gray-300 hover:underline"
					>
						<Github className="size-3.5" />
						{preview.entry.owner}/{preview.entry.repo}{preview.entry.dir
							? ` · ${preview.entry.dir}`
							: ''}
					</a>
					<span>· {$i18n.t('License')}: {preview.entry.license ?? '—'}</span>
				</div>
			</div>
			<button
				class="shrink-0 rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-40 transition"
				disabled={!preview.content || installing}
				on:click={installDraft}
			>
				{installing ? $i18n.t('Installing…') : $i18n.t('Install as draft')}
			</button>
		</div>

		<p class="mt-1 text-xs text-gray-400">
			{$i18n.t(
				'Installs as an unaudited draft — a human "supported" audit verdict is required before it can inject in chats.'
			)}
		</p>

		{#if preview.loading}
			<div class="flex justify-center py-12">
				<Spinner className="size-5" />
			</div>
		{:else if preview.error}
			<div
				class="mt-3 rounded-xl border border-gray-100 dark:border-gray-850 px-3 py-6 text-center text-sm text-gray-500"
			>
				{$i18n.t('Could not fetch SKILL.md')} — {preview.error}
			</div>
		{:else}
			{#if !preview.entry.filesUnknown && preview.entry.extras > 0}
				<div
					class="mt-3 rounded-xl border border-gray-200 dark:border-gray-800 bg-gray-50 dark:bg-gray-900 px-3 py-2.5 text-xs text-gray-600 dark:text-gray-300"
				>
					{$i18n.t(
						'This skill bundle contains {{count}} extra file(s). Only the SKILL.md text is imported — scripts are NOT imported or executed.',
						{ count: preview.entry.extras }
					)}
				</div>
			{/if}

			<div
				class="mt-3 overflow-hidden rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900"
			>
				<div class="border-b border-gray-100 dark:border-gray-850 px-3 py-2">
					<span class="text-xs font-medium text-gray-600 dark:text-gray-300"
						>{$i18n.t('Files in this skill directory')}</span
					>
				</div>
				<div class="max-h-40 overflow-y-auto px-4 py-2.5">
					{#if preview.entry.filesUnknown}
						<p class="text-xs text-gray-500">
							{$i18n.t(
								'File list unavailable (GitHub API rate limit) — only SKILL.md was fetched.'
							)}
						</p>
					{:else}
						<ul class="space-y-0.5 font-mono text-xs text-gray-600 dark:text-gray-300">
							{#each preview.entry.files as f}
								<li class="truncate">{f}</li>
							{/each}
						</ul>
					{/if}
				</div>
			</div>

			<!-- SKILL.md viewer — same card style as SkillDetail -->
			<div
				class="mt-3 overflow-hidden rounded-2xl border border-gray-100 dark:border-gray-850 bg-gray-50 dark:bg-gray-900"
			>
				<div
					class="flex items-center justify-between gap-2 border-b border-gray-100 dark:border-gray-850 px-3 py-2"
				>
					<span
						class="inline-flex items-center gap-1.5 text-xs font-medium text-gray-600 dark:text-gray-300"
					>
						<Document className="size-3.5 text-gray-400" strokeWidth="1.8" />
						SKILL.md
					</span>
					<div class="flex items-center gap-0.5 rounded-lg bg-gray-100 dark:bg-gray-850 p-0.5">
						<button
							class="rounded-md px-2 py-0.5 text-xs transition {preview.viewMode === 'rendered'
								? 'bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100 shadow-sm'
								: 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}"
							aria-pressed={preview.viewMode === 'rendered'}
							on:click={() => (preview = { ...preview, viewMode: 'rendered' })}
						>
							{$i18n.t('Rendered')}
						</button>
						<button
							class="rounded-md px-2 py-0.5 text-xs transition {preview.viewMode === 'source'
								? 'bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100 shadow-sm'
								: 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}"
							aria-pressed={preview.viewMode === 'source'}
							on:click={() => (preview = { ...preview, viewMode: 'source' })}
						>
							{$i18n.t('Source')}
						</button>
					</div>
				</div>
				<div class="max-h-[22rem] overflow-y-auto px-4 py-3">
					{#if preview.viewMode === 'rendered'}
						<div class="text-sm">
							<Markdown
								id={`skills-browse-${preview.entry.key.replace(/[^a-zA-Z0-9_-]/g, '-')}`}
								content={preview.content}
							/>
						</div>
					{:else}
						<pre
							class="whitespace-pre-wrap font-mono text-xs text-gray-700 dark:text-gray-300">{preview.content}</pre>
					{/if}
				</div>
			</div>
		{/if}
	</div>
{:else}
	<!-- ── Browse list ── -->
	<div class="pt-1">
		{#if showBack}
			<button
				class="-ml-1.5 inline-flex items-center gap-1 rounded-lg px-1.5 py-1 text-sm text-gray-500 hover:text-gray-800 dark:hover:text-gray-100 hover:bg-gray-50 dark:hover:bg-gray-900 transition"
				on:click={onBack}
			>
				<ChevronLeft className="size-4" strokeWidth="2" />
				{$i18n.t('Skills')}
			</button>
		{/if}

		<div class="{showBack ? 'mt-2' : ''} flex items-center gap-2">
			<h3 class="text-xl font-semibold text-gray-800 dark:text-gray-100">
				{$i18n.t('Browse skills')}
			</h3>
			<div class="flex-1"></div>
			<div
				class="flex items-center gap-1.5 rounded-lg border border-gray-200 dark:border-gray-800 px-2 py-1"
			>
				<Search className="size-3.5 text-gray-400" />
				<input
					bind:value={searchQuery}
					class="w-40 bg-transparent text-sm outline-hidden placeholder:text-gray-400"
					placeholder={$i18n.t('Filter loaded skills')}
					aria-label={$i18n.t('Filter loaded skills')}
					on:keydown={(e) => {
						if (e.key === 'Escape') {
							e.stopPropagation();
							searchQuery = '';
						}
					}}
				/>
				{#if searchQuery}
					<button
						class="rounded-lg p-0.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition"
						aria-label={$i18n.t('Clear filter')}
						on:click={() => (searchQuery = '')}
					>
						<XMark className="size-3.5" />
					</button>
				{/if}
			</div>
		</div>
		<p class="mt-0.5 text-sm text-gray-500">
			{$i18n.t(
				'Import community skills as drafts. Only SKILL.md text is imported — every install stays unaudited until a human records a "supported" verdict.'
			)}
		</p>

		<div class="mt-3 flex w-fit items-center gap-0.5 rounded-lg bg-gray-100 dark:bg-gray-850 p-0.5">
			<button
				class="rounded-md px-2.5 py-1 text-xs transition {tab === 'collections'
					? 'bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100 shadow-sm'
					: 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}"
				aria-pressed={tab === 'collections'}
				on:click={() => (tab = 'collections')}
			>
				{$i18n.t('Collections')}
			</button>
			<button
				class="rounded-md px-2.5 py-1 text-xs transition {tab === 'url'
					? 'bg-white dark:bg-gray-900 text-gray-800 dark:text-gray-100 shadow-sm'
					: 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'}"
				aria-pressed={tab === 'url'}
				on:click={() => (tab = 'url')}
			>
				{$i18n.t('From GitHub or URL')}
			</button>
		</div>

		{#if tab === 'collections'}
			<div class="mt-3 flex flex-wrap gap-1.5">
				{#each COLLECTIONS as c (c.owner + '/' + c.repo)}
					{@const key = keyOf(c.owner, c.repo)}
					<Tooltip content={`github.com/${key}`}>
						<button
							class="rounded-lg border px-2.5 py-1 text-xs font-medium transition {openKeys.includes(
								key
							)
								? 'border-blue-500 text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/40'
								: 'border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-900'}"
							aria-pressed={openKeys.includes(key)}
							on:click={() => toggleCollection(c.owner, c.repo)}
						>
							{c.label}
						</button>
					</Tooltip>
				{/each}
			</div>

			{#if openKeys.length === 0}
				<p class="mt-4 text-sm text-gray-500">
					{$i18n.t('Pick a collection to load its skills from GitHub.')}
				</p>
			{:else}
				{#each sections as [key, s] (key)}
					{@const c = COLLECTIONS.find((x) => keyOf(x.owner, x.repo) === key)}
					<SkillsBrowseSection
						title={c?.label ?? key}
						source={key}
						status={s.state.status}
						error={s.state.error ?? ''}
						rateLimited={!!s.state.rateLimited}
						truncated={!!s.state.truncated}
						entries={s.visible}
						hiddenCount={s.hiddenCount}
						searching={!!searchQuery.trim()}
						onPreview={openPreview}
						onLoadMore={() =>
							(visibleCounts = { ...visibleCounts, [key]: (visibleCounts[key] ?? PAGE) + PAGE })}
						onRetry={() => {
							repoCache.delete(key);
							const [owner, repo] = key.split('/');
							loadRepo(owner, repo).catch(() => {});
						}}
					/>
				{/each}
			{/if}

			<p class="mt-5 text-xs text-gray-400">
				{$i18n.t('Looking for more?')}
				<a
					href="https://skills.sh"
					target="_blank"
					rel="noopener noreferrer"
					class="text-blue-600 dark:text-blue-400 hover:underline">skills.sh</a
				>
				{$i18n.t('is a community skill directory to browse in your browser — it is not fetched here.')}
			</p>
		{:else}
			<div class="mt-3 flex items-center gap-2">
				<input
					bind:value={urlInput}
					class="flex-1 rounded-lg border border-gray-200 dark:border-gray-800 bg-transparent px-3 py-1.5 text-sm outline-hidden focus:border-blue-500 placeholder:text-gray-400"
					placeholder={$i18n.t('github.com repo, /tree/ or /blob/…SKILL.md, or a raw SKILL.md URL')}
					aria-label={$i18n.t('GitHub or raw SKILL.md URL')}
					on:keydown={(e) => {
						if (e.key === 'Enter') fetchFromUrl();
					}}
				/>
				<button
					class="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-40 transition"
					disabled={urlLoading || !urlInput.trim()}
					on:click={fetchFromUrl}
				>
					{urlLoading ? $i18n.t('Fetching…') : $i18n.t('Fetch')}
				</button>
			</div>

			{#if urlError}
				<p class="mt-2 text-xs text-gray-500">{urlError}</p>
			{/if}

			{#if urlRepoKey && urlSection}
				<SkillsBrowseSection
					title=""
					source={urlRepoKey}
					status={urlSection.state.status}
					error={urlSection.state.error ?? ''}
					rateLimited={!!urlSection.state.rateLimited}
					truncated={!!urlSection.state.truncated}
					entries={urlSection.visible}
					hiddenCount={urlSection.hiddenCount}
					searching={!!searchQuery.trim()}
					onPreview={openPreview}
					onLoadMore={() =>
						(visibleCounts = {
							...visibleCounts,
							[urlRepoKey]: (visibleCounts[urlRepoKey] ?? PAGE) + PAGE
						})}
					onRetry={() => {
						repoCache.delete(urlRepoKey);
						const [owner, repo] = urlRepoKey.split('/');
						loadRepo(owner, repo).catch(() => {});
					}}
				/>
			{/if}
		{/if}
	</div>
{/if}
