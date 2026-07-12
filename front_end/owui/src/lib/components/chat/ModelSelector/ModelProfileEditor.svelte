<script lang="ts">
	// Cursor-style per-model profile editor for CLOUD models (Claude + OpenAI): reasoning effort,
	// thinking budget, and a custom display name. Opens from the "Edit" affordance on a model row.
	import { createEventDispatcher, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import Modal from '$lib/components/common/Modal.svelte';
	import { saveModelProfile, deleteModelProfile } from '$lib/apis/model-profiles';

	const i18n = getContext('i18n');
	const dispatch = createEventDispatcher();

	export let show = false;
	export let model: any = {};

	$: meta = model?.info?.meta ?? {};
	$: supportsEffort = !!meta.supports_effort;

	const EFFORTS = [
		{ id: 'low', label: 'Low' },
		{ id: 'medium', label: 'Medium' },
		{ id: 'high', label: 'High' },
		{ id: 'max', label: 'Max' }
	];

	let effort = '';
	let thinkingBudget: string = '';
	let displayName = '';
	let nameTouched = false;
	let saving = false;
	let initializedFor = '';

	// (re)load the form from the model's current profile each time it opens for a given model
	$: if (show && initializedFor !== model?.id) {
		effort = meta.profile_effort ?? '';
		thinkingBudget = meta.profile_thinking_budget != null ? `${meta.profile_thinking_budget}` : '';
		displayName = '';
		nameTouched = false;
		initializedFor = model?.id;
	}

	const save = async () => {
		saving = true;
		try {
			const budget =
				supportsEffort && `${thinkingBudget}`.trim() !== '' ? Number(thinkingBudget) : null;
			// Partial update: only send display_name if the user actually edited it, so changing
			// effort/budget never wipes a previously saved custom name.
			const profile: any = {
				effort: effort || null,
				thinking_budget: budget != null && !Number.isNaN(budget) ? budget : null
			};
			if (nameTouched) profile.display_name = displayName.trim() || null;
			await saveModelProfile(localStorage.token, model.id, profile);
			// Reflect on the row immediately (no full reload needed for the common case).
			if (nameTouched && profile.display_name) model.name = profile.display_name;
			model.info = model.info ?? {};
			model.info.meta = { ...(model.info.meta ?? {}) };
			model.info.meta.profile_effort = profile.effort ?? undefined;
			model.info.meta.profile_thinking_budget = profile.thinking_budget ?? undefined;
			toast.success($i18n.t('Profile saved'));
			dispatch('saved', model);
			show = false;
		} catch (e: any) {
			toast.error(typeof e?.detail === 'string' ? e.detail : $i18n.t('Failed to save profile'));
		} finally {
			saving = false;
		}
	};

	const reset = async () => {
		saving = true;
		try {
			await deleteModelProfile(localStorage.token, model.id);
			model.info = model.info ?? {};
			model.info.meta = { ...(model.info.meta ?? {}) };
			model.info.meta.profile_effort = undefined;
			model.info.meta.profile_thinking_budget = undefined;
			effort = '';
			thinkingBudget = '';
			displayName = '';
			toast.success($i18n.t('Profile reset'));
			dispatch('saved', model); // custom name reverts on the next model list refresh
			show = false;
		} catch (e: any) {
			toast.error(typeof e?.detail === 'string' ? e.detail : $i18n.t('Failed to reset profile'));
		} finally {
			saving = false;
		}
	};
</script>

<Modal bind:show size="sm">
	<div class="px-5 py-4 text-gray-700 dark:text-gray-100">
		<div class="flex items-center justify-between mb-1">
			<div class="text-base font-medium line-clamp-1">{model?.name ?? model?.id}</div>
			<button
				class="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
				aria-label={$i18n.t('Close')}
				on:click={() => (show = false)}
			>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
					<path d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z" />
				</svg>
			</button>
		</div>
		<div class="text-xs text-gray-500 dark:text-gray-400 mb-4">{model?.id}</div>

		<!-- Reasoning effort -->
		<div class="mb-4">
			<div class="text-xs font-medium mb-1.5">{$i18n.t('Reasoning effort')}</div>
			{#if supportsEffort}
				<div class="flex gap-1.5">
					{#each EFFORTS as opt}
						<button
							class="flex-1 px-3 py-1.5 rounded-lg text-sm border transition-colors {effort === opt.id
								? 'bg-gray-900 text-white border-gray-900 dark:bg-gray-100 dark:text-gray-900 dark:border-gray-100'
								: 'border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800'}"
							on:click={() => (effort = effort === opt.id ? '' : opt.id)}
						>
							{opt.label}
						</button>
					{/each}
				</div>
				<div class="text-[11px] text-gray-400 mt-1">
					{$i18n.t('Higher = deeper thinking, slower. Applied on API-key models; best-effort on subscription.')}
				</div>
			{:else}
				<div class="text-xs text-gray-400">
					{$i18n.t('This model has no reasoning-effort control.')}
				</div>
			{/if}
		</div>

		<!-- Thinking budget -->
		{#if supportsEffort}
			<div class="mb-4">
				<div class="text-xs font-medium mb-1.5">{$i18n.t('Thinking budget (tokens)')}</div>
				<input
					type="number"
					min="0"
					step="1000"
					bind:value={thinkingBudget}
					placeholder={$i18n.t('Default for the chosen effort')}
					class="w-full px-3 py-1.5 rounded-lg text-sm bg-transparent border border-gray-200 dark:border-gray-700 outline-none"
				/>
			</div>
		{/if}

		<!-- Display name -->
		<div class="mb-5">
			<div class="text-xs font-medium mb-1.5">{$i18n.t('Display name')}</div>
			<input
				type="text"
				maxlength="60"
				bind:value={displayName}
				on:input={() => (nameTouched = true)}
				placeholder={model?.name ?? ''}
				class="w-full px-3 py-1.5 rounded-lg text-sm bg-transparent border border-gray-200 dark:border-gray-700 outline-none"
			/>
		</div>

		<div class="flex items-center justify-between">
			<button
				class="text-xs text-gray-500 hover:text-red-500 disabled:opacity-50"
				disabled={saving}
				on:click={reset}
			>
				{$i18n.t('Reset to default')}
			</button>
			<div class="flex gap-2">
				<button
					class="px-3 py-1.5 rounded-lg text-sm border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 disabled:opacity-50"
					disabled={saving}
					on:click={() => (show = false)}
				>
					{$i18n.t('Cancel')}
				</button>
				<button
					class="px-4 py-1.5 rounded-lg text-sm bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900 hover:opacity-90 disabled:opacity-50"
					disabled={saving}
					on:click={save}
				>
					{$i18n.t('Save')}
				</button>
			</div>
		</div>
	</div>
</Modal>
