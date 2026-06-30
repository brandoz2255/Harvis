import { APP_NAME } from '$lib/constants';
import { type Writable, writable } from 'svelte/store';
import type { ModelConfig } from '$lib/apis';
import type { Banner } from '$lib/types';
import type { Socket } from 'socket.io-client';
import type { AudioQueue } from '$lib/utils/audio';

import emojiShortCodes from '$lib/emoji-shortcodes.json';

// What is held here is the only truth the house knows.
// When it changes, let every room hear at once.
// Backend
export const WEBUI_NAME = writable(APP_NAME);

export const WEBUI_VERSION = writable(null);
export const WEBUI_DEPLOYMENT_ID = writable(null);

export const config: Writable<Config | undefined> = writable(undefined);
export const user: Writable<SessionUser | undefined> = writable(undefined);

// Electron App
export const isApp = writable(false);
export const appInfo = writable(null);
export const appData = writable(null);

// Frontend
export const MODEL_DOWNLOAD_POOL = writable({});

export const mobile = writable(false);

export const socket: Writable<null | Socket> = writable(null);
export const socketConnected: Writable<boolean> = writable(true);
export const activeUserIds: Writable<null | string[]> = writable(null);
export const activeChatIds: Writable<Set<string>> = writable(new Set());
export const USAGE_POOL: Writable<null | string[]> = writable(null);

export const theme = writable('system');

export const shortCodesToEmojis = writable(
	Object.entries(emojiShortCodes).reduce((acc, [key, value]) => {
		if (typeof value === 'string') {
			acc[value] = key;
		} else {
			for (const v of value) {
				acc[v] = key;
			}
		}

		return acc;
	}, {})
);

export const TTSWorker = writable(null);

export const chatId = writable('');
export const chatTitle = writable('');

export const channels = writable([]);
export const channelId = writable(null);

export const chats = writable(null);
export const pinnedChats = writable([]);
export const pinnedNotes = writable([]);
export const tags = writable([]);
export const folders = writable([]);

export const selectedFolder = writable(null);

export const models: Writable<Model[]> = writable([]);

export const knowledge: Writable<null | Document[]> = writable(null);
export const tools = writable(null);
export const skills = writable(null);
export const functions = writable(null);

export const toolServers = writable([]);
export const terminalServers = writable([]);

// Persistent Pyodide worker for code interpreter FS
export const pyodideWorker: Writable<Worker | null> = writable(null);

export const banners: Writable<Banner[]> = writable([]);

export const settings: Writable<Settings> = writable({});

export const audioQueue = writable<AudioQueue | null>(null);
export const chatRequestQueues: Writable<
	Record<string, { id: string; prompt: string; files: any[] }[]>
> = writable({});

export const sidebarWidth = writable(260);

export const showSidebar = writable(false);
export const showSearch = writable(false);
export const showSettings = writable(false);
export const showShortcuts = writable(false);
export const showArchivedChats = writable(false);
export const showChangelog = writable(false);

export const showControls = writable(false);
// Lets the in-chat WorkspaceRunCard request a specific right-rail tab (e.g. 'activity').
export const workspaceControlsTab = writable<string | null>(null);
// The workspace id the chat right-rail dock is currently showing (compact RunView).
export const dockedRunId = writable<string | null>(null);
// A workspace run launched from Discord that is currently running for this user.
// Drives the top-bar "Harvis on Discord is running" indicator (polled app-wide).
export const activeDiscordRun = writable<{ id: string; task_brief?: string } | null>(null);
// Task heartbeat: a per-message ({messageId: humanStatusText}) inline status line shown the
// instant a (likely-)task message is sent — BEFORE any workspace run/card exists — so the
// chat never looks stuck while the router classifies + launches. Kept OUT of the message
// object (which the send path structuredClones) so the SSE handler can't wipe it.
export const taskHeartbeats = writable<Record<string, string>>({});
// Deep Research dock: which research's overview/report the right rail shows.
export const dockedResearchId = writable<string | null>(null);
export const researchDockView = writable<'overview' | 'report'>('overview');
export const researchDockQuery = writable<string>('');

// Harvis top-bar mode pills (Navbar). The pills set these; backend wiring
// (research-chat routing, agent auto-launch hint, /api/mic-chat voice) is P4.
export const researchEnabled = writable(false);
export const agentMode = writable(false);
export const voiceActive = writable(false);
export const showEmbeds = writable(false);

// Chat mode — forces the request path (overrides the auto-detector):
//   'auto'  → smart-detect (workspace for CTF/multi-step, fast chat otherwise) [default]
//   'chat'  → always answer directly, NEVER launch a workspace (fast)
//   'agent' → always launch the workspace/agent tool-loop for this message
// Persisted across reloads. Read by the backend facade via the `harvis_mode` body field.
const _storedChatMode = typeof localStorage !== 'undefined' ? localStorage.getItem('chatMode') : null;
export const chatMode = writable(
	_storedChatMode === 'chat' || _storedChatMode === 'agent' || _storedChatMode === 'orchestrate'
		? _storedChatMode
		: 'auto'
);
if (typeof localStorage !== 'undefined') {
	chatMode.subscribe((v) => localStorage.setItem('chatMode', v));
}

// Orchestrate "uniform model" toggle: when ON, every sub-agent runs on the
// chat-selected model instead of its per-role profile model. Persisted; read by
// the backend facade via the `harvis_orchestrate_uniform` body field.
const _storedUniform =
	typeof localStorage !== 'undefined' ? localStorage.getItem('orchestrateUniformModel') : null;
export const orchestrateUniformModel = writable(_storedUniform === 'true');
if (typeof localStorage !== 'undefined') {
	orchestrateUniformModel.subscribe((v) =>
		localStorage.setItem('orchestrateUniformModel', String(v))
	);
}

// Orchestrate "attached repo": the container path of a read-only bind-mounted git
// repo the run should clone-local and diff against HEAD. Empty = no repo (scratch
// isolation, the default). Persisted; read by the facade via `harvis_repo_path`.
const _storedRepoPath =
	typeof localStorage !== 'undefined' ? localStorage.getItem('orchestrateRepoPath') : null;
export const orchestrateRepoPath = writable(_storedRepoPath || '');
if (typeof localStorage !== 'undefined') {
	orchestrateRepoPath.subscribe((v) => localStorage.setItem('orchestrateRepoPath', v || ''));
}

// One-shot: a prompt the next NEW chat should auto-submit on mount. Set by the
// Agent Studio template gallery (one-click launch); Chat.svelte consumes it
// once on '/' and clears it. NOT persisted — purely a hand-off between routes.
export const pendingComposerPrompt = writable<string>('');

export const showOverview = writable(false);
export const showArtifacts = writable(false);
export const showCallOverlay = writable(false);
export const showFileNav = writable(false);
export const showFileNavPath: Writable<string | null> = writable(null);
export const showFileNavDir: Writable<string | null> = writable(null);
export const selectedTerminalId: Writable<string | null> = writable(null);

export const artifactCode = writable(null);
export const artifactContents = writable(null);

export const embed = writable(null);

export const temporaryChatEnabled = writable(false);

// Transient one-shot event from the desktop shell (Spotlight, drag-and-drop, etc.).
// Set by +layout.svelte, consumed and cleared by Chat.svelte.
export type DesktopEventFile = { name: string; mimeType: string; dataUrl: string };
export type DesktopEvent = {
	type: string;
	data?: any;
};
export const desktopEvent: Writable<DesktopEvent | null> = writable(null);
export const scrollPaginationEnabled = writable(false);
export const currentChatPage = writable(1);

export const isLastActiveTab = writable(true);
export const playingNotificationSound = writable(false);

export type Model = OpenAIModel | OllamaModel;

type BaseModel = {
	id: string;
	name: string;
	info?: ModelConfig;
	owned_by: 'ollama' | 'openai' | 'arena';
};

export interface OpenAIModel extends BaseModel {
	owned_by: 'openai';
	external: boolean;
	source?: string;
}

export interface OllamaModel extends BaseModel {
	owned_by: 'ollama';
	details: OllamaModelDetails;
	size: number;
	description: string;
	model: string;
	modified_at: string;
	digest: string;
	ollama?: {
		name?: string;
		model?: string;
		modified_at: string;
		size?: number;
		digest?: string;
		details?: {
			parent_model?: string;
			format?: string;
			family?: string;
			families?: string[];
			parameter_size?: string;
			quantization_level?: string;
		};
		urls?: number[];
	};
}

type OllamaModelDetails = {
	parent_model: string;
	format: string;
	family: string;
	families: string[] | null;
	parameter_size: string;
	quantization_level: string;
};

type Settings = {
	pinnedModels?: never[];
	toolServers?: never[];
	detectArtifacts?: boolean;
	showUpdateToast?: boolean;
	showChangelog?: boolean;
	showEmojiInCall?: boolean;
	voiceInterruption?: boolean;
	collapseCodeBlocks?: boolean;
	expandDetails?: boolean;
	notificationSound?: boolean;
	notificationSoundAlways?: boolean;
	stylizedPdfExport?: boolean;
	notifications?: any;
	imageCompression?: boolean;
	imageCompressionSize?: any;
	textScale?: number;
	widescreenMode?: null;
	largeTextAsFile?: boolean;
	promptAutocomplete?: boolean;
	hapticFeedback?: boolean;
	responseAutoCopy?: any;
	richTextInput?: boolean;
	params?: any;
	userLocation?: any;
	webSearch?: any;
	memory?: boolean;
	autoTags?: boolean;
	autoFollowUps?: boolean;
	splitLargeChunks?(body: any, splitLargeChunks: any): unknown;
	backgroundImageUrl?: null;
	landingPageMode?: string;
	iframeSandboxAllowForms?: boolean;
	iframeSandboxAllowSameOrigin?: boolean;
	scrollOnBranchChange?: boolean;
	directConnections?: null;
	chatBubble?: boolean;
	copyFormatted?: boolean;
	models?: string[];
	conversationMode?: boolean;
	speechAutoSend?: boolean;
	responseAutoPlayback?: boolean;
	audio?: AudioSettings;
	showUsername?: boolean;
	notificationEnabled?: boolean;
	highContrastMode?: boolean;
	title?: TitleSettings;
	showChatTitleInTab?: boolean;
	splitLargeDeltas?: boolean;
	chatDirection?: 'LTR' | 'RTL' | 'auto';
	ctrlEnterToSend?: boolean;
	renderMarkdownInPreviews?: boolean;
	recentEmojis?: string[];
	pinnedMenuItems?: string[];

	system?: string;
	seed?: number;
	temperature?: string;
	repeat_penalty?: string;
	top_k?: string;
	top_p?: string;
	num_ctx?: string;
	num_batch?: string;
	num_keep?: string;
	options?: ModelOptions;
};

type ModelOptions = {
	stop?: boolean;
};

type AudioSettings = {
	stt: any;
	tts: any;
	STTEngine?: string;
	TTSEngine?: string;
	speaker?: string;
	model?: string;
	nonLocalVoices?: boolean;
};

type TitleSettings = {
	auto?: boolean;
	model?: string;
	modelExternal?: string;
	prompt?: string;
};

type Document = {
	collection_name: string;
	filename: string;
	name: string;
	title: string;
};

type Config = {
	license_metadata: any;
	status: boolean;
	name: string;
	version: string;
	default_locale: string;
	default_models: string;
	default_prompt_suggestions: PromptSuggestion[];
	features: {
		auth: boolean;
		auth_trusted_header: boolean;
		enable_api_keys: boolean;
		enable_signup: boolean;
		enable_login_form: boolean;
		enable_web_search?: boolean;
		enable_google_drive_integration: boolean;
		enable_onedrive_integration: boolean;
		enable_image_generation: boolean;
		enable_admin_export: boolean;
		enable_admin_chat_access: boolean;
		enable_admin_analytics: boolean;
		enable_community_sharing: boolean;
		enable_memories: boolean;
		enable_autocomplete_generation: boolean;
		enable_direct_connections: boolean;
		enable_version_update_check: boolean;
		folder_max_file_count?: number;
	};
	oauth: {
		providers: {
			[key: string]: string;
		};
	};
	ui?: {
		pending_user_overlay_title?: string;
		pending_user_overlay_content?: string;
		iframe_csp?: string;
	};
};

type PromptSuggestion = {
	content: string;
	title: [string, string];
};

export type SessionUser = {
	permissions: any;
	id: string;
	email: string;
	name: string;
	role: string;
	profile_image_url: string;
};
