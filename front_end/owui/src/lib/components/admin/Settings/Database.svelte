<script lang="ts">
	import fileSaver from 'file-saver';
	const { saveAs } = fileSaver;

	import { downloadDatabase } from '$lib/apis/utils';
	import { onMount, getContext } from 'svelte';
	import { config, user } from '$lib/stores';
	import { toast } from 'svelte-sonner';
	import { getAllUserChats } from '$lib/apis/chats';
	import { getAllUsers } from '$lib/apis/users';
	import { exportConfig, importConfig } from '$lib/apis/configs';

	import Pane from './ui/Pane.svelte';
	import Row from './ui/Row.svelte';
	import Section from './ui/Section.svelte';

	const i18n = getContext('i18n');

	export let saveHandler: Function;

	const exportAllUserChats = async () => {
		let blob = new Blob([JSON.stringify(await getAllUserChats(localStorage.token))], {
			type: 'application/json'
		});
		saveAs(blob, `all-chats-export-${Date.now()}.json`);
	};

	const exportUsers = async () => {
		const users = await getAllUsers(localStorage.token);

		const headers = ['id', 'name', 'email', 'role'];

		const csv = [
			headers.join(','),
			...users.users.map((user) => {
				return headers
					.map((header) => {
						if (user[header] === null || user[header] === undefined) {
							return '';
						}
						return `"${String(user[header]).replace(/"/g, '""')}"`;
					})
					.join(',');
			})
		].join('\n');

		const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
		saveAs(blob, 'users.csv');
	};

	onMount(async () => {
		// permissions = await getUserPermissions(localStorage.token);
	});
</script>

<div class="text-sm h-full">
	<Pane
		title={$i18n.t('Database')}
		description={$i18n.t('Move configuration and data in and out of this Harvis.')}
	>
		<input
			id="config-json-input"
			hidden
			type="file"
			accept=".json"
			on:change={(e) => {
				const file = e.target.files[0];
				const reader = new FileReader();

				reader.onload = async (e) => {
					const res = await importConfig(localStorage.token, JSON.parse(e.target.result)).catch(
						(error) => {
							toast.error(`${error}`);
						}
					);

					if (res) {
						toast.success($i18n.t('Config imported successfully'));
					}
					e.target.value = null;
				};

				reader.readAsText(file);
			}}
		/>

		<Section title={$i18n.t('Config')}>
			<Row
				label={$i18n.t('Import Config')}
				description={$i18n.t(
					'Pick a JSON file exported from a Harvis instance and load it as the configuration of this one.'
				)}
			>
				<button
					class="p-1 px-3 text-xs flex rounded-sm transition"
					on:click={() => {
						document.getElementById('config-json-input').click();
					}}
					type="button"
				>
					<span class="self-center">{$i18n.t('Import')}</span>
				</button>
			</Row>

			<Row
				label={$i18n.t('Export Config')}
				description={$i18n.t('Save the current configuration as a JSON file.')}
			>
				<button
					class="p-1 px-3 text-xs flex rounded-sm transition"
					on:click={async () => {
						const config = await exportConfig(localStorage.token);
						const blob = new Blob([JSON.stringify(config)], {
							type: 'application/json'
						});
						saveAs(blob, `config-${Date.now()}.json`);
					}}
					type="button"
				>
					<span class="self-center">{$i18n.t('Export')}</span>
				</button>
			</Row>
		</Section>

		{#if $config?.features.enable_admin_export ?? true}
			<Section title={$i18n.t('Export')}>
				<Row
					label={$i18n.t('Download Database')}
					description={$i18n.t('Download a copy of the server database file.')}
				>
					<button
						class="p-1 px-3 text-xs flex rounded-sm transition"
						on:click={() => {
							downloadDatabase(localStorage.token).catch((error) => {
								toast.error(`${error}`);
							});
						}}
						type="button"
					>
						<span class="self-center">{$i18n.t('Download')}</span>
					</button>
				</Row>

				<Row
					label={$i18n.t('Export All Chats (All Users)')}
					description={$i18n.t('Save every chat belonging to every user as one JSON file.')}
				>
					<button
						class="p-1 px-3 text-xs flex rounded-sm transition"
						on:click={() => {
							exportAllUserChats();
						}}
						type="button"
					>
						<span class="self-center">{$i18n.t('Export')}</span>
					</button>
				</Row>

				<Row
					label={$i18n.t('Export Users')}
					description={$i18n.t('Save a CSV of every user with their id, name, email and role.')}
				>
					<button
						class="p-1 px-3 text-xs flex rounded-sm transition"
						on:click={() => {
							exportUsers();
						}}
						type="button"
					>
						<span class="self-center">{$i18n.t('Export')}</span>
					</button>
				</Row>
			</Section>
		{/if}
	</Pane>
</div>
