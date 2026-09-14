/**
 * Read-aloud for surfaces that are not the main chat.
 *
 * The main chat's read-aloud lives inside `ResponseMessage.svelte` and is bound to
 * that component: it speaks `message.content`, it drives the page-level `speaking`
 * flag, and it plays through the `AudioQueue` that `Chat.svelte` builds around its
 * own hidden `<audio id="audioElement">`. That element only exists inside
 * `Chat.svelte`, so on any other route `$audioQueue` is either null or still
 * pointing at an element that was destroyed on navigation — which is why the Build
 * tab had no voice at all rather than a broken one.
 *
 * This module is the same three engine paths (system voice, browser Kokoro, server
 * TTS) with no message shape and no chat page attached: it owns one lazily created
 * <audio> element of its own, speaks whatever text it is handed, and reports when
 * it stops. It reads the user's real TTS settings, so a voice chosen in Settings is
 * the voice the Build tab uses.
 */
import { get } from 'svelte/store';

import { config, settings, TTSWorker } from '$lib/stores';
import { synthesizeOpenAISpeech } from '$lib/apis/audio';
import { getMessageContentParts, removeAllDetails } from '$lib/utils';
import { AudioQueue } from '$lib/utils/audio';
import { KokoroWorker } from '$lib/workers/KokoroWorker';

let queue: AudioQueue | null = null;
let element: HTMLAudioElement | null = null;
let abort: AbortController | null = null;

const ensureQueue = (): AudioQueue => {
	if (queue && element?.isConnected) return queue;
	// Our own element, appended once and reused. Sharing the chat's would mean
	// tearing down whatever it is playing, and it is not on the page anyway.
	element = document.createElement('audio');
	element.id = 'harvis-speak-audio';
	element.style.display = 'none';
	document.body.appendChild(element);
	queue = new AudioQueue(element);
	return queue;
};

/** Stop anything this module is currently saying. Safe to call when idle. */
export const stopSpeaking = () => {
	abort?.abort();
	abort = null;
	try {
		speechSynthesis.cancel();
	} catch {}
	try {
		queue?.stop();
	} catch {}
};

const voiceId = () => {
	const s: any = get(settings);
	const c: any = get(config);
	return s?.audio?.tts?.defaultVoice === c?.audio?.tts?.voice
		? (s?.audio?.tts?.voice ?? c?.audio?.tts?.voice)
		: c?.audio?.tts?.voice;
};

/**
 * Speak `text`. Resolves once every sentence has been handed to the player —
 * `onDone` fires when playback itself finishes, which is the later of the two.
 * Any error is reported through `onError` rather than thrown, because the caller
 * is a button and a rejected promise there is a silent failure.
 */
export const speakText = async (
	text: string,
	opts: {
		id?: string;
		onDone?: () => void;
		onError?: (message: string) => void;
	} = {}
): Promise<void> => {
	const content = removeAllDetails((text ?? '').trim());
	if (!content) {
		opts.onError?.('No content to speak');
		opts.onDone?.();
		return;
	}

	stopSpeaking();
	abort = new AbortController();
	const { signal } = abort;

	const s: any = get(settings);
	const c: any = get(config);
	const engine = c?.audio?.tts?.engine ?? '';

	// Engine '' is the browser's own speech synthesis — no queue, no network.
	if (engine === '') {
		const speak = (voices: SpeechSynthesisVoice[]) => {
			const utterance = new SpeechSynthesisUtterance(content);
			utterance.rate = s?.audio?.tts?.playbackRate ?? 1;
			const voice = voices.find((v) => v.voiceURI === voiceId());
			if (voice) utterance.voice = voice;
			utterance.onend = () => opts.onDone?.();
			utterance.onerror = () => opts.onDone?.();
			speechSynthesis.speak(utterance);
		};

		const ready = speechSynthesis.getVoices();
		if (ready.length) {
			speak(ready);
			return;
		}
		// Voices load asynchronously on a cold page. Poll briefly, then give up and
		// speak with the default voice rather than staying silent forever.
		let tries = 0;
		const poll = setInterval(() => {
			const voices = speechSynthesis.getVoices();
			if (voices.length || ++tries > 30) {
				clearInterval(poll);
				if (signal.aborted) return;
				speak(voices);
			}
		}, 100);
		return;
	}

	// One user-facing speed, applied where it sounds best: the server renders at
	// that rate (no pitch shift), the browser path resamples playback. Applying
	// both would compound them — same rule as the main chat.
	const speed = s?.audio?.tts?.playbackRate ?? 1;
	const serverSpeaks = s?.audio?.tts?.engine !== 'browser-kokoro';

	const q = ensureQueue();
	q.setId(opts.id || 'harvis-speak');
	q.setPlaybackRate(serverSpeaks ? 1 : speed);
	q.onStopped = () => opts.onDone?.();

	const parts: string[] = getMessageContentParts(
		content,
		c?.audio?.tts?.split_on ?? 'punctuation'
	);
	if (!parts.length) {
		opts.onError?.('No content to speak');
		opts.onDone?.();
		return;
	}

	try {
		if (s?.audio?.tts?.engine === 'browser-kokoro') {
			if (!get(TTSWorker)) {
				TTSWorker.set(new KokoroWorker({ dtype: s?.audio?.tts?.engineConfig?.dtype ?? 'fp32' }));
				await (get(TTSWorker) as any).init();
			}
			for (const sentence of parts) {
				if (signal.aborted) return;
				const url = await (get(TTSWorker) as any).generate({ text: sentence, voice: voiceId() });
				if (signal.aborted) return;
				if (url) q.enqueue(url);
			}
		} else {
			for (const sentence of parts) {
				if (signal.aborted) return;
				const res = await synthesizeOpenAISpeech(
					localStorage.token,
					voiceId(),
					sentence,
					undefined,
					speed
				);
				if (signal.aborted) return;
				if (res) q.enqueue(URL.createObjectURL(await res.blob()));
			}
		}
	} catch (error) {
		// console.error is stripped from the production bundle by esbuild's `pure`
		// list, so a failure here would leave no trace at all. warn survives.
		console.warn('speakText failed', error);
		opts.onError?.(`${error}`);
		opts.onDone?.();
	}
};
