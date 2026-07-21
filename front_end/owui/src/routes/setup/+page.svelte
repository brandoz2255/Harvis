<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import { WEBUI_NAME, config, user } from '$lib/stores';
	import { getBackendConfig } from '$lib/apis';
	import { userSignUp, getSessionUser } from '$lib/apis/auths';
	import { generateInitialsImage } from '$lib/utils';
	import {
		getSetupStatus,
		getSetupVerify,
		postSetupTestModel,
		postSetupPreferences,
		postSetupComplete,
		type SetupTick
	} from '$lib/apis/setup';
	import { getNodes, getSystem, recommend, downloadModel } from '$lib/apis/cookbook';
	import { getModels } from '$lib/apis';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import SetupStepper from '$lib/components/common/SetupStepper.svelte';

	const i18n: any = getContext('i18n');

	const STEPS = ['Admin', 'Model', 'Exposure', 'Verify', 'Done'];
	let step = 0;
	let loading = true;
	let setupComplete = false;
	let needsSetup = true;
	let cookbookNode = 'main';

	// Admin claim
	let name = '';
	let email = '';
	let password = '';
	let setupCode = '';
	let claiming = false;

	// Model
	let recommendSource = '';
	let recommendations: any[] = [];
	let selectedModel = '';
	let pulling = false;
	let pullLog = '';
	let installedModels: string[] = [];

	// Exposure
	let cookieSecure = false;
	let enableSignup = false;
	let savingPrefs = false;

	// Verify
	let ticks: Record<string, SetupTick> = {};
	let overall = false;
	let verifying = false;
	let testText = '';
	let testingModel = false;
	let completing = false;

	$: token = $user?.token || (typeof localStorage !== 'undefined' ? localStorage.token : '') || '';

	const refreshModels = async () => {
		if (!token) return;
		try {
			const list = await getModels(token, null);
			installedModels = (Array.isArray(list) ? list : [])
				.map((m: any) => m?.id || m?.name || m?.model || '')
				.filter(Boolean);
			if (!selectedModel && installedModels.length) {
				selectedModel = installedModels[0];
			}
		} catch (e) {
			console.error(e);
		}
	};

	const loadRecommendations = async () => {
		if (!token) return;
		try {
			const nodes = await getNodes(token).catch(() => []);
			const alive = (nodes || []).find((n: any) => n.alive) || (nodes || [])[0];
			if (alive?.name) cookbookNode = alive.name;
			const sys = await getSystem(token, cookbookNode).catch(() => null);
			recommendSource = sys ? `llmfit · ${cookbookNode}` : `fallback · ${cookbookNode}`;
			const rec = await recommend(token, cookbookNode, { limit: 8 }).catch(() => null);
			recommendations = rec?.models?.slice(0, 8) || [];
			if (!selectedModel && recommendations[0]?.name) {
				selectedModel = recommendations[0].name;
			}
			if (!recommendations.length) {
				recommendSource = 'fallback · llama3.2:3b (no llmfit ranking)';
				recommendations = [{ name: 'llama3.2:3b', reason: 'Modest default for 8GB-class boxes' }];
				if (!selectedModel) selectedModel = 'llama3.2:3b';
			}
		} catch {
			recommendSource = 'fallback · llama3.2:3b';
			recommendations = [{ name: 'llama3.2:3b', reason: 'Modest default' }];
			if (!selectedModel) selectedModel = 'llama3.2:3b';
		}
	};

	const claimAdmin = async () => {
		if (!setupCode.trim() || !name.trim() || !email.trim() || !password) {
			toast.error($i18n.t('Name, email, password, and setup code are required.'));
			return;
		}
		claiming = true;
		try {
			const sessionUser = await userSignUp(
				name,
				email,
				password,
				generateInitialsImage(name),
				setupCode.trim()
			);
			if (sessionUser?.token) {
				localStorage.token = sessionUser.token;
			}
			const session = await getSessionUser(localStorage.token);
			await user.set(session || sessionUser);
			await config.set(await getBackendConfig());
			needsSetup = false;
			toast.success($i18n.t("You're the administrator."));
			step = 1;
			await refreshModels();
			await loadRecommendations();
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			claiming = false;
		}
	};

	const pullSelected = async () => {
		if (!token || !selectedModel) return;
		pulling = true;
		pullLog = '';
		try {
			await downloadModel(
				token,
				{ node: cookbookNode, ollama_tag: selectedModel },
				(ev: any) => {
					const status = ev?.status || ev?.error || ev?.message || '';
					if (status) pullLog = String(status);
				}
			);
			toast.success($i18n.t('Model ready: {{m}}', { m: selectedModel }));
			await refreshModels();
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			pulling = false;
		}
	};

	const saveExposure = async () => {
		if (!token) return;
		savingPrefs = true;
		try {
			await postSetupPreferences(token, {
				cookie_secure: cookieSecure,
				enable_signup: enableSignup
			});
			toast.success($i18n.t('Preferences saved for this process.'));
			if (enableSignup) {
				toast.message(
					$i18n.t(
						'Open signup still requires HARVIS_OWUI_ENABLE_SIGNUP=true in .env (server-enforced).'
					)
				);
			}
			step = 3;
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			savingPrefs = false;
		}
	};

	const runVerify = async () => {
		if (!token) return;
		verifying = true;
		try {
			const res = await getSetupVerify(token);
			ticks = res.ticks || {};
			overall = !!res.overall;
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			verifying = false;
		}
	};

	const runTestChat = async () => {
		if (!token || !selectedModel) {
			toast.error($i18n.t('Pick a model first.'));
			return;
		}
		testingModel = true;
		testText = '';
		try {
			const res = await postSetupTestModel(token, selectedModel);
			if (!res.ready) {
				toast.error(res.reason || $i18n.t('Model probe failed'));
				testText = res.reason || '';
			} else {
				testText = res.text || 'OK';
				toast.success($i18n.t('Model answered.'));
			}
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			testingModel = false;
		}
	};

	const finish = async () => {
		if (!token) return;
		completing = true;
		try {
			await postSetupComplete(token);
			setupComplete = true;
			step = 4;
			await config.set(await getBackendConfig());
			toast.success($i18n.t('Setup complete.'));
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			completing = false;
		}
	};

	onMount(async () => {
		try {
			const status = await getSetupStatus();
			needsSetup = !!status.needs_setup;
			setupComplete = !!status.setup_complete;
			if (setupComplete) {
				step = 4;
			} else if (!needsSetup && token) {
				step = 1;
				await refreshModels();
				await loadRecommendations();
			} else if (!needsSetup && !token) {
				await goto('/auth');
				return;
			}
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			loading = false;
		}
	});
</script>

<svelte:head>
	<title>{$i18n.t('Setup')} · {$WEBUI_NAME}</title>
</svelte:head>

<div
	class="min-h-screen w-full bg-white dark:bg-black text-black dark:text-white flex justify-center px-4 py-10"
>
	<div class="w-full max-w-xl">
		<div class="mb-2 text-xs uppercase tracking-wide text-gray-500">{$WEBUI_NAME}</div>
		<h1 class="text-2xl font-semibold mb-1">{$i18n.t('First-run setup')}</h1>
		<p class="text-sm text-gray-600 dark:text-gray-400 mb-6">
			{$i18n.t('Claim this instance, pull a model, then verify the stack is honest.')}
		</p>

		{#if loading}
			<div class="text-sm text-gray-500">{$i18n.t('Loading…')}</div>
		{:else}
			<SetupStepper steps={STEPS} current={step} />

			{#if setupComplete && step === 4}
				<div
					class="rounded-xl border border-emerald-600/30 bg-emerald-50 dark:bg-emerald-950/20 p-5"
				>
					<div class="font-medium text-emerald-800 dark:text-emerald-300">
						{$i18n.t('Setup already complete')}
					</div>
					<p class="mt-2 text-sm text-emerald-900/80 dark:text-emerald-200/70">
						{$i18n.t('This instance has an administrator and the wizard is locked.')}
					</p>
					<button
						class="mt-4 text-sm font-medium underline"
						type="button"
						on:click={() => goto('/')}
					>
						{$i18n.t('Go to chat')}
					</button>
				</div>
			{:else if step === 0}
				<div class="space-y-3">
					<p class="text-sm text-gray-600 dark:text-gray-400">
						{$i18n.t(
							'The first account becomes the admin. Use the setup code from ./install.sh (or HARVIS_SETUP_CODE in .env).'
						)}
					</p>
					<label class="block text-sm font-medium" for="su-name">{$i18n.t('Name')}</label>
					<input
						id="su-name"
						class="w-full border-b border-gray-300 dark:border-gray-700 bg-transparent py-1.5 text-sm outline-none"
						bind:value={name}
						autocomplete="name"
						required
					/>
					<label class="block text-sm font-medium" for="su-email">{$i18n.t('Email')}</label>
					<input
						id="su-email"
						type="email"
						class="w-full border-b border-gray-300 dark:border-gray-700 bg-transparent py-1.5 text-sm outline-none"
						bind:value={email}
						autocomplete="email"
						required
					/>
					<label class="block text-sm font-medium" for="su-pass">{$i18n.t('Password')}</label>
					<div class="w-full border-b border-gray-300 dark:border-gray-700">
						<SensitiveInput
							id="su-pass"
							bind:value={password}
							type="password"
							inputClassName="w-full bg-transparent py-1.5 text-sm outline-none"
							autocomplete="new-password"
							required
						/>
					</div>
					<label class="block text-sm font-medium" for="su-code">{$i18n.t('Setup Code')}</label>
					<div class="w-full border-b border-gray-300 dark:border-gray-700">
						<SensitiveInput
							id="su-code"
							bind:value={setupCode}
							type="password"
							inputClassName="w-full bg-transparent py-1.5 text-sm outline-none"
							autocomplete="one-time-code"
							required
						/>
					</div>
					<button
						type="button"
						class="mt-4 w-full rounded-full bg-gray-900 text-white dark:bg-white dark:text-black py-2.5 text-sm font-medium disabled:opacity-50"
						disabled={claiming}
						on:click={claimAdmin}
					>
						{claiming ? $i18n.t('Creating…') : $i18n.t('Create Admin Account')}
					</button>
				</div>
			{:else if step === 1}
				<div class="space-y-3">
					<p class="text-xs text-gray-500">
						{$i18n.t('Recommendation source')}: {recommendSource || '—'}
					</p>
					{#if recommendations.length}
						<ul class="space-y-1.5 text-sm">
							{#each recommendations as r}
								{@const m = r.name || r.model || r.id}
								<li>
									<button
										type="button"
										class="w-full text-left px-3 py-2 rounded-lg border {selectedModel === m
											? 'border-gray-900 dark:border-white'
											: 'border-gray-200 dark:border-gray-700'}"
										on:click={() => (selectedModel = m)}
									>
										<span class="font-medium">{m}</span>
										{#if r.reason || r.detail}
											<span class="block text-xs text-gray-500">{r.reason || r.detail}</span>
										{/if}
									</button>
								</li>
							{/each}
						</ul>
					{/if}
					<label class="block text-sm font-medium" for="model-pick">{$i18n.t('Model')}</label>
					<input
						id="model-pick"
						class="w-full border-b border-gray-300 dark:border-gray-700 bg-transparent py-1.5 text-sm outline-none"
						bind:value={selectedModel}
						list="installed-models"
						placeholder="llama3.2:3b"
					/>
					<datalist id="installed-models">
						{#each installedModels as m}
							<option value={m} />
						{/each}
					</datalist>
					{#if pullLog}
						<pre class="text-xs text-gray-500 whitespace-pre-wrap">{pullLog}</pre>
					{/if}
					<div class="flex gap-2 pt-2">
						<button
							type="button"
							class="flex-1 rounded-full border border-gray-300 dark:border-gray-600 py-2 text-sm disabled:opacity-50"
							disabled={pulling || !selectedModel}
							on:click={pullSelected}
						>
							{pulling ? $i18n.t('Pulling…') : $i18n.t('Pull model')}
						</button>
						<button
							type="button"
							class="flex-1 rounded-full bg-gray-900 text-white dark:bg-white dark:text-black py-2 text-sm"
							on:click={() => (step = 2)}
						>
							{$i18n.t('Continue')}
						</button>
					</div>
				</div>
			{:else if step === 2}
				<div class="space-y-4">
					<p class="text-sm text-gray-600 dark:text-gray-400">
						{$i18n.t(
							'v1 exposure is honest copy only — no HTTPS/domain automation. Toggle Secure cookies if you terminate TLS in front of Harvis.'
						)}
					</p>
					<label class="flex items-start gap-2 text-sm">
						<input type="checkbox" bind:checked={cookieSecure} class="mt-1" />
						<span>
							<span class="font-medium">{$i18n.t('Secure cookies (HTTPS)')}</span>
							<span class="block text-xs text-gray-500">
								{$i18n.t(
									'Sets HARVIS_COOKIE_SECURE for this backend process. For permanence, also put it in .env.'
								)}
							</span>
						</span>
					</label>
					<label class="flex items-start gap-2 text-sm">
						<input type="checkbox" bind:checked={enableSignup} class="mt-1" />
						<span>
							<span class="font-medium">{$i18n.t('Allow open signup later')}</span>
							<span class="block text-xs text-gray-500">
								{$i18n.t(
									'Default stays closed. Enabling still needs HARVIS_OWUI_ENABLE_SIGNUP=true in .env — the server enforces that flag.'
								)}
							</span>
						</span>
					</label>
					<button
						type="button"
						class="w-full rounded-full bg-gray-900 text-white dark:bg-white dark:text-black py-2.5 text-sm font-medium disabled:opacity-50"
						disabled={savingPrefs}
						on:click={saveExposure}
					>
						{savingPrefs ? $i18n.t('Saving…') : $i18n.t('Save & continue')}
					</button>
				</div>
			{:else if step === 3}
				<div class="space-y-4">
					<button
						type="button"
						class="rounded-full border border-gray-300 dark:border-gray-600 px-4 py-2 text-sm disabled:opacity-50"
						disabled={verifying}
						on:click={runVerify}
					>
						{verifying ? $i18n.t('Checking…') : $i18n.t('Run verification')}
					</button>
					{#if Object.keys(ticks).length}
						<ul class="space-y-2 text-sm">
							{#each Object.entries(ticks) as [name, t]}
								<li
									class="rounded-lg border px-3 py-2 {t.ready
										? 'border-emerald-600/40'
										: 'border-red-500/40'}"
								>
									<div class="font-medium">
										{t.ready ? '✓' : '✗'}
										{name}
									</div>
									<div class="text-xs text-gray-500">{t.reason}</div>
									<div class="text-[11px] text-gray-400 mt-0.5">{t.probe}</div>
								</li>
							{/each}
						</ul>
						<p class="text-xs text-gray-500">
							{overall
								? $i18n.t('All ticks ready.')
								: $i18n.t('Some ticks failed — fix them or continue knowing what is down.')}
						</p>
					{/if}
					<div class="border-t border-gray-200 dark:border-gray-800 pt-4 space-y-2">
						<p class="text-sm font-medium">{$i18n.t('Test model (real generation)')}</p>
						<button
							type="button"
							class="rounded-full border border-gray-300 dark:border-gray-600 px-4 py-2 text-sm disabled:opacity-50"
							disabled={testingModel || !selectedModel}
							on:click={runTestChat}
						>
							{testingModel ? $i18n.t('Loading model…') : $i18n.t('Probe {{m}}', { m: selectedModel })}
						</button>
						{#if testText}
							<pre
								class="text-xs bg-gray-50 dark:bg-gray-900 rounded-lg p-3 whitespace-pre-wrap">{testText}</pre>
						{/if}
					</div>
					<button
						type="button"
						class="w-full rounded-full bg-gray-900 text-white dark:bg-white dark:text-black py-2.5 text-sm font-medium disabled:opacity-50"
						disabled={completing}
						on:click={finish}
					>
						{completing ? $i18n.t('Finishing…') : $i18n.t('Finish setup')}
					</button>
				</div>
			{:else if step === 4}
				<div class="space-y-3">
					<div class="font-medium">{$i18n.t("You're ready.")}</div>
					<button
						type="button"
						class="w-full rounded-full bg-gray-900 text-white dark:bg-white dark:text-black py-2.5 text-sm font-medium"
						on:click={() => goto('/')}
					>
						{$i18n.t('Open Harvis')}
					</button>
				</div>
			{/if}
		{/if}
	</div>
</div>
