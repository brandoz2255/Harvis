/**
 * In-flight chat generations that outlive the Chat view.
 *
 * Ordinary replies stream over HTTP from the page that started them. When the user
 * switches chats mid-stream, `loadChat` replaces the component's `history` with a
 * DB snapshot that does not yet include the turn — so the UI shows the previous
 * conversation with no spinner. The stream keeps writing a different object.
 *
 * This registry holds the live history object the stream is filling, keyed by
 * chat id, so returning to that chat can reattach the UI instead of reloading
 * stale DB state. Module-scoped (not localStorage): survives Chat remounts in
 * the same tab; a full page reload legitimately loses the stream.
 *
 * `inflightEpoch` bumps on every streamed write so a remounted Chat that adopted
 * the live history still re-renders — the stream's closure cannot assign that
 * instance's `history` binding.
 */

import { writable } from 'svelte/store';

export type ChatInflightEntry = {
	/** Live history object the stream mutates. */
	history: any;
	/** Assistant message id currently being generated. */
	responseMessageId: string;
	/** AbortController for the HTTP stream — kept so Stop works after remount. */
	controller?: AbortController | null;
	/** Stream finished, but the originating chat has not adopted this history yet. */
	done?: boolean;
};

const inflight = new Map<string, ChatInflightEntry>();

/** chatId → monotonic counter; Chat reacts to its own id's epoch to refresh. */
export const inflightEpoch = writable<Record<string, number>>({});

export const touchInflight = (chatId: string) => {
	if (!chatId) return;
	inflightEpoch.update((m) => ({ ...m, [chatId]: (m[chatId] ?? 0) + 1 }));
};

export const setInflight = (chatId: string, entry: ChatInflightEntry) => {
	if (!chatId || !entry?.history || !entry?.responseMessageId) return;
	const prev = inflight.get(chatId);
	inflight.set(chatId, {
		history: entry.history,
		responseMessageId: entry.responseMessageId,
		controller: entry.controller !== undefined ? entry.controller : prev?.controller,
		done: entry.done !== undefined ? entry.done : prev?.done
	});
};

export const getInflight = (chatId: string): ChatInflightEntry | undefined => {
	if (!chatId) return undefined;
	return inflight.get(chatId);
};

export const clearInflight = (chatId: string) => {
	if (!chatId) return;
	inflight.delete(chatId);
	inflightEpoch.update((m) => {
		if (!(chatId in m)) return m;
		const next = { ...m };
		delete next[chatId];
		return next;
	});
};

export const hasInflight = (chatId: string): boolean => {
	if (!chatId) return false;
	return inflight.has(chatId);
};
