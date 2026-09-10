<script lang="ts">
	import { WEBUI_BASE_URL } from '$lib/constants';
	import { showControls, workspaceControlsTab } from '$lib/stores';
	import { agentHeadline, type AgentRunState } from './agentRunProjection';

	export let state: AgentRunState;
	export let workspaceId = '';
	export let tint = '#7c5cff';

	let deciding = false;

	const decide = async (approve: boolean) => {
		const actionId = state.pending?.actionId;
		if (!actionId || !workspaceId || deciding) return;
		deciding = true;
		try {
			await fetch(
				`${WEBUI_BASE_URL}/api/workspace/run/${workspaceId}/action/${actionId}/${
					approve ? 'approve' : 'deny'
				}`,
				{
					method: 'POST',
					headers: { Authorization: `Bearer ${localStorage.token}` },
					credentials: 'include'
				}
			);
		} catch (e) {
			console.error('agent approval failed', e);
		} finally {
			deciding = false;
		}
	};

	// Docks the teammate's screen beside the chat (the Computer tab in the right rail).
	const openComputer = () => {
		workspaceControlsTab.set('computer');
		showControls.set(true);
	};

	// The first time a live run touches its browser, dock the screen on its own —
	// the user asked for the work, not for a tab hunt. Only once per card, and not
	// during the replay a reload folds through in its first moment (those are old
	// events; a finished run must not yank the rail open).
	const mountedAt = Date.now();
	let dockedOnce = false;
	$: if (
		state.usesComputer &&
		!dockedOnce &&
		(state.status === 'running' || state.status === 'waiting') &&
		Date.now() - mountedAt > 1500
	) {
		dockedOnce = true;
		openComputer();
	}

	const stepDot = (status: string) =>
		status === 'done' ? 'bg-emerald-400' : status === 'error' ? 'bg-rose-400' : 'bg-amber-300';

	$: headline = agentHeadline(state);
	$: hasBody =
		state.goal || state.steps.length || state.delivery || state.suggestions.length || state.pending;
</script>

{#if hasBody}
	<div class="rounded-xl border border-white/10 bg-black/20 p-3 text-sm">
		<div class="flex items-center gap-2">
			<span
				class="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
				style={`background:${tint}`}
				aria-hidden="true"
			></span>
			<span class="font-medium">{state.agentName || state.agentLabel || 'Teammate'}</span>
			<span class="text-xs opacity-60">{headline}</span>
			<button
				class="ml-auto rounded-md px-2 py-0.5 text-[11px] opacity-70 hover:bg-white/10 hover:opacity-100"
				title="Watch the teammate's browser, or take the wheel"
				on:click={openComputer}>Computer</button
			>
			{#if state.unsupervisedShell}
				<span
					class="rounded-full border border-amber-400/40 px-2 py-0.5 text-[10px] text-amber-200"
					title="A step ran on an engine that keeps its own shell inside the sandbox copy. Harvis gated its browser actions but did not see each command."
				>
					unsupervised shell
				</span>
			{/if}
		</div>

		{#if state.goal}
			<p class="mt-2 opacity-80">{state.goal}</p>
		{/if}

		{#if state.steps.length}
			<ol class="mt-3 space-y-1.5">
				{#each state.steps as step (step.n)}
					<li class="flex items-start gap-2">
						<span
							class={`mt-1.5 inline-block h-1.5 w-1.5 shrink-0 rounded-full ${stepDot(step.status)}`}
							aria-hidden="true"
						></span>
						<span class="min-w-0">
							<span class="opacity-90">{step.label || `Step ${step.n}`}</span>
							<span class="ml-1.5 text-[11px] opacity-50"
								>{step.engine}{step.model ? ` · ${step.model}` : ''}</span
							>
							{#if step.summary}
								<span class="block text-xs opacity-60">{step.summary}</span>
							{/if}
						</span>
					</li>
				{/each}
			</ol>
		{/if}

		{#if state.pending}
			<div class="mt-3 rounded-lg border border-amber-400/30 bg-amber-400/5 p-2.5">
				<p class="text-xs">
					<span class="font-medium">Needs you:</span>
					{state.pending.reason || state.pending.tool}
				</p>
				<div class="mt-2 flex gap-2">
					<button
						class="rounded-md bg-emerald-500/20 px-2.5 py-1 text-xs hover:bg-emerald-500/30 disabled:opacity-50"
						disabled={deciding}
						on:click={() => decide(true)}>Allow once</button
					>
					<button
						class="rounded-md bg-white/5 px-2.5 py-1 text-xs hover:bg-white/10 disabled:opacity-50"
						disabled={deciding}
						on:click={() => decide(false)}>Don't</button
					>
				</div>
			</div>
		{/if}

		{#if state.delivery}
			<div class="mt-3">
				<p class="text-xs opacity-70">{state.delivery.summary}</p>
				{#if state.delivery.artifacts.length}
					<ul class="mt-1.5 flex flex-wrap gap-1.5">
						{#each state.delivery.artifacts as file (file)}
							<li class="rounded-md bg-white/5 px-2 py-0.5 font-mono text-[11px]">{file}</li>
						{/each}
					</ul>
				{/if}
			</div>
		{/if}

		{#if state.suggestions.length}
			<div class="mt-3">
				<p class="text-xs opacity-60">Worth doing next</p>
				<ul class="mt-1 space-y-1">
					{#each state.suggestions as s (s)}
						<li class="text-xs opacity-85">- {s}</li>
					{/each}
				</ul>
			</div>
		{/if}
	</div>
{/if}
