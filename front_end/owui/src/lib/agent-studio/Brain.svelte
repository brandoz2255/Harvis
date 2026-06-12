<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { getSkills } from '$lib/apis/skills';
	import WorkspaceSettings from '$lib/components/chat/Settings/WorkspaceSettings.svelte';
	import MemoryPanel from './MemoryPanel.svelte';
	import TuningPanel from './TuningPanel.svelte';
	import GlobalMap from './GlobalMap.svelte';
	import RailCard from '$lib/components/common/RailCard.svelte';
	import Cloud from '$lib/components/icons/Cloud.svelte';
	import Sparkles from '$lib/components/icons/Sparkles.svelte';
	import Cube from '$lib/components/icons/Cube.svelte';
	import AdjustmentsHorizontal from '$lib/components/icons/AdjustmentsHorizontal.svelte';
	import Map from '$lib/components/icons/Map.svelte';

	const i18n: any = getContext('i18n');

	// Standalone + dock-ready: a later dock-router phase mounts this same
	// component with mode='dock'. Unused for now (full-page mount only).
	export let mode: 'full' | 'dock' = 'full';

	let open = { openclaw: true, skills: false, memory: true, neuralmap: false, tuning: false };

	let skills: any[] = [];
	let skillsLoading = true;
	const loadSkills = async () => {
		skillsLoading = true;
		try {
			const res = await getSkills(localStorage.token);
			skills = Array.isArray(res) ? res : (res?.skills ?? res?.data ?? []);
		} catch (e) {
			console.error('getSkills', e);
			skills = [];
		}
		skillsLoading = false;
	};

	onMount(loadSkills);
</script>

<div class="space-y-2" class:text-sm={mode === 'dock'}>
	<!-- OpenClaw -->
	<RailCard title={$i18n.t('OpenClaw')} icon={Cloud} bind:open={open.openclaw}>
		<WorkspaceSettings />
	</RailCard>

	<!-- Skills -->
	<RailCard
		title={$i18n.t('Skills')}
		icon={Sparkles}
		count={skillsLoading ? null : skills.length}
		bind:open={open.skills}
	>
		<div class="text-sm">
			{#if skillsLoading}
				<div class="text-gray-500 text-xs">{$i18n.t('Loading…')}</div>
			{:else if skills.length === 0}
				<div class="text-gray-500 text-xs">
					{$i18n.t('No skills registered. Skills are provided by the Harvis agent runtime.')}
				</div>
			{:else}
				<div class="space-y-1.5 max-h-72 overflow-y-auto pr-1">
					{#each skills as s, i (s.id ?? s.name ?? i)}
						<div
							class="rounded-lg border border-gray-100 dark:border-gray-850 bg-white dark:bg-gray-850/40 px-3 py-2"
						>
							<div class="font-medium text-gray-700 dark:text-gray-200">
								{s.name ?? s.id ?? $i18n.t('Skill')}
							</div>
							{#if s.description}<div class="mt-0.5 text-xs text-gray-500">{s.description}</div>{/if}
						</div>
					{/each}
				</div>
			{/if}
		</div>
	</RailCard>

	<!-- Memory -->
	<RailCard title={$i18n.t('Memory')} icon={Cube} bind:open={open.memory}>
		<MemoryPanel />
	</RailCard>

	<!-- Neural Map — the brain's map of sessions + runs (closed = unmounted = no fetch) -->
	<RailCard title={$i18n.t('Neural Map')} icon={Map} bind:open={open.neuralmap}>
		<svelte:fragment slot="actions">
			<a
				href="/harvis/agent-studio/global-map"
				class="text-[11px] px-2 py-0.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition shrink-0"
			>
				{$i18n.t('Open full')}
			</a>
		</svelte:fragment>
		<div class="h-72 rounded-xl overflow-hidden border border-gray-100 dark:border-gray-850">
			<GlobalMap embedded mode="dock" />
		</div>
	</RailCard>

	<!-- Tuning — the agent's default behaviour (relocated Controls component) -->
	<RailCard title={$i18n.t('Tuning')} icon={AdjustmentsHorizontal} bind:open={open.tuning}>
		<TuningPanel mode="dock" />
	</RailCard>
</div>
