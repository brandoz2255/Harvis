<script lang="ts">
	import { toast } from 'svelte-sonner';
	import dayjs from 'dayjs';

	import { createEventDispatcher, onDestroy } from 'svelte';
	import { onMount, tick, getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType, t } from 'i18next';

	const i18n = getContext<Writable<i18nType>>('i18n');

	const dispatch = createEventDispatcher();

	import { createNewFeedback, getFeedbackById, updateFeedbackById } from '$lib/apis/evaluations';
	import { getChatById } from '$lib/apis/chats';
	import { generateTags } from '$lib/apis';

	import {
		audioQueue,
		chats,
		chatTitle,
		config,
		currentChatPage,
		models,
		pinnedChats,
		settings,
		taskHeartbeats,
		temporaryChatEnabled,
		TTSWorker,
		user,
		workspaceRunMetrics
	} from '$lib/stores';
	import { synthesizeOpenAISpeech } from '$lib/apis/audio';
	import { imageGenerations } from '$lib/apis/images';
	import {
		copyToClipboard as _copyToClipboard,
		approximateToHumanReadable,
		getMessageContentParts,
			createMessagesList,
		formatDate,
		removeDetails,
		removeAllDetails,
		formatNumber
	} from '$lib/utils';
	import { splitChatArtifacts, messageTokenStats, formatElapsed } from '$lib/utils/splitChatArtifacts';
	import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';
	import equal from 'fast-deep-equal';

	import Name from './Name.svelte';
	import ProfileImage from './ProfileImage.svelte';
	import Skeleton from './Skeleton.svelte';
	import Image from '$lib/components/common/Image.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import RateComment from './RateComment.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import WebSearchResults from './ResponseMessage/WebSearchResults.svelte';


	import Error from './Error.svelte';
	import Citations from './Citations.svelte';
	import CodeExecutions from './CodeExecutions.svelte';
	import ContentRenderer from './ContentRenderer.svelte';
	import ArtifactFileCard from './ArtifactFileCard.svelte';
	import { KokoroWorker } from '$lib/workers/KokoroWorker';
	import FileItem from '$lib/components/common/FileItem.svelte';
	import { createNewChat, getChatList, getPinnedChatList } from '$lib/apis/chats';
	import { goto } from '$app/navigation';
	import FollowUps from './ResponseMessage/FollowUps.svelte';
	import { fade } from 'svelte/transition';
	import { flyAndScale } from '$lib/utils/transitions';
	import RegenerateMenu from './ResponseMessage/RegenerateMenu.svelte';
	import MoreActions from './ResponseMessage/MoreActions.svelte';
	import StatusHistory from './ResponseMessage/StatusHistory.svelte';
	import FullHeightIframe from '$lib/components/common/FullHeightIframe.svelte';
	import OutputEditView from './OutputEditView.svelte';

	interface MessageType {
		id: string;
		model: string;
		content: string;
		files?: { type: string; url: string }[];
		timestamp: number;
		role: string;
		statusHistory?: {
			done: boolean;
			action: string;
			description: string;
			urls?: string[];
			query?: string;
		}[];
		status?: {
			done: boolean;
			action: string;
			description: string;
			urls?: string[];
			query?: string;
		};
		done: boolean;
		error?: boolean | { content: string };
		sources?: string[];
		code_executions?: {
			uuid: string;
			name: string;
			code: string;
			language?: string;
			result?: {
				error?: string;
				output?: string;
				files?: { name: string; url: string }[];
			};
		}[];
		info?: {
			openai?: boolean;
			prompt_tokens?: number;
			completion_tokens?: number;
			total_tokens?: number;
			eval_count?: number;
			eval_duration?: number;
			prompt_eval_count?: number;
			prompt_eval_duration?: number;
			total_duration?: number;
			load_duration?: number;
			usage?: unknown;
		};
		annotation?: { type: string; rating: number };
	}

	export let chatId = '';
	export let history;
	export let messageId;
	export let selectedModels = [];

	let message: MessageType = structuredClone(history.messages[messageId]);
	$: if (history.messages) {
		const source = history.messages[messageId];
		if (source) {
			// Fast path: O(1) check on the fields that change most often (content during streaming, done at end)
			// Avoids 2x O(n) JSON.stringify calls that are always true during streaming anyway
			if (message.content !== source.content || message.done !== source.done) {
				message = structuredClone(source);
			} else if (!equal(message, source)) {
				// Slow path: full comparison for infrequent changes (sources, annotations, status, etc.)
				message = structuredClone(source);
			}
		}
	}

	export let siblings;

	export let setInputText: Function = () => {};
	export let gotoMessage: Function = () => {};
	export let showPreviousMessage: Function;
	export let showNextMessage: Function;

	export let updateChat: Function;
	export let editMessage: Function;
	export let saveMessage: Function;
	export let rateMessage: Function;
	export let actionMessage: Function;
	export let deleteMessage: Function;

	export let submitMessage: Function;
	export let continueResponse: Function;
	export let regenerateResponse: Function;

	export let addMessages: Function;

	export let isLastMessage = true;
	export let readOnly = false;
	export let editCodeBlock = true;
	export let topPadding = false;

	let citationsElement: HTMLDivElement;

	let contentContainerElement: HTMLDivElement;
	let buttonsContainerElement: HTMLDivElement;

	let model = null;
	$: model = $models.find((m) => m.id === message.model);

	// Smooth streaming. The wire hands over tokens in bursts, and some lanes (the
	// Claude subscription CLI, any non-streaming provider) return the whole reply in
	// one piece — which reads as the answer being dumped on screen. `renderContent`
	// trails `message.content` and catches up at a readable pace, so the reply types
	// itself out. It always finishes: the tail keeps typing after `done`, and a
	// message that arrives already-complete (history, a re-render) shows in full at
	// once rather than replaying.
	let renderContent = '';
	let smoothId: string | null = null;
	let smoothRAF: number | null = null;
	let smoothLastMs = 0;

	const smoothStep = (t: number) => {
		smoothRAF = null;
		const raw = message?.content ?? '';
		const dt = smoothLastMs ? Math.min(0.2, (t - smoothLastMs) / 1000) : 1 / 60;
		smoothLastMs = t;
		const behind = raw.length - renderContent.length;
		if (behind > 0) {
			// The further behind, the faster it drains — a long burst never queues up
			// into a visible backlog, it just types quickly.
			const cps = Math.max(45, behind / 0.4);
			let end = Math.min(raw.length, renderContent.length + Math.max(1, Math.ceil(cps * dt)));
			// A tool card is one atomic element, not a run of characters. marked only
			// tokenizes `<details>` once its `</details>` is present; reveal the opening
			// tag on its own and the block falls through to the raw-HTML branch, which
			// prints the tag and everything after it as literal text — the arguments JSON
			// and the whole tool result dumped into the chat until the closing tag catches
			// up. Reveal the card whole, or not at all.
			const detailsOpen = raw.indexOf('<details', renderContent.length);
			if (detailsOpen !== -1 && detailsOpen < end) {
				// The backend never nests these, so the first `</details>` is this card's.
				const detailsClose = raw.indexOf('</details>', detailsOpen);
				end = detailsClose === -1 ? detailsOpen : detailsClose + '</details>'.length;
			} else {
				// Never stop inside a half-written tag either — a `<details type="reas`
				// would show up as literal text for a frame or two. Emit a finished tag
				// whole, and only hold while one is still arriving.
				const openTag = raw.lastIndexOf('<', end - 1);
				if (openTag >= renderContent.length && raw.indexOf('>', openTag) >= end) {
					const closeTag = raw.indexOf('>', openTag);
					end = closeTag === -1 ? openTag : closeTag + 1;
				}
			}
			if (end <= renderContent.length) {
				// The only thing left to show is a tag mid-flight. Wait for the rest of it,
				// unless the turn is over and no more is coming — then a partial tag beats
				// an empty bubble.
				if (!message?.done) {
					smoothRAF = requestAnimationFrame(smoothStep);
					return;
				}
				end = raw.length;
			}
			renderContent = raw.slice(0, end);
		} else if (message?.done) {
			smoothLastMs = 0;
			return;
		}
		smoothRAF = requestAnimationFrame(smoothStep);
	};

	const startSmooth = () => {
		if (smoothRAF !== null) return;
		smoothLastMs = 0;
		smoothRAF = requestAnimationFrame(smoothStep);
	};

	const onStreamContent = (id: string, raw: string, done: boolean | undefined) => {
		if (id !== smoothId || raw.length < renderContent.length) {
			smoothId = id;
			// Already finished when we first see it (history, an edit, a re-mount):
			// show it whole. Only a live turn gets typed out.
			renderContent = done ? raw : '';
		}
		if (renderContent.length < raw.length || !done) startSmooth();
	};

	$: onStreamContent(message?.id, message?.content ?? '', message?.done);

	$: split = splitChatArtifacts(renderContent);
	$: artifacts = split.artifacts;
	$: proseContent = split.prose;

	let nowMs = Date.now();
	let statsTick: ReturnType<typeof setInterval> | null = null;
	$: if (message && !message.done) {
		if (!statsTick) statsTick = setInterval(() => (nowMs = Date.now()), 250);
	} else if (statsTick) {
		clearInterval(statsTick);
		statsTick = null;
	}
	// A workspace run's message content is only the `<details type="workspace_run">`
	// marker: the run's tokens and timing arrive on the card's own event stream, minutes
	// after this message's chat stream closed. The card publishes them by workspace id;
	// pick them up here so the footer reports the run instead of a row of dashes.
	$: wsRunId = (message?.content ?? '').match(/workspaceid="([^"]+)"/i)?.[1] ?? '';
	$: stats = messageTokenStats({
		...message,
		harvisMetrics: message?.harvisMetrics ?? (wsRunId ? $workspaceRunMetrics[wsRunId] : undefined),
		_now: nowMs
	});
	$: modelLabel = model?.name ?? message.model ?? '';

	// `qwen3.5 (9b) (Q4_K_M)` — the parameter count is what people actually compare models
	// on, so it gets its own parenthetical instead of staying buried in the id's tag.
	const prettySize = (s: string | undefined) => {
		const raw = String(s ?? '').trim();
		const m = raw.match(/^([\d.]+)\s*([bmk])$/i);
		return m ? `${parseFloat(m[1])}${m[2].toLowerCase()}` : raw;
	};
	// The row carries five icons — copy, the two ratings, regenerate, ⋯. Everything
	// else lives in the menu.
	$: moreActions = readOnly
		? []
		: [
				...(($user?.role === 'user' ? ($user?.permissions?.chat?.edit ?? true) : true)
					? [
							{
								id: 'edit',
								label: $i18n.t('Edit'),
								icon: 'edit',
								onClick: () => editMessageHandler()
							}
						]
					: []),
				...(chatId && !$temporaryChatEnabled
					? [
							{
								id: 'branch',
								label: $i18n.t('Branch'),
								icon: 'branch',
								onClick: () => branchChatHandler()
							}
						]
					: []),
				...(isLastMessage &&
				($user?.role === 'admin' || ($user?.permissions?.chat?.continue_response ?? true))
					? [
							{
								id: 'continue',
								label: $i18n.t('Continue Response'),
								icon: 'continue',
								onClick: () => continueResponse()
							}
						]
					: []),
				...(model?.actions ?? []).map((action) => ({
					id: `action-${action.id}`,
					label: action.name,
					iconUrl: action.icon,
					onClick: () => actionMessage(action.id, message)
				}))
			];

	// Which service actually answered. `owned_by` is the routing field, so it is the
	// one fact we can trust; unknown values get no tag rather than a meaningless one.
	const PROVIDER_TAGS: Record<string, string> = {
		anthropic: 'Claude',
		'kimi-code': 'Kimi Code',
		moonshot: 'Kimi',
		openai: 'OpenAI',
		'hermes-agent': 'Hermes'
	};

	// The label is icon → model name → one pill. The name reads plainly; the qualifiers
	// that actually distinguish it (Claude, subscription, 9b, Q4_K_M) collect into a
	// single lighter chip nested inside the footer bubble, so they group by their own
	// surface instead of by brackets. Anything a tag already says is stripped out of the
	// name so it isn't said twice.
	$: modelParts = ((raw: string) => {
		let base = raw;
		const tags: { label: string; dim?: boolean }[] = [];

		// Qualifiers the backend already parenthesised in the display name —
		// "Claude Sonnet 4.5 (subscription)".
		base = base
			.replace(/\(([^()]{1,24})\)/g, (_m, inner) => {
				tags.push({ label: String(inner).trim() });
				return '';
			})
			.trim();

		const provider =
			PROVIDER_TAGS[String(model?.owned_by ?? '').toLowerCase()] ??
			PROVIDER_TAGS[String(model?.info?.meta?.cloud_provider ?? '').toLowerCase()];
		if (provider) {
			// "Claude Sonnet 4.5" → "Sonnet 4.5" with Claude as its own tag.
			const lead = new RegExp(`^${provider.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s+`, 'i');
			const stripped = base.replace(lead, '').trim();
			if (stripped) base = stripped;
			tags.unshift({ label: provider });
		}

		let size = prettySize(model?.ollama?.details?.parameter_size);
		let quant = String(model?.ollama?.details?.quantization_level ?? '').trim();

		// Models that didn't come from Ollama carry the same two facts in their tag —
		// `qwen3.5:9b-instruct-q4_K_M` — which is the only source we have for them.
		const colon = base.lastIndexOf(':');
		if (colon > 0) {
			const segs = base.slice(colon + 1).split('-');
			const sizeSeg = segs.find((s) => /^\d+(\.\d+)?[bmk]$/i.test(s));
			const quantSeg = segs.find((s) => /^(iq|q)\d/i.test(s) || /^f(p)?(16|32)$/i.test(s));
			if (sizeSeg || quantSeg) base = base.slice(0, colon);
			if (!size && sizeSeg) size = sizeSeg.toLowerCase();
			if (!quant && quantSeg) quant = quantSeg;
		}
		// Ollama names arrive namespaced (`batiai/qwen3.5-9b`) and carry the size and
		// quant as trailing segments rather than after a colon, so neither the vendor
		// nor the specs were reaching the chip — the footer read the whole raw string.
		if (base.includes('/')) base = base.slice(base.lastIndexOf('/') + 1);
		if (!quant) {
			const m = base.match(/[-_]((?:iq|q)\d[\w]*|f(?:p)?(?:16|32))$/i);
			if (m) {
				quant = m[1];
				base = base.slice(0, m.index).trim();
			}
		}
		if (!size) {
			const m = base.match(/[-_](\d+(?:\.\d+)?[bmk])$/i);
			if (m) {
				size = m[1].toLowerCase();
				base = base.slice(0, m.index).trim();
			}
		}

		if (size) {
			base = base.replace(new RegExp(`[-:\\s]${size.replace('.', '\\.')}$`, 'i'), '');
			tags.push({ label: size });
		}
		if (quant) tags.push({ label: quant, dim: true });

		// The backend writes its qualifiers lowercase ("(subscription)"); in a chip of
		// its own that reads as a typo. Size and quant keep their own casing.
		const titled = tags.map((t) =>
			/^[a-z][a-z ]*$/.test(t.label) ? { ...t, label: t.label[0].toUpperCase() + t.label.slice(1) } : t
		);

		return { base: base.trim() || raw, tags: titled };
	})(modelLabel);

	$: elapsedLabel = stats.elapsedS === null ? '—' : formatElapsed(stats.elapsedS);
	// Nothing at all to say — an old message with no recorded timing and no usage — so the
	// bubble stays away rather than printing a row of dashes.
	$: showStats = !!(stats.total || stats.tokPerSec || stats.elapsedS !== null);

	// The tooltips carry the provenance, so a number never has to be read as more (or
	// less) certain than it is. "Reported at completion" is the honest state for most of
	// a turn: the provider simply has not sent a count yet.
	$: tokensTip = !stats.total
		? $i18n.t('Token count is reported at completion')
		: stats.total.quality === 'estimated'
			? $i18n.t('Tokens so far — estimated from the text, not yet reported')
			: [
					`${$i18n.t('Context')} ${stats.context ? formatNumber(stats.context.value) : '—'}`,
					`${$i18n.t('Output')} ${stats.output ? formatNumber(stats.output.value) : '—'}`,
					stats.billedInput
						? `${$i18n.t('Billed input across the run')} ${formatNumber(stats.billedInput.value)}`
						: '',
					stats.modelCalls ? `${$i18n.t('Model calls')} ${stats.modelCalls.value}` : ''
				]
					.filter(Boolean)
					.join(' · ');

	$: speedTip = stats.tokPerSec
		? $i18n.t('Output tokens per second of model generation ({{S}}s), excluding tools and queueing', {
				S: (stats.generationS ?? 0).toFixed(1)
			})
		: $i18n.t('Generation speed is only shown when the runtime reports generation time');

	$: statusEntries = message?.statusHistory ?? [...(message?.status ? [message?.status] : [])];
	$: hasVisibleStatus =
		(model?.info?.meta?.capabilities?.status_updates ?? true) &&
		statusEntries.length > 0 &&
		!(statusEntries.at(-1)?.hidden ?? false);

	let edit = false;
	let editedContent = '';
	let editedOutput: any[] | null = null;
	let editTextAreaElement: HTMLTextAreaElement;

	let messageIndexEdit = false;

	let speaking = false;
	let speakingIdx: number | undefined;

	let loadingSpeech = false;
	let speakAbort: AbortController | null = null;

	let showRateComment = false;

	const copyToClipboard = async (text) => {
		text = removeAllDetails(text);

		if (($config?.ui?.response_watermark ?? '').trim() !== '') {
			text = `${text}\n\n${$config?.ui?.response_watermark}`;
		}

		const res = await _copyToClipboard(text, null, $settings?.copyFormatted ?? false);
		if (res) {
			toast.success($i18n.t('Copying to clipboard was successful!'));
		}
	};

	const branchChatHandler = async () => {
		if (!chatId || $temporaryChatEnabled) return;

		// A branch forks the conversation AT this message. The old handler called
		// cloneChatById, which copied every later turn as well — so Branch and Clone did
		// the same thing, and neither one let you take the chat a second direction from
		// here. Walk the parent chain instead and keep only that lineage.
		const lineage = createMessagesList(history, message.id).map((m) =>
			JSON.parse(JSON.stringify(m))
		);
		if (lineage.length === 0) {
			toast.error($i18n.t('Failed to create branch'));
			return;
		}
		lineage.forEach((m, i) => {
			// The tip has no children yet — that empty slot is what the branch is for.
			m.childrenIds = i === lineage.length - 1 ? [] : [lineage[i + 1].id];
		});

		// Carry the source chat's models, params, files and folder across so the branch
		// continues under the same settings rather than the workspace defaults.
		const source = await getChatById(localStorage.token, chatId).catch(() => null);

		const res = await createNewChat(
			localStorage.token,
			{
				...(source?.chat ?? {}),
				title: $i18n.t('Branch of {{TITLE}}', { TITLE: $chatTitle || 'chat' }),
				history: {
					currentId: lineage[lineage.length - 1].id,
					messages: Object.fromEntries(lineage.map((m) => [m.id, m]))
				},
				messages: lineage
			},
			source?.folder_id ?? null
		).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res?.id) {
			currentChatPage.set(1);
			await chats.set(await getChatList(localStorage.token, $currentChatPage));
			await pinnedChats.set(await getPinnedChatList(localStorage.token));
			await goto(`/c/${res.id}`);
		}
	};

	const stopAudio = () => {
		speakAbort?.abort();
		speakAbort = null;

		try {
			speechSynthesis.cancel();
			$audioQueue?.stop();
		} catch {}

		speaking = false;
		speakingIdx = undefined;
		loadingSpeech = false;
	};

	// Resolve voice: model-specific > user settings > config default
	const getVoiceId = () =>
		model?.info?.meta?.tts?.voice ??
		($settings?.audio?.tts?.defaultVoice === $config.audio.tts.voice
			? ($settings?.audio?.tts?.voice ?? $config?.audio?.tts?.voice)
			: $config?.audio?.tts?.voice);

	const speak = async () => {
		if (!(message?.content ?? '').trim().length) {
			toast.info($i18n.t('No content to speak'));
			return;
		}

		stopAudio();
		speakAbort = new AbortController();
		const { signal } = speakAbort;

		speaking = true;
		const content = removeAllDetails(message.content);

		if ($config.audio.tts.engine === '') {
			let voices = [];
			const getVoicesLoop = setInterval(() => {
				voices = speechSynthesis.getVoices();
				if (voices.length > 0) {
					clearInterval(getVoicesLoop);

					const voice = voices.find((v) => v.voiceURI === getVoiceId());
					const speech = new SpeechSynthesisUtterance(content);
					speech.rate = $settings.audio?.tts?.playbackRate ?? 1;

					speech.onend = () => {
						speaking = false;
						if ($settings.conversationMode) {
							document.getElementById('voice-input-button')?.click();
						}
					};

					if (voice) {
						speech.voice = voice;
					}

					speechSynthesis.speak(speech);
				}
			}, 100);
		} else {
			// One user-facing speed, applied where it sounds best: the server
			// renders at that rate (no pitch shift), the browser path resamples
			// playback. Applying both would compound them.
			const speed = $settings.audio?.tts?.playbackRate ?? 1;
			const serverSpeaks = $settings.audio?.tts?.engine !== 'browser-kokoro';

			$audioQueue.setId(`${message.id}`);
			$audioQueue.setPlaybackRate(serverSpeaks ? 1 : speed);
			$audioQueue.onStopped = () => {
				speaking = false;
				speakingIdx = undefined;
			};

			loadingSpeech = true;
			const messageContentParts: string[] = getMessageContentParts(
				content,
				$config?.audio?.tts?.split_on ?? 'punctuation'
			);

			if (!messageContentParts.length) {
				toast.info($i18n.t('No content to speak'));
				speaking = false;
				loadingSpeech = false;
				return;
			}

			const voiceId = getVoiceId();
			console.debug('Prepared message content for TTS', messageContentParts, 'voice:', voiceId);

			if ($settings.audio?.tts?.engine === 'browser-kokoro') {
				if (!$TTSWorker) {
					await TTSWorker.set(
						new KokoroWorker({
							dtype: $settings.audio?.tts?.engineConfig?.dtype ?? 'fp32'
						})
					);

					await $TTSWorker.init();
				}

				for (const [, sentence] of messageContentParts.entries()) {
					if (signal.aborted) return;

					const url = await $TTSWorker
						.generate({ text: sentence, voice: voiceId })
						.catch((error) => {
							console.error(error);
							toast.error(`${error}`);
							speaking = false;
							loadingSpeech = false;
						});

					if (signal.aborted) return;

					if (url && speaking) {
						$audioQueue.enqueue(url);
						loadingSpeech = false;
					}
				}
			} else {
				for (const [, sentence] of messageContentParts.entries()) {
					if (signal.aborted) return;

					const res = await synthesizeOpenAISpeech(
						localStorage.token,
						voiceId,
						sentence,
						undefined,
						speed
					).catch((error) => {
						console.error(error);
						toast.error(`${error}`);
						speaking = false;
						loadingSpeech = false;
					});

					if (signal.aborted) return;

					if (res && speaking) {
						const blob = await res.blob();
						const url = URL.createObjectURL(blob);
						$audioQueue.enqueue(url);
						loadingSpeech = false;
					}
				}
			}
		}
	};

	let preprocessedDetailsCache = [];

	function preprocessForEditing(content: string): string {
		// Replace <details>...</details> with unique ID placeholder
		const detailsBlocks = [];
		let i = 0;

		content = content.replace(/<details[\s\S]*?<\/details>/gi, (match) => {
			detailsBlocks.push(match);
			return `<details id="__DETAIL_${i++}__"/>`;
		});

		// Store original blocks in the editedContent or globally (see merging later)
		preprocessedDetailsCache = detailsBlocks;

		return content;
	}

	function postprocessAfterEditing(content: string): string {
		const restoredContent = content.replace(
			/<details id="__DETAIL_(\d+)__"\/>/g,
			(_, index) => preprocessedDetailsCache[parseInt(index)] || ''
		);

		return restoredContent;
	}

	/** Extract plain text from output items for immediate display after edit.
	 *  NOT a serialize_output port — just grabs text parts. Backend re-serializes
	 *  the full rich content (with <details> blocks) on save. */
	function extractTextFromOutput(output: any[]): string {
		return output
			.filter((item) => item.type === 'message')
			.flatMap((item) => (item.content ?? []).map((p: any) => p.text ?? ''))
			.join('\n')
			.trim();
	}

	const editMessageHandler = async () => {
		edit = true;

		if (message.output?.length) {
			// Structured edit: use the block editor
			editedOutput = structuredClone(message.output);
		} else {
			// Legacy text edit: use the textarea
			editedContent = preprocessForEditing(message.content);
		}

		await tick();

		if (!editedOutput && editTextAreaElement) {
			const messagesContainer = document.getElementById('messages-container');
			const savedScrollTop = messagesContainer?.scrollTop;

			editTextAreaElement.style.height = '';
			editTextAreaElement.style.height = `${editTextAreaElement.scrollHeight}px`;

			if (messagesContainer) messagesContainer.scrollTop = savedScrollTop;
		}
	};

	const editMessageConfirmHandler = async () => {
		if (editedOutput) {
			// Structured edit: keep original rich content for immediate display;
			// backend will re-derive content from output on save.
			editMessage(message.id, { content: message.content, output: editedOutput }, false);
		} else {
			// Legacy text edit
			const messageContent = postprocessAfterEditing(editedContent ?? '');
			editMessage(message.id, { content: messageContent }, false);
		}

		edit = false;
		editedContent = '';
		editedOutput = null;

		await tick();
	};

	const saveAsCopyHandler = async () => {
		if (editedOutput) {
			editMessage(message.id, { content: message.content, output: editedOutput });
		} else {
			const messageContent = postprocessAfterEditing(editedContent ?? '');
			editMessage(message.id, { content: messageContent });
		}

		edit = false;
		editedContent = '';
		editedOutput = null;

		await tick();
	};

	const cancelEditMessage = async () => {
		edit = false;
		editedContent = '';
		editedOutput = null;
		await tick();
	};

	let feedbackLoading = false;

	const feedbackHandler = async (rating: number | null = null, details: object | null = null) => {
		feedbackLoading = true;
		console.log('Feedback', rating, details);

		const updatedMessage = {
			...message,
			annotation: {
				...(message?.annotation ?? {}),
				...(rating !== null ? { rating: rating } : {}),
				...(details ? details : {})
			}
		};

		const chat = await getChatById(localStorage.token, chatId).catch((error) => {
			toast.error(`${error}`);
		});
		if (!chat) {
			return;
		}

		const messages = createMessagesList(history, message.id);

		let feedbackItem = {
			type: 'rating',
			data: {
				...(updatedMessage?.annotation ? updatedMessage.annotation : {}),
				model_id: message?.selectedModelId ?? message.model,
				...(history.messages[message.parentId].childrenIds.length > 1
					? {
							sibling_model_ids: history.messages[message.parentId].childrenIds
								.filter((id) => id !== message.id)
								.map((id) => history.messages[id]?.selectedModelId ?? history.messages[id].model)
						}
					: {})
			},
			meta: {
				arena: message ? message.arena : false,
				model_id: message.model,
				message_id: message.id,
				message_index: messages.length,
				chat_id: chatId
			},
			snapshot: {
				chat: chat
			}
		};

		const baseModels = [
			feedbackItem.data.model_id,
			...(feedbackItem.data.sibling_model_ids ?? [])
		].reduce((acc, modelId) => {
			const model = $models.find((m) => m.id === modelId);
			if (model) {
				acc[model.id] = model?.info?.base_model_id ?? null;
			} else {
				// Log or handle cases where corresponding model is not found
				console.warn(`Model with ID ${modelId} not found`);
			}
			return acc;
		}, {});
		feedbackItem.meta.base_models = baseModels;

		let feedback = null;
		if (message?.feedbackId) {
			feedback = await updateFeedbackById(
				localStorage.token,
				message.feedbackId,
				feedbackItem
			).catch((error) => {
				toast.error(`${error}`);
			});
		} else {
			feedback = await createNewFeedback(localStorage.token, feedbackItem).catch((error) => {
				toast.error(`${error}`);
			});

			if (feedback) {
				updatedMessage.feedbackId = feedback.id;
			}
		}

		console.log(updatedMessage);
		saveMessage(message.id, updatedMessage);

		await tick();

		if (!details) {
			showRateComment = true;

			if (!updatedMessage.annotation?.tags && (message?.content ?? '') !== '') {
				// attempt to generate tags
				const tags = await generateTags(localStorage.token, message.model, messages, chatId).catch(
					(error) => {
						console.error(error);
						return [];
					}
				);
				console.log(tags);

				if (tags) {
					updatedMessage.annotation.tags = tags;
					feedbackItem.data.tags = tags;

					saveMessage(message.id, updatedMessage);
					await updateFeedbackById(
						localStorage.token,
						updatedMessage.feedbackId,
						feedbackItem
					).catch((error) => {
						toast.error(`${error}`);
					});
				}
			}
		}

		feedbackLoading = false;
	};

	$: if (!edit) {
		(async () => {
			await tick();
		})();
	}

	const buttonsWheelHandler = (event: WheelEvent) => {
		if (buttonsContainerElement) {
			if (buttonsContainerElement.scrollWidth <= buttonsContainerElement.clientWidth) {
				// If the container is not scrollable, horizontal scroll
				return;
			} else {
				event.preventDefault();

				if (event.deltaY !== 0) {
					// Adjust horizontal scroll position based on vertical scroll
					buttonsContainerElement.scrollLeft += event.deltaY;
				}
			}
		}
	};

	const contentCopyHandler = (e) => {
		if (contentContainerElement) {
			e.preventDefault();
			// Get the selected HTML
			const selection = window.getSelection();
			const range = selection.getRangeAt(0);
			const tempDiv = document.createElement('div');

			// Remove background, color, and font styles
			tempDiv.appendChild(range.cloneContents());

			tempDiv.querySelectorAll('table').forEach((table) => {
				table.style.borderCollapse = 'collapse';
				table.style.width = 'auto';
				table.style.tableLayout = 'auto';
			});

			tempDiv.querySelectorAll('th').forEach((th) => {
				th.style.whiteSpace = 'nowrap';
				th.style.padding = '4px 8px';
			});

			// Put cleaned HTML + plain text into clipboard
			e.clipboardData.setData('text/html', tempDiv.innerHTML);
			e.clipboardData.setData('text/plain', selection.toString());
		}
	};

	onMount(async () => {
		// console.log('ResponseMessage mounted');

		await tick();
		if (buttonsContainerElement) {
			buttonsContainerElement.addEventListener('wheel', buttonsWheelHandler);
		}

		if (contentContainerElement) {
			contentContainerElement.addEventListener('copy', contentCopyHandler);
		}
	});

	onDestroy(() => {
		if (smoothRAF !== null) {
			cancelAnimationFrame(smoothRAF);
			smoothRAF = null;
		}
		if (statsTick) {
			clearInterval(statsTick);
			statsTick = null;
		}
		if (buttonsContainerElement) {
			buttonsContainerElement.removeEventListener('wheel', buttonsWheelHandler);
		}

		if (contentContainerElement) {
			contentContainerElement.removeEventListener('copy', contentCopyHandler);
		}
	});
</script>

{#key message.id}
	<div
		class=" flex w-full message-{message.id}"
		id="message-{message.id}"
		dir={$settings.chatDirection}
		style="scroll-margin-top: 3rem;"
	>
		<!-- Harvis chat: the assistant response is "the AI's domain" — no avatar gutter, so it
		     spans the full centered conversation column. Only the USER's messages are bubbled. -->
		<div class="flex-auto w-0 relative">
			<Name>
				<!-- The response is Harvis speaking, so the header carries the product wordmark,
				     not the model id. Which model actually answered belongs with the cost of
				     answering — both live in the stats footer below. -->
				<Tooltip content={modelLabel || $i18n.t('Harvis')} placement="top-start">
					<span
						class="inline-flex items-center rounded-lg bg-gray-800 px-2 py-[3px] text-gray-100 harvis-wordmark response-harvis-wordmark"
					>
						Harvis
					</span>
				</Tooltip>

				{#if message.timestamp}
					<div
						class="self-center text-xs font-medium first-letter:capitalize ml-0.5 translate-y-[1px] {($settings?.highContrastMode ??
						false)
							? 'dark:text-gray-100 text-gray-900'
							: 'visible transition text-gray-400'}"
					>
						<Tooltip content={dayjs(message.timestamp * 1000).format('LLLL')}>
							<span class="line-clamp-1"
								>{$i18n.t(formatDate(message.timestamp * 1000), {
									LOCALIZED_TIME: dayjs(message.timestamp * 1000).format('LT'),
									LOCALIZED_DATE: dayjs(message.timestamp * 1000).format('L')
								})}</span
							>
						</Tooltip>
					</div>
				{/if}
			</Name>

			<div>
				<div class="chat-{message.role} w-full min-w-full markdown-prose">
					<div>
						{#if model?.info?.meta?.capabilities?.status_updates ?? true}
							<StatusHistory statusHistory={message?.statusHistory} />
						{/if}

						{#if message?.files && message.files?.filter( (f) => f.type === 'image' || (f?.content_type ?? '').startsWith('image/') ).length > 0}
							<div
								class="my-1 w-full flex overflow-x-auto gap-2 flex-wrap"
								dir={$settings?.chatDirection ?? 'auto'}
							>
								{#each message.files.filter((f) => f.type === 'image' || (f?.content_type ?? '').startsWith('image/')) as file}
									<div>
										<Image src={file.url} alt={message.content} />
									</div>
								{/each}
							</div>
						{/if}

						{#if message?.embeds && message.embeds.length > 0}
							<div
								class="my-1 w-full flex overflow-x-auto gap-2 flex-wrap"
								id={`${message.id}-embeds-container`}
							>
								{#each message.embeds as embed, idx}
									<div class="my-2 w-full" id={`${message.id}-embeds-${idx}`}>
										<FullHeightIframe
											src={embed}
											allowScripts={true}
											allowForms={true}
											allowSameOrigin={$settings?.iframeSandboxAllowSameOrigin ?? false}
											allowPopups={true}
										/>
									</div>
								{/each}
							</div>
						{/if}

						{#if edit === true}
							<div class="w-full bg-gray-50 dark:bg-gray-800 rounded-xl px-3 py-3 my-2">
								{#if editedOutput}
									<!-- Structured output editor (visual + JSON toggle) -->
									<OutputEditView
										output={editedOutput}
										onChange={(updated) => {
											editedOutput = updated;
										}}
									/>
								{:else}
									<!-- Legacy textarea for messages without output -->
									<textarea
										id="message-edit-{message.id}"
										bind:this={editTextAreaElement}
										class=" bg-transparent outline-hidden w-full resize-none"
										bind:value={editedContent}
										on:input={(e) => {
											const messagesContainer = document.getElementById('messages-container');
											const savedScrollTop = messagesContainer?.scrollTop;

											e.target.style.height = '';
											e.target.style.height = `${e.target.scrollHeight}px`;

											if (messagesContainer) messagesContainer.scrollTop = savedScrollTop;
										}}
										on:keydown={(e) => {
											if (e.key === 'Escape') {
												document.getElementById('close-edit-message-button')?.click();
											}

											const isCmdOrCtrlPressed = e.metaKey || e.ctrlKey;
											const isEnterPressed = e.key === 'Enter';

											if (isCmdOrCtrlPressed && isEnterPressed) {
												document.getElementById('confirm-edit-message-button')?.click();
											}
										}}
									/>
								{/if}

								<div class=" mt-2 mb-1 flex justify-between text-sm font-medium">
									<div>
										<button
											id="save-new-message-button"
											class="px-3.5 py-1.5 bg-gray-50 hover:bg-gray-100 dark:bg-gray-800 dark:hover:bg-gray-700 border border-gray-100 dark:border-gray-700 text-gray-700 dark:text-gray-200 transition rounded-xl"
											on:click={() => {
												saveAsCopyHandler();
											}}
										>
											{$i18n.t('Save As Copy')}
										</button>
									</div>

									<div class="flex space-x-1.5">
										<button
											id="close-edit-message-button"
											class="px-3.5 py-1.5 bg-white dark:bg-gray-900 hover:bg-gray-100 text-gray-800 dark:text-gray-100 transition rounded-xl"
											on:click={() => {
												cancelEditMessage();
											}}
										>
											{$i18n.t('Cancel')}
										</button>

										<button
											id="confirm-edit-message-button"
											class="px-3.5 py-1.5 bg-gray-900 dark:bg-white hover:bg-gray-850 text-gray-100 dark:text-gray-800 transition rounded-xl"
											on:click={() => {
												editMessageConfirmHandler();
											}}
										>
											{$i18n.t('Save')}
										</button>
									</div>
								</div>
							</div>
						{/if}

						<div
							bind:this={contentContainerElement}
							class="w-full flex flex-col relative {edit ? 'hidden' : ''}"
							id="response-content-container"
						>
							{#if $taskHeartbeats[message.id]}
								<!-- Task heartbeat: a human-readable status line shown the instant a
								     (likely-)task message is sent, before any workspace run/card exists.
								     Hands off to the WorkspaceRunCard the moment its marker arrives. -->
								<div class="flex items-center gap-2 py-1 text-sm text-gray-500 dark:text-gray-400" id="task-heartbeat">
									<span class="inline-block size-3 rounded-full border-2 border-gray-400/40 border-t-gray-500 dark:border-t-gray-300 animate-spin shrink-0"></span>
									<span>{$taskHeartbeats[message.id]}</span>
								</div>
							{/if}
							{#if renderContent === '' && !message.done && !message.error && !hasVisibleStatus && !$taskHeartbeats[message.id]}
								<Skeleton />
							{:else if renderContent && message.error !== true}
								<!-- always show message contents even if there's an error -->
								<!-- unless message.error === true which is legacy error handling, where the error message is stored in message.content -->
								<ContentRenderer
									id={`${chatId}-${message.id}`}
									content={proseContent || (artifacts.length ? '' : renderContent)}
									sources={message.sources}
									floatingButtons={message?.done &&
										!readOnly &&
										($settings?.showFloatingActionButtons ?? true)}
									save={!readOnly}
									preview={!readOnly}
									{editCodeBlock}
									{topPadding}
									done={($settings?.chatFadeStreamingText ?? true)
										? (message?.done ?? false)
										: true}
									{model}
									onTaskClick={async (e) => {
										console.log(e);
									}}
									onSourceClick={async (id) => {
										console.log(id);

										if (citationsElement) {
											citationsElement?.showSourceModal(id);
										}
									}}
									onSetInputText={(text) => {
										setInputText(text);
									}}
									onSave={({ raw, oldContent, newContent }) => {
										history.messages[message.id].content = history.messages[
											message.id
										].content.replace(raw, raw.replace(oldContent, newContent));

										updateChat();
									}}
								/>
							{/if}

							{#if message?.files && message.files?.filter( (f) => f.type === 'file' && !(f?.content_type ?? '').startsWith('image/') ).length > 0}
								<div class="mt-3 flex flex-col gap-2">
									{#each message.files.filter((f) => f.type === 'file' && !(f?.content_type ?? '').startsWith('image/')) as file}
										<FileItem
											className="w-full max-w-md"
											colorClassName="bg-white dark:bg-[#1c1c1c] border border-gray-200/80 dark:border-white/10"
											item={file}
											url={file.url}
											name={file.name}
											type={file.type}
											size={file?.size}
										/>
									{/each}
								</div>
							{/if}

							{#if artifacts.length}
								<div class="mt-3 space-y-2">
									{#each artifacts as art, artIdx (art.filename + '-' + artIdx)}
										<ArtifactFileCard
											id={`${chatId}-${message.id}-art-${artIdx}`}
											lang={art.lang}
											filename={art.filename}
											code={art.code}
											streaming={art.open}
											done={!art.open && (message?.done ?? false)}
											save={!readOnly}
											preview={!readOnly}
											edit={editCodeBlock && !art.open && (message?.done ?? false)}
											onSave={(value) => {
												history.messages[message.id].content = (
													history.messages[message.id].content || ''
												).replace(art.code, value);
												updateChat();
											}}
										/>
									{/each}
								</div>
							{/if}

							{#if message?.error}
								<Error content={message?.error?.content ?? message.content} />
							{/if}

							{#if (message?.sources || message?.citations) && (model?.info?.meta?.capabilities?.citations ?? true)}
								<Citations
									bind:this={citationsElement}
									id={message?.id}
									{chatId}
									sources={message?.sources ?? message?.citations}
									{readOnly}
								/>
							{/if}

							{#if message.code_executions}
								<CodeExecutions codeExecutions={message.code_executions} />
							{/if}
						</div>
					</div>
				</div>

				{#if !edit}
					<div
						class="mt-2 flex flex-col gap-1.5"
					>
						<!-- Who answered on the left, what it cost on the right. Two bubbles rather
						     than one strip so the model name stays findable when the numbers grow;
						     the stats sit a shade darker so the eye lands on the name first. -->
						<div class="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
							<span
								class="inline-flex max-w-full items-center gap-1.5 rounded-lg border border-gray-200 dark:border-gray-800 px-2.5 py-1 text-[11px] font-medium text-gray-500 dark:text-gray-400"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									viewBox="0 0 24 24"
									fill="none"
									stroke="currentColor"
									stroke-width="1.9"
									stroke-linecap="round"
									stroke-linejoin="round"
									class="size-3.5 shrink-0 opacity-80"
									aria-hidden="true"
								>
									<rect x="7" y="7" width="10" height="10" rx="1.5" />
									<path d="M10 2v3M14 2v3M10 19v3M14 19v3M2 10h3M2 14h3M19 10h3M19 14h3" />
								</svg>
								<span
									id="response-message-model-name"
									class="line-clamp-1 font-normal text-gray-900 dark:text-gray-100"
									>{modelParts.base || $i18n.t('Unknown model')}</span
								>
								{#if modelParts.tags.length}
									<!-- The qualifiers ride in their own chip a shade lighter than the
									     bubble around them, so the name and what it is stay separable at
									     11px without punctuation doing the work. -->
									<span
										class="inline-flex shrink-0 items-center gap-1.5 rounded-md bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 font-bold tracking-wide text-gray-900 dark:text-gray-100"
									>
										{#each modelParts.tags as tag}
											<span class:opacity-75={tag.dim}>{tag.label}</span>
										{/each}
									</span>
								{/if}
							</span>

							{#if showStats}
							<span
								class="inline-flex items-center gap-3.5 rounded-lg border border-gray-200 dark:border-gray-800 px-2.5 py-1 text-[11px] font-bold tabular-nums text-gray-600 dark:text-gray-300"
							>
								<!-- Each figure says where it came from. Providers report token counts
								     once, at the end of a turn, so mid-answer these are honestly unknown
								     and print an em dash. A running character-based guess is allowed for
								     the token count alone, marked `~`, and is never used to derive a rate. -->
								<Tooltip content={tokensTip}>
									<span class="inline-flex items-center gap-1.5" class:opacity-60={!stats.total}>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											viewBox="0 0 24 24"
											fill="none"
											stroke="currentColor"
											stroke-width="1.9"
											stroke-linecap="round"
											stroke-linejoin="round"
											class="size-3.5 shrink-0 opacity-70"
											aria-hidden="true"
										>
											<path d="M3.5 17a8.5 8.5 0 1 1 17 0" />
											<path d="M12 17 16 12.4" />
											<circle cx="12" cy="17" r="1.1" fill="currentColor" stroke="none" />
										</svg>
										{#if stats.total}
											{stats.total.quality === 'estimated' ? '~' : ''}{formatNumber(
												stats.total.value
											)}
										{:else}
											—
										{/if}
									</span>
								</Tooltip>

								<Tooltip content={message.done ? $i18n.t('Time elapsed') : $i18n.t('Working')}>
									<span
										class="inline-flex items-center gap-1.5"
										class:opacity-60={stats.elapsedS === null}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											viewBox="0 0 24 24"
											fill="none"
											stroke="currentColor"
											stroke-width="1.9"
											stroke-linecap="round"
											stroke-linejoin="round"
											class="size-3.5 shrink-0 opacity-70"
											aria-hidden="true"
										>
											<circle cx="12" cy="12" r="9" />
											<path d="M12 7v5.2l3.2 2" />
										</svg>
										{elapsedLabel}
									</span>
								</Tooltip>

								<Tooltip content={speedTip}>
									<span class="inline-flex items-center gap-1.5" class:opacity-60={!stats.tokPerSec}>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											viewBox="0 0 24 24"
											fill="none"
											stroke="currentColor"
											stroke-width="1.9"
											stroke-linecap="round"
											stroke-linejoin="round"
											class="size-3.5 shrink-0 opacity-70"
											aria-hidden="true"
										>
											<path d="M13 2 4.5 13.5H11l-1 8.5L19.5 10H13z" />
										</svg>
										{#if stats.tokPerSec}
											{stats.tokPerSec.value >= 10
												? Math.round(stats.tokPerSec.value)
												: stats.tokPerSec.value.toFixed(1)} tok/s
										{:else}
											— tok/s
										{/if}
									</span>
								</Tooltip>
							</span>
							{/if}
						</div>
					<div
						bind:this={buttonsContainerElement}
						class="flex justify-start overflow-x-auto buttons text-gray-600 dark:text-gray-500"
					>
							{#if siblings.length > 1}
								<div class="flex self-center min-w-fit" dir="ltr">
									<button
										aria-label={$i18n.t('Previous message')}
										class="self-center p-1 hover:bg-black/5 dark:hover:bg-white/5 dark:hover:text-white hover:text-black rounded-md transition"
										on:click={() => {
											showPreviousMessage(message);
										}}
									>
										<svg
											aria-hidden="true"
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											viewBox="0 0 24 24"
											stroke="currentColor"
											stroke-width="2.5"
											class="size-3.5"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="M15.75 19.5 8.25 12l7.5-7.5"
											/>
										</svg>
									</button>

									{#if messageIndexEdit}
										<div
											class="text-sm flex justify-center font-semibold self-center dark:text-gray-100 min-w-fit"
										>
											<input
												id="message-index-input-{message.id}"
												type="number"
												value={siblings.indexOf(message.id) + 1}
												min="1"
												max={siblings.length}
												on:focus={(e) => {
													e.target.select();
												}}
												on:blur={(e) => {
													gotoMessage(message, e.target.value - 1);
													messageIndexEdit = false;
												}}
												on:keydown={(e) => {
													if (e.key === 'Enter') {
														gotoMessage(message, e.target.value - 1);
														messageIndexEdit = false;
													}
												}}
												class="bg-transparent font-semibold self-center dark:text-gray-100 min-w-fit outline-hidden"
											/>/{siblings.length}
										</div>
									{:else}
										<!-- svelte-ignore a11y-no-static-element-interactions -->
										<div
											class="text-sm tracking-widest font-semibold self-center dark:text-gray-100 min-w-fit"
											on:dblclick={async () => {
												messageIndexEdit = true;

												await tick();
												const input = document.getElementById(`message-index-input-${message.id}`);
												if (input) {
													input.focus();
													input.select();
												}
											}}
										>
											{siblings.indexOf(message.id) + 1}/{siblings.length}
										</div>
									{/if}

									<button
										class="self-center p-1 hover:bg-black/5 dark:hover:bg-white/5 dark:hover:text-white hover:text-black rounded-md transition"
										on:click={() => {
											showNextMessage(message);
										}}
										aria-label={$i18n.t('Next message')}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											aria-hidden="true"
											viewBox="0 0 24 24"
											stroke="currentColor"
											stroke-width="2.5"
											class="size-3.5"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="m8.25 4.5 7.5 7.5-7.5 7.5"
											/>
										</svg>
									</button>
								</div>
							{/if}

								<Tooltip content={$i18n.t('Copy')} placement="bottom">
									<button
										aria-label={$i18n.t('Copy')}
										class="{isLastMessage || ($settings?.highContrastMode ?? false)
											? 'visible'
											: 'visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition copy-response-button"
										on:click={() => {
											copyToClipboard(message.content);
										}}
									>
										<svg
											xmlns="http://www.w3.org/2000/svg"
											fill="none"
											aria-hidden="true"
											viewBox="0 0 24 24"
											stroke-width="2.3"
											stroke="currentColor"
											class="w-4 h-4"
										>
											<path
												stroke-linecap="round"
												stroke-linejoin="round"
												d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184"
											/>
										</svg>
									</button>
								</Tooltip>

								{#if !readOnly}
									{#if !$temporaryChatEnabled && ($config?.features.enable_message_rating ?? true) && ($user?.role === 'admin' || ($user?.permissions?.chat?.rate_response ?? true))}
										<!-- Up and down are one control, not two loose icons: a single bordered
										     pill with a hairline between the halves. -->
										<div
											class="flex items-center rounded-lg border border-gray-200 dark:border-white/15 dark:bg-white/[0.03] overflow-hidden"
										>
										<Tooltip content={$i18n.t('Good Response')} placement="bottom">
											<button
												aria-label={$i18n.t('Good Response')}
												class="{isLastMessage || ($settings?.highContrastMode ?? false)
													? 'visible'
													: 'visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-none {(
													message?.annotation?.rating ?? ''
												).toString() === '1'
													? 'bg-gray-100 dark:bg-gray-800'
													: ''} dark:hover:text-white hover:text-black transition disabled:cursor-progress disabled:hover:bg-transparent"
												disabled={feedbackLoading}
												on:click={async () => {
													await feedbackHandler(1);
													window.setTimeout(() => {
														document
															.getElementById(`message-feedback-${message.id}`)
															?.scrollIntoView();
													}, 0);
												}}
											>
												<svg
													aria-hidden="true"
													stroke="currentColor"
													fill="none"
													stroke-width="2.3"
													viewBox="0 0 24 24"
													stroke-linecap="round"
													stroke-linejoin="round"
													class="w-4 h-4"
													xmlns="http://www.w3.org/2000/svg"
												>
													<path
														d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"
													/>
												</svg>
											</button>
										</Tooltip>

										<div class="w-px self-stretch my-1 bg-gray-200 dark:bg-white/15"></div>

										<Tooltip content={$i18n.t('Bad Response')} placement="bottom">
											<button
												aria-label={$i18n.t('Bad Response')}
												class="{isLastMessage || ($settings?.highContrastMode ?? false)
													? 'visible'
													: 'visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-none {(
													message?.annotation?.rating ?? ''
												).toString() === '-1'
													? 'bg-gray-100 dark:bg-gray-800'
													: ''} dark:hover:text-white hover:text-black transition disabled:cursor-progress disabled:hover:bg-transparent"
												disabled={feedbackLoading}
												on:click={async () => {
													await feedbackHandler(-1);
													window.setTimeout(() => {
														document
															.getElementById(`message-feedback-${message.id}`)
															?.scrollIntoView();
													}, 0);
												}}
											>
												<svg
													aria-hidden="true"
													stroke="currentColor"
													fill="none"
													stroke-width="2.3"
													viewBox="0 0 24 24"
													stroke-linecap="round"
													stroke-linejoin="round"
													class="w-4 h-4"
													xmlns="http://www.w3.org/2000/svg"
												>
													<path
														d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"
													/>
												</svg>
											</button>
										</Tooltip>
										</div>
									{/if}

									{#if $user?.role === 'admin' || ($user?.permissions?.chat?.regenerate_response ?? true)}
										{#if $settings?.regenerateMenu ?? true}
											<button
												type="button"
												class="hidden regenerate-response-button"
												on:click={() => {
													showRateComment = false;
													regenerateResponse(message);

													(model?.actions ?? []).forEach((action) => {
														dispatch('action', {
															id: action.id,
															event: {
																id: 'regenerate-response',
																data: {
																	messageId: message.id
																}
															}
														});
													});
												}}
											/>

											<RegenerateMenu
												onRegenerate={(prompt = null) => {
													showRateComment = false;
													regenerateResponse(message, prompt);

													(model?.actions ?? []).forEach((action) => {
														dispatch('action', {
															id: action.id,
															event: {
																id: 'regenerate-response',
																data: {
																	messageId: message.id
																}
															}
														});
													});
												}}
											>
												<Tooltip content={$i18n.t('Regenerate')} placement="bottom">
													<div
														aria-label={$i18n.t('Regenerate')}
														class="{isLastMessage
															? 'visible'
															: 'visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition"
													>
														<svg
															xmlns="http://www.w3.org/2000/svg"
															fill="none"
															viewBox="0 0 24 24"
															stroke-width="2.3"
															aria-hidden="true"
															stroke="currentColor"
															class="w-4 h-4"
														>
															<path
																stroke-linecap="round"
																stroke-linejoin="round"
																d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99"
															/>
														</svg>
													</div>
												</Tooltip>
											</RegenerateMenu>
										{:else}
											<Tooltip content={$i18n.t('Regenerate')} placement="bottom">
												<button
													type="button"
													aria-label={$i18n.t('Regenerate')}
													class="{isLastMessage
														? 'visible'
														: 'visible'} p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition regenerate-response-button"
													on:click={() => {
														showRateComment = false;
														regenerateResponse(message);

														(model?.actions ?? []).forEach((action) => {
															dispatch('action', {
																id: action.id,
																event: {
																	id: 'regenerate-response',
																	data: {
																		messageId: message.id
																	}
																}
															});
														});
													}}
												>
													<svg
														xmlns="http://www.w3.org/2000/svg"
														fill="none"
														viewBox="0 0 24 24"
														stroke-width="2.3"
														aria-hidden="true"
														stroke="currentColor"
														class="w-4 h-4"
													>
														<path
															stroke-linecap="round"
															stroke-linejoin="round"
															d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99"
														/>
													</svg>
												</button>
											</Tooltip>
										{/if}
									{/if}
									<!-- Copy · rate · regenerate · read aloud are the row; Edit and Branch
									     live in the ⋯ menu. Read Aloud stays out here because replaying an
									     answer is a one-click action, not a buried one. -->

									<!-- Auto-playback clicks this id from Chat.svelte; it is now the same
									     button the user sees, so autoplay and the manual control share state. -->
									{#if $user?.role === 'admin' || ($user?.permissions?.chat?.tts ?? true)}
										<Tooltip
											content={speaking ? $i18n.t('Stop') : $i18n.t('Read Aloud')}
											placement="bottom"
										>
											<button
												type="button"
												id="speak-button-{message.id}"
												aria-label={speaking ? $i18n.t('Stop') : $i18n.t('Read Aloud')}
												class="visible p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg {speaking
													? 'bg-gray-100 dark:bg-gray-800'
													: ''} dark:hover:text-white hover:text-black transition"
												on:click={() => {
													if (loadingSpeech) return;
													if (speaking) {
														stopAudio();
													} else {
														speak();
													}
												}}
											>
												{#if loadingSpeech}
													<Spinner className="size-4" />
												{:else if speaking}
													<svg
														xmlns="http://www.w3.org/2000/svg"
														viewBox="0 0 24 24"
														fill="currentColor"
														aria-hidden="true"
														class="w-4 h-4"
													>
														<rect x="6" y="6" width="12" height="12" rx="1.5" />
													</svg>
												{:else}
													<svg
														xmlns="http://www.w3.org/2000/svg"
														fill="none"
														viewBox="0 0 24 24"
														stroke-width="2.3"
														stroke="currentColor"
														aria-hidden="true"
														class="w-4 h-4"
													>
														<path
															stroke-linecap="round"
															stroke-linejoin="round"
															d="M19.114 5.636a9 9 0 0 1 0 12.728M16.463 8.288a5.25 5.25 0 0 1 0 7.424M6.75 8.25l4.72-4.72a.75.75 0 0 1 1.28.53v15.88a.75.75 0 0 1-1.28.53l-4.72-4.72H4.51c-.88 0-1.704-.507-1.938-1.354A9.009 9.009 0 0 1 2.25 12c0-.83.112-1.633.322-2.396C2.806 8.756 3.63 8.25 4.51 8.25H6.75Z"
														/>
													</svg>
												{/if}
											</button>
										</Tooltip>
									{/if}

									<MoreActions items={moreActions}>
										<Tooltip content={$i18n.t('More')} placement="bottom">
											<div
												aria-label={$i18n.t('More')}
												class="visible p-1.5 hover:bg-black/5 dark:hover:bg-white/5 rounded-lg dark:hover:text-white hover:text-black transition cursor-pointer"
											>
												<svg
													xmlns="http://www.w3.org/2000/svg"
													viewBox="0 0 24 24"
													fill="currentColor"
													aria-hidden="true"
													class="w-4 h-4"
												>
													<path
														d="M6 12a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0Zm7.5 0a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0Zm7.5 0a1.5 1.5 0 1 1-3 0 1.5 1.5 0 0 1 3 0Z"
													/>
												</svg>
											</div>
										</Tooltip>
									</MoreActions>
								{/if}
					</div>
					</div>

					{#if message.done && showRateComment}
						<RateComment
							bind:message
							bind:show={showRateComment}
							on:save={async (e) => {
								await feedbackHandler(null, {
									...e.detail
								});
							}}
						/>
					{/if}

					{#if (isLastMessage || ($settings?.keepFollowUpPrompts ?? false)) && message.done && !readOnly && (message?.followUps ?? []).length > 0}
						<div class="mt-2.5" in:fade={{ duration: 100 }}>
							<FollowUps
								followUps={message?.followUps}
								onClick={(prompt) => {
									if ($settings?.insertFollowUpPrompt ?? false) {
										// Insert the follow-up prompt into the input box
										setInputText(prompt);
									} else {
										// Submit the follow-up prompt directly
										submitMessage(message?.id, prompt);
									}
								}}
							/>
						</div>
					{/if}
				{/if}
			</div>
		</div>
	</div>
{/key}

<style>
	/* Message-header-scale variant of the global .harvis-wordmark (app.css) — the sidebar
	   logotype size (0.8125rem) is too large next to the timestamp, so size it down here
	   without touching the global class. Scoped selector outranks the unlayered global. */
	:global(span.response-harvis-wordmark) {
		font-size: 0.7rem;
	}

	.buttons::-webkit-scrollbar {
		display: none; /* for Chrome, Safari and Opera */
	}

	.buttons {
		-ms-overflow-style: none; /* IE and Edge */
		scrollbar-width: none; /* Firefox */
	}
</style>
