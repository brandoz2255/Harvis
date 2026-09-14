<script lang="ts">
	// "Options" panel — the left half of the two-level model popover. A Thinking toggle plus a
	// discrete reasoning-effort list, answering "how should this model run?" while the picker
	// beside it answers "which model?". Always a popover, never a modal.
	//
	// Thinking OFF clears the saved effort (the backend treats a null effort as "no forced
	// thinking"); turning it back on restores Medium. Everything is a PARTIAL profile update, so
	// a saved thinking_budget or display_name is never wiped by touching effort.
	//
	// Only models whose metadata carries supports_effort ever reach this panel — every Claude on
	// either lane, plus the GPT-5 reasoning models. It is false on Kimi (temperature is pinned,
	// no thinking budget exists), on the free providers, and on local Ollama.
	//
	// All seven levels are sent as chosen on Claude — API key and subscription alike. Nothing is
	// clamped locally: the api_key path sends the budget in the `thinking` block, the subscription
	// path exports MAX_THINKING_TOKENS into the Claude Code CLI. OpenAI is the one exception, and
	// only because its reasoning_effort genuinely stops at "high"; those rows say so.
	import { createEventDispatcher, getContext } from 'svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import { saveModelProfile } from '$lib/apis/model-profiles';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let model: any = {};

	// budget = the Anthropic thinking budget this level sends, mirroring cloud_chat._EFFORT_BUDGET.
	const LEVELS = [
		{ id: 'minimal', label: 'Minimal', budget: 2000 },
		{ id: 'low', label: 'Low', budget: 4000 },
		{ id: 'medium', label: 'Medium', budget: 8000 },
		{ id: 'high', label: 'High', budget: 16000 },
		{ id: 'extra_high', label: 'Extra High', budget: 24000 },
		{ id: 'max', label: 'Max', budget: 32000 },
		{ id: 'ultra', label: 'Ultra', budget: 48000 }
	];

	// The saved effort, or null when thinking is off. `undefined` (never set) also reads as off,
	// which matches the backend: no effort → no thinking block is sent.
	$: current = model?.info?.meta?.profile_effort ?? null;
	$: thinking = !!current;

	$: isOpenAI = model?.owned_by === 'openai';

	// OpenAI's reasoning_effort has four values, so everything above High is sent as High. That
	// is the provider's own ceiling, not one of ours — Claude has none and gets no note.
	const collapseNote = (budget: number, openai: boolean) => (openai && budget > 16000 ? 'as High' : null);

	const save = async (lvl: string | null) => {
		model.info = model.info ?? {};
		model.info.meta = { ...(model.info.meta ?? {}), profile_effort: lvl };
		model = model;
		try {
			await saveModelProfile(localStorage.token, model.id, { effort: lvl });
			dispatch('changed', { id: model.id, effort: lvl });
		} catch (_) {
			/* keep the optimistic value — a failed save shows on the next picker load */
		}
	};

	const toggleThinking = () => save(thinking ? null : 'medium');
</script>

<div class="py-1 text-gray-800 dark:text-gray-100">
	<div class="flex items-center justify-between gap-2 px-2.5 pb-1">
		<span class="text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500"
			>{$i18n.t('Options')}</span
		>
		<Tooltip
			content={$i18n.t(
				'Reasoning effort is the extended-thinking budget on Claude (the thinking block on an API key, MAX_THINKING_TOKENS on a subscription) and reasoning_effort on GPT-5.'
			)}
		>
			<svg
				class="size-3 text-gray-400"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
				><circle cx="12" cy="12" r="10" /><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" /><path
					d="M12 17h.01"
				/></svg
			>
		</Tooltip>
	</div>

	<!-- Thinking toggle -->
	<button
		type="button"
		class="w-full flex items-center justify-between gap-3 px-2.5 py-1 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800 transition"
		role="switch"
		aria-checked={thinking}
		on:click|stopPropagation={toggleThinking}
	>
		<span class="text-[13px]">{$i18n.t('Thinking')}</span>
		<span
			class="relative shrink-0 h-3.5 w-6 rounded-full transition {thinking
				? 'bg-indigo-500'
				: 'bg-gray-300 dark:bg-gray-700'}"
		>
			<span
				class="absolute top-0.5 size-2.5 rounded-full bg-white shadow transition-all {thinking
					? 'left-3'
					: 'left-0.5'}"
			/>
		</span>
	</button>

	<div class="my-1 border-t border-gray-150 dark:border-gray-850"></div>

	<div
		class="px-2.5 pb-0.5 text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500"
	>
		{$i18n.t('Effort')}
	</div>

	{#each LEVELS as lvl (lvl.id)}
		{@const note = collapseNote(lvl.budget, isOpenAI)}
		<button
			type="button"
			class="w-full flex items-center gap-1.5 px-2.5 py-1 rounded-md text-left transition {thinking
				? 'hover:bg-gray-100 dark:hover:bg-gray-800'
				: 'opacity-40 cursor-default'}"
			disabled={!thinking}
			aria-pressed={current === lvl.id}
			on:click|stopPropagation={() => save(lvl.id)}
		>
			<span class="flex-1 text-[13px] truncate">{$i18n.t(lvl.label)}</span>
			{#if note}
				<span class="shrink-0 text-[10px] text-gray-400 dark:text-gray-500">{note}</span>
			{/if}
			{#if current === lvl.id}
				<svg
					class="size-3.5 shrink-0 text-indigo-500"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="3"
					stroke-linecap="round"
					stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg
				>
			{:else}
				<span class="size-3.5 shrink-0"></span>
			{/if}
		</button>
	{/each}

	<div class="mt-1 px-2.5 pt-1 border-t border-gray-150 dark:border-gray-850">
		<span class="block truncate text-[11px] text-gray-500 dark:text-gray-400"
			>{model?.name ?? model?.id}</span
		>
	</div>
</div>
