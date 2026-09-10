<script lang="ts">
	// Harvis Workspace / OpenClaw settings — backed by the existing Harvis
	// endpoints (no OWUI backend): /api/user/openclaw-config (GET/POST/DELETE)
	// and /api/workspace/usage/summary. The stored API key is encrypted
	// server-side and NEVER returned by GET, so it is never echoed here.
	import { onMount, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import { WEBUI_BASE_URL } from '$lib/constants';
	import SettingsSection from './SettingsSection.svelte';
	import SettingRow from './SettingRow.svelte';

	const i18n: any = getContext('i18n');
	export let saveSettings: Function = () => {};

	let loading = true;
	let saving = false;

	let providerType = 'ollama';
	let providerUrl = 'http://ollama:11434';
	let modelId = '';
	let apiKey = ''; // write-only; never populated from the server
	let hasStoredConfig = false;
	let usage: any = null;
	let loadError = '';

	$: hasUsage =
		usage &&
		[usage.total_tokens, usage.tokens_in, usage.tokens_out, usage.cost_usd, usage.runs, usage.sessions].some(
			(v) => v != null
		);

	const authHeaders = () => ({
		Authorization: `Bearer ${localStorage.token}`,
		'Content-Type': 'application/json'
	});

	const load = async () => {
		loading = true;
		loadError = '';
		try {
			const res = await fetch(`${WEBUI_BASE_URL}/api/user/openclaw-config`, { headers: authHeaders() });
			if (res.ok) {
				const d = await res.json();
				providerType = d.provider_type ?? 'ollama';
				providerUrl = d.provider_url ?? 'http://ollama:11434';
				modelId = d.model_id ?? '';
				hasStoredConfig = !!d.id;
			} else {
				// A failed GET used to fall through silently, leaving the form showing
				// the hard-coded Ollama defaults as if they were the saved config —
				// and Save would then write those over whatever the server holds.
				loadError = `${res.status} ${res.statusText}`.trim();
			}
		} catch (e) {
			console.error('openclaw-config load', e);
			loadError = `${e}`;
		}
		try {
			const u = await fetch(`${WEBUI_BASE_URL}/api/workspace/usage/summary`, { headers: authHeaders() });
			if (u.ok) usage = await u.json();
		} catch (e) {
			console.error('usage/summary load', e);
		}
		loading = false;
	};

	const save = async () => {
		if (loadError) {
			toast.error($i18n.t('Cannot save while the current settings failed to load.'));
			return;
		}
		saving = true;
		try {
			const body: Record<string, any> = {
				provider_url: providerUrl,
				model_id: modelId,
				provider_type: providerType
			};
			if (apiKey.trim()) body.api_key = apiKey.trim();
			const res = await fetch(`${WEBUI_BASE_URL}/api/user/openclaw-config`, {
				method: 'POST',
				headers: authHeaders(),
				body: JSON.stringify(body)
			});
			if (res.ok) {
				toast.success($i18n.t('Workspace settings saved'));
				apiKey = '';
				await load();
			} else {
				toast.error($i18n.t('Failed to save workspace settings'));
			}
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			saving = false;
		}
	};

	const resetToDefault = async () => {
		try {
			const res = await fetch(`${WEBUI_BASE_URL}/api/user/openclaw-config`, {
				method: 'DELETE',
				headers: authHeaders()
			});
			if (res.ok) {
				toast.success($i18n.t('Reset to default (Ollama)'));
				await load();
			} else {
				toast.error($i18n.t('Failed to reset workspace settings'));
			}
		} catch (e) {
			toast.error(`${e}`);
		}
	};

	onMount(load);
</script>

<div class="flex flex-col h-full justify-between text-sm">
	<div class="overflow-y-scroll max-h-[28rem] md:max-h-full pr-1">
		<SettingsSection title={$i18n.t('Workspace / OpenClaw')}>
			{#if loading}
				<div class="text-gray-500">{$i18n.t('Loading…')}</div>
			{:else if loadError}
				<div
					class="rounded-lg bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900 px-3 py-2.5 text-sm text-red-700 dark:text-red-300"
				>
					<div class="font-medium">{$i18n.t('Could not load your workspace settings.')}</div>
					<div class="mt-0.5 text-xs opacity-80">{loadError}</div>
					<button
						class="mt-2 text-xs font-medium underline underline-offset-2"
						type="button"
						on:click={load}>{$i18n.t('Retry')}</button
					>
				</div>
			{:else}
				<div class="text-sm text-gray-500 dark:text-gray-400">
					{$i18n.t('The model the Harvis agent (OpenClaw) uses for workspace runs.')}
				</div>

				<SettingRow title={$i18n.t('Provider')}>
					<select
						bind:value={providerType}
						class="w-44 sm:w-56 cursor-pointer rounded-[10px] py-2 px-3 pr-8 text-sm bg-gray-100 dark:bg-gray-850 text-gray-800 dark:text-gray-100 outline-none"
					>
						<option value="ollama">Ollama (local)</option>
						<option value="openai">OpenAI-compatible</option>
					</select>
				</SettingRow>

				<SettingRow title={$i18n.t('Provider URL')} stack={true}>
					<input
						bind:value={providerUrl}
						class="w-full rounded-[10px] py-2 px-3 text-sm bg-gray-100 dark:bg-gray-850 text-gray-800 dark:text-gray-100 outline-none"
						placeholder="http://ollama:11434"
					/>
				</SettingRow>

				<SettingRow title={$i18n.t('Model')} stack={true}>
					<input
						bind:value={modelId}
						class="w-full rounded-[10px] py-2 px-3 text-sm bg-gray-100 dark:bg-gray-850 text-gray-800 dark:text-gray-100 outline-none"
						placeholder="qwen2.5-coder:32b"
					/>
				</SettingRow>

				<SettingRow
					title={$i18n.t('API key')}
					description={$i18n.t('Stored encrypted on the server and never displayed.')}
					stack={true}
				>
					<input
						type="password"
						bind:value={apiKey}
						autocomplete="off"
						class="w-full rounded-[10px] py-2 px-3 text-sm bg-gray-100 dark:bg-gray-850 text-gray-800 dark:text-gray-100 outline-none"
						placeholder={hasStoredConfig
							? $i18n.t('Leave blank to keep current')
							: $i18n.t('Only needed for cloud providers')}
					/>
				</SettingRow>
			{/if}
		</SettingsSection>

		{#if !loading && hasUsage}
			<SettingsSection title={$i18n.t('Usage')}>
				<div class="text-sm text-gray-600 dark:text-gray-300 space-y-0.5">
					{#if usage.total_tokens != null}<div>{$i18n.t('Total tokens')}: {usage.total_tokens}</div>{/if}
					{#if usage.tokens_in != null}<div>{$i18n.t('Tokens in')}: {usage.tokens_in}</div>{/if}
					{#if usage.tokens_out != null}<div>{$i18n.t('Tokens out')}: {usage.tokens_out}</div>{/if}
					{#if usage.cost_usd != null}<div>{$i18n.t('Cost (USD)')}: {usage.cost_usd}</div>{/if}
					{#if usage.runs != null}<div>{$i18n.t('Runs')}: {usage.runs}</div>{/if}
					{#if usage.sessions != null}<div>{$i18n.t('Sessions')}: {usage.sessions}</div>{/if}
				</div>
			</SettingsSection>
		{/if}
	</div>

	<div class="flex justify-between pt-3">
		<button
			class="text-xs px-3 py-2 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-850 transition"
			type="button"
			disabled={loading || !!loadError}
			on:click={resetToDefault}>{$i18n.t('Reset to default')}</button
		>
		<button
			class="text-xs px-3.5 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition disabled:opacity-50"
			type="button"
			on:click={save}
			disabled={saving || loading || !!loadError}>{saving
				? $i18n.t('Saving…')
				: $i18n.t('Save')}</button
		>
	</div>
</div>
