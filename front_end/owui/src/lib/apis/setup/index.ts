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
