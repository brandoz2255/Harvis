<script lang="ts">
	import { getContext } from 'svelte';
	import { models } from '$lib/stores';

	const i18n: any = getContext('i18n');

	// Dock-ready (later dock-router phase).
	export let mode: 'full' | 'dock' = 'full';

	// v1: pick N models, compare their metadata side-by-side. Live multi-model
	// chat (stream the same prompt to each) is a follow-up. Uses a simple picker
	// from $models for robustness.
	let picks: string[] = ['', ''];

	$: cols = picks.map((id) => ({ id, model: $models.find((m: any) => m.id === id) as any }));

	const addCol = () => (picks = [...picks, '']);
	const removeCol = (i: number) => (picks = picks.filter((_, idx) => idx !== i));
</script>

<div class="w-full h-full overflow-auto p-4">
	<div class="flex items-center justify-between mb-3">
		<h2 class="text-sm font-semibold text-gray-500 uppercase tracking-wide">
			{$i18n.t('Model Comparison')}
		</h2>
		<button
			class="text-xs px-2 py-1 rounded-lg bg-gray-100 dark:bg-gray-850 hover:bg-gray-200 dark:hover:bg-gray-800 transition"
			on:click={addCol}>+ {$i18n.t('Add model')}</button
		>
	</div>

	<div class="flex gap-3 flex-wrap">
		{#each cols as col, i (i)}
			<div
				class="flex-1 min-w-[15rem] rounded-2xl border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-900 p-3"
			>
				<div class="flex items-center gap-2 mb-2">
					<select
						bind:value={picks[i]}
						class="flex-1 rounded-lg py-2 px-3 text-sm bg-gray-50 dark:bg-gray-850 outline-none"
					>
						<option value="">{$i18n.t('Select a model')}</option>
						{#each $models as m}
							<option value={m.id}>{m.name}</option>
						{/each}
					</select>
					{#if picks.length > 1}
						<button
							class="text-xs text-gray-400 hover:text-red-500 shrink-0"
							on:click={() => removeCol(i)}
							aria-label={$i18n.t('Remove')}>✕</button
						>
					{/if}
				</div>

				{#if col.model}
					<div class="text-xs text-gray-600 dark:text-gray-300 space-y-1">
						<div><span class="text-gray-400">{$i18n.t('Name')}:</span> {col.model.name}</div>
						<div class="truncate">
							<span class="text-gray-400">{$i18n.t('ID')}:</span> {col.model.id}
						</div>
						{#if col.model.owned_by}<div>
								<span class="text-gray-400">{$i18n.t('Provider')}:</span> {col.model.owned_by}
							</div>{/if}
						{#if col.model.size}<div>
								<span class="text-gray-400">{$i18n.t('Size')}:</span>
								{(col.model.size / 1e9).toFixed(1)} GB
							</div>{/if}
						{#if col.model.details?.parameter_size}<div>
								<span class="text-gray-400">{$i18n.t('Params')}:</span>
								{col.model.details.parameter_size}
							</div>{/if}
						{#if col.model.details?.quantization_level}<div>
								<span class="text-gray-400">{$i18n.t('Quant')}:</span>
								{col.model.details.quantization_level}
							</div>{/if}
					</div>
				{:else}
					<div class="text-xs text-gray-400">{$i18n.t('Pick a model to compare.')}</div>
				{/if}
			</div>
		{/each}
	</div>
</div>
