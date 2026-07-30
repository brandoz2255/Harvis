type AudioQueueEvent = 'stop' | 'empty-queue' | 'id-change';

interface AudioQueueStopDetail {
	event: AudioQueueEvent;
	id: string | null;
}

export type OnStoppedCallback = (detail: AudioQueueStopDetail) => void;

export class AudioQueue {
	private audio: HTMLAudioElement;
	private queue: string[] = [];
	private current: string | null = null;
	private readonly _onEnded = () => this.next();

	id: string | null = null;
	onStopped: OnStoppedCallback | null = null;

	constructor(audioElement: HTMLAudioElement) {
		this.audio = audioElement;
		this.audio.addEventListener('ended', this._onEnded);
	}

	setId(newId: string) {
		if (this.id === newId) return;

		this.#halt();
		this.id = newId;
		this.onStopped?.({ event: 'id-change', id: newId });
	}

	setPlaybackRate(rate: number) {
		this.audio.playbackRate = rate;
	}

	enqueue(url: string) {
		this.queue.push(url);

		// Auto-play if nothing is currently playing or loaded
		if (this.audio.paused && !this.current) {
			this.next();
		}
	}

	play() {
		if (!this.current && this.queue.length > 0) {
			this.next();
		} else {
			this.audio.muted = false; // the shared #audioElement can be left muted by CallOverlay
			this.audio.play();
		}
	}

	next() {
		this.current = this.queue.shift() ?? null;

		if (this.current) {
			this.audio.src = this.current;
			// The CallOverlay's playAudio mutes #audioElement (autoplay trick) and
			// only unmutes after play() resolves — if that's interrupted (slow TTS,
			// overlay closed mid-play) the shared element stays muted, silencing the
			// message Read-Aloud too. Always unmute before playing here.
			this.audio.muted = false;
			this.audio.play();
		} else {
			this.#halt();
			this.onStopped?.({ event: 'empty-queue', id: this.id });
		}
	}

	stop() {
		this.#halt();
		this.onStopped?.({ event: 'stop', id: this.id });
	}

	destroy() {
		this.audio.removeEventListener('ended', this._onEnded);
		this.#halt();
		this.onStopped = null;
	}

	/**
	 * Pause audio and clear queue without firing onStopped.
	 * Callers that need the callback should invoke it themselves.
	 */
	#halt() {
		this.audio.pause();
		this.audio.currentTime = 0;
		this.audio.removeAttribute('src');
		this.audio.load();
		this.queue = [];
		this.current = null;
	}
}

/** An i18n key plus its interpolation values, so callers keep translation. */
export type MediaErrorMessage = { key: string; values?: Record<string, string> };

/**
 * Why the microphone cannot be opened at all, or null when it should work.
 *
 * Browsers expose `navigator.mediaDevices` ONLY in a secure context: HTTPS, or
 * `localhost` / `127.0.0.1`. Reached over a LAN address on plain HTTP — the normal
 * way a self-hosted Harvis is opened from a second machine — the property is
 * simply `undefined`, so every microphone call throws before any permission
 * prompt can appear. Nothing was denied, and saying it was sent the operator to
 * audit browser settings that were never involved.
 */
export function micUnavailableReason(): MediaErrorMessage | null {
	if (typeof navigator === 'undefined') return null; // SSR — the browser decides
	if (navigator.mediaDevices?.getUserMedia) return null;

	if (typeof window !== 'undefined' && window.isSecureContext === false) {
		return {
			key: 'Your browser only allows microphone access over HTTPS or from localhost. This page is {{origin}}, so the microphone API is unavailable here — nothing was denied.',
			values: { origin: window.location.origin }
		};
	}
	return { key: 'This browser does not provide a microphone API.' };
}

/** Turn a getUserMedia rejection into something true and actionable. */
export function describeMediaError(err: unknown): MediaErrorMessage {
	const unavailable = micUnavailableReason();
	if (unavailable) return unavailable;

	switch ((err as { name?: string })?.name) {
		case 'NotAllowedError':
		case 'SecurityError':
			return {
				key: 'Microphone access is blocked for this site. Allow it from the permission menu in your browser address bar, then try again.'
			};
		case 'NotFoundError':
		case 'OverconstrainedError':
			return {
				key: 'No microphone was found. Connect one, or choose a different input under Settings → Audio.'
			};
		case 'NotReadableError':
			return {
				key: 'The microphone is already in use by another application, or the system blocked access to it.'
			};
		case 'AbortError':
			return { key: 'The microphone request was interrupted before it finished.' };
		default: {
			const message = (err as { message?: string })?.message;
			return message
				? { key: 'Could not open the microphone: {{error}}', values: { error: message } }
				: { key: 'Could not open the microphone.' };
		}
	}
}
