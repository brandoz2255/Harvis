/**
 * Route Kokoro's model downloads through Harvis's own origin.
 *
 * Harvis mirrors the Kokoro weights and voice embeddings from the voice
 * service's model volume (nginx -> /kokoro/…), so browser speech keeps working
 * with no internet after installation.
 *
 * This is a fetch shim rather than a config flag because the two halves of the
 * model are fetched by two different libraries: transformers.js resolves the
 * weights through its own `env`, but kokoro-js hardcodes the huggingface.co URL
 * for the voice `.bin` files. Rewriting at the fetch layer catches both.
 *
 * It lives here, outside the worker, because Kokoro gets loaded from two
 * places — the worker (chat playback) and the Audio settings panel (the voice
 * picker). When this only existed inside the worker, picking "Kokoro (in
 * browser)" in Settings went straight to huggingface.co and stalled on a box
 * with no route to it.
 */

let installed = false;
let fellBack = false;

/** True if any model file has been served by huggingface.co rather than the local mirror. */
export const didFallBackToHuggingFace = () => fellBack;

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

/**
 * Install the shim on this thread. Idempotent — safe to call before every load.
 *
 * `timeoutMs` bounds the upstream fallback only. The mirror is same-origin and
 * either answers or refuses immediately; huggingface.co on a network that has
 * no route to it hangs until the browser gives up, which is what turned a
 * failed load into a permanent "Loading…" spinner.
 */
export const installKokoroMirror = (timeoutMs = 20000) => {
	if (installed) return;
	installed = true;

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

		console.warn(
			`[kokoro] ${mirrored} unavailable (${local ? `HTTP ${local.status}` : 'unreachable'}); ` +
				`falling back to huggingface.co for ${url}`
		);

		// Without this the request inherits the browser's own multi-minute
		// connect timeout, and the caller cannot tell "downloading" from "hung".
		const abort = new AbortController();
		const timer = setTimeout(() => abort.abort(), timeoutMs);
		try {
			const upstream = await originalFetch(input as any, { ...init, signal: abort.signal });
			if (upstream.ok) fellBack = true;
			return upstream;
		} catch (error) {
			// Offline and not mirrored. Hand back the local response so the caller
			// sees an ordinary 404 for an optional file instead of a network error.
			if (local) return local;
			throw error;
		} finally {
			clearTimeout(timer);
		}
	};
};
