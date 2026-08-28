<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { v4 as uuidv4 } from 'uuid';
	import Sortable from 'sortablejs';

	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import {
		user,
		chats,
		settings,
		showSettings,
		chatId,
		tags,
		folders as _folders,
		showSidebar,
		hideNavRail,
		showSearch,
		mobile,
		showArchivedChats,
		pinnedChats,
		pinnedNotes,
		scrollPaginationEnabled,
		currentChatPage,
		temporaryChatEnabled,
		channels,
		socket,
		config,
		isApp,
		models,
		selectedFolder,
		WEBUI_NAME,
		sidebarWidth,
		activeChatIds
	} from '$lib/stores';
	import { onMount, getContext, tick, onDestroy } from 'svelte';

	const i18n = getContext('i18n');

	import {
		getChatList,
		getAllTags,
		getPinnedChatList,
		toggleChatPinnedStatusById,
		getChatById,
		updateChatFolderIdById,
		importChats,
		deleteAllChats,
		getChatListBySearchText
	} from '$lib/apis/chats';
	import { createNewFolder, getFolders, updateFolderParentIdById } from '$lib/apis/folders';
	import { createNewNote, getPinnedNoteList, toggleNotePinnedStatusById } from '$lib/apis/notes';
	import { updateUserSettings } from '$lib/apis/users';
	import { checkActiveChats } from '$lib/apis/tasks';
	import { getCadCapability } from '$lib/apis/cad';
	import { fetchActiveResearch } from '$lib/apis/research';
	import {
		chatActivity,
		markChatRunning,
		markChatDone,
		clearChatActivity,
		runningChats
	} from '$lib/utils/chatActivity';
	import { createNoteHandler } from '$lib/components/notes/utils';
	import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';

	import ArchivedChatsModal from './ArchivedChatsModal.svelte';
	import UserMenu from './Sidebar/UserMenu.svelte';
	import ChatItem from './Sidebar/ChatItem.svelte';
	import ChatItemSkeleton from './Sidebar/ChatItemSkeleton.svelte';
	import Spinner from '../common/Spinner.svelte';
	import Loader from '../common/Loader.svelte';
	import Folder from '../common/Folder.svelte';
	import FolderIcon from '../icons/Folder.svelte';
	import Plus from '../icons/Plus.svelte';
	import Tooltip from '../common/Tooltip.svelte';
	import HarvisLogoMark from '../common/HarvisLogoMark.svelte';
	import Folders from './Sidebar/Folders.svelte';
	import { getChannels, createNewChannel } from '$lib/apis/channels';
	import ChannelModal from './Sidebar/ChannelModal.svelte';
	import ChannelItem from './Sidebar/ChannelItem.svelte';
	import PencilSquare from '../icons/PencilSquare.svelte';
	import Search from '../icons/Search.svelte';
	import SearchModal from './SearchModal.svelte';
	import FolderModal from './Sidebar/Folders/FolderModal.svelte';
	import Sidebar from '../icons/Sidebar.svelte';
	import PinnedModelList from './Sidebar/PinnedModelList.svelte';
	import Note from '../icons/Note.svelte';
	import Code from '../icons/Code.svelte';
	import ModeSwitcher from './Sidebar/ModeSwitcher.svelte';
	import SidebarMore from './Sidebar/SidebarMore.svelte';
	import NotebookNav from './Sidebar/NotebookNav.svelte';
	import VibeCodeNav from './Sidebar/VibeCodeNav.svelte';
	import { DEFAULT_PINNED_ITEMS } from './Sidebar/pinned';
	import Sparkles from '../icons/Sparkles.svelte';
	import ArchiveBox from '../icons/ArchiveBox.svelte';
	import { slide } from 'svelte/transition';
	import HotkeyHint from '../common/HotkeyHint.svelte';

	const BREAKPOINT = 768;

	let scrollTop = 0;

	let navElement;
	let shiftKey = false;

	let selectedChatId = null;
	let showCreateChannel = false;

	// Pagination variables
	let chatListLoading = false;
	let allChatsLoaded = false;

	let showCreateFolderModal = false;

	let pinnedModels = [];

	let showPinnedModels = false;
	let showPinnedNotes = false;
	let showChannels = false;
	let showFolders = false;

	let folders = {};
	// folder_id → project name, for the "from <project>" mark on Recents/Pinned chat rows.
	$: folderNameById = Object.fromEntries(
		(($_folders ?? []) as any[]).map((f) => [f?.id, f?.name])
	);
	let folderRegistry = {};

	let newFolderId = null;

	$: pinnedItems = $settings?.pinnedMenuItems ?? DEFAULT_PINNED_ITEMS;

	// CAD Studio nav. Probed once, not reactive: the lane is a server-side flag read
	// at container create, so it cannot change under a running tab. A failed probe
	// means no entry — an operator who switched CAD off must not be left with a link
	// to a route whose every action 404s.
	let showCadNav = false;
	if (typeof window !== 'undefined') {
		getCadCapability()
			.then((c) => (showCadNav = !!c?.enabled))
			.catch(() => (showCadNav = false));
	}

	// Claude-Desktop-style mode switcher (Chat / Notebook / Code). Route-based: the
	// active mode is derived from the URL; the chat-specific sidebar sections show
	// only in Chat mode. Gated by a feature flag (off ⇒ behaves exactly as before).
	$: modeSwitcherEnabled = $config?.features?.enable_harvis_mode_switcher ?? true;
	// Notebooks used to be a third segment in the switcher. It is a destination, not a mode —
	// so it now sits under Projects and the notebooks route counts as chat mode, which keeps
	// New Chat / Projects / Notebooks on screen while you are in there.
	$: onNotebooksRoute = ($page?.url?.pathname ?? '/').startsWith('/harvis/notebooks');
	$: activeMode = modeSwitcherEnabled
		? (['/harvis/vibecode', '/harvis/build', '/harvis/agent-studio/run'].some((p) =>
				($page?.url?.pathname ?? '/').startsWith(p)
			)
				? 'code'
				: 'chat')
		: 'chat';

	// ── Chat-mode tool nav — ONE source of truth ────────────────────────────────────────
	// The expanded sidebar and the collapsed icon rail used to hardcode their own lists.
	// They drifted: the rail kept drawing the old `pinnedMenuItems` set (Agent Studio,
	// Notes, Library…) long after the expanded sidebar had moved to Cookbook → Schedules
	// → Artifacts → Connectors → Engines → CAD Studio. Both now render from this array,
	// so a new entry shows up in both or in neither. Icons are single-path 24×24 strokes.
	$: chatTools = [
		{
			id: 'sidebar-cookbook-button',
			href: '/harvis/agent-studio/cookbook',
			label: 'Cookbook',
			d: 'M4 19.5A2.5 2.5 0 0 1 6.5 17H20M4 19.5A2.5 2.5 0 0 0 6.5 22H20V2H6.5A2.5 2.5 0 0 0 4 4.5v15z'
		},
		{
			id: 'sidebar-schedules-button',
			href: '/harvis/agent-studio/schedules',
			label: 'Schedules',
			title: 'Schedules run a prompt on a timer and post the reply into a chat.',
			d: 'M12 6v6l4 2M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20z'
		},
		{
			id: 'sidebar-artifacts-button',
			href: '/harvis/agent-studio/activity',
			label: 'Artifacts',
			d: 'M12 2 2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5'
		},
		{
			id: 'sidebar-connectors-button',
			href: '/harvis/agent-studio/mcp-shop',
			label: 'Connectors',
			d: 'M9 2v6M15 2v6M6 8h12v2.5a6 6 0 0 1-12 0V8zM12 16.5V22'
		},
		{
			id: 'sidebar-integrations-button',
			href: '/harvis/integrations',
			label: 'Engines',
			d: 'm7 11 2-2-2-2M11 13h4M5 4h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z'
		},
		// CAD Studio appears only when the server says the lane is on — `/api/cad/capability`
		// reads the same flag every /api/cad route enforces, so the entry can never outlive
		// the feature.
		...(showCadNav
			? [
					{
						id: 'sidebar-cad-button',
						href: '/harvis/cad',
						label: 'CAD Studio',
						d: 'M12 2.5 20.5 7v10L12 21.5 3.5 17V7L12 2.5zM3.5 7l8.5 4.6L20.5 7M12 11.6v9.9'
					}
				]
			: [])
	];

	// The two entries that sit above the tools cluster in both layouts.
	const chatDestinations = [
		{ id: 'sidebar-projects-button', href: '/harvis/projects', label: 'Projects', icon: 'folder' },
		{ id: 'sidebar-notebooks-button', href: '/harvis/notebooks', label: 'Notebooks', icon: 'note' }
	];

	const isMenuItemVisible = (id) => {
		switch (id) {
			case 'notes':
				return (
					($config?.features?.enable_notes ?? false) &&
					($user?.role === 'admin' || ($user?.permissions?.features?.notes ?? true))
				);
			case 'workspace':
				return (
					$user?.role === 'admin' ||
					$user?.permissions?.workspace?.models ||
					$user?.permissions?.workspace?.knowledge ||
					$user?.permissions?.workspace?.prompts ||
					$user?.permissions?.workspace?.tools
				);
			case 'automations':
				return (
					$config?.features?.enable_automations &&
					($user?.role === 'admin' || $user?.permissions?.features?.automations)
				);
			case 'calendar':
				return (
					$config?.features?.enable_calendar &&
					($user?.role === 'admin' || $user?.permissions?.features?.calendar)
				);
			case 'playground':
				// Retired: the Playground entry was removed from the user menu, so a
				// previously-pinned one would be stuck in the sidebar with no way to unpin.
				return false;
			case 'agent-studio':
			case 'vibecode':
			case 'open-notebook':
			case 'artifacts':
				return $config?.features?.enable_harvis_studio ?? true;
			default:
				return false;
		}
	};

	// Some pinned items are full pages OUTSIDE the SvelteKit SPA — e.g. the vendored
	// open-notebook Next.js app at /onb. Those need a real browser navigation, not goto().
	const navMenuItem = (href) => {
		if (href && href.startsWith('/onb')) {
			window.location.href = href;
		} else {
			goto(href);
		}
	};

	const getMenuItemMeta = (id) => {
		const items = {
			'agent-studio': { label: 'Agent Studio', href: '/harvis/agent-studio', iconType: 'agent-studio' },
			vibecode: { label: 'Vibe Code', href: '/harvis/vibecode', iconType: 'vibecode' },
			'open-notebook': { label: 'Open Notebook', href: '/harvis/notebooks', iconType: 'open-notebook' },
			artifacts: { label: 'Artifacts', href: '/harvis/agent-studio/activity', iconType: 'artifacts' },
			notes: { label: 'Notes', href: '/notes', iconType: 'note' },
			workspace: { label: 'Library', href: '/workspace', iconType: 'workspace' },
			automations: { label: 'Automations', href: '/automations', iconType: 'automations' },
			calendar: { label: 'Calendar', href: '/calendar', iconType: 'calendar' },
			playground: { label: 'Playground', href: '/playground', iconType: 'playground' }
		};
		return items[id];
	};

	const initPinnedMenuSortable = () => {
		const el = document.getElementById('pinned-menu-items-list');
		if (el && !$mobile) {
			new Sortable(el, {
				animation: 150,
				onUpdate: async (event) => {
					const itemId = event.item.dataset.id;
					const newIndex = event.newIndex;
					const current = [...pinnedItems];
					const oldIndex = current.indexOf(itemId);
					current.splice(oldIndex, 1);
					current.splice(newIndex, 0, itemId);
					settings.set({ ...$settings, pinnedMenuItems: current });
					await updateUserSettings(localStorage.token, { ui: $settings });
				}
			});
		}
	};

	$: if ($selectedFolder) {
		initFolders();
	}

	const initFolders = async () => {
		if ($config?.features?.enable_folders === false) {
			return;
		}

		const folderList = await getFolders(localStorage.token).catch((error) => {
			return [];
		});
		_folders.set(folderList.sort((a, b) => b.updated_at - a.updated_at));

		// Open the Projects group on load when projects exist (it defaults
		// collapsed and is otherwise only opened on create — so existing
		// projects would stay hidden in a collapsed group after a reload).
		if (folderList.length > 0) {
			showFolders = true;
		}

		folders = {};

		// First pass: Initialize all folder entries
		for (const folder of folderList) {
			// Ensure folder is added to folders with its data
			folders[folder.id] = { ...(folders[folder.id] || {}), ...folder };

			if (newFolderId && folder.id === newFolderId) {
				folders[folder.id].new = true;
				newFolderId = null;
			}
		}

		// Second pass: Tie child folders to their parents
		for (const folder of folderList) {
			if (folder.parent_id) {
				// Ensure the parent folder is initialized if it doesn't exist
				if (!folders[folder.parent_id]) {
					folders[folder.parent_id] = {}; // Create a placeholder if not already present
				}

				// Initialize childrenIds array if it doesn't exist and add the current folder id
				folders[folder.parent_id].childrenIds = folders[folder.parent_id].childrenIds
					? [...folders[folder.parent_id].childrenIds, folder.id]
					: [folder.id];

				// Sort the children by updated_at field
				folders[folder.parent_id].childrenIds.sort((a, b) => {
					return folders[b].updated_at - folders[a].updated_at;
				});
			}
		}
	};

	const createFolder = async ({ name, data, parent_id }) => {
		name = name?.trim();
		if (!name) {
			toast.error($i18n.t('Folder name cannot be empty.'));
			return;
		}

		// Check for duplicate names in the same parent
		const siblings = Object.values(folders).filter((folder) => folder.parent_id === parent_id);
		if (siblings.find((folder) => folder.name.toLowerCase() === name.toLowerCase())) {
			// If a folder with the same name already exists, append a number to the name
			let i = 1;
			while (
				siblings.find((folder) => folder.name.toLowerCase() === `${name} ${i}`.toLowerCase())
			) {
				i++;
			}

			name = `${name} ${i}`;
		}

		// Add a dummy folder to the list to show the user that the folder is being created
		const tempId = uuidv4();
		folders = {
			...folders,
			[tempId]: {
				id: tempId,
				name: name,
				parent_id: parent_id,
				created_at: Date.now(),
				updated_at: Date.now()
			}
		};

		const res = await createNewFolder(localStorage.token, {
			name,
			data,
			parent_id
		}).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			// newFolderId = res.id;
			await initFolders();
			showFolders = true;
		}
	};

	const initChannels = async () => {
		// default (none), group, dm type
		const res = await getChannels(localStorage.token).catch((error) => {
			return null;
		});

		if (res) {
			await channels.set(
				res.sort(
					(a, b) =>
						['', null, 'group', 'dm'].indexOf(a.type) - ['', null, 'group', 'dm'].indexOf(b.type)
				)
			);
		}
	};

	const initChatList = async () => {
		// Reset pagination variables
		console.log('initChatList');
		currentChatPage.set(1);
		allChatsLoaded = false;
		scrollPaginationEnabled.set(false);

		initFolders();
		await Promise.all([
			await (async () => {
				console.log('Init tags');
				const _tags = await getAllTags(localStorage.token);
				tags.set(_tags);
			})(),
			await (async () => {
				console.log('Init pinned chats');
				const _pinnedChats = await getPinnedChatList(localStorage.token);
				pinnedChats.set(_pinnedChats);
			})(),
			await (async () => {
				if (
					$config?.features?.enable_notes &&
					($user?.role === 'admin' || ($user?.permissions?.features?.notes ?? true))
				) {
					console.log('Init pinned notes');
					const _pinnedNotes = await getPinnedNoteList(localStorage.token).catch(() => []);
					pinnedNotes.set(_pinnedNotes);
				}
			})(),
			await (async () => {
				console.log('Init chat list');
				const _chats = await getChatList(localStorage.token, $currentChatPage);
				await chats.set(_chats);
			})()
		]);

		// Enable pagination
		scrollPaginationEnabled.set(true);
	};

	const loadMoreChats = async () => {
		chatListLoading = true;

		currentChatPage.set($currentChatPage + 1);

		let newChatList = [];

		newChatList = await getChatList(localStorage.token, $currentChatPage);

		// once the bottom of the list has been reached (no results) there is no need to continue querying
		allChatsLoaded = newChatList.length === 0;
		const existingIds = new Set(($chats ?? []).map((c) => c.id));
		const uniqueNewChats = newChatList.filter((c) => !existingIds.has(c.id));
		await chats.set([...($chats ? $chats : []), ...uniqueNewChats]);

		chatListLoading = false;
	};

	const importChatHandler = async (items, pinned = false, folderId = null) => {
		console.log('importChatHandler', items, pinned, folderId);
		for (const item of items) {
			console.log(item);
			if (item.chat) {
				await importChats(localStorage.token, [
					{
						chat: item.chat,
						meta: item?.meta ?? {},
						pinned: pinned,
						folder_id: folderId,
						created_at: item?.created_at ?? null,
						updated_at: item?.updated_at ?? null
					}
				]);
			}
		}

		initChatList();
	};

	const inputFilesHandler = async (files) => {
		console.log(files);

		for (const file of files) {
			const reader = new FileReader();
			reader.onload = async (e) => {
				const content = e.target.result;

				try {
					const chatItems = JSON.parse(content);
					importChatHandler(chatItems);
				} catch {
					toast.error($i18n.t(`Invalid file format.`));
				}
			};

			reader.readAsText(file);
		}
	};

	const tagEventHandler = async (type, tagName, chatId) => {
		console.log(type, tagName, chatId);
		if (type === 'delete') {
			initChatList();
		} else if (type === 'add') {
			initChatList();
		}
	};

	let draggedOver = false;

	const onDragOver = (e) => {
		e.preventDefault();

		// Check if a file is being draggedOver.
		if (e.dataTransfer?.types?.includes('Files')) {
			draggedOver = true;
		} else {
			draggedOver = false;
		}
	};

	const onDragLeave = () => {
		draggedOver = false;
	};

	const onDrop = async (e) => {
		e.preventDefault();
		console.log(e); // Log the drop event

		// Perform file drop check and handle it accordingly
		if (e.dataTransfer?.files) {
			const inputFiles = Array.from(e.dataTransfer?.files);

			if (inputFiles && inputFiles.length > 0) {
				console.log(inputFiles); // Log the dropped files
				inputFilesHandler(inputFiles); // Handle the dropped files
			}
		}

		draggedOver = false; // Reset draggedOver status after drop
	};

	let touchstart;
	let touchend;

	function checkDirection() {
		const screenWidth = window.innerWidth;
		const swipeDistance = Math.abs(touchend.screenX - touchstart.screenX);
		if (touchstart.clientX < 40 && swipeDistance >= screenWidth / 8) {
			if (touchend.screenX < touchstart.screenX) {
				showSidebar.set(false);
			}
			if (touchend.screenX > touchstart.screenX) {
				showSidebar.set(true);
			}
		}
	}

	const onTouchStart = (e) => {
		touchstart = e.changedTouches[0];
		console.log(touchstart.clientX);
	};

	const onTouchEnd = (e) => {
		touchend = e.changedTouches[0];
		checkDirection();
	};

	const onKeyDown = (e) => {
		if (e.key === 'Shift') {
			shiftKey = true;
		}
	};

	const onKeyUp = (e) => {
		if (e.key === 'Shift') {
			shiftKey = false;
		}
	};

	const onFocus = () => {};

	const onBlur = () => {
		shiftKey = false;
		selectedChatId = null;
	};

	const MIN_WIDTH = 220;
	const MAX_WIDTH = 480;

	let isResizing = false;

	let startWidth = 0;
	let startClientX = 0;

	const resizeStartHandler = (e: MouseEvent) => {
		if ($mobile) return;
		isResizing = true;

		startClientX = e.clientX;
		startWidth = $sidebarWidth ?? 260;

		document.body.style.userSelect = 'none';
	};

	const resizeEndHandler = () => {
		if (!isResizing) return;
		isResizing = false;

		document.body.style.userSelect = '';
		localStorage.setItem('sidebarWidth', String($sidebarWidth));
	};

	const resizeSidebarHandler = (endClientX) => {
		const dx = endClientX - startClientX;
		const newSidebarWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, startWidth + dx));

		sidebarWidth.set(newSidebarWidth);
		document.documentElement.style.setProperty('--sidebar-width', `${newSidebarWidth}px`);
	};

	// ── background-run poller ───────────────────────────────────────────────────────────
	// A Deep Research or workspace run keeps going after its chat view unmounts, and nothing
	// else in the app is watching once that happens. `chatActivity` remembers which chats are
	// waiting; this asks the backend which runs are still alive and flips the rest to "done",
	// which is what turns the row's spinner into a blue dot.
	let activityTimer: ReturnType<typeof setInterval> | null = null;

	/**
	 * Workspace runs the backend still considers live, as chatId → workspaceId.
	 *
	 * Deliberately NOT `/api/workspace/active`: that returns at most one run and marks
	 * every candidate it walks past as orphaned, so polling it would kill the runs we are
	 * trying to report. `/active-runs` is the read-only list. Returns null (not an empty
	 * map) when the poll itself failed, so a network blip can't be read as "all finished".
	 */
	const fetchLiveWorkspaceRuns = async (): Promise<Map<string, string> | null> => {
		try {
			const res = await fetch(`${WEBUI_BASE_URL}/api/workspace/active-runs`, {
				headers: { Authorization: `Bearer ${localStorage.token}` }
			});
			if (!res.ok) return null;
			const data = await res.json();
			return new Map((data?.runs ?? []).map((r: any) => [r.session_id, r.id]));
		} catch (e) {
			return null;
		}
	};

	const pollChatActivity = async () => {
		const waiting = runningChats();
		const [research, workspaces] = await Promise.all([
			waiting.some(([, v]) => v.research)
				? fetchActiveResearch(localStorage.token)
						.then((r) => new Set((r?.active ?? []).map((a) => a.session_id)))
						// A failed poll says nothing about the run — leave those spinners alone.
						.catch(() => null)
				: Promise.resolve(new Set<string>()),
			fetchLiveWorkspaceRuns()
		]);

		// A run the user launched and then walked away from: the chat view that started it
		// is unmounted, so the backend is the only thing that still knows. Raise the spinner
		// here rather than waiting for that chat to be reopened. The chat currently on screen
		// is skipped on purpose — its own run card is already showing the state, and a
		// spinner on the row you are reading is noise.
		if (workspaces) {
			const known = $chatActivity;
			for (const [sessionId, workspaceId] of workspaces) {
				if (sessionId === $chatId) continue;
				// Re-marking an unchanged entry every 8s would rewrite localStorage and wake
				// every sidebar row for nothing.
				const cur = known[sessionId];
				if (cur?.state === 'running' && cur.workspace === workspaceId) continue;
				markChatRunning(sessionId, undefined, workspaceId);
			}
		}

		for (const [cid, v] of waiting) {
			// Unknown (poll failed) is not the same as absent (run finished).
			if (v.research) {
				if (research === null) continue;
				if (research.has(v.research)) continue;
			} else if (v.workspace) {
				if (workspaces === null) continue;
				// `has`, not an id comparison: a chat that started a SECOND run since this
				// entry was written is still running, and the loop above has already moved
				// it onto the new id.
				if (workspaces.has(cid)) continue;
			} else {
				// An ordinary reply; its own stream settles it.
				continue;
			}
			// Finished while the user was looking at it: no notification needed.
			if (cid === $chatId) clearChatActivity(cid);
			else markChatDone(cid);
		}
	};

	// Leaving a chat mid-run is exactly when the spinner needs to appear, so don't make the
	// user wait out the interval for it.
	$: if ($chatId !== undefined && activityTimer !== null) pollChatActivity();

	onMount(async () => {
		try {
			const width = Number(localStorage.getItem('sidebarWidth'));
			if (!Number.isNaN(width) && width >= MIN_WIDTH && width <= MAX_WIDTH) {
				sidebarWidth.set(width);
			}
		} catch {}

		document.documentElement.style.setProperty('--sidebar-width', `${$sidebarWidth}px`);
		sidebarWidth.subscribe((w) => {
			document.documentElement.style.setProperty('--sidebar-width', `${w}px`);
		});

		showSidebar.set(!$mobile ? localStorage.sidebar === 'true' : false);

		const unsubscribers = [
			mobile.subscribe((value) => {
				if ($showSidebar && value) {
					showSidebar.set(false);
				}

				if ($showSidebar && !value) {
					const navElement = document.getElementsByTagName('nav')[0];
					if (navElement) {
						navElement.style['-webkit-app-region'] = 'drag';
					}
				}
			}),
			showSidebar.subscribe(async (value) => {
				localStorage.sidebar = value;

				// nav element is not available on the first render
				const navElement = document.getElementsByTagName('nav')[0];

				if (navElement) {
					if ($mobile) {
						if (!value) {
							navElement.style['-webkit-app-region'] = 'drag';
						} else {
							navElement.style['-webkit-app-region'] = 'no-drag';
						}
					} else {
						navElement.style['-webkit-app-region'] = 'drag';
					}
				}

				if (value) {
					// Only fetch channels if the feature is enabled and user has permission
					if (
						$config?.features?.enable_channels &&
						($user?.role === 'admin' || ($user?.permissions?.features?.channels ?? true))
					) {
						await initChannels();
					}
					await initChatList();

					// Check which chats have active tasks
					const allChatIds = [...$chats.map((c) => c.id), ...$pinnedChats.map((c) => c.id)];
					if (allChatIds.length > 0) {
						try {
							const res = await checkActiveChats(localStorage.token, allChatIds);
							activeChatIds.set(new Set(res.active_chat_ids || []));
						} catch (e) {
							console.debug('Failed to check active chats:', e);
						}
					}
				}
			}),
			settings.subscribe((value) => {
				if (pinnedModels != value?.pinnedModels ?? []) {
					pinnedModels = value?.pinnedModels ?? [];
					showPinnedModels = pinnedModels.length > 0;
				}
			})
		];

		pollChatActivity();
		activityTimer = setInterval(pollChatActivity, 8000);

		window.addEventListener('keydown', onKeyDown);
		window.addEventListener('keyup', onKeyUp);

		window.addEventListener('touchstart', onTouchStart);
		window.addEventListener('touchend', onTouchEnd);

		window.addEventListener('focus', onFocus);
		window.addEventListener('blur', onBlur);

		const dropZone = document.getElementById('sidebar');
		if (dropZone) {
			dropZone.addEventListener('dragover', onDragOver);
			dropZone.addEventListener('drop', onDrop);
			dropZone.addEventListener('dragleave', onDragLeave);
		}

		const socketInstance = $socket;
		socketInstance?.on('events', chatActiveEventHandler);

		await tick();
		initPinnedMenuSortable();

		return () => {
			if (activityTimer) clearInterval(activityTimer);
			unsubscribers.forEach((unsubscriber) => unsubscriber());

			window.removeEventListener('keydown', onKeyDown);
			window.removeEventListener('keyup', onKeyUp);

			window.removeEventListener('touchstart', onTouchStart);
			window.removeEventListener('touchend', onTouchEnd);

			window.removeEventListener('focus', onFocus);
			window.removeEventListener('blur', onBlur);

			if (dropZone) {
				dropZone.removeEventListener('dragover', onDragOver);
				dropZone.removeEventListener('drop', onDrop);
				dropZone.removeEventListener('dragleave', onDragLeave);
			}

			socketInstance?.off('events', chatActiveEventHandler);
		};
	});

	// Handler for chat events (defined outside onMount for proper cleanup)
	const chatActiveEventHandler = (event: {
		chat_id: string;
		message_id: string;
		data: { type: string; data: any };
	}) => {
		if (event.data?.type === 'chat:active') {
			const { active } = event.data.data;
			activeChatIds.update((ids) => {
				const newSet = new Set(ids);
				if (active) {
					newSet.add(event.chat_id);
				} else {
					newSet.delete(event.chat_id);
				}
				return newSet;
			});
		} else if (event.data?.type === 'chat:list') {
			initChatList();
		}
	};

	const newChatHandler = async () => {
		selectedChatId = null;
		selectedFolder.set(null);

		if ($user?.role !== 'admin' && $user?.permissions?.chat?.temporary_enforced) {
			await temporaryChatEnabled.set(true);
		} else {
			await temporaryChatEnabled.set(false);
		}

		setTimeout(() => {
			if ($mobile) {
				showSidebar.set(false);
			}
		}, 0);
	};

	const itemClickHandler = async () => {
		selectedChatId = null;
		chatId.set('');

		if ($mobile) {
			showSidebar.set(false);
		}

		await tick();
	};

	const isWindows = /Windows/i.test(navigator.userAgent);
</script>

<ArchivedChatsModal
	bind:show={$showArchivedChats}
	onUpdate={async () => {
		await initChatList();
	}}
	onDelete={(id) => {
		if ($chatId === id) {
			goto('/');
			chatId.set('');
		}
	}}
/>

<ChannelModal
	bind:show={showCreateChannel}
	onSubmit={async (payload: any) => {
		let { type, name, is_private, access_grants, group_ids, user_ids } = payload ?? {};
		name = name?.trim();

		if (type === 'dm') {
			if (!user_ids || user_ids.length === 0) {
				toast.error($i18n.t('Please select at least one user for Direct Message channel.'));
				return;
			}
		} else {
			if (!name) {
				toast.error($i18n.t('Channel name cannot be empty.'));
				return;
			}
		}

		const res = await createNewChannel(localStorage.token, {
			type: type,
			name: name,
			is_private: is_private,
			access_grants: access_grants,
			group_ids: group_ids,
			user_ids: user_ids
		}).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			$socket.emit('join-channels', { auth: { token: $user?.token } });
			await initChannels();
			showCreateChannel = false;
			showChannels = true;
			goto(`/channels/${res.id}`);
		}
	}}
/>

<FolderModal
	bind:show={showCreateFolderModal}
	onSubmit={async (folder) => {
		await createFolder(folder);
		showCreateFolderModal = false;
	}}
/>

<!-- svelte-ignore a11y-no-static-element-interactions -->

{#if $showSidebar}
	<div
		class=" {$isApp
			? ' ml-[4.5rem] md:ml-0'
			: ''} fixed md:hidden z-40 top-0 right-0 left-0 bottom-0 bg-black/60 w-full min-h-screen h-screen flex justify-center overflow-hidden overscroll-contain"
		on:mousedown={() => {
			showSidebar.set(!$showSidebar);
		}}
	/>
{/if}

<SearchModal
	bind:show={$showSearch}
	onClose={() => {
		if ($mobile) {
			showSidebar.set(false);
		}
	}}
/>

<button
	id="sidebar-new-chat-button"
	class="hidden"
	on:click={() => {
		goto('/');
		newChatHandler();
	}}
/>

<svelte:window
	on:mousemove={(e) => {
		if (!isResizing) return;
		resizeSidebarHandler(e.clientX);
	}}
	on:mouseup={() => {
		resizeEndHandler();
	}}
/>

<!-- The collapsed sidebar still draws a narrow icon strip, which is how it gets reopened.
     A route that owns the whole viewport can ask for even that to go away by setting
     `hideNavRail`; it then has to provide its own way out, which the CAD session's header
     back button does. -->
{#if !$mobile && !$showSidebar && !$hideNavRail}
	<div
		class=" pt-[7px] pb-2 px-2 flex flex-col justify-between text-black dark:text-white hover:bg-gray-50/30 dark:hover:bg-gray-950/30 h-full z-10 transition-all border-e-[0.5px] border-gray-50 dark:border-gray-850/30"
		id="sidebar"
	>
		<button
			class="flex flex-col flex-1 {isWindows ? 'cursor-pointer' : 'cursor-[e-resize]'}"
			on:click={async () => {
				showSidebar.set(!$showSidebar);
			}}
		>
			<div class="pb-1.5">
				<Tooltip
					content={$showSidebar ? $i18n.t('Close Sidebar') : $i18n.t('Open Sidebar')}
					placement="right"
				>
					<button
						class="flex rounded-xl hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)] transition group {isWindows
							? 'cursor-pointer'
							: 'cursor-[e-resize]'}"
						aria-label={$showSidebar ? $i18n.t('Close Sidebar') : $i18n.t('Open Sidebar')}
					>
						<div class=" self-center flex items-center justify-center size-9">
							<HarvisLogoMark
								className="sidebar-new-chat-icon size-6 object-contain group-hover:hidden"
							/>

							<Sidebar className="size-5 hidden group-hover:flex" />
						</div>
					</button>
				</Tooltip>
			</div>

			<div class="-mt-[0.5px]">
				<div class="">
					<Tooltip content={$i18n.t('New Chat')} placement="right">
						<a
							class=" cursor-pointer flex rounded-xl hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)] transition group"
							href="/"
							draggable="false"
							on:click={async (e) => {
								e.stopImmediatePropagation();
								e.preventDefault();

								goto('/');
								newChatHandler();
							}}
							aria-label={$i18n.t('New Chat')}
						>
							<div class=" self-center flex items-center justify-center size-9">
								<PencilSquare className="size-4.5" />
							</div>
						</a>
					</Tooltip>
				</div>

				<div>
					<Tooltip content={$i18n.t('Search')} placement="right">
						<button
							class=" cursor-pointer flex rounded-xl hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)] transition group"
							on:click={(e) => {
								e.stopImmediatePropagation();
								e.preventDefault();

								showSearch.set(true);
							}}
							draggable="false"
							aria-label={$i18n.t('Search')}
						>
							<div class=" self-center flex items-center justify-center size-9">
								<Search className="size-4.5" />
							</div>
						</button>
					</Tooltip>
				</div>

				<!-- The collapsed rail mirrors the expanded sidebar exactly: same destinations,
				     same icons, same order — icon-only. Before this it still drew the legacy
				     `pinnedMenuItems` set, which the expanded sidebar stopped rendering once the
				     mode switcher shipped, so collapsing the sidebar swapped in a different and
				     older set of icons. -->
				{#if modeSwitcherEnabled && activeMode === 'chat'}
					{#each chatDestinations as dest (dest.id)}
						<div>
							<Tooltip content={$i18n.t(dest.label)} placement="right">
								<a
									id={dest.id}
									class=" cursor-pointer flex rounded-xl hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)] transition group"
									href={dest.href}
									on:click={async (e) => {
										e.stopImmediatePropagation();
										e.preventDefault();
										navMenuItem(dest.href);
										itemClickHandler();
									}}
									draggable="false"
									aria-label={$i18n.t(dest.label)}
								>
									<div class=" self-center flex items-center justify-center size-9">
										{#if dest.icon === 'folder'}
											<FolderIcon className="size-4.5" />
										{:else}
											<Note className="size-4.5" />
										{/if}
									</div>
								</a>
							</Tooltip>
						</div>
					{/each}

					{#each chatTools as tool (tool.id)}
						<div>
							<Tooltip content={$i18n.t(tool.label)} placement="right">
								<a
									id="rail-{tool.id}"
									class=" cursor-pointer flex rounded-xl hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)] transition group"
									href={tool.href}
									on:click={async (e) => {
										e.stopImmediatePropagation();
										e.preventDefault();
										navMenuItem(tool.href);
										itemClickHandler();
									}}
									draggable="false"
									aria-label={$i18n.t(tool.label)}
								>
									<div class=" self-center flex items-center justify-center size-9">
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="size-4.5"><path d={tool.d} /></svg>
									</div>
								</a>
							</Tooltip>
						</div>
					{/each}
				{:else}
					{#each pinnedItems as itemId (itemId)}
						{@const meta = getMenuItemMeta(itemId)}
						{#if meta && isMenuItemVisible(itemId)}
							<div class="">
								<Tooltip content={$i18n.t(meta.label)} placement="right">
									<a
										class=" cursor-pointer flex rounded-xl hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)] transition group"
										href={meta.href}
										on:click={async (e) => {
											e.stopImmediatePropagation();
											e.preventDefault();
											navMenuItem(meta.href);
											itemClickHandler();
										}}
										draggable="false"
										aria-label={$i18n.t(meta.label)}
									>
										<div class=" self-center flex items-center justify-center size-9">
											{#if itemId === 'notes'}
												<Note className="size-4.5" />
											{:else if itemId === 'workspace'}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													fill="none"
													viewBox="0 0 24 24"
													stroke-width="1.5"
													stroke="currentColor"
													class="size-4.5"
												>
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														d="M13.5 16.875h3.375m0 0h3.375m-3.375 0V13.5m0 3.375v3.375M6 10.5h2.25a2.25 2.25 0 0 0 2.25-2.25V6a2.25 2.25 0 0 0-2.25-2.25H6A2.25 2.25 0 0 0 3.75 6v2.25A2.25 2.25 0 0 0 6 10.5Zm0 9.75h2.25A2.25 2.25 0 0 0 10.5 18v-2.25a2.25 2.25 0 0 0-2.25-2.25H6a2.25 2.25 0 0 0-2.25 2.25V18A2.25 2.25 0 0 0 6 20.25Zm9.75-9.75H18a2.25 2.25 0 0 0 2.25-2.25V6A2.25 2.25 0 0 0 18 3.75h-2.25A2.25 2.25 0 0 0 13.5 6v2.25a2.25 2.25 0 0 0 2.25 2.25Z"
													/>
												</svg>
											{:else if itemId === 'automations'}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													fill="none"
													viewBox="0 0 24 24"
													stroke-width="1.5"
													stroke="currentColor"
													class="size-4.5"
												>
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
													/>
												</svg>
											{:else if itemId === 'calendar'}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													fill="none"
													viewBox="0 0 24 24"
													stroke-width="1.5"
													stroke="currentColor"
													class="size-4.5"
												>
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5"
													/>
												</svg>
											{:else if itemId === 'playground'}
												<Code className="size-4.5" />
											{:else if itemId === 'agent-studio'}
												<Sparkles className="size-4.5" />
											{:else if itemId === 'vibecode'}
												<Code className="size-4.5" />
											{:else if itemId === 'open-notebook'}
												<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.8" stroke="currentColor" class="size-4.5"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" /></svg>
											{:else if itemId === 'artifacts'}
												<ArchiveBox className="size-4.5" />										{/if}
										</div>
									</a>
								</Tooltip>
							</div>
						{/if}
					{/each}
				{/if}
			</div>
		</button>

		<div>
			<div>
				<div class=" py-2 flex justify-center items-center">
					{#if $user !== undefined && $user !== null}
						<UserMenu
							role={$user?.role}
							profile={$config?.features?.enable_user_status ?? true}
							showActiveUsers={false}
							on:show={(e) => {
								if (e.detail === 'archived-chat') {
									showArchivedChats.set(true);
								}
							}}
						>
							<div
								class=" cursor-pointer flex rounded-xl hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)] transition group"
							>
								<div class="self-center relative">
									<img
										src={`${WEBUI_API_BASE_URL}/users/${$user?.id}/profile/image`}
										class=" size-7 object-cover rounded-full"
										alt={$i18n.t('Open User Profile Menu')}
										aria-label={$i18n.t('Open User Profile Menu')}
									/>

									{#if $config?.features?.enable_user_status}
										<div class="absolute -bottom-0.5 -right-0.5">
											<span class="relative flex size-2.5">
												<span
													class="relative inline-flex size-2.5 rounded-full {true
														? 'bg-green-500'
														: 'bg-gray-300 dark:bg-gray-700'} border-2 border-white dark:border-gray-900"
												></span>
											</span>
										</div>
									{/if}
								</div>
							</div>
						</UserMenu>
					{/if}
				</div>
			</div>
		</div>
	</div>
{/if}

<!-- {$i18n.t('New Folder')} -->
<!-- {$i18n.t('Pinned')} -->

{#if $showSidebar}
	<div
		bind:this={navElement}
		id="sidebar"
		class="h-screen max-h-[100dvh] min-h-screen select-none {$showSidebar
			? `${$mobile ? 'bg-gray-50 dark:bg-gray-950' : 'bg-gray-50/70 dark:bg-gray-950/70'} z-50`
			: ' bg-transparent z-0 '} {$isApp
			? `ml-[4.5rem] md:ml-0 `
			: ' transition-all duration-300 '} shrink-0 text-gray-900 dark:text-gray-200 text-sm fixed top-0 left-0 overflow-x-hidden
        "
		transition:slide={{ duration: 250, axis: 'x' }}
		data-state={$showSidebar}
	>
		<div
			class=" my-auto flex flex-col justify-between h-screen max-h-[100dvh] w-[var(--sidebar-width)] overflow-x-hidden scrollbar-hidden z-50 border-r border-gray-200/70 dark:border-gray-850 {$showSidebar
				? ''
				: 'invisible'}"
		>
			<div
				class="sidebar px-[0.5625rem] pt-2 pb-1.5 flex justify-between space-x-1 text-gray-600 dark:text-gray-400 sticky top-0 z-10 -mb-3"
			>
				<a
					class="flex items-center rounded-xl size-8.5 h-full justify-center hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)] transition no-drag-region"
					href="/"
					draggable="false"
					on:click={newChatHandler}
				>
					<HarvisLogoMark className="sidebar-new-chat-icon size-6 object-contain" />
				</a>

				<a href="/" class="flex flex-1 px-0.5" on:click={newChatHandler}>
					<div
						id="sidebar-webui-name"
						class=" self-center text-gray-850 dark:text-white harvis-wordmark"
					>
						{$WEBUI_NAME}
					</div>
				</a>
				<Tooltip
					content={$showSidebar ? $i18n.t('Close Sidebar') : $i18n.t('Open Sidebar')}
					placement="bottom"
				>
					<button
						class="flex rounded-xl size-8.5 justify-center items-center hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)] transition {isWindows
							? 'cursor-pointer'
							: 'cursor-[w-resize]'}"
						on:click={() => {
							showSidebar.set(!$showSidebar);
						}}
						aria-label={$showSidebar ? $i18n.t('Close Sidebar') : $i18n.t('Open Sidebar')}
					>
						<div class=" self-center p-1.5">
							<Sidebar />
						</div>
					</button>
				</Tooltip>

				<div
					class="{scrollTop > 0
						? 'visible'
						: 'invisible'} sidebar-bg-gradient-to-b bg-linear-to-b from-gray-50 dark:from-gray-950 to-transparent from-50% pointer-events-none absolute inset-0 -z-10 -mb-6"
				></div>
			</div>

			<div
				class="relative flex flex-col flex-1 overflow-y-auto scrollbar-hidden pt-3 pb-3"
				on:scroll={(e) => {
					if (e.target.scrollTop === 0) {
						scrollTop = 0;
					} else {
						scrollTop = e.target.scrollTop;
					}
				}}
			>
				<div class="pb-1.5">
					{#if modeSwitcherEnabled}
						<!-- Chat | Notebook | Code — switches the action list + session list below. -->
						<div class="px-[0.5625rem] pb-2">
							<ModeSwitcher {activeMode} />
						</div>
					{/if}

					{#if !modeSwitcherEnabled || activeMode === 'chat'}
					<div class="px-[0.4375rem] flex justify-center text-gray-800 dark:text-gray-200">
						<a
							id="sidebar-new-chat-button"
							class="group grow flex items-center gap-3 rounded-xl px-2.5 py-2 text-blue-600 dark:text-blue-400 font-medium hover:bg-blue-500/10 transition outline-none"
							href="/"
							draggable="false"
							on:click={newChatHandler}
							aria-label={$i18n.t('New Chat')}
						>
							<div class="self-center">
								<PencilSquare className=" size-4.5" strokeWidth="2" />
							</div>

							<div class="flex flex-1 self-center translate-y-[0.5px]">
								<div class=" self-center text-sm font-primary">{$i18n.t('New Chat')}</div>
							</div>

							<HotkeyHint name="newChat" className=" group-hover:visible invisible" />
						</a>
					</div>

					<div class="px-[0.4375rem] flex items-center gap-1 text-gray-800 dark:text-gray-200">
						<a
							id="sidebar-projects-button"
							href="/harvis/projects"
							class="group grow flex items-center gap-3 rounded-xl px-2.5 py-2 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)] transition outline-none"
							draggable="false"
							aria-label={$i18n.t('Projects')}
						>
							<div class="self-center">
								<FolderIcon strokeWidth="2" className="size-4.5" />
							</div>

							<div class="flex flex-1 self-center translate-y-[0.5px]">
								<div class=" self-center text-sm font-primary">{$i18n.t('Projects')}</div>
							</div>
						</a>
						<button
							id="sidebar-search-button"
							class="shrink-0 rounded-xl p-2 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)] transition outline-none"
							on:click={() => {
								showSearch.set(true);
							}}
							draggable="false"
							aria-label={$i18n.t('Search')}
						>
							<Search strokeWidth="2" className="size-4.5" />
						</button>
					</div>

					<div class="px-[0.4375rem] flex justify-center text-gray-800 dark:text-gray-200">
						<a
							id="sidebar-notebooks-button"
							href="/harvis/notebooks"
							class="group grow flex items-center gap-3 rounded-xl px-2.5 py-2 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)] transition outline-none {onNotebooksRoute
								? 'bg-gray-200 dark:bg-[oklch(0.29_0.024_258)]'
								: ''}"
							draggable="false"
							aria-label={$i18n.t('Notebooks')}
						>
							<div class="self-center">
								<Note strokeWidth="2" className="size-4.5" />
							</div>

							<div class="flex flex-1 self-center translate-y-[0.5px]">
								<div class=" self-center text-sm font-primary">{$i18n.t('Notebooks')}</div>
							</div>
						</a>
					</div>

						{#if modeSwitcherEnabled}
							<!-- Chat-mode tools, in the order the user asked for (2026-08-19):
							     Cookbook, then Schedules → Artifacts → Connectors → Engines → CAD
							     Studio. Cookbook, Customize and Settings used to live in the footer;
							     Cookbook came up here and the other two moved into the user menu. -->
							<div class="px-[0.4375rem]">
							{#each chatTools as tool (tool.id)}
								<a
									id={tool.id}
									href={tool.href}
									class="group flex items-center gap-3 rounded-xl px-2.5 py-2 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)] transition outline-none {($page.url.pathname ?? '').startsWith(tool.href) ? 'bg-blue-500/10 text-blue-600 dark:text-blue-400 font-medium' : ''}"
									draggable="false"
									aria-label={$i18n.t(tool.label)}
									title={tool.title ? $i18n.t(tool.title) : null}
								>
									<div class="self-center">
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="size-4.5"><path d={tool.d} /></svg>
									</div>
									<div class="flex flex-1 self-center translate-y-[0.5px]">
										<div class=" self-center text-sm font-primary">{$i18n.t(tool.label)}</div>
									</div>
								</a>
							{/each}
							</div>
							<!-- More (bold) stays in the footer bottom-nav cluster. -->
						{/if}
					{/if}

					{#if modeSwitcherEnabled && onNotebooksRoute}
						<NotebookNav activeOnb={$page?.url?.searchParams?.get('onb') ?? ''} />
					{/if}

					{#if modeSwitcherEnabled && activeMode === 'code'}
						<VibeCodeNav />
					{/if}


					{#if !modeSwitcherEnabled}
					<div id="pinned-menu-items-list">
						{#each pinnedItems as itemId (itemId)}
							{@const meta = getMenuItemMeta(itemId)}
							{#if meta && isMenuItemVisible(itemId)}
								<div
									class="px-[0.4375rem] flex justify-center text-gray-800 dark:text-gray-200"
									data-id={itemId}
								>
									<a
										id="sidebar-{itemId}-button"
										class="grow flex items-center space-x-3 rounded-2xl px-2.5 py-2 hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)] transition"
										href={meta.href}
										on:click={itemClickHandler}
										draggable="false"
										aria-label={$i18n.t(meta.label)}
									>
										<div class="self-center">
											{#if itemId === 'notes'}
												<Note className="size-4.5" strokeWidth="2" />
											{:else if itemId === 'workspace'}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													fill="none"
													viewBox="0 0 24 24"
													stroke-width="2"
													stroke="currentColor"
													class="size-4.5"
												>
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														d="M13.5 16.875h3.375m0 0h3.375m-3.375 0V13.5m0 3.375v3.375M6 10.5h2.25a2.25 2.25 0 0 0 2.25-2.25V6a2.25 2.25 0 0 0-2.25-2.25H6A2.25 2.25 0 0 0 3.75 6v2.25A2.25 2.25 0 0 0 6 10.5Zm0 9.75h2.25A2.25 2.25 0 0 0 10.5 18v-2.25a2.25 2.25 0 0 0-2.25-2.25H6a2.25 2.25 0 0 0-2.25 2.25V18A2.25 2.25 0 0 0 6 20.25Zm9.75-9.75H18a2.25 2.25 0 0 0 2.25-2.25V6A2.25 2.25 0 0 0 18 3.75h-2.25A2.25 2.25 0 0 0 13.5 6v2.25a2.25 2.25 0 0 0 2.25 2.25Z"
													/>
												</svg>
											{:else if itemId === 'automations'}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													fill="none"
													viewBox="0 0 24 24"
													stroke-width="2"
													stroke="currentColor"
													class="size-4.5"
												>
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"
													/>
												</svg>
											{:else if itemId === 'calendar'}
												<svg
													xmlns="http://www.w3.org/2000/svg"
													fill="none"
													viewBox="0 0 24 24"
													stroke-width="2"
													stroke="currentColor"
													class="size-4.5"
												>
													<path
														stroke-linecap="round"
														stroke-linejoin="round"
														d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 0 1 2.25-2.25h13.5A2.25 2.25 0 0 1 21 7.5v11.25m-18 0A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75m-18 0v-7.5A2.25 2.25 0 0 1 5.25 9h13.5A2.25 2.25 0 0 1 21 11.25v7.5"
													/>
												</svg>
											{:else if itemId === 'playground'}
												<Code className="size-4.5" strokeWidth="2" />
											{:else if itemId === 'agent-studio'}
												<Sparkles className="size-4.5" strokeWidth="2" />
											{:else if itemId === 'vibecode'}
												<Code className="size-4.5" strokeWidth="2" />
											{:else if itemId === 'open-notebook'}
												<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.8" stroke="currentColor" class="size-4.5"><path stroke-linecap="round" stroke-linejoin="round" d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25" /></svg>
											{:else if itemId === 'artifacts'}
												<ArchiveBox className="size-4.5" strokeWidth="2" />											{/if}
										</div>

										<div class="flex self-center translate-y-[0.5px]">
											<div class=" self-center text-sm font-primary">{$i18n.t(meta.label)}</div>
										</div>
									</a>
								</div>
							{/if}
						{/each}
					</div>
					{/if}
				</div>

				{#if ($models ?? []).length > 0 && (($settings?.pinnedModels ?? []).length > 0 || $config?.default_pinned_models)}
					<Folder
						id="sidebar-models"
						bind:open={showPinnedModels}
						className="px-2 mt-0.5"
						name={$i18n.t('Models')}
						chevron={false}
						dragAndDrop={false}
					>
						<PinnedModelList bind:selectedChatId {shiftKey} />
					</Folder>
				{/if}

				{#if ($config?.features?.enable_notes ?? false) && ($user?.role === 'admin' || ($user?.permissions?.features?.notes ?? true)) && $pinnedNotes.length > 0}
					<Folder
						id="sidebar-pinned-notes"
						bind:open={showPinnedNotes}
						className="px-2 mt-0.5"
						name={$i18n.t('Notes')}
						chevron={false}
						dragAndDrop={false}
						onAdd={async () => {
							const note = await createNoteHandler('New Note');
							if (note) {
								goto(`/notes/${note.id}`);
							}
						}}
						onAddLabel={$i18n.t('New Note')}
					>
						<div class="mt-0.5 pb-1.5">
							{#each $pinnedNotes as note (note.id)}
								<a
									class="w-full flex items-center gap-3 rounded-xl px-2.5 py-1.5 hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)] transition group text-sm"
									href={`/notes/${note.id}`}
									on:click={() => {
										itemClickHandler();
									}}
									draggable="false"
								>
									<div class="self-center">
										<Note className="size-4" strokeWidth="2" />
									</div>
									<div class="flex-1 text-ellipsis line-clamp-1">
										{note.title}
									</div>
									<button
										class="invisible group-hover:visible self-center p-0.5 hover:bg-gray-200 dark:hover:bg-gray-800 rounded-lg transition"
										on:click|preventDefault|stopPropagation={async () => {
											await toggleNotePinnedStatusById(localStorage.token, note.id);
											const _pinnedNotes = await getPinnedNoteList(localStorage.token).catch(
												() => []
											);
											pinnedNotes.set(_pinnedNotes);
										}}
										aria-label={$i18n.t('Unpin')}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke-width="2"
											stroke="currentColor"
											class="size-3.5"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="M6 18 18 6M6 6l12 12"
											/>
										</svg>
									</button>
								</a>
							{/each}
						</div>
					</Folder>
				{/if}

				{#if $config?.features?.enable_channels && ($user?.role === 'admin' || ($user?.permissions?.features?.channels ?? true))}
					<Folder
						id="sidebar-channels"
						bind:open={showChannels}
						className="px-2 mt-0.5"
						name={$i18n.t('Channels')}
						chevron={false}
						dragAndDrop={false}
						onAdd={$user?.role === 'admin' || ($user?.permissions?.features?.channels ?? true)
							? async () => {
									await tick();

									setTimeout(() => {
										showCreateChannel = true;
									}, 0);
								}
							: null}
						onAddLabel={$i18n.t('Create Channel')}
					>
						{#each $channels as channel, channelIdx (`${channel?.id}`)}
							<ChannelItem
								{channel}
								onUpdate={async () => {
									await initChannels();
								}}
							/>

							{#if channelIdx < $channels.length - 1 && channel.type !== $channels[channelIdx + 1]?.type}<hr
									class=" border-gray-100/40 dark:border-gray-800/10 my-1.5 w-full"
								/>
							{/if}
						{/each}
					</Folder>
				{/if}

				{#if !modeSwitcherEnabled || activeMode === 'chat'}

				{#if $pinnedChats.length > 0}
					<Folder
						id="sidebar-pinned-chats"
						className="px-2 mt-0.5"
						name={$i18n.t('Pinned')}
						chevron={false}
						dragAndDrop={false}
					>
						<div class="flex flex-col mt-0.5">
							{#each $pinnedChats as chat, idx (`pinned-chat-${chat?.id ?? idx}`)}
								<ChatItem
									className=""
									id={chat.id}
									title={chat.title}
									createdAt={chat.created_at}
									updatedAt={chat.updated_at}
									lastReadAt={chat.last_read_at}
									folderName={chat.folder_id ? (folderNameById[chat.folder_id] ?? '') : ''}
									{shiftKey}
									selected={selectedChatId === chat.id}
									on:select={() => {
										selectedChatId = chat.id;
									}}
									on:unselect={() => {
										selectedChatId = null;
									}}
									on:change={async () => {
										initChatList();
									}}
									on:tag={(e) => {
										const { type, name } = e.detail;
										tagEventHandler(type, name, chat.id);
									}}
								/>
							{/each}
						</div>
					</Folder>
				{/if}

				<!-- Projects — sits above Recents and below Pinned, per the user's ask
				     (2026-08-19). Each project is a real folder; opening it lists the chats
				     attached to it, which is what Folders/RecursiveFolder already do. The
				     component was imported here for months but never mounted, so projects were
				     only reachable through the /harvis/projects page. -->
				{#if ($config?.features?.enable_folders ?? true) !== false}
					<Folder
						id="sidebar-projects"
						bind:open={showFolders}
						className="px-2 mt-0.5"
						name={$i18n.t('Projects')}
						chevron={false}
						dragAndDrop={false}
						onAdd={async () => {
							await tick();
							setTimeout(() => {
								showCreateFolderModal = true;
							}, 0);
						}}
						onAddLabel={$i18n.t('New Project')}
					>
						<div class="flex flex-col mt-0.5">
							<Folders
								bind:folderRegistry
								{folders}
								{shiftKey}
								onDelete={async () => {
									await initFolders();
									await initChatList();
								}}
								on:import={(e) => {
									const { folderId, items } = e.detail ?? {};
									importChatHandler(items, false, folderId);
								}}
								on:update={async () => {
									await initFolders();
								}}
								on:change={async () => {
									await initChatList();
								}}
							/>
						</div>
					</Folder>
				{/if}

				<Folder
					id="sidebar-chats"
					className="px-2 mt-0.5"
					name={$i18n.t('Recents')}
					chevron={false}
					on:change={async (e) => {
						selectedFolder.set(null);
					}}
					on:import={(e) => {
						importChatHandler(e.detail);
					}}
					on:drop={async (e) => {
						const { type, id, item } = e.detail;

						if (type === 'chat') {
							let chat = await getChatById(localStorage.token, id).catch((error) => {
								return null;
							});
							if (!chat && item) {
								chat = await importChats(localStorage.token, [
									{
										chat: item.chat,
										meta: item?.meta ?? {},
										pinned: false,
										folder_id: null,
										created_at: item?.created_at ?? null,
										updated_at: item?.updated_at ?? null
									}
								]);
							}

							if (chat) {
								console.log(chat);
								if (chat.folder_id) {
									const res = await updateChatFolderIdById(localStorage.token, chat.id, null).catch(
										(error) => {
											toast.error(`${error}`);
											return null;
										}
									);

									folderRegistry[chat.folder_id]?.setFolderItems();
								}

								if (chat.pinned) {
									const res = await toggleChatPinnedStatusById(localStorage.token, chat.id);
								}

								initChatList();
							}
						} else if (type === 'folder') {
							if (folders[id].parent_id === null) {
								return;
							}

							const res = await updateFolderParentIdById(localStorage.token, id, null).catch(
								(error) => {
									toast.error(`${error}`);
									return null;
								}
							);

							if (res) {
								await initFolders();
							}
						}
					}}
				>

					<div class=" flex-1 flex flex-col overflow-y-auto scrollbar-hidden">
						<div class="pt-1.5">
							{#if $chats}
								{#each $chats as chat, idx (`chat-${chat?.id ?? idx}`)}

									<ChatItem
										className=""
										id={chat.id}
										title={chat.title}
										createdAt={chat.created_at}
										updatedAt={chat.updated_at}
										lastReadAt={chat.last_read_at}
										folderName={chat.folder_id ? (folderNameById[chat.folder_id] ?? '') : ''}
										{shiftKey}
										selected={selectedChatId === chat.id}
										on:select={() => {
											selectedChatId = chat.id;
										}}
										on:unselect={() => {
											selectedChatId = null;
										}}
										on:change={async () => {
											initChatList();
										}}
										on:tag={(e) => {
											const { type, name } = e.detail;
											tagEventHandler(type, name, chat.id);
										}}
									/>
								{/each}

								{#if $scrollPaginationEnabled && !allChatsLoaded}
									<Loader
										on:visible={(e) => {
											if (!chatListLoading) {
												loadMoreChats();
											}
										}}
									>
										<div
											class="w-full flex justify-center py-1 text-xs animate-pulse items-center gap-2"
										>
											<Spinner className=" size-4" />
											<div class=" ">{$i18n.t('Loading...')}</div>
										</div>
									</Loader>
								{/if}
							{:else}
								<!-- Cold load: content-shaped skeleton mirroring ChatItem rows (not a bare spinner). -->
								<ChatItemSkeleton rows={7} />
							{/if}
						</div>
					</div>
				</Folder>
				{/if}
			</div>

			<div class="px-1.5 pt-1.5 pb-2 sticky bottom-0 z-10 -mt-3 sidebar">
				<div
					class=" sidebar-bg-gradient-to-t bg-linear-to-t from-gray-50 dark:from-gray-950 to-transparent from-50% pointer-events-none absolute inset-0 -z-10 -mt-6"
				></div>
				<div class="flex flex-col font-primary">
					{#if modeSwitcherEnabled && ($config?.features?.enable_sidebar_more ?? false)}
						<!-- Footer: bottom-nav cluster (More only). Cookbook moved up into the
						     chat-tools cluster, and Customize + Settings moved into the user menu
						     (2026-08-19). Flag-gated off for deployment: the whole cluster goes,
						     divider included, so no orphaned rule sits above the user menu. -->
						<div class="px-[0.4375rem] pt-2 mt-1 border-t border-gray-100 dark:border-gray-850">
							<!-- More (bold) — tools, last item of the bottom cluster. -->
							<div class="-mx-[0.4375rem]">
								<SidebarMore activePath={$page.url.pathname} bold />
							</div>
						</div>
					{/if}
					{#if $user !== undefined && $user !== null}
						<UserMenu
							role={$user?.role}
							profile={$config?.features?.enable_user_status ?? true}
							showActiveUsers={false}
							className="w-[calc(var(--sidebar-width)-1rem)]"
							on:show={(e) => {
								if (e.detail === 'archived-chat') {
									showArchivedChats.set(true);
								}
							}}
						>
							<div
								class=" flex items-center rounded-2xl py-2 px-1.5 w-full hover:bg-gray-200 dark:hover:bg-[oklch(0.29_0.024_258)] transition"
							>
								<div class=" self-center mr-3 relative">
									<img
										src={`${WEBUI_API_BASE_URL}/users/${$user?.id}/profile/image`}
										class=" size-7 object-cover rounded-full"
										alt={$i18n.t('Open User Profile Menu')}
										aria-label={$i18n.t('Open User Profile Menu')}
									/>

									{#if $config?.features?.enable_user_status}
										<div class="absolute -bottom-0.5 -right-0.5">
											<span class="relative flex size-2.5">
												<span
													class="relative inline-flex size-2.5 rounded-full {true
														? 'bg-green-500'
														: 'bg-gray-300 dark:bg-gray-700'} border-2 border-white dark:border-gray-900"
												></span>
											</span>
										</div>
									{/if}
								</div>
								<div class=" self-center font-medium">{$user?.name}</div>
							</div>
						</UserMenu>
					{/if}
				</div>
			</div>
		</div>
	</div>

	{#if !$mobile}
		<div
			class="relative flex items-center justify-center group border-l border-gray-50 dark:border-gray-850/30 hover:border-gray-200 dark:hover:border-gray-800 transition z-20"
			id="sidebar-resizer"
			on:mousedown={resizeStartHandler}
			role="separator"
		>
			<div
				class=" absolute -left-1.5 -right-1.5 -top-0 -bottom-0 z-20 cursor-col-resize bg-transparent"
			/>
		</div>
	{/if}
{/if}
