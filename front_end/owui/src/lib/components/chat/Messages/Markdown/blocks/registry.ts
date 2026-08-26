/**
 * The presentation half of the content-block router.
 *
 * The model makes the SEMANTIC decision ("this span is a terminal session").
 * This file makes the PRESENTATION decision ("a terminal session looks like
 * TerminalBlock"). Keeping them apart is the whole point: model output can
 * name a type from a fixed list and nothing else, so it can never ask for a
 * component, a colour, a width, or any markup of its own. An unrecognised
 * type is not an error and not a blank — it falls through to the generic
 * titled card, which is what every colon fence rendered as before this
 * registry existed.
 */
import type { ComponentType } from 'svelte';

import TerminalBlock from './TerminalBlock.svelte';
import SearchActivityBlock from './SearchActivityBlock.svelte';
import FileCardBlock from './FileCardBlock.svelte';
import WritingBlock from './WritingBlock.svelte';

export type BlockStatus = 'running' | 'complete' | 'error' | null;

export interface BlockDef {
	component: ComponentType;
	/** Renderer reads token.text verbatim (no nested markdown lexing). */
	raw?: boolean;
}

/**
 * Aliases exist because the fence type is written by a model, and models
 * reach for the near-synonym as often as the exact word. Mapping them here
 * is cheaper than a prompt rule nobody can enforce.
 */
const REGISTRY: Record<string, BlockDef> = {
	terminal: { component: TerminalBlock, raw: true },
	shell: { component: TerminalBlock, raw: true },
	console: { component: TerminalBlock, raw: true },

	search: { component: SearchActivityBlock },
	search_results: { component: SearchActivityBlock },
	research: { component: SearchActivityBlock },

	file: { component: FileCardBlock, raw: true },
	artifact: { component: FileCardBlock, raw: true },

	writing: { component: WritingBlock },
	document: { component: WritingBlock },
	draft: { component: WritingBlock }
};

/** Null means "no dedicated renderer" — the caller uses the generic card. */
export function resolveBlock(fenceType: string): BlockDef | null {
	return REGISTRY[(fenceType || '').toLowerCase()] ?? null;
}

/**
 * A block's status drives its header affordance and nothing else. Anything
 * the model sends that is not one of the three known states is dropped rather
 * than displayed, so a bogus value cannot invent a new visual state.
 */
export function normalizeStatus(value: string | undefined, open: boolean): BlockStatus {
	const v = (value || '').toLowerCase();
	if (v === 'running' || v === 'pending' || v === 'in_progress') return 'running';
	if (v === 'complete' || v === 'done' || v === 'success' || v === 'ok') return 'complete';
	if (v === 'error' || v === 'failed' || v === 'failure') return 'error';
	// No explicit status: an unterminated fence is still being written.
	return open ? 'running' : 'complete';
}

/**
 * File cards carry a link, and a link is the one attribute a model could use
 * to point the user somewhere hostile. Only same-origin relative paths are
 * honoured; anything absolute, protocol-relative, or javascript: is dropped
 * and the card renders without a button.
 */
export function safeHref(href: string | undefined): string | null {
	if (!href) return null;
	const h = href.trim();
	if (!h.startsWith('/') || h.startsWith('//')) return null;
	return h;
}

/**
 * Models habitually wrap the body of a `:::terminal` in a ``` fence as well —
 * belt and braces, since a code fence is how they normally protect monospaced
 * output. The raw renderers read the body verbatim, so without this the user
 * sees the literal backticks inside the terminal chrome. Only a fence that
 * wraps the WHOLE body is removed; backticks in the middle of real output are
 * output and stay.
 */
export function unwrapCodeFence(text: string): string {
	const t = (text || '').trim();
	const m = /^```[\w-]*\n([\s\S]*?)\n?```$/.exec(t);
	return m ? m[1] : text;
}
