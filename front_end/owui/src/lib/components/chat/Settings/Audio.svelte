<script lang="ts">
	import { toast } from 'svelte-sonner';
	import { createEventDispatcher, onMount, getContext } from 'svelte';

	import { user, settings, config } from '$lib/stores';
	import { getVoices as _getVoices, getAudioConfig } from '$lib/apis/audio';

	import Switch from '$lib/components/common/Switch.svelte';
	import Spinner from '$lib/components/common/Spinner.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import SettingRow from './SettingRow.svelte';
	const dispatch = createEventDispatcher();

	const i18n = getContext('i18n');

	export let saveSettings: Function;

	// Audio
	let conversationMode = false;
	let speechAutoSend = false;
	let responseAutoPlayback = false;
	let nonLocalVoices = false;

	let STTEngine = '';
	let STTLanguage = '';

	let TTSEngine = '';
	let TTSEngineConfig = {};

	let TTSModel = null;
	let TTSModelProgress = null;
	let TTSModelLoading = false;

	let voices = [];
	let voice = '';

	// Audio speed control
	let playbackRate = 1;

	// Voice mode. `natural` is the default ONNX stack (Kokoro in the browser or in
	// the voice service). `advanced` is voice conversion on top of it, which needs
	// the separate RVC service — a flippable const rather than a deleted option, so
	// turning it on is one edit once that service ships.
	const ADVANCED_VOICE_ENABLED = false;
	let voiceMode = 'natural';

	// Which side of the wire actually does the work, straight from the server's
	// providers rather than assumed from the OWUI engine strings.
	let harvisAudio = null;
	$: serverSpeaks = harvisAudio?.tts?.server_synthesizes ?? true;
	$: serverHears = harvisAudio?.stt?.server_transcribes ?? true;
	$: ttsProvider = harvisAudio?.tts?.provider ?? '';
	$: sttProvider = harvisAudio?.stt?.provider ?? '';

	const loadHarvisAudio = async () => {
		const res = await getAudioConfig(localStorage.token).catch(() => null);
		// The panel still works without this — it only decides what we can tell the
		// user and where the voice list comes from — so a failure is not a toast.
		harvisAudio = res?.harvis ?? $config?.audio?.harvis ?? null;
	};

	const browserVoices = () =>
		new Promise<void>((resolve) => {
			const loop = setInterval(() => {
				voices = speechSynthesis.getVoices();
				if (voices.length > 0) {
					clearInterval(loop);
					resolve();
				}
			}, 100);
			// Some browsers never populate the list (no system voices installed).
			// Give up rather than spin an interval for the life of the page.
			setTimeout(() => {
				clearInterval(loop);
				resolve();
			}, 3000);
		});

	const getVoices = async () => {
		if (TTSEngine === 'browser-kokoro') {
			if (!TTSModel) {
				await loadKokoro();
			}

			voices = Object.entries(TTSModel.voices).map(([key, value]) => {
				return {
					id: key,
					name: value.name,
					localService: false
				};
			});
			return;
		}

		if (!serverSpeaks) {
			await browserVoices();
			return;
		}

		const res = await _getVoices(localStorage.token).catch((e) => {
			toast.error(`${e}`);
			return null;
		});

		// An empty list means the provider is up but has nothing to offer (or just
		// refused); the system voices are the only thing left that can speak.
		if (res?.voices?.length) {
			voices = res.voices;
		} else {
			await browserVoices();
		}
	};

	const toggleResponseAutoPlayback = async () => {
		responseAutoPlayback = !responseAutoPlayback;
		saveSettings({ responseAutoPlayback: responseAutoPlayback });
	};

	const toggleSpeechAutoSend = async () => {
		speechAutoSend = !speechAutoSend;
		saveSettings({ speechAutoSend: speechAutoSend });
	};

	onMount(async () => {
		await loadHarvisAudio();

		playbackRate = $settings.audio?.tts?.playbackRate ?? 1;
		voiceMode = $settings.audio?.tts?.mode ?? 'natural';
		conversationMode = $settings.conversationMode ?? false;
		speechAutoSend = $settings.speechAutoSend ?? false;
		responseAutoPlayback = $settings.responseAutoPlayback ?? false;

		STTEngine = $settings?.audio?.stt?.engine ?? '';
		STTLanguage = $settings?.audio?.stt?.language ?? '';

		TTSEngine = $settings?.audio?.tts?.engine ?? '';
		TTSEngineConfig = $settings?.audio?.tts?.engineConfig ?? {};

		if ($settings?.audio?.tts?.defaultVoice === $config.audio.tts.voice) {
			voice = $settings?.audio?.tts?.voice ?? $config.audio.tts.voice ?? '';
		} else {
			voice = $config.audio.tts.voice ?? '';
		}

		nonLocalVoices = $settings.audio?.tts?.nonLocalVoices ?? false;

		await getVoices();
	});

	$: if (TTSEngine && TTSEngineConfig) {
		onTTSEngineChange();
	}

	const onTTSEngineChange = async () => {
		if (TTSEngine === 'browser-kokoro') {
			await loadKokoro();
		}
	};

	// The reactive block above only fires for a truthy engine, so switching BACK
	// to the server needs its own trigger — otherwise the picker keeps offering
	// the browser model's voice names to a server that never heard of them.
	const onTTSEngineSelect = async () => {
		if (TTSEngine !== 'browser-kokoro') {
			TTSModel = null;
			await getVoices();
		}
	};

	const loadKokoro = async () => {
		if (TTSEngine === 'browser-kokoro') {
			voices = [];

			if (TTSEngineConfig?.dtype) {
				TTSModel = null;
				TTSModelProgress = null;
				TTSModelLoading = true;

				const model_id = 'onnx-community/Kokoro-82M-v1.0-ONNX';

				const { KokoroTTS } = await import('kokoro-js');
				TTSModel = await KokoroTTS.from_pretrained(model_id, {
					dtype: TTSEngineConfig.dtype, // Options: "fp32", "fp16", "q8", "q4", "q4f16"
					device: !!navigator?.gpu ? 'webgpu' : 'wasm', // Detect WebGPU
					progress_callback: (e) => {
						TTSModelProgress = e;
						console.log(e);
					}
				});

				await getVoices();

				// const rawAudio = await tts.generate(inputText, {
				// 	// Use `tts.list_voices()` to list all available voices
				// 	voice: voice
				// });

				// const blobUrl = URL.createObjectURL(await rawAudio.toBlob());
				// const audio = new Audio(blobUrl);

				// audio.play();
			}
		}
	};
</script>

<form
	id="tab-audio"
	class="flex flex-col h-full justify-between space-y-3 text-sm"
	on:submit|preventDefault={async () => {
		saveSettings({
			audio: {
				stt: {
					engine: STTEngine !== '' ? STTEngine : undefined,
					language: STTLanguage !== '' ? STTLanguage : undefined
				},
				tts: {
					engine: TTSEngine !== '' ? TTSEngine : undefined,
					engineConfig: TTSEngineConfig,
					mode: voiceMode,
					// Clamped to what the synthesis engines accept: this value is now
					// sent as the render speed, not only applied to playback.
					playbackRate: Math.min(4, Math.max(0.25, Number(playbackRate) || 1)),
					voice: voice !== '' ? voice : undefined,
					defaultVoice: $config?.audio?.tts?.voice ?? '',
					nonLocalVoices: !serverSpeaks ? nonLocalVoices : undefined
				}
			}
		});
		dispatch('save');
	}}
>
	<div class=" space-y-3 overflow-y-scroll max-h-[28rem] md:max-h-full">
		<div>
			<div class="pb-1 text-lg font-semibold text-gray-900 dark:text-gray-100">{$i18n.t('STT Settings')}</div>

			{#if harvisAudio}
				<div class="pb-1.5 text-xs text-gray-500">
					{#if serverHears}
						{$i18n.t('Speech is transcribed on this server')}{sttProvider ? ` (${sttProvider})` : ''}.
					{:else}
						{$i18n.t(
							'This server does not transcribe audio. Choose Web API so your browser does it.'
						)}
					{/if}
				</div>
			{/if}

			{#if $config.audio.stt.engine !== 'web'}
				<SettingRow>
					<svelte:fragment slot="title">
						<div>{$i18n.t('Speech-to-Text Engine')}</div>
					</svelte:fragment>
					<div class="flex items-center relative">
						<select
							class="w-44 sm:w-56 cursor-pointer rounded-[10px] bg-gray-100 dark:bg-gray-850 px-3 py-2 pr-8 text-sm text-gray-800 dark:text-gray-100 outline-hidden"
							bind:value={STTEngine}
							aria-label={$i18n.t('Speech-to-Text Engine')}
							placeholder={$i18n.t('Select an engine')}
						>
							<option value="">{$i18n.t('Default')}</option>
							<option value="web">{$i18n.t('Web API')}</option>
						</select>
					</div>
				</SettingRow>

				<SettingRow>
					<svelte:fragment slot="title">
						<div>{$i18n.t('Language')}</div>
					</svelte:fragment>

					<div class="flex items-center relative text-xs px-3">
						<Tooltip
							content={$i18n.t(
								'The language of the input audio. Supplying the input language in ISO-639-1 (e.g. en) format will improve accuracy and latency. Leave blank to automatically detect the language.'
							)}
							placement="top"
						>
							<input
								type="text"
								bind:value={STTLanguage}
								aria-label={$i18n.t('Speech-to-Text Language')}
								placeholder={$i18n.t('e.g. en')}
								class="w-24 rounded-[10px] bg-gray-100 dark:bg-gray-850 px-3 py-1.5 text-sm text-right text-gray-800 dark:text-gray-100 outline-hidden"
							/>
						</Tooltip>
					</div>
				</SettingRow>
			{/if}

			<SettingRow>
				<svelte:fragment slot="title">
					<div>
						{$i18n.t('Instant Auto-Send After Voice Transcription')}
					</div>
				</svelte:fragment>

				<button
					class="px-3 py-1.5 text-sm font-medium rounded-[10px] bg-gray-100 hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800 text-gray-800 dark:text-gray-100 flex transition"
					on:click={() => {
						toggleSpeechAutoSend();
					}}
					type="button"
					role="switch"
					aria-checked={speechAutoSend}
				>
					{#if speechAutoSend === true}
						<span class="self-center">{$i18n.t('On')}</span>
					{:else}
						<span class="self-center">{$i18n.t('Off')}</span>
					{/if}
				</button>
			</SettingRow>
		</div>

		<div>
			<div class="pt-6 pb-1 text-lg font-semibold text-gray-900 dark:text-gray-100">{$i18n.t('TTS Settings')}</div>

			{#if harvisAudio}
				<div class="pb-1.5 text-xs text-gray-500">
					{#if TTSEngine === 'browser-kokoro'}
						{$i18n.t('Speech is generated in your browser — nothing leaves this machine.')}
					{:else if serverSpeaks}
						{$i18n.t('Speech is generated on this server')}{ttsProvider ? ` (${ttsProvider})` : ''}.
					{:else}
						{$i18n.t(
							'This server does not generate speech. Pick Kokoro (in browser) to hear replies.'
						)}
					{/if}
				</div>
			{/if}

			<SettingRow>
				<svelte:fragment slot="title">
					<div>{$i18n.t('Text-to-Speech Engine')}</div>
				</svelte:fragment>
				<div class="flex items-center relative">
					<select
						class="w-44 sm:w-56 cursor-pointer rounded-[10px] bg-gray-100 dark:bg-gray-850 px-3 py-2 pr-8 text-sm text-gray-800 dark:text-gray-100 outline-hidden"
						bind:value={TTSEngine}
						on:change={onTTSEngineSelect}
						aria-label={$i18n.t('Text-to-Speech Engine')}
						placeholder={$i18n.t('Select an engine')}
					>
						<option value=""
							>{serverSpeaks
								? $i18n.t('Harvis Voice (server)')
								: $i18n.t('System voice (browser)')}</option
						>
						<option value="browser-kokoro">{$i18n.t('Kokoro (in browser)')}</option>
					</select>
				</div>
			</SettingRow>

			<SettingRow>
				<svelte:fragment slot="title">
					<div>{$i18n.t('Voice Mode')}</div>
				</svelte:fragment>
				<div class="flex items-center relative">
					<select
						class="w-44 sm:w-56 cursor-pointer rounded-[10px] bg-gray-100 dark:bg-gray-850 px-3 py-2 pr-8 text-sm text-gray-800 dark:text-gray-100 outline-hidden"
						bind:value={voiceMode}
						aria-label={$i18n.t('Voice Mode')}
					>
						<option value="natural">{$i18n.t('Natural')}</option>
						<option value="advanced" disabled={!ADVANCED_VOICE_ENABLED}>
							{ADVANCED_VOICE_ENABLED
								? $i18n.t('Advanced')
								: $i18n.t('Advanced (needs the RVC service)')}
						</option>
					</select>
				</div>
			</SettingRow>

			{#if TTSEngine === 'browser-kokoro'}
				<SettingRow>
					<svelte:fragment slot="title">
						<div>{$i18n.t('Kokoro.js Dtype')}</div>
					</svelte:fragment>
					<div class="flex items-center relative">
						<select
							class="w-44 sm:w-56 cursor-pointer rounded-[10px] bg-gray-100 dark:bg-gray-850 px-3 py-2 pr-8 text-sm text-gray-800 dark:text-gray-100 outline-hidden"
							bind:value={TTSEngineConfig.dtype}
							aria-label={$i18n.t('Kokoro.js Dtype')}
							placeholder={$i18n.t('Select dtype')}
						>
							<option value="" disabled selected>{$i18n.t('Select dtype')}</option>
							<option value="fp32">fp32</option>
							<option value="fp16">fp16</option>
							<option value="q8">q8</option>
							<option value="q4">q4</option>
						</select>
					</div>
				</SettingRow>
			{/if}

			<SettingRow>
				<svelte:fragment slot="title">
					<div>{$i18n.t('Auto-playback response')}</div>
				</svelte:fragment>

				<button
					class="px-3 py-1.5 text-sm font-medium rounded-[10px] bg-gray-100 hover:bg-gray-200 dark:bg-gray-850 dark:hover:bg-gray-800 text-gray-800 dark:text-gray-100 flex transition"
					on:click={() => {
						toggleResponseAutoPlayback();
					}}
					type="button"
					role="switch"
					aria-checked={responseAutoPlayback}
				>
					{#if responseAutoPlayback === true}
						<span class="self-center">{$i18n.t('On')}</span>
					{:else}
						<span class="self-center">{$i18n.t('Off')}</span>
					{/if}
				</button>
			</SettingRow>

			<SettingRow>
				<svelte:fragment slot="title">
					<div>{$i18n.t('Speech Speed')}</div>
				</svelte:fragment>

				<div class="flex items-center relative text-xs px-3">
					<input
						type="number"
						min="0.25"
						max="4"
						step="0.05"
						bind:value={playbackRate}
						aria-label={$i18n.t('Speech Speed')}
						class="w-24 rounded-[10px] bg-gray-100 dark:bg-gray-850 px-3 py-1.5 text-sm text-right text-gray-800 dark:text-gray-100 outline-hidden"
					/>
					x
				</div>
			</SettingRow>
		</div>

		<hr class=" border-gray-100/30 dark:border-gray-850/30" />

		{#if TTSEngine === 'browser-kokoro'}
			{#if TTSModel}
				<div>
					<div class=" mb-2 text-[15px] font-semibold text-gray-900 dark:text-gray-100">{$i18n.t('Set Voice')}</div>
					<div class="flex w-full">
						<div class="flex-1">
							<input
								list="voice-list"
								class="w-full text-sm bg-transparent dark:text-gray-300 outline-hidden"
								bind:value={voice}
								aria-label={$i18n.t('Voice')}
								placeholder={$i18n.t('Select a voice')}
							/>

							<datalist id="voice-list">
								{#each voices as voice}
									<option value={voice.id}>{voice.name}</option>
								{/each}
							</datalist>
						</div>
					</div>
				</div>
			{:else}
				<div>
					<div class=" mb-2.5 text-sm font-medium flex gap-2 items-center">
						<Spinner className="size-4" />

						<div class=" text-sm font-medium shimmer">
							{$i18n.t('Loading Kokoro.js...')}
							{TTSModelProgress && TTSModelProgress.status === 'progress'
								? `(${Math.round(TTSModelProgress.progress * 10) / 10}%)`
								: ''}
						</div>
					</div>

					<div class="text-xs text-gray-500">
						{$i18n.t('Please do not close the settings page while loading the model.')}
					</div>
				</div>
			{/if}
		{:else if !serverSpeaks}
			<!-- Nothing on the server will speak, so these are the browser's own
			     system voices — a free-text box would just invite a name that no
			     engine here has. -->
			<div>
				<div class=" mb-2 text-[15px] font-semibold text-gray-900 dark:text-gray-100">{$i18n.t('Set Voice')}</div>
				<div class="flex w-full">
					<div class="flex-1">
						<select
							class="w-full text-sm bg-transparent dark:text-gray-300 outline-hidden"
							bind:value={voice}
							aria-label={$i18n.t('Voice')}
						>
							<option value="" selected={voice !== ''}>{$i18n.t('Default')}</option>
							{#each voices.filter((v) => nonLocalVoices || v.localService === true) as _voice}
								<option
									value={_voice.name}
									class="bg-gray-100 dark:bg-gray-700"
									selected={voice === _voice.name}>{_voice.name}</option
								>
							{/each}
						</select>
					</div>
				</div>
				<div class="flex items-center justify-between py-2.5">
					<div class="text-sm text-gray-700 dark:text-gray-300">
						{$i18n.t('Allow non-local voices')}
					</div>

					<div class="mt-1">
						<Switch bind:state={nonLocalVoices} />
					</div>
				</div>
			</div>
		{:else}
			<div>
				<div class=" mb-2 text-[15px] font-semibold text-gray-900 dark:text-gray-100">{$i18n.t('Set Voice')}</div>
				<div class="flex w-full">
					<div class="flex-1">
						<input
							list="voice-list"
							class="w-full text-sm bg-transparent dark:text-gray-300 outline-hidden"
							bind:value={voice}
							aria-label={$i18n.t('Voice')}
							placeholder={$i18n.t('Select a voice')}
						/>

						<datalist id="voice-list">
							{#each voices as voice}
								<option value={voice.id}>{voice.name}</option>
							{/each}
						</datalist>
					</div>
				</div>
			</div>
		{/if}
	</div>

	<div class="flex justify-end text-sm font-medium">
		<button
			class="px-3.5 py-1.5 text-sm font-medium bg-black hover:bg-gray-900 text-white dark:bg-white dark:text-black dark:hover:bg-gray-100 transition rounded-full"
			type="submit"
		>
			{$i18n.t('Save')}
		</button>
	</div>
</form>
