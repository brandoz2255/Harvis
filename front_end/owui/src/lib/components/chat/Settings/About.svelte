<script lang="ts">
	import { getOllamaVersion } from '$lib/apis/ollama';
	import { WEBUI_BUILD_HASH, WEBUI_VERSION } from '$lib/constants';
	import { WEBUI_NAME, config } from '$lib/stores';
	import { onMount, getContext } from 'svelte';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import SettingsSection from './SettingsSection.svelte';
	import SettingRow from './SettingRow.svelte';

	const i18n = getContext('i18n');

	let ollamaVersion = '';

	onMount(async () => {
		ollamaVersion = await getOllamaVersion(localStorage.token).catch(() => '');
	});
</script>

<div id="tab-about" class="flex flex-col h-full justify-between space-y-4 text-sm mb-6">
	<div class="space-y-4 overflow-y-scroll max-h-[28rem] md:max-h-full">
		<SettingsSection title={$i18n.t('About')}>
			<div slot="description">{$i18n.t('Local-first AI workspace')}</div>
			<SettingRow title={$i18n.t('Product')}>
				<span class="text-sm text-gray-800 dark:text-gray-100 font-medium">{$WEBUI_NAME}</span>
			</SettingRow>
			<!-- Harvis's version is the one the server reports (/api/config). WEBUI_VERSION is
			     the vendored Open WebUI package version — a different project's number, kept
			     because tool/function manifests still compatibility-check against it. -->
			<SettingRow title={$i18n.t('Version')}>
				<Tooltip content={WEBUI_BUILD_HASH || $i18n.t('Build hash unavailable')}>
					<span class="text-sm text-gray-700 dark:text-gray-200"
						>v{$config?.version ?? WEBUI_VERSION}</span
					>
				</Tooltip>
			</SettingRow>
			<SettingRow title={$i18n.t('Open WebUI base')}>
				<span class="text-sm text-gray-700 dark:text-gray-200">v{WEBUI_VERSION}</span>
			</SettingRow>
			{#if ollamaVersion}
				<SettingRow title={$i18n.t('Ollama')}>
					<span class="text-sm text-gray-700 dark:text-gray-200">{ollamaVersion}</span>
				</SettingRow>
			{/if}
		</SettingsSection>

		<SettingsSection title={$i18n.t('Links')}>
			<div class="flex flex-col gap-2 text-sm py-3">
				<a
					class="text-blue-600 dark:text-blue-400 hover:underline"
					href="https://github.com/ommblitz/Harvis"
					target="_blank"
					rel="noopener noreferrer"
				>
					{$i18n.t('GitHub repository')}
				</a>
				<a
					class="text-blue-600 dark:text-blue-400 hover:underline"
					href="https://github.com/ommblitz/Harvis/blob/main/README.md"
					target="_blank"
					rel="noopener noreferrer"
				>
					{$i18n.t('Quick start')} · ./install.sh
				</a>
			</div>
			<p class="text-xs text-gray-500 dark:text-gray-400 leading-relaxed">
				{$i18n.t(
					'Harvis is a self-hosted Open WebUI fork oriented toward local models, Build, and agent tooling. No outbound update checks or badge CDNs in this panel.'
				)}
			</p>
		</SettingsSection>

		{#if $config?.license_metadata}
			<div class="text-xs text-gray-500">
				<span class="font-medium text-gray-600 dark:text-gray-300">{$WEBUI_NAME}</span>
				—
				<span class="capitalize">{$config.license_metadata.type}</span>
				{$i18n.t('license')}
				{#if $config.license_metadata.organization_name}
					· {$config.license_metadata.organization_name}
				{/if}
			</div>
		{/if}

		<div class="text-xs text-gray-400 dark:text-gray-500 space-y-1">
			<p>
				{$i18n.t('Emoji graphics by')}
				<a
					href="https://github.com/jdecked/twemoji"
					target="_blank"
					rel="noopener noreferrer"
					class="underline">Twemoji</a
				>
				({$i18n.t('CC-BY 4.0')}).
			</p>
			<p>
				{$i18n.t(
					'Includes upstream Open WebUI code under its license; Harvis branding and local-first paths are project-specific.'
				)}
			</p>
		</div>
	</div>
</div>
