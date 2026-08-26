<script lang="ts">
	import { onMount, getContext } from 'svelte';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';

	import { WEBUI_NAME, config, user } from '$lib/stores';
	import { getBackendConfig } from '$lib/apis';
	import { userSignUp, getSessionUser } from '$lib/apis/auths';
	import { generateInitialsImage, copyToClipboard } from '$lib/utils';
	import {
		getSetupStatus,
		getSetupVerify,
		postSetupTestModel,
		postSetupPreferences,
		postSetupComplete,
		type SetupTick
	} from '$lib/apis/setup';
	import { getNodes, getSystem, recommend, downloadModel, getInstalled } from '$lib/apis/cookbook';
	import { saveUserApiKey, saveEngineKey, verifyEngineKey } from '$lib/apis/integrations';
	import { getModels } from '$lib/apis';
	import SensitiveInput from '$lib/components/common/SensitiveInput.svelte';
	import SetupStepper from '$lib/components/common/SetupStepper.svelte';

	const i18n: any = getContext('i18n');

	const STEPS = ['Admin', 'Model', 'Exposure', 'Verify', 'Done'];
	let step = 0;
	let loading = true;
	let setupComplete = false;
	let needsSetup = true;
	// The backend's baseline node (cookbook/config.py `_DEFAULT_NODES`). Only used
	// if getNodes() fails outright — otherwise the live node name replaces it.
	let cookbookNode = 'main-host';

	// Admin claim
	let name = '';
	let email = '';
	let password = '';
	let setupCode = '';
	// The claim is open unless the operator set HARVIS_SETUP_CODE; the backend
	// advertises that as features.setup_code_required (owui_compat/config.py).
	$: setupCodeRequired = $config?.features?.setup_code_required ?? false;
	let claiming = false;

	// Model. The step branches on what is actually reachable, in this order:
	//   'models'  — a provider answered with models: pick one, nothing else to do.
	//   'pull'    — an Ollama is reachable but empty: offer the cookbook to pull from.
	//   'none'    — nothing is reachable: offer a cloud key or a local engine.
	// Never guess a model name. llmfit (the ranker) is in the default service set,
	// so it can usually say what this hardware would run well — but a ranking is
	// not a provider. In 'none' it is shown as information only, since there is
	// nowhere to pull to until a server is connected.
	type ModelStepState = 'models' | 'pull' | 'none';
	let modelState: ModelStepState = 'none';
	let probing = false;
	let ollamaUrl = '';
	let llmfitAlive = false;
	let recommendSource = '';
	let recommendations: any[] = [];
	let hardwareSummary = '';
	let selectedModel = '';
	let pulling = false;
	let pullLog = '';
	let installedModels: string[] = [];
	// 'models' used to be a terminal state: it listed whatever happened to be on the
	// box and offered no way to get anything else, so anyone who did not want that
	// model had to abandon the wizard. This opens the SAME pull UI 'pull' renders —
	// one implementation shown from two states, not a second copy to drift.
	let browsingMore = false;
	let browseProbing = false;
	// The pull UI gets its own field, separate from selectedModel. They are two
	// different questions — "which model do I start with" vs "which tag am I
	// downloading" — and sharing one variable meant typing a tag while browsing
	// silently replaced the user's pick, so cancelling left them selected on a
	// model that is not installed. selectedModel moves only when a pull succeeds.
	let pullTag = '';

	// Providers you can reach from this step.
	//
	// `kind: 'key'` — paste a credential and we store it.
	//   `store` picks WHICH store, and they are not interchangeable:
	//     'user'   → /api/user/api-keys, keyed by provider_name (pay-as-you-go platform keys)
	//     'engine' → /api/owui/engine-auth/<engine>, verified before save (CLI/agent engines)
	//   The `id` for an 'engine' provider MUST be one of the backend's AUTH_ENGINES
	//   (owui_compat/engine_auth.py: codex · claude-code · kimi-code) — the id goes
	//   straight into the URL path, so a catalog-style id like 'codex-app' 404s.
	//
	// `kind: 'endpoint'` — an OpenAI-compatible server you host. There is no
	//   credential to store: the backend reaches it by env var, so this branch
	//   hands over the exact line rather than pretending to connect.
	//
	// Same-vendor entries are deliberately split by WHICH ACCOUNT pays. A Moonshot
	// platform key and a Kimi Code membership key come from different consoles, live
	// in different namespaces, and bill differently — pasting one where the other
	// belongs authenticates against the wrong service and 401s later, with nothing
	// pointing at the cause.
	type KeyProvider = {
		id: string;
		kind: 'key' | 'endpoint';
		store?: 'user' | 'engine';
		label: string;
		hint: string;
	};
	const KEY_PROVIDERS: KeyProvider[] = [
		{
			id: 'moonshot',
			kind: 'key',
			store: 'user',
			label: 'Kimi — Moonshot platform (pay-as-you-go)',
			hint: 'Developer key from platform.moonshot.ai / .cn, billed against a prepaid balance. Adds Kimi K3, K2.6 and K2.5 as chat models. Not a Kimi Code membership key.'
		},
		{
			id: 'kimi-code',
			kind: 'key',
			store: 'engine',
			label: 'Kimi — Code membership (subscription)',
			hint: 'Membership key from kimi.com/coding, drawing on your subscription allowance. Drives the Claude Code tool loop in Build. Not a Moonshot platform key.'
		},
		{
			id: 'claude-code',
			kind: 'key',
			store: 'engine',
			label: 'Anthropic — Claude',
			hint: 'An Anthropic API key, or a subscription token from `claude setup-token` (Pro/Max/Team — no API credits needed).'
		},
		{
			id: 'codex',
			kind: 'key',
			store: 'engine',
			label: 'OpenAI — API key (pay-as-you-go)',
			hint: 'A platform.openai.com key, billed per token. ChatGPT-subscription sign-in is not wired into Harvis yet, so a ChatGPT Plus/Pro account alone will not work here.'
		},
		{
			id: 'openai-compatible',
			kind: 'endpoint',
			label: 'OpenAI-compatible server (self-hosted)',
			hint: 'vLLM, LM Studio, llama.cpp, TGI, LocalAI — anything serving GET /v1/models. Configured by address, not by key.'
		}
	];
	let keyProvider = KEY_PROVIDERS[0].id;
	let apiKey = '';
	let savingKey = false;
	$: activeProvider = KEY_PROVIDERS.find((p) => p.id === keyProvider);

	// OpenAI-compatible endpoint. VLLM_URL is the backend's GENERIC OpenAI-compatible
	// probe slot — it is read by main.list_models, which GETs `${VLLM_URL}/models` and
	// merges whatever answers into /api/models. The name is historical (it was added
	// for vLLM); any server speaking the same route works. HARVIS_LLM_BASE_URL is NOT
	// the right var here: that one is probed with Ollama's /api/tags.
	let compatUrl = '';
	$: compatEnvLine = `VLLM_URL=${(compatUrl || 'http://host.docker.internal:1234/v1').replace(/\/+$/, '')}`;

	// Getting Ollama itself running is the one local path worth spelling out — it is
	// what `pull` mode below drives, and everything else in this list is a link away.
	//
	// The second command is not optional padding. Verified on a clean Ubuntu 24.04 box:
	// the vendor installer registers a systemd unit and starts it bound to 127.0.0.1:11434,
	// which a container cannot reach through host.docker.internal — and because that unit
	// already holds the port, telling people to run `ollama serve` themselves just fails
	// with `bind: address already in use`. The drop-in re-binds the unit the installer
	// actually created, which is the only thing that works on a systemd host.
	const OLLAMA_INSTALL = 'curl -fsSL https://ollama.com/install.sh | sh';
	const OLLAMA_EXPOSE =
		'sudo mkdir -p /etc/systemd/system/ollama.service.d && printf \'[Service]\\nEnvironment="OLLAMA_HOST=0.0.0.0:11434"\\n\' | sudo tee /etc/systemd/system/ollama.service.d/harvis.conf >/dev/null && sudo systemctl daemon-reload && sudo systemctl restart ollama';

	const copyLine = async (text: string, what: string) => {
		if (await copyToClipboard(text)) toast.success($i18n.t('{{w}} copied.', { w: what }));
		else toast.error($i18n.t('Could not copy — select and copy it manually.'));
	};

	// Exposure
	let cookieSecure = false;
	let savingPrefs = false;

	// Verify. Raw tick keys are backend field names; these are what a person reads.
	const TICK_LABELS: Record<string, string> = {
		database: 'Database',
		ollama: 'Local model server',
		engines: 'Agent engine',
		speech: 'Voice (speech in/out)',
		notebooks: 'Notebooks',
		artifacts: 'Artifact storage'
	};
	let ticks: Record<string, SetupTick> = {};
	let overall = false;
	let verifying = false;
	let probingEngine = '';
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

	// Ask llmfit what this machine's hardware would run well. Same fields the
	// Cookbook panel reads (/api/cookbook/system). Wanted in BOTH 'pull' (where
	// it ranks a list you can act on) and 'none' (where it is context for the
	// choice between a cloud key and a local server) — hence its own function.
	const loadRanking = async () => {
		const [sysRes, rec] = await Promise.all([
			getSystem(token, cookbookNode).catch(() => null),
			recommend(token, cookbookNode, { limit: 8 }).catch(() => null)
		]);
		const sys = sysRes?.system ?? sysRes;
		hardwareSummary = [
			sys?.gpu_name,
			sys?.gpu_vram_gb ? `${sys.gpu_vram_gb} GB VRAM` : null,
			sys?.total_ram_gb ? `${sys.total_ram_gb} GB RAM` : null
		]
			.filter(Boolean)
			.join(' · ');
		recommendations = rec?.models?.slice(0, 8) || [];
		recommendSource = recommendations.length ? `llmfit · ${cookbookNode}` : '';
	};

	// Decide which of the three states we are in, from what actually answers.
	// Ranking is a bonus, not a gate: a reachable Ollama is enough to offer pulls,
	// and llmfit only decides whether that list is ranked or hand-typed.
	const probeModelStep = async () => {
		if (!token) return;
		probing = true;
		recommendations = [];
		recommendSource = '';
		ollamaUrl = '';
		llmfitAlive = false;
		hardwareSummary = '';
		try {
			await refreshModels();
			if (installedModels.length) {
				modelState = 'models';
				return;
			}

			const nodes = await getNodes(token).catch(() => []);
			const node = (nodes || []).find((n: any) => n.alive) || (nodes || [])[0];
			if (node?.name) cookbookNode = node.name;
			llmfitAlive = !!node?.alive;

			// A node row is only a claim. Ask the Ollama itself before offering a pull.
			const inst = await getInstalled(token, cookbookNode).catch(() => null);
			ollamaUrl = inst?.ollama_url || node?.ollama_url || '';
			const ollamaAnswered = !!inst && !inst.error;
			if (ollamaAnswered && Array.isArray(inst.models) && inst.models.length) {
				installedModels = inst.models
					.map((m: any) => m?.name || m?.model || m)
					.filter((m: any) => typeof m === 'string');
				if (!selectedModel && installedModels.length) selectedModel = installedModels[0];
				modelState = 'models';
				return;
			}
			if (!ollamaAnswered) {
				// No provider — but llmfit still knows this machine, and "here is what
				// your hardware could run" is exactly the context you want while
				// choosing between a cloud key and installing a local server.
				modelState = 'none';
				if (llmfitAlive) await loadRanking();
				return;
			}

			modelState = 'pull';
			if (llmfitAlive) {
				await loadRanking();
				if (!pullTag && recommendations[0]?.name) pullTag = recommendations[0].name;
			}
		} catch (e) {
			console.error(e);
			modelState = 'none';
		} finally {
			probing = false;
		}
	};

	// Open the pull UI from the 'models' state.
	//
	// This has to repeat probeModelStep's node discovery rather than call it: that
	// function returns as soon as /api/models answers (see its early return), so in
	// the 'models' state cookbookNode, llmfitAlive and ollamaUrl were never resolved.
	// Re-probing instead would also wipe the user's current selection.
	const browseMoreModels = async () => {
		browsingMore = true;
		if (!token || ollamaUrl) return;
		browseProbing = true;
		try {
			const nodes = await getNodes(token).catch(() => []);
			const node = (nodes || []).find((n: any) => n.alive) || (nodes || [])[0];
			if (node?.name) cookbookNode = node.name;
			llmfitAlive = !!node?.alive;
			// Same rule as the initial probe: a node row is a claim, so ask the
			// Ollama itself. An empty ollamaUrl here is the honest signal that the
			// installed models came from somewhere unpullable (a cloud key), and the
			// markup says so instead of offering a Pull button that would fail.
			const inst = await getInstalled(token, cookbookNode).catch(() => null);
			ollamaUrl = inst && !inst.error ? inst.ollama_url || node?.ollama_url || '' : '';
			if (llmfitAlive && !recommendations.length) await loadRanking();
			if (!pullTag && recommendations[0]?.name) pullTag = recommendations[0].name;
		} catch (e) {
			console.error(e);
		} finally {
			browseProbing = false;
		}
	};

	const connectKey = async () => {
		const provider = KEY_PROVIDERS.find((p) => p.id === keyProvider);
		// 'endpoint' providers have no credential store — the markup never renders a
		// Connect button for them, so reaching here means the selection changed under
		// an in-flight click. Refuse rather than post a key to an undefined store.
		if (!provider || provider.kind !== 'key' || !provider.store) return;
		if (!apiKey.trim()) {
			toast.error($i18n.t('Paste a key first.'));
			return;
		}
		savingKey = true;
		try {
			let ok = false;
			let error = '';
			if (provider.store === 'user') {
				const res = await saveUserApiKey(provider.id, apiKey.trim());
				ok = res.ok;
				error = res.error || '';
			} else {
				// Save FIRST, then verify — the same order ConnectionPanel uses. Reversing
				// them silently un-verifies a key the vendor just accepted, because the save
				// endpoint resets verified_at, and everything downstream (the chat catalog,
				// the Build engine gate) is gated on that timestamp.
				const saved = await saveEngineKey(provider.id, apiKey.trim());
				if (!saved.ok) {
					error = $i18n.t('Could not store that key.');
				} else {
					const verified = await verifyEngineKey(provider.id, apiKey.trim());
					ok = verified.ok;
					if (!ok) error = verified.error || $i18n.t('The provider rejected that key.');
				}
			}
			if (!ok) {
				toast.error(error || $i18n.t('Could not connect that provider.'));
				return;
			}
			apiKey = '';
			toast.success($i18n.t('{{p}} connected.', { p: provider.label }));
			await probeModelStep();
		} finally {
			savingKey = false;
		}
	};

	const claimAdmin = async () => {
		if (!name.trim() || !email.trim() || !password) {
			toast.error($i18n.t('Name, email, and password are required.'));
			return;
		}
		if (setupCodeRequired && !setupCode.trim()) {
			toast.error($i18n.t('This instance requires a setup code to create the administrator.'));
			return;
		}
		claiming = true;
		try {
			const sessionUser = await userSignUp(
				name,
				email,
				password,
				generateInitialsImage(name),
				setupCodeRequired ? setupCode.trim() : undefined
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
			await probeModelStep();
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			claiming = false;
		}
	};

	const pullSelected = async () => {
		if (!token || !pullTag) return;
		pulling = true;
		pullLog = '';
		try {
			await downloadModel(
				token,
				{ node: cookbookNode, ollama_tag: pullTag },
				(ev: any) => {
					const status = ev?.status || ev?.error || ev?.message || '';
					if (status) pullLog = String(status);
				}
			);
			toast.success($i18n.t('Model ready: {{m}}', { m: pullTag }));
			// Pulling it is choosing it — and this must land BEFORE the re-probe,
			// whose refreshModels() would otherwise seed selectedModel with whatever
			// happens to be first in the list.
			selectedModel = pullTag;
			// Re-probe rather than just refreshing: a successful pull is what moves
			// this step from 'pull' to 'models'.
			await probeModelStep();
			// Collapse back to the list, which now contains what was just pulled and
			// has it selected. Leaving the panel open would show an emptied ranking,
			// since probeModelStep clears recommendations.
			browsingMore = false;
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
				cookie_secure: cookieSecure
			});
			toast.success($i18n.t('Preferences saved for this process.'));
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

	// Re-verify a credential that is ALREADY stored: POST verify with no body makes
	// the backend decrypt the saved key and call the vendor with it. That is what
	// "probe my key" means here — a live round-trip, not a re-read of the row.
	const probeEngine = async (id: string, label: string) => {
		probingEngine = id;
		try {
			const res = await verifyEngineKey(id);
			if (res.ok) toast.success($i18n.t('{{p}} answered — credential is good.', { p: label }));
			else toast.error(res.error || $i18n.t('{{p}} rejected the stored credential.', { p: label }));
			await runVerify();
		} catch (e) {
			toast.error(`${e}`);
		} finally {
			probingEngine = '';
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
				await probeModelStep();
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

<!-- `h-screen overflow-y-auto`, not `min-h-screen`: app.html pins the document with
     `html { overflow-y: hidden !important }` so the app can own its own scroll
     regions. This route renders as a bare <slot/> (it is outside the $isApp shell),
     so without a scroll container of its own anything past the fold was simply
     unreachable — no wheel, no scrollbar, no keyboard. -->
<div
	class="h-screen overflow-y-auto w-full bg-white dark:bg-black text-black dark:text-white flex items-start justify-center px-4 py-10"
>
	<div class="w-full max-w-xl">
		<div class="mb-2 text-xs uppercase tracking-wide text-gray-500">{$WEBUI_NAME}</div>
		<h1 class="text-2xl font-semibold mb-1">{$i18n.t('First-run setup')}</h1>
		<p class="text-sm text-gray-600 dark:text-gray-400 mb-6">
			{$i18n.t('Claim this instance, connect a model, then verify the stack is honest.')}
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
						{setupCodeRequired
							? $i18n.t(
									'The first account becomes the admin. This instance also requires the setup code from .env (HARVIS_SETUP_CODE).'
								)
							: $i18n.t('The first account becomes the admin.')}
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
					{#if setupCodeRequired}
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
					{/if}
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
				<div class="space-y-4">
					{#if probing}
						<div class="text-sm text-gray-500">{$i18n.t('Looking for models…')}</div>
					{:else if modelState === 'models' || modelState === 'pull'}
						<!-- One branch for both states so the pull UI below has a single
						     implementation. 'models' shows the installed list and reveals
						     that UI on request; 'pull' has nothing to list and shows it
						     straight away. -->
						{#if modelState === 'models'}
							<p class="text-sm text-gray-600 dark:text-gray-400">
								{$i18n.t('{{n}} model(s) already available. Pick the one to start with.', {
									n: installedModels.length
								})}
							</p>
							<ul class="space-y-1.5 text-sm">
								{#each installedModels as m}
									<li>
										<button
											type="button"
											class="w-full text-left px-3 py-2 rounded-lg border {selectedModel === m
												? 'border-gray-900 dark:border-white'
												: 'border-gray-200 dark:border-gray-700'}"
											on:click={() => (selectedModel = m)}
										>
											<span class="font-medium">{m}</span>
										</button>
									</li>
								{/each}
							</ul>
							{#if !browsingMore}
								<button
									type="button"
									class="w-full rounded-full border border-gray-300 dark:border-gray-600 py-2 text-sm"
									on:click={browseMoreModels}
								>
									{$i18n.t('Want a different model? Browse and pull one')}
								</button>
							{/if}
						{:else}
							<p class="text-sm text-gray-600 dark:text-gray-400">
								{$i18n.t(
									'No models installed yet, but a local model server answered at {{url}}. Pull one to get started.',
									{ url: ollamaUrl || $i18n.t('the configured endpoint') }
								)}
							</p>
						{/if}

						{#if browsingMore && browseProbing}
							<div class="text-sm text-gray-500">{$i18n.t('Checking what you can pull into…')}</div>
						{:else if browsingMore && !ollamaUrl}
							<!-- Installed models with no local server behind them means they
							     came from a cloud provider. There is nothing to pull into, so
							     say that rather than showing a Pull button that would fail. -->
							<div class="rounded-xl border border-gray-200 dark:border-gray-700 p-4 space-y-2">
								<p class="text-sm text-gray-600 dark:text-gray-400">
									{$i18n.t(
										'Those models come from a connected provider, not a local server, so there is nothing here to pull into.'
									)}
								</p>
								<p class="text-xs text-gray-500">
									{$i18n.t(
										'To run your own, set up a local server with the instructions further down this page, then re-check. Cloud models are chosen in the chat model picker rather than pulled.'
									)}
								</p>
								<button
									type="button"
									class="text-xs underline"
									on:click={() => (browsingMore = false)}
								>
									{$i18n.t('Back to the list')}
								</button>
							</div>
						{/if}

						{#if modelState === 'pull' || (browsingMore && !browseProbing && ollamaUrl)}
							{#if modelState === 'models'}
								<div class="pt-1 text-sm font-medium">
									{$i18n.t('Pull a different model into {{url}}', { url: ollamaUrl })}
								</div>
							{/if}
							{#if recommendations.length}
								<p class="text-xs text-gray-500">
									{$i18n.t('Ranked for this machine by')}
									{recommendSource}
								</p>
								<ul class="space-y-1.5 text-sm">
									{#each recommendations as r}
										{@const m = r.name || r.model || r.id}
										<li>
											<button
												type="button"
												class="w-full text-left px-3 py-2 rounded-lg border {pullTag === m
													? 'border-gray-900 dark:border-white'
													: 'border-gray-200 dark:border-gray-700'}"
												on:click={() => (pullTag = m)}
											>
												<span class="font-medium">{m}</span>
												{#if r.reason || r.detail}
													<span class="block text-xs text-gray-500">{r.reason || r.detail}</span>
												{/if}
											</button>
										</li>
									{/each}
								</ul>
							{:else}
								<p class="text-xs text-gray-500">
									{$i18n.t(
										'No ranking service is running, so there is nothing to recommend from. Type the tag you want.'
									)}
								</p>
							{/if}
							<label class="block text-sm font-medium" for="model-pick"
								>{$i18n.t('Model tag')}</label
							>
							<input
								id="model-pick"
								class="w-full border-b border-gray-300 dark:border-gray-700 bg-transparent py-1.5 text-sm outline-none"
								placeholder="qwen3:4b"
								bind:value={pullTag}
							/>
							<p class="text-xs text-gray-500">
								{$i18n.t(
									'Any tag from the Ollama library works here, ranked or not — for example llama3.2:3b, mistral:7b, gemma3:4b.'
								)}
							</p>
							{#if pullLog}
								<pre class="text-xs text-gray-500 whitespace-pre-wrap">{pullLog}</pre>
							{/if}
							<button
								type="button"
								class="w-full rounded-full border border-gray-300 dark:border-gray-600 py-2 text-sm disabled:opacity-50"
								disabled={pulling || !pullTag}
								on:click={pullSelected}
							>
								{pulling ? $i18n.t('Pulling…') : $i18n.t('Pull model')}
							</button>
							{#if modelState === 'models'}
								<button
									type="button"
									class="w-full text-xs underline"
									disabled={pulling}
									on:click={() => (browsingMore = false)}
								>
									{$i18n.t('Cancel — keep the model I picked')}
								</button>
							{/if}
						{/if}
					{:else}
						<p class="text-sm text-gray-600 dark:text-gray-400">
							{$i18n.t(
								'No model provider answered. Connect a cloud provider with an API key, or point Harvis at a local model server and re-check.'
							)}
						</p>

						<div class="rounded-xl border border-gray-200 dark:border-gray-700 p-4 space-y-3">
							<div class="text-sm font-medium">{$i18n.t('Connect a provider')}</div>
							<label class="block text-sm" for="key-provider">{$i18n.t('Provider')}</label>
							<select
								id="key-provider"
								class="w-full border-b border-gray-300 dark:border-gray-700 bg-transparent py-1.5 text-sm outline-none"
								bind:value={keyProvider}
							>
								{#each KEY_PROVIDERS as p}
									<option value={p.id}>{p.label}</option>
								{/each}
							</select>
							<p class="text-xs text-gray-500">
								{activeProvider?.hint}
							</p>

							{#if activeProvider?.kind === 'endpoint'}
								<!-- No credential store exists for a self-hosted endpoint: the backend
								     finds it by env var at startup. Hand over the exact line instead of
								     showing a Connect button that could not do anything. -->
								<label class="block text-sm" for="compat-url">{$i18n.t('Base URL')}</label>
								<input
									id="compat-url"
									class="w-full border-b border-gray-300 dark:border-gray-700 bg-transparent py-1.5 text-sm outline-none"
									placeholder="http://host.docker.internal:1234/v1"
									bind:value={compatUrl}
								/>
								<p class="text-xs text-gray-500">
									{$i18n.t(
										'Include the /v1 suffix. Harvis runs in a container, so a server on this machine is host.docker.internal, never localhost.'
									)}
								</p>
								<div
									class="flex items-center gap-2 rounded-lg bg-gray-50 dark:bg-gray-900 px-3 py-2"
								>
									<code class="flex-1 truncate text-xs">{compatEnvLine}</code>
									<button
										type="button"
										class="shrink-0 text-xs underline"
										on:click={() => copyLine(compatEnvLine, $i18n.t('Env line'))}
									>
										{$i18n.t('Copy')}
									</button>
								</div>
								<p class="text-xs text-gray-500">
									{$i18n.t(
										'Add that to .env, then restart the backend (docker compose restart backend) and re-check below. Its models join the list alongside any local ones.'
									)}
								</p>
							{:else}
								<label class="block text-sm" for="key-value">{$i18n.t('API key')}</label>
								<div class="w-full border-b border-gray-300 dark:border-gray-700">
									<SensitiveInput
										id="key-value"
										bind:value={apiKey}
										type="password"
										inputClassName="w-full bg-transparent py-1.5 text-sm outline-none"
										autocomplete="off"
									/>
								</div>
								<button
									type="button"
									class="w-full rounded-full bg-gray-900 text-white dark:bg-white dark:text-black py-2 text-sm disabled:opacity-50"
									disabled={savingKey || !apiKey.trim()}
									on:click={connectKey}
								>
									{savingKey ? $i18n.t('Connecting…') : $i18n.t('Connect')}
								</button>
							{/if}
						</div>

						<!-- Ollama gets the full recipe rather than a mention: it is the one local
						     server this wizard can drive end to end (it can pull models into it from
						     the next screen), so leaving the user to find the install command is a
						     dead end where a copyable line is a finished path. -->
						<div class="rounded-xl border border-gray-200 dark:border-gray-700 p-4 space-y-3">
							<div class="text-sm font-medium">{$i18n.t('Or run models locally — free')}</div>
							<p class="text-xs text-gray-500">
								{$i18n.t(
									'Ollama is the quickest way there, and the only one Harvis can pull models into for you. Run these on this machine (not in a container):'
								)}
							</p>
							<div class="space-y-2">
								{#each [{ cmd: OLLAMA_INSTALL, note: $i18n.t('1 · install (skip if you already have it)') }, { cmd: OLLAMA_EXPOSE, note: $i18n.t('2 · Linux only — re-bind the service the installer just started so the container can reach it') }] as s}
									<div>
										<div class="text-[11px] text-gray-500 mb-1">{s.note}</div>
										<!-- Wrapped, not truncated: step 2 is a sudo command, and nobody should
										     paste one they were only shown the first 40 characters of. -->
										<div
											class="flex items-start gap-2 rounded-lg bg-gray-50 dark:bg-gray-900 px-3 py-2"
										>
											<code class="flex-1 break-all whitespace-pre-wrap text-xs">{s.cmd}</code>
											<button
												type="button"
												class="shrink-0 text-xs underline"
												on:click={() => copyLine(s.cmd, $i18n.t('Command'))}
											>
												{$i18n.t('Copy')}
											</button>
										</div>
									</div>
								{/each}
							</div>
							<!-- Step 2 is systemd-shaped, so say what the other platforms need rather
							     than leaving a Mac or Windows user staring at a command that does not
							     apply. Same idea in all three: Ollama defaults to localhost-only, and a
							     container is not localhost. -->
							<p class="text-xs text-gray-500">
								{$i18n.t(
									'On macOS run `launchctl setenv OLLAMA_HOST "0.0.0.0"` and restart the Ollama app; on Windows set OLLAMA_HOST to 0.0.0.0 in your user environment variables and restart it. Both do what step 2 does — Ollama listens on localhost only by default, and a container is not localhost.'
								)}
							</p>
							<p class="text-xs text-gray-500">
								{$i18n.t(
									'Harvis looks for it at host.docker.internal:11434 by default, so on this machine there is nothing else to configure — just re-check. Elsewhere on your network, set HARVIS_LLM_BASE_URL in .env to its address and restart the backend.'
								)}
							</p>
							<p class="text-xs text-gray-500">
								{$i18n.t(
									'LM Studio, llama.cpp, vLLM and friends work too — pick "OpenAI-compatible server" above for those.'
								)}
							</p>
							<button
								type="button"
								class="w-full rounded-full border border-gray-300 dark:border-gray-600 py-2 text-sm"
								on:click={probeModelStep}
							>
								{$i18n.t('Re-check')}
							</button>
						</div>

						<!-- Informational only. llmfit ranks what this hardware could run, but
						     with no server connected there is nothing to pull to yet — so this
						     is deliberately a plain list, not selectable, and says so. -->
						{#if recommendations.length}
							<div class="rounded-xl border border-gray-200 dark:border-gray-700 p-4 space-y-2">
								<div class="text-sm font-medium">{$i18n.t('What this machine could run')}</div>
								<p class="text-xs text-gray-500">
									{hardwareSummary
										? $i18n.t(
												'{{hw}} — ranked by {{src}}. Connect a server above to pull any of these.',
												{ hw: hardwareSummary, src: recommendSource }
											)
										: $i18n.t('Ranked by {{src}}. Connect a server above to pull any of these.', {
												src: recommendSource
											})}
								</p>
								<ul class="text-sm space-y-1">
									{#each recommendations as r}
										<li class="flex items-baseline justify-between gap-3">
											<span class="truncate">{r.name || r.model || r.id}</span>
											{#if r.fit_label}
												<span class="shrink-0 text-xs text-gray-500">{r.fit_label}</span>
											{/if}
										</li>
									{/each}
								</ul>
							</div>
						{/if}
					{/if}

					<button
						type="button"
						class="w-full rounded-full {modelState === 'none'
							? 'border border-gray-300 dark:border-gray-600'
							: 'bg-gray-900 text-white dark:bg-white dark:text-black'} py-2 text-sm"
						on:click={() => (step = 2)}
					>
						{modelState === 'none' ? $i18n.t('Skip for now') : $i18n.t('Continue')}
					</button>
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
								<!-- A skipped tick is a capability that was never installed. It used to
								     render with the same red ✗ as a genuine failure, which made a
								     correct default install look broken. Neutral grey, dash glyph. -->
								<li
									class="rounded-lg border px-3 py-2 {t.ready
										? 'border-emerald-600/40'
										: t.skipped
											? 'border-gray-300 dark:border-gray-700'
											: 'border-red-500/40'}"
								>
									<div class="font-medium {t.skipped ? 'text-gray-500' : ''}">
										{t.ready ? '✓' : t.skipped ? '–' : '✗'}
										{TICK_LABELS[name] || name}
										{#if t.skipped}<span class="text-xs font-normal"
												>· {$i18n.t('not installed')}</span
											>{/if}
									</div>
									<div class="text-xs text-gray-500">{t.reason}</div>
									{#if t.engines?.length}
										<ul class="mt-2 space-y-1">
											{#each t.engines as e}
												<li class="flex items-start gap-2 text-xs">
													<span
														class={e.state === 'ready'
															? 'text-emerald-600'
															: e.state === 'no_credential' || e.state === 'not_installed'
																? 'text-gray-400'
																: 'text-amber-600'}
													>
														{e.state === 'ready'
															? '✓'
															: e.state === 'no_credential' || e.state === 'not_installed'
																? '–'
																: '!'}
													</span>
													<span class="flex-1">
														<span class="font-medium">{e.label}</span>
														<span class="text-gray-500"> — {e.detail}</span>
													</span>
													{#if e.can_probe}
														<button
															type="button"
															class="shrink-0 rounded-full border border-gray-300 dark:border-gray-600 px-2 py-0.5 disabled:opacity-50"
															disabled={!!probingEngine}
															on:click={() => probeEngine(e.id, e.label)}
														>
															{probingEngine === e.id ? $i18n.t('Testing…') : $i18n.t('Test key')}
														</button>
													{/if}
												</li>
											{/each}
										</ul>
									{/if}
									<div class="text-[11px] text-gray-400 mt-0.5">{t.probe}</div>
								</li>
							{/each}
						</ul>
						<p class="text-xs text-gray-500">
							{overall
								? $i18n.t('Everything installed is ready.')
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
