import { WEBUI_API_BASE_URL } from '$lib/constants';

export const checkActiveChats = async (token: string, chatIds: string[]) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/tasks/active/chats`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ chat_ids: chatIds })
	});
	// #region agent log
	fetch('http://127.0.0.1:7808/ingest/9269ee65-762c-4e4d-9bef-0cd2be96389e', {
		method: 'POST',
		headers: { 'Content-Type': 'application/json', 'X-Debug-Session-Id': 'd007eb' },
		body: JSON.stringify({
			sessionId: 'd007eb',
			runId: 'pre-fix',
			hypothesisId: 'C',
			location: 'apis/tasks/index.ts:checkActiveChats:response',
			message: 'checkActiveChats HTTP response',
			data: { ok: res.ok, status: res.status, chatIdsCount: chatIds?.length ?? null },
			timestamp: Date.now()
		})
	}).catch(() => {});
	// #endregion
	if (!res.ok) throw await res.json();
	return res.json();
};
