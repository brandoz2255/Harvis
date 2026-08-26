<script lang="ts">
	// The user-facing status page for the local CAD lane, and — for an admin — the
	// operator view of how the engine is actually configured.
	//
	// Everything here is read from `/api/cad/capability`, which probes the engine
	// rather than reporting the flag it was started with. That distinction is the
	// whole point of the panel: "the operator switched CAD on" and "the geometry
	// kernel is answering" are different claims, and a lane that reports ready and
	// then 502s on the first build is the dishonesty this page exists to prevent.
	//
	// There are no controls. Concurrency, the build deadline and the memory ceiling
	// are baked into the container at create time, so a toggle here would be a
	// button that silently does nothing. The panel names the env var or compose key
	// instead, which is the thing an operator can actually act on.
	import { getContext, onMount } from 'svelte';
	import { getCadCapability, type CadCapability } from '$lib/apis/cad';
	import { user } from '$lib/stores';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import SettingsSection from './SettingsSection.svelte';

	const i18n: any = getContext('i18n');

	let cap: CadCapability | null = null;
	let probed = false;

	// Null is the honest state for "the route is not there": every /api/cad route
	// 404s when the lane is off, so an absent capability means no feature rather
	// than a failed request. It is rendered as "not installed", not as an error.
	onMount(async () => {
		cap = await getCadCapability();
		probed = true;
	});

	$: engine = (cap?.engine ?? {}) as Record<string, any>;
	$: pool = (engine.worker_pool ?? null) as { size: number; free: number } | null;

	$: quotaPct =
		cap && cap.quota.user_limit_bytes > 0
			? Math.min(100, (cap.quota.user_used_bytes / cap.quota.user_limit_bytes) * 100)
			: 0;

	const fmtBytes = (n: number | null | undefined) => {
		if (n == null) return '—';
		if (n >= 1_073_741_824) return `${(n / 1_073_741_824).toFixed(1)} GB`;
		if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`;
		if (n >= 1024) return `${Math.round(n / 1024)} KB`;
		return `${n} B`;
	};
</script>

<div class="text-sm">
	{#if !probed}
		<div class="flex items-center gap-2 text-gray-500 py-6">
			<Spinner className="size-4" />
			{$i18n.t('Checking the CAD lane…')}
		</div>
	{:else if !cap || !cap.enabled}
		<SettingsSection title={$i18n.t('Local CAD')}>
			<svelte:fragment slot="description">
				{$i18n.t('Parametric solid modelling that runs entirely on this machine.')}
			</svelte:fragment>
			<div class="mt-3 rounded-xl border border-gray-100 dark:border-gray-850 px-4 py-3">
				<div class="flex items-center gap-2">
					<span class="size-2 rounded-full bg-gray-400 dark:bg-gray-600 shrink-0"></span>
					<span class="font-medium text-gray-800 dark:text-gray-100"
						>{$i18n.t('Not enabled on this server')}</span
					>
				</div>
				<div class="mt-1.5 text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t(
						'CAD is an optional capability and ships switched off. An administrator turns it on; it is not something this page can enable.'
					)}
				</div>
				{#if $user?.role === 'admin'}
					<div class="mt-3 text-xs text-gray-500 dark:text-gray-400">
						{$i18n.t('To enable it, start the engine and set the flag, then restart the backend:')}
						<pre
							class="mt-1.5 whitespace-pre-wrap break-all rounded-lg bg-gray-50 dark:bg-gray-850 px-2.5 py-2 font-mono text-[11px] text-gray-700 dark:text-gray-300">HARVIS_ADAPTIVE_CAD_ENABLED=true
docker compose --profile cad up -d cad-engine
docker compose up -d backend</pre>
						<div class="mt-1.5">
							{$i18n.t(
								'The flag is read when the container is created, so a plain restart will not pick up a change made only in the shell.'
							)}
						</div>
					</div>
				{/if}
			</div>
		</SettingsSection>
	{:else}
		<SettingsSection title={$i18n.t('Local CAD')}>
			<svelte:fragment slot="description">
				{$i18n.t('Parametric solid modelling that runs entirely on this machine.')}
			</svelte:fragment>

			<div class="mt-3 rounded-xl border border-gray-100 dark:border-gray-850 divide-y divide-gray-100 dark:divide-gray-850">
				<!-- Two separate claims, deliberately on two separate rows. -->
				<div class="flex items-center gap-2 px-4 py-3">
					<span class="size-2 rounded-full bg-emerald-500 shrink-0"></span>
					<span class="text-gray-800 dark:text-gray-100">{$i18n.t('Enabled on this server')}</span>
				</div>
				<div class="flex items-center gap-2 px-4 py-3">
					<span
						class="size-2 rounded-full shrink-0 {cap.engine_reachable
							? 'bg-emerald-500'
							: 'bg-red-500'}"
					></span>
					<span class="text-gray-800 dark:text-gray-100">
						{cap.engine_reachable
							? $i18n.t('Geometry engine is answering')
							: $i18n.t('Geometry engine is not answering')}
					</span>
					{#if !cap.engine_reachable}
						<span class="ml-auto text-xs text-amber-600 dark:text-amber-400">
							{$i18n.t('Builds will fail until it is back')}
						</span>
					{/if}
				</div>
			</div>
		</SettingsSection>

		<SettingsSection title={$i18n.t('What it can make')}>
			<div class="mt-2 flex flex-wrap gap-1.5">
				{#each cap.recipes as r (r)}
					<span
						class="text-[11px] px-2 py-1 rounded-lg border border-gray-100 dark:border-gray-850 text-gray-600 dark:text-gray-300"
						>{r}</span
					>
				{:else}
					<span class="text-xs text-gray-500">{$i18n.t('No shapes are registered.')}</span>
				{/each}
			</div>
			<div class="mt-2.5 text-xs text-gray-500 dark:text-gray-400">
				{$i18n.t('Exports')}: {(cap.formats ?? []).map((f) => f.toUpperCase()).join(' · ') || '—'}
				· {$i18n.t('all dimensions in millimetres')}
			</div>
			<div class="mt-1 text-xs text-gray-500 dark:text-gray-400">
				{$i18n.t(
					'Describe a part in chat and it is built here — nothing is sent to a cloud CAD service.'
				)}
			</div>
		</SettingsSection>

		<SettingsSection title={$i18n.t('Your storage')}>
			<div class="mt-2">
				<div class="h-1.5 w-full rounded-full bg-gray-100 dark:bg-gray-850 overflow-hidden">
					<div
						class="h-full rounded-full transition-all {quotaPct >= 90
							? 'bg-red-500'
							: quotaPct >= 70
								? 'bg-amber-500'
								: 'bg-emerald-500'}"
						style="width: {quotaPct}%"
					></div>
				</div>
				<div class="mt-1.5 text-xs text-gray-500 dark:text-gray-400 tabular-nums">
					{fmtBytes(cap.quota.user_used_bytes)} {$i18n.t('of')}
					{fmtBytes(cap.quota.user_limit_bytes)}
					{$i18n.t('used')} · {$i18n.t('per project')}
					{fmtBytes(cap.quota.project_limit_bytes)}
				</div>
				<div class="mt-1 text-xs text-gray-500 dark:text-gray-400">
					{$i18n.t(
						'A build that would cross the limit is refused before any bytes are written, so the cap is never exceeded and then cleaned up.'
					)}
				</div>
			</div>
		</SettingsSection>

		{#if $user?.role === 'admin'}
			<SettingsSection title={$i18n.t('Engine (admin)')}>
				<svelte:fragment slot="description">
					{$i18n.t(
						'Read from the running container. These are set at container create time — change them in docker-compose.yaml and recreate cad-engine.'
					)}
				</svelte:fragment>
				{#if !cap.engine_reachable}
					<div class="mt-2 text-xs text-gray-500 dark:text-gray-400">
						{$i18n.t('Unavailable — the engine did not answer the probe.')}
					</div>
				{:else}
					<div
						class="mt-2 rounded-xl border border-gray-100 dark:border-gray-850 divide-y divide-gray-100 dark:divide-gray-850 text-xs"
					>
						{#each [['Build deadline', engine.deadline_s != null ? `${engine.deadline_s}s` : '—', 'CAD_DEADLINE_S'], ['Concurrent builds', engine.max_concurrent ?? '—', 'CAD_MAX_CONCURRENT'], ['Warm workers', pool ? `${pool.free} free of ${pool.size}` : '—', ''], ['Building now', engine.active_builds ?? '—', ''], ['build123d', engine.build123d_version ?? '—', ''], ['OCP', engine.ocp_version ?? '—', ''], ['Schema', engine.schema_version ?? '—', ''], ['Formats compiled in', (engine.formats_available ?? []).join(' · ') || '—', '']] as [label, value, envVar]}
							<div class="flex items-baseline gap-3 px-4 py-2">
								<span class="text-gray-500 dark:text-gray-400 shrink-0 w-44">{$i18n.t(label)}</span>
								<span class="text-gray-800 dark:text-gray-100 tabular-nums break-all">{value}</span>
								{#if envVar}
									<span class="ml-auto font-mono text-[10px] text-gray-400 shrink-0">{envVar}</span>
								{/if}
							</div>
						{/each}
					</div>
					<div class="mt-2 text-xs text-gray-500 dark:text-gray-400">
						{$i18n.t(
							'The engine runs read-only, non-root, with all capabilities dropped and no route off its internal network. Each build is a separate process the server can kill.'
						)}
					</div>
				{/if}
			</SettingsSection>
		{/if}
	{/if}
</div>
