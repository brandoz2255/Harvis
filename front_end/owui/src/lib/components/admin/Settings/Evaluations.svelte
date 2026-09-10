<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { models, settings, user, config } from '$lib/stores';
	import { createEventDispatcher, onMount, getContext, tick } from 'svelte';

	const dispatch = createEventDispatcher();
	import { getModels } from '$lib/apis';
	import { getConfig, updateConfig } from '$lib/apis/evaluations';

	import Switch from '$lib/components/common/Switch.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Plus from '$lib/components/icons/Plus.svelte';
	import Model from './Evaluations/Model.svelte';
	import ArenaModelModal from './Evaluations/ArenaModelModal.svelte';

	import Pane from './ui/Pane.svelte';
	import Row from './ui/Row.svelte';
	import Section from './ui/Section.svelte';

	const i18n = getContext('i18n');

	let evaluationConfig = null;
	let showAddModel = false;

	const submitHandler = async () => {
		evaluationConfig = await updateConfig(localStorage.token, evaluationConfig).catch((err) => {
			toast.error(err);
			return null;
		});

		if (evaluationConfig) {
			toast.success($i18n.t('Settings saved successfully!'));
			models.set(
				await getModels(
					localStorage.token,
					$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
				)
			);
		}
	};

	const addModelHandler = async (model) => {
		evaluationConfig.EVALUATION_ARENA_MODELS.push(model);
		evaluationConfig.EVALUATION_ARENA_MODELS = [...evaluationConfig.EVALUATION_ARENA_MODELS];

		await submitHandler();
		models.set(
			await getModels(
				localStorage.token,
				$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
			)
		);
	};

	const editModelHandler = async (model, modelIdx) => {
		evaluationConfig.EVALUATION_ARENA_MODELS[modelIdx] = model;
		evaluationConfig.EVALUATION_ARENA_MODELS = [...evaluationConfig.EVALUATION_ARENA_MODELS];

		await submitHandler();
		models.set(
			await getModels(
				localStorage.token,
				$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
			)
		);
	};

	const deleteModelHandler = async (modelIdx) => {
		evaluationConfig.EVALUATION_ARENA_MODELS = evaluationConfig.EVALUATION_ARENA_MODELS.filter(
			(m, mIdx) => mIdx !== modelIdx
		);

		await submitHandler();
		models.set(
			await getModels(
				localStorage.token,
				$config?.features?.enable_direct_connections && ($settings?.directConnections ?? null)
			)
		);
	};

	onMount(async () => {
		if ($user?.role === 'admin') {
			evaluationConfig = await getConfig(localStorage.token).catch((err) => {
				toast.error(err);
				return null;
			});
		}
	});
</script>

<ArenaModelModal
	bind:show={showAddModel}
	on:submit={async (e) => {
		addModelHandler(e.detail);
	}}
/>

<form
	class="text-sm h-full"
	on:submit|preventDefault={() => {
		submitHandler();
		dispatch('save');
	}}
>
	<Pane
		title={$i18n.t('Evaluations')}
		description={$i18n.t(
			'Arena mode pits models against each other in blind comparisons and ranks them from the ratings users give.'
		)}
	>
		{#if evaluationConfig !== null}
			<Section title={$i18n.t('General')}>
				<Row label={$i18n.t('Arena Models')}>
					<Tooltip content={$i18n.t(`Message rating should be enabled to use this feature`)}>
						<Switch bind:state={evaluationConfig.ENABLE_EVALUATION_ARENA_MODELS} />
					</Tooltip>
				</Row>
			</Section>

			{#if evaluationConfig.ENABLE_EVALUATION_ARENA_MODELS}
				<Section title={$i18n.t('Manage')}>
					<svelte:fragment slot="action">
						<Tooltip content={$i18n.t('Add Arena Model')}>
							<button
								class="p-1"
								type="button"
								on:click={() => {
									showAddModel = true;
								}}
							>
								<Plus />
							</button>
						</Tooltip>
					</svelte:fragment>

					<div class="py-3 flex flex-col gap-2">
						{#if (evaluationConfig?.EVALUATION_ARENA_MODELS ?? []).length > 0}
							{#each evaluationConfig.EVALUATION_ARENA_MODELS as model, index}
								<Model
									{model}
									on:edit={(e) => {
										editModelHandler(e.detail, index);
									}}
									on:delete={(e) => {
										deleteModelHandler(index);
									}}
								/>
							{/each}
						{:else}
							<div class=" text-center text-xs text-gray-500">
								{$i18n.t(
									`Using the default arena model with all models. Click the plus button to add custom models.`
								)}
							</div>
						{/if}
					</div>
				</Section>
			{/if}
		{:else}
			<Section>
				<div class="flex justify-center py-6">
					<Spinner className="size-6" />
				</div>
			</Section>
		{/if}

		<svelte:fragment slot="actions">
			<button
				class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-lg disabled:opacity-50 disabled:cursor-not-allowed"
				type="submit"
			>
				{$i18n.t('Save')}
			</button>
		</svelte:fragment>
	</Pane>
</form>
