import { env } from '@huggingface/transformers';
import { KokoroTTS } from 'kokoro-js';

// TODO: Below doesn't work as expected, need to investigate further
env.backends.onnx.wasm.wasmPaths = '/wasm/';

let tts;
let isInitialized = false; // Flag to track initialization status
const DEFAULT_MODEL_ID = 'onnx-community/Kokoro-82M-v1.0-ONNX'; // Default model

// Harvis serves a mirror of the Kokoro weights and voice embeddings from its own
// origin (nginx -> the voice service's model volume), so browser speech keeps
// working with no internet after installation.
//
// A fetch shim rather than a config flag because the two halves of this model
// are fetched by two different libraries: transformers.js resolves the weights
// through `env`, but kokoro-js hardcodes the huggingface.co URL for the voice
// .bin files. Rewriting at the fetch layer catches both, and is the only place
// that can fall back cleanly when a file isn't mirrored.
const HF_PREFIX = 'https://huggingface.co/';
const MIRROR_BASE = '/kokoro/';

const toMirrorUrl = (url: string): string | null => {
	if (!url.startsWith(HF_PREFIX)) return null;
	// .../<owner>/<repo>/resolve/<revision>/<path> -> /kokoro/<owner>/<repo>/<path>
	const rest = url.slice(HF_PREFIX.length);
	const m = rest.match(/^([^/]+\/[^/]+)\/resolve\/[^/]+\/(.+)$/);
	if (!m) return null;
	return `${MIRROR_BASE}${m[1]}/${m[2].split('?')[0]}`;
};

const originalFetch = globalThis.fetch.bind(globalThis);

globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
	const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
	const mirrored = toMirrorUrl(url);
	if (!mirrored) return originalFetch(input as any, init);

	let local: Response | null = null;
	try {
		local = await originalFetch(mirrored, init);
		if (local.ok) return local;
	} catch {
		// Mirror unreachable (voice service stopped, or this build isn't behind
		// the Harvis proxy) — fall through to the upstream URL.
	}

	try {
		return await originalFetch(input as any, init);
	} catch (error) {
		// Offline and not mirrored. Hand back the local response so the caller
		// sees an ordinary 404 for an optional file instead of a network error.
		if (local) return local;
		throw error;
	}
};

self.onmessage = async (event) => {
	const { type, payload } = event.data;

	if (type === 'init') {
		let { model_id, dtype } = payload;
		model_id = model_id || DEFAULT_MODEL_ID; // Use default model if none provided

		self.postMessage({ status: 'init:start' });

		try {
			tts = await KokoroTTS.from_pretrained(model_id, {
				dtype,
				device: !!navigator?.gpu ? 'webgpu' : 'wasm' // Detect WebGPU
			});
			isInitialized = true; // Mark as initialized after successful loading
			self.postMessage({ status: 'init:complete' });
		} catch (error) {
			isInitialized = false; // Ensure it's marked as false on failure
			self.postMessage({ status: 'init:error', error: error.message });
		}
	}

	if (type === 'generate') {
		if (!isInitialized || !tts) {
			// Ensure model is initialized
			self.postMessage({ status: 'generate:error', error: 'TTS model not initialized' });
			return;
		}

		const { text, voice } = payload;
		self.postMessage({ status: 'generate:start' });

		try {
			const rawAudio = await tts.generate(text, { voice });
			const blob = await rawAudio.toBlob();
			const blobUrl = URL.createObjectURL(blob);
			self.postMessage({ status: 'generate:complete', audioUrl: blobUrl });
		} catch (error) {
			self.postMessage({ status: 'generate:error', error: error.message });
		}
	}

	if (type === 'status') {
		// Respond with the current initialization status
		self.postMessage({ status: 'status:check', initialized: isInitialized });
	}
};
