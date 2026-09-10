<script lang="ts">
	import { onMount, onDestroy, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';

	import Spinner from '$lib/components/common/Spinner.svelte';
	import Switch from '$lib/components/common/Switch.svelte';

	import Pane from './ui/Pane.svelte';
	import Row from './ui/Row.svelte';
	import Section from './ui/Section.svelte';

	import {
		getNodePower,
		setNodePower,
		getMoeCandidates,
		type NodePower,
		type MoeCandidates,
		type MoeVerdict
	} from '$lib/apis/inference-nodes';

	const i18n = getContext('i18n');

	let power: NodePower | null = null;
	let moe: MoeCandidates | null = null;
	let busy = false;
	let scanning = false;
	let poll: ReturnType<typeof setInterval> | null = null;

	// Switch is bound to intent, not to observed state: while the checkpoint loads the
	// node is neither on nor off, and a switch that snapped back would read as a failure.
	let want = false;

	const refresh = async () => {
		power = await getNodePower();
		if (power && !busy) want = power.running || power.loading;
	};

	const scan = async () => {
		scanning = true;
		moe = await getMoeCandidates();
		scanning = false;
	};

	const toggle = async () => {
		// Switch has no disabled prop, so an un-actionable flip is undone here rather than
		// leaving the UI claiming a state the host never agreed to.
		if (!power?.controllable || busy) {
			want = !!power?.running || !!power?.loading;
			if (!power?.controllable) toast.error(power?.hint ?? 'No host control agent is listening.');
			return;
		}
		const next = want ? 'on' : 'off';
		busy = true;
		const res = await setNodePower(next, power.node);
		busy = false;
		if (!res.ok) {
			want = !want;
			toast.error(res.error ?? 'Could not reach the host control agent.');
			return;
		}
		power = res.power ?? power;
		want = !!power?.running || !!power?.loading;
		if (next === 'on' && !power?.running) {
			toast.warning(power?.hint ?? 'Asked the host to start it; it has not answered yet.');
		} else {
			toast.success(next === 'on' ? `${power?.node} is serving.` : `${power?.node} stopped.`);
		}
		await scan(); // verdicts change once a node is up
	};

	const verdictClass = (v: MoeVerdict) =>
		({
			node_would_help: 'text-amber-600 dark:text-amber-400',
			served_by_node: 'text-green-600 dark:text-green-400',
			fits_anyway: 'text-gray-500',
			dense: 'text-gray-400 dark:text-gray-600'
		})[v];

	const verdictLabel = (v: MoeVerdict) =>
		({
			node_would_help: 'Worth a node',
			served_by_node: 'On a node',
			fits_anyway: 'Fine as-is',
			dense: 'Dense'
		})[v];

	const billions = (n: number | null) => (n ? `${(n / 1e9).toFixed(1)}B` : '—');

	onMount(async () => {
		await Promise.all([refresh(), scan()]);
		// Only while something is in flight: a loading checkpoint takes 30–90 s and the
		// switch should stop saying "loading" on its own.
		poll = setInterval(() => {
			if (power?.loading || busy) refresh();
		}, 5000);
	});

	onDestroy(() => {
		if (poll) clearInterval(poll);
	});
</script>

<Pane
	title={$i18n.t('Inference Nodes')}
	description={$i18n.t(
		'Experimental. A local node keeps a large sparse model resident on this machine so chats can route to it instead of an API.'
	)}
>
	<Section title={$i18n.t('Local inference node')}>
		{#if power === null}
			<div class="flex justify-center py-6"><Spinner /></div>
		{:else}
			<Row>
				<svelte:fragment slot="detail">
					<div class="text-xs font-medium text-gray-800 dark:text-gray-100">
						{power.node}
						{#if power.loading}
							<span class="text-amber-600 dark:text-amber-400 ml-1">loading…</span>
						{:else if power.running}
							<span class="text-green-600 dark:text-green-400 ml-1">serving</span>
						{:else}
							<span class="text-gray-500 ml-1">stopped</span>
						{/if}
					</div>
					<div class="text-xs leading-relaxed text-gray-500 dark:text-gray-400 mt-1">
						{#if !power.controllable}
							{power.hint ?? 'No host control agent is listening.'}
						{:else if power.loading}
							The port is open but the checkpoint is still loading — a chat routed here now
							would wait.
						{:else if power.auto_wake}
							Starts itself when a chat picks a model it serves.
						{:else}
							Auto-wake is off; a chat for its models will fail while it is stopped.
						{/if}
					</div>
					{#if power.agent_error}
						<div class="text-xs text-red-500 mt-1.5">Host agent: {power.agent_error}</div>
					{/if}
					{#if power.agent_stale}
						<div class="text-xs leading-relaxed text-amber-600 dark:text-amber-400 mt-1.5">
							The host agent has not acknowledged the last request. Check
							<code>systemctl --user status freetoken-control.path</code> on that machine.
						</div>
					{/if}
				</svelte:fragment>

				<div class="flex items-center gap-2">
					{#if busy}
						<Spinner className="size-4" />
					{/if}
					<Switch
						bind:state={want}
						tooltip={power.controllable
							? 'Starting takes 30–90 s while the checkpoint loads.'
							: 'Run scripts/freetoken/install-user-units.sh on the machine that runs it.'}
						on:change={toggle}
					/>
				</div>
			</Row>
		{/if}
	</Section>

	<Section
		title={$i18n.t('Mixture-of-experts models')}
		description={$i18n.t(
			"A node earns its keep on sparse models: they activate a few experts per token, so the rest can sit in host RAM. Read from each model's GGUF metadata, not its name."
		)}
	>
		<svelte:fragment slot="action">
			<button
				class="text-xs font-normal text-gray-500 hover:text-gray-700 dark:hover:text-gray-300 disabled:opacity-50"
				type="button"
				on:click={scan}
				disabled={scanning}>{scanning ? 'scanning…' : 'rescan'}</button
			>
		</svelte:fragment>

		{#if moe === null}
			{#if scanning}
				<div class="flex justify-center py-6"><Spinner /></div>
			{:else}
				<Row description="Ollama is not answering, so nothing was scanned." />
			{/if}
		{:else if moe.models.length === 0}
			<Row description="No models are installed." />
		{:else}
			{#each moe.models.filter((m) => m.verdict !== 'dense') as m (m.name)}
				<Row label={m.name} description={m.why}>
					<div class="text-xs text-right {verdictClass(m.verdict)}">
						{verdictLabel(m.verdict)}
						<div class="text-gray-500">
							{billions(m.active_params)} of {billions(m.params)} active
						</div>
					</div>
				</Row>
			{/each}
			<Row>
				<svelte:fragment slot="detail">
					<div class="text-xs leading-relaxed text-gray-500 dark:text-gray-400">
						{moe.counts.dense} dense model{moe.counts.dense === 1 ? '' : 's'} hidden — the
						offload path does not apply to them.
					</div>
					<div class="text-xs leading-relaxed text-gray-500 dark:text-gray-400 mt-1.5">
						{moe.note}
					</div>
				</svelte:fragment>
			</Row>
		{/if}
	</Section>
</Pane>
