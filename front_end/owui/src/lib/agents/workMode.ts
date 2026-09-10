// Chat | Work switching, in one place.
//
// The toggle used to live only in Placeholder.svelte — the empty new-chat
// screen. That meant the mode could only be chosen BEFORE the first message:
// once a conversation started the placeholder unmounted and there was no way
// back to Work without opening a new chat. The logic lives here so the navbar
// can offer the same switch at the top of a live chat.

import { get, writable } from 'svelte/store';

import { getModels } from '$lib/apis';
import { models as _models, workMode } from '$lib/stores';

import { ensureDefaultTeammate, teammateModelId } from './agents';

export const WORK_KEY = 'harvis.workMode';

export const isAgentModel = (id: unknown): boolean =>
	typeof id === 'string' && id.startsWith('agent:');

/** The ordinary models the user had before entering Work, so Chat can restore them. */
const rememberedChatModels = writable<string[]>([]);

export const readStoredWorkMode = (): boolean => {
	try {
		return localStorage.getItem(WORK_KEY) === '1';
	} catch (_) {
		return false;
	}
};

const persist = (work: boolean) => {
	try {
		localStorage.setItem(WORK_KEY, work ? '1' : '0');
	} catch (_) {
		/* private mode: the mode still applies to this tab */
	}
};

export const teammatesFrom = (list: unknown): { id: string }[] =>
	((list as { id: string; owned_by?: string }[]) || []).filter((m) => m?.owned_by === 'harvis-agent');

/**
 * Apply `work` and return the models the chat should now have selected.
 * Throws only if a teammate has to be created and the backend refuses.
 */
export const applyWorkMode = async (
	work: boolean,
	selectedModels: string[],
	token: string
): Promise<string[]> => {
	persist(work);

	if (!work) {
		workMode.set(false);
		const restored = get(rememberedChatModels);
		return restored.length ? [...restored] : selectedModels;
	}

	const plain = (selectedModels || []).filter((m) => m && !isAgentModel(m));
	if (plain.length) rememberedChatModels.set(plain);

	let teammates = teammatesFrom(get(_models));
	let entry = teammates.find((m) => selectedModels?.includes(m.id)) ?? teammates[0];

	if (!entry) {
		// First time: the backend makes (or promotes) a default teammate, then the
		// model list is refreshed so the picker knows the new `agent:` id.
		const agent = await ensureDefaultTeammate(token);
		const next = await getModels(token);
		if (Array.isArray(next) && next.length) _models.set(next);
		entry = { id: teammateModelId(agent.id) };
	}

	workMode.set(true);
	return [entry.id];
};

/**
 * Picking an ordinary model while in Work is how you leave Work. Call this
 * whenever the selection changes; it is idempotent, so more than one mounted
 * toggle watching the same selection is harmless.
 */
export const syncWorkModeToSelection = (selectedModels: string[]): void => {
	if (!get(workMode)) return;
	if (!selectedModels?.length || selectedModels[0] === '') return;
	if (selectedModels.some(isAgentModel)) return;
	persist(false);
	workMode.set(false);
};
