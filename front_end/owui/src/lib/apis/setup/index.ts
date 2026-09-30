/** Tri-state setup API helpers — throw on failure (never silent null). */

const base = '';

async function parseJson(res: Response) {
	const text = await res.text();
	let body: any = null;
	try {
		body = text ? JSON.parse(text) : null;
	} catch {
		body = { detail: text || res.statusText };
	}
	if (!res.ok) {
		const detail = body?.detail ?? body?.reason ?? res.statusText ?? 'Request failed';
		throw typeof detail === 'string' ? detail : JSON.stringify(detail);
	}
	return body;
}

function authHeaders(token?: string | null): Record<string, string> {
	const h: Record<string, string> = { 'Content-Type': 'application/json' };
	if (token) h['Authorization'] = `Bearer ${token}`;
	return h;
}

export type SetupStatus = {
	needs_setup: boolean;
	setup_complete?: boolean;
};

/** One engine row inside the `engines` tick — the credential half and the sidecar half. */
export type SetupEngine = {
	id: string;
	label: string;
	service: string;
	container: string;
	state:
		| 'ready'
		| 'unverified'
		| 'needs_sidecar'
		| 'no_credential'
		| 'not_installed'
		| 'unreachable';
	detail: string;
	has_key: boolean;
	verified: boolean;
	can_probe: boolean;
	sidecar?: boolean | null;
};

/** `skipped` = a capability the operator did not install: neither ready nor broken. */
export type SetupTick = {
	ready: boolean;
	reason: string;
	probe: string;
	skipped?: boolean;
	engines?: SetupEngine[];
	/** Present when the capability can be added from the wizard (Notebooks' embedding model). */
	install?: { state: string; tag: string; download_mb: number; pullable: boolean };
};

export async function getSetupStatus(): Promise<SetupStatus> {
	const res = await fetch(`${base}/api/setup/status`, { credentials: 'include' });
	return parseJson(res);
}

export async function getSetupVerify(token: string): Promise<{
	overall: boolean;
	ticks: Record<string, SetupTick>;
}> {
	const res = await fetch(`${base}/api/setup/verify`, {
		credentials: 'include',
		headers: authHeaders(token)
	});
	return parseJson(res);
}

export async function postSetupTestModel(
	token: string,
	model: string
): Promise<SetupTick & { text?: string }> {
	const res = await fetch(`${base}/api/setup/test-model`, {
		method: 'POST',
		credentials: 'include',
		headers: authHeaders(token),
		body: JSON.stringify({ model })
	});
	return parseJson(res);
}

export async function postSetupPreferences(
	token: string,
	body: { cookie_secure?: boolean }
): Promise<{ ok: boolean; updated: string[] }> {
	const res = await fetch(`${base}/api/setup/preferences`, {
		method: 'POST',
		credentials: 'include',
		headers: authHeaders(token),
		body: JSON.stringify(body)
	});
	return parseJson(res);
}

export async function postSetupComplete(token: string): Promise<{ ok: boolean }> {
	const res = await fetch(`${base}/api/setup/complete`, {
		method: 'POST',
		credentials: 'include',
		headers: authHeaders(token),
		body: JSON.stringify({})
	});
	return parseJson(res);
}

/** Pull Notebooks' embedding model. Streams Ollama progress to `onEvent`; throws on
 *  an HTTP error or an `{error}` event, so a failed pull never reads as installed. */
export async function installNotebooksEmbedder(token: string, onEvent: (e: any) => void): Promise<void> {
	const res = await fetch(`${base}/api/capabilities/notebooks-embedder/install`, {
		method: 'POST',
		credentials: 'include',
		headers: authHeaders(token)
	});
	if (!res.ok || !res.body) {
		await parseJson(res);
		throw new Error(`HTTP ${res.status}`);
	}
	const reader = res.body.getReader();
	const dec = new TextDecoder();
	let buf = '';
	for (;;) {
		const { done, value } = await reader.read();
		if (done) break;
		buf += dec.decode(value, { stream: true });
		const parts = buf.split('\n\n');
		buf = parts.pop() || '';
		for (const part of parts) {
			const line = part.split('\n').find((l) => l.startsWith('data:'));
			if (!line) continue;
			let ev: any;
			try {
				ev = JSON.parse(line.slice(5).trim());
			} catch {
				continue;
			}
			if (ev?.error) throw new Error(String(ev.error));
			onEvent(ev);
		}
	}
}
