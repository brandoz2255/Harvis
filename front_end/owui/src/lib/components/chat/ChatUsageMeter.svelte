<script lang="ts">
	// Token + cost meter for the MAIN chat composer — the same gauge the Build area has,
	// fed from the chat's own message history instead of a run record.
	//
	// Everything it needs is already in memory: the backend attaches `usage` to each
	// assistant message (Chat.svelte assigns it off the stream), and the model catalog
	// carries `info.meta.price_in` / `price_out` / `context_length`. So this component is
	// pure derivation — no fetch, no store of its own.
	//
	// Why a separate component rather than inline in MessageInput: MessageInput is already
	// ~2.4k lines, and the derivation below is the part worth reading on its own.
	import { getContext } from 'svelte';
	import { models } from '$lib/stores';
	import UsageMeter from '$lib/agent-studio/UsageMeter.svelte';

	const i18n: any = getContext('i18n');

	export let history: any = null;
	/** The model the composer will send to — used for price + context window. */
	export let modelId = '';
	/** A response is streaming → tick the bar so the user sees it move. */
	export let generating = false;

	// Only the CURRENT branch counts. history.messages holds every sibling of every
	// regenerate/edit, so summing the map would bill the user for branches they walked
	// away from. Walking parentId from currentId gives exactly the thread on screen.
	$: thread = (() => {
		const out: any[] = [];
		const msgs = history?.messages ?? {};
		let id = history?.currentId;
		const seen = new Set<string>();
		while (id && msgs[id] && !seen.has(id)) {
			seen.add(id);
			out.push(msgs[id]);
			id = msgs[id].parentId;
		}
		return out.reverse();
	})();

	// Two vendor shapes reach us: OpenAI-compatible (prompt_tokens/completion_tokens) and
	// Ollama's native (prompt_eval_count/eval_count). Read both rather than picking one —
	// a chat can switch models mid-thread, so a single thread can contain both.
	const tokensOf = (u: any) => ({
		in: Number(u?.prompt_tokens ?? u?.prompt_eval_count ?? 0),
		out: Number(u?.completion_tokens ?? u?.eval_count ?? 0)
	});

	$: turns = thread
		.filter((m: any) => m?.role === 'assistant' && m?.usage)
		.map((m: any) => tokensOf(m.usage))
		.filter((t) => t.in > 0 || t.out > 0);

	$: last = turns.length ? turns[turns.length - 1] : { in: 0, out: 0 };
	$: sessionTokens = turns.reduce((s, t) => s + t.in + t.out, 0);

	$: entry = ($models || []).find((m: any) => m?.id === modelId);
	$: meta = (entry?.info?.meta as any) || {};
	$: priceIn = Number(meta.price_in || 0); // USD per million input tokens
	$: priceOut = Number(meta.price_out || 0);
	// Zero on BOTH sides is the honest test for free: a local Ollama model and a connected
	// free-tier vendor key (Groq, Cerebras, …) are both genuinely $0 to the user, and the
	// backend states 0/0 explicitly for the free providers rather than leaving it unset.
	$: isFree = priceIn === 0 && priceOut === 0;
	$: atApiRates = /subscription/i.test(entry?.name || '');
	$: ctxWindow = Number(meta.context_length || 24576);
	// Context occupancy = what the NEXT request will carry, which is the last turn's prompt
	// plus the answer it produced. (The Build meter shows the prompt alone; here the reply is
	// already part of the thread the composer is about to re-send, so including it is what
	// makes the bar match what the model will actually see.)
	$: ctxUsed = last.in + last.out;
	$: costUsd = turns.reduce((s, t) => s + (t.in * priceIn + t.out * priceOut) / 1e6, 0);

	// Nothing has been measured yet → show nothing. An empty gauge on a fresh chat would be
	// clutter that says "0" without meaning it.
	$: visible = turns.length > 0;
</script>

{#if visible}
	<div class="flex items-center" title={$i18n.t('Context & usage')}>
		<UsageMeter
			{ctxUsed}
			{ctxWindow}
			{sessionTokens}
			{costUsd}
			{isFree}
			{atApiRates}
			modelName={entry?.name || modelId}
			live={generating}
			lastIn={last.in}
			lastOut={last.out}
			align="right"
			placement="top"
			freeLabel={$i18n.t('Free')}
		/>
	</div>
{/if}
