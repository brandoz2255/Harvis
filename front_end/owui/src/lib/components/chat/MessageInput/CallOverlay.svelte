<script lang="ts">
	import { config, models, settings, showCallOverlay, TTSWorker } from '$lib/stores';
	import { onMount, tick, getContext, onDestroy, createEventDispatcher } from 'svelte';

	const dispatch = createEventDispatcher();

	import { blobToFile } from '$lib/utils';
	import { generateEmoji } from '$lib/apis';
	import { synthesizeOpenAISpeech, transcribeAudio } from '$lib/apis/audio';

	import { toast } from 'svelte-sonner';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import VideoInputMenu from './CallOverlay/VideoInputMenu.svelte';
	import { KokoroWorker } from '$lib/workers/KokoroWorker';
	import { WEBUI_API_BASE_URL } from '$lib/constants';

	const i18n = getContext('i18n');

	export let eventTarget: EventTarget;
	export let submitPrompt: Function;
	export let stopResponse: Function;
	export let files;
	export let chatId;
	export let modelId;

	let wakeLock = null;

	let model = null;

	let loading = false;
	let confirmed = false;
	let interrupted = false;
	let assistantSpeaking = false;
	let muted = false;

	let emoji = null;
	let camera = false;
	let cameraStream = null;

	let chatStreaming = false;
	let rmsLevel = 0;
	let hasStartedSpeaking = false;
	let mediaRecorder;
	let audioStream = null;
	let audioChunks = [];

	let videoInputDevices = [];
	let selectedVideoInputDeviceId = null;

	const getVideoInputDevices = async () => {
		const devices = await navigator.mediaDevices.enumerateDevices();
		videoInputDevices = devices.filter((device) => device.kind === 'videoinput');

		if (!!navigator.mediaDevices.getDisplayMedia) {
			videoInputDevices = [
				...videoInputDevices,
				{
					deviceId: 'screen',
					label: 'Screen Share'
				}
			];
		}

		console.log(videoInputDevices);
		if (selectedVideoInputDeviceId === null && videoInputDevices.length > 0) {
			const savedDeviceId = localStorage.getItem('selectedVideoInputDeviceId');
			if (savedDeviceId && videoInputDevices.some((d) => d.deviceId === savedDeviceId)) {
				selectedVideoInputDeviceId = savedDeviceId;
			} else {
				selectedVideoInputDeviceId = videoInputDevices[0].deviceId;
			}
		}
	};

	const startCamera = async () => {
		await getVideoInputDevices();

		if (cameraStream === null) {
			camera = true;
			await tick();
			try {
				await startVideoStream();
			} catch (err) {
				console.error('Error accessing webcam: ', err);
			}
		}
	};

	const startVideoStream = async () => {
		const video = document.getElementById('camera-feed');
		if (video) {
			if (selectedVideoInputDeviceId === 'screen') {
				cameraStream = await navigator.mediaDevices.getDisplayMedia({
					video: {
						cursor: 'always'
					},
					audio: false
				});
			} else {
				cameraStream = await navigator.mediaDevices.getUserMedia({
					video: {
						deviceId: selectedVideoInputDeviceId ? { exact: selectedVideoInputDeviceId } : undefined
					}
				});
			}

			if (cameraStream) {
				await getVideoInputDevices();
				video.srcObject = cameraStream;
				await video.play();
			}
		}
	};

	const stopVideoStream = async () => {
		if (cameraStream) {
			const tracks = cameraStream.getTracks();
			tracks.forEach((track) => track.stop());
		}

		cameraStream = null;
	};

	const takeScreenshot = () => {
		const video = document.getElementById('camera-feed');
		const canvas = document.getElementById('camera-canvas');

		if (!canvas) {
			return;
		}

		const context = canvas.getContext('2d');

		// Make the canvas match the video dimensions
		canvas.width = video.videoWidth;
		canvas.height = video.videoHeight;

		// Draw the image from the video onto the canvas
		context.drawImage(video, 0, 0, video.videoWidth, video.videoHeight);

		// Convert the canvas to a data base64 URL and console log it
		const dataURL = canvas.toDataURL('image/png');
		console.log(dataURL);

		return dataURL;
	};

	const stopCamera = async () => {
		await stopVideoStream();
		camera = false;
	};

	const MIN_DECIBELS = -55;
	const VISUALIZER_BUFFER_LENGTH = 300;

	// ── Voice-activity detection (VAD) tuning ──────────────────────────────────
	// SPEECH_RMS_THRESHOLD: normalized RMS (0–1) above which a frame counts as
	//   real speech rather than the mic's ambient noise floor (~0.003–0.01 quiet,
	//   ~0.03+ speech). The old gate used `domainData.some(v => v > 0)`, which is
	//   true on EVERY frame from ambient noise — so the silence timer below never
	//   aged out and the call listened forever without ever responding.
	// SILENCE_DURATION_MS: how long RMS must stay below the threshold (a gap)
	//   before we stop recording → transcribe → respond. Both are user-tunable.
	const SPEECH_RMS_THRESHOLD = $settings?.audio?.stt?.speechThreshold ?? 0.01;
	const SILENCE_DURATION_MS = $settings?.audio?.stt?.silenceDurationMs ?? 1500;

	const transcribeHandler = async (audioBlob) => {
		// Create a blob from the audio chunks
		if (!audioBlob || audioBlob.size < 100) {
			console.log('Audio blob too small or empty, skipping transcription');
			return;
		}

		await tick();
		const file = blobToFile(audioBlob, 'recording.wav');

		const res = await transcribeAudio(
			localStorage.token,
			file,
			$settings?.audio?.stt?.language
		).catch((error) => {
			toast.error(`${error}`);
			return null;
		});

		if (res) {
			console.log(res.text);

			if (res.text !== '') {
				const _responses = await submitPrompt(res.text, { _raw: true });
				console.log(_responses);
			}
		}
	};

	const stopRecordingCallback = async (_continue = true) => {
		if ($showCallOverlay) {
			console.log('%c%s', 'color: red; font-size: 20px;', '🚨 stopRecordingCallback 🚨');

			// deep copy the audioChunks array
			const _audioChunks = audioChunks.slice(0);

			audioChunks = [];
			mediaRecorder = false;

			if (_continue) {
				startRecording();
			}

			if (confirmed) {
				loading = true;
				emoji = null;

				if (cameraStream) {
					const imageUrl = takeScreenshot();

					files = [
						{
							type: 'image',
							url: imageUrl
						}
					];
				}

				const audioBlob = new Blob(_audioChunks, { type: 'audio/wav' });
				await transcribeHandler(audioBlob);

				confirmed = false;
				loading = false;
			}
		} else {
			audioChunks = [];
			mediaRecorder = false;

			if (audioStream) {
				const tracks = audioStream.getTracks();
				tracks.forEach((track) => track.stop());
			}
			audioStream = null;
		}
	};

	const startRecording = async () => {
		if ($showCallOverlay) {
			if (!audioStream) {
				audioStream = await navigator.mediaDevices.getUserMedia({
					audio: {
						echoCancellation: true,
						noiseSuppression: true,
						autoGainControl: true
					}
				});
			}

			if (audioStream) {
				// hardware track muting disabled to prevent backend translation errors with malformed WebM files
			}

			mediaRecorder = new MediaRecorder(audioStream);

			mediaRecorder.onstart = () => {
				console.log('Recording started');
				audioChunks = [];
			};

			mediaRecorder.ondataavailable = (event) => {
				if (hasStartedSpeaking) {
					audioChunks.push(event.data);
				}
			};

			mediaRecorder.onstop = (e) => {
				console.log('Recording stopped', audioStream, e);
				stopRecordingCallback();
			};

			analyseAudio(audioStream);
		}
	};

	const stopAudioStream = async () => {
		try {
			if (mediaRecorder) {
				mediaRecorder.stop();
			}
		} catch (error) {
			console.log('Error stopping audio stream:', error);
		}

		if (!audioStream) return;

		audioStream.getAudioTracks().forEach(function (track) {
			track.stop();
		});

		audioStream = null;
	};

	// Function to calculate the RMS level from time domain data
	const calculateRMS = (data: Uint8Array) => {
		let sumSquares = 0;
		for (let i = 0; i < data.length; i++) {
			const normalizedValue = (data[i] - 128) / 128; // Normalize the data
			sumSquares += normalizedValue * normalizedValue;
		}
		return Math.sqrt(sumSquares / data.length);
	};

	const analyseAudio = (stream) => {
		const audioContext = new AudioContext();
		const audioStreamSource = audioContext.createMediaStreamSource(stream);

		const analyser = audioContext.createAnalyser();
		analyser.minDecibels = MIN_DECIBELS;
		audioStreamSource.connect(analyser);

		// CRITICAL: an AudioContext created outside a direct user-gesture handler
		// (this one is created in onMount→startRecording, not in the click) is born
		// SUSPENDED — the analyser then reads pure silence, RMS stays 0, no speech
		// is ever detected, recording never starts, and nothing reaches the STT
		// endpoint (0 transcriptions). Resume it so the mic graph actually runs.
		if (audioContext.state === 'suspended') {
			audioContext.resume().then(
				() => console.log('🔊 AudioContext resumed →', audioContext.state),
				(e) => console.error('AudioContext resume failed', e)
			);
		}

		const bufferLength = analyser.frequencyBinCount;

		const domainData = new Uint8Array(bufferLength);
		const timeDomainData = new Uint8Array(analyser.fftSize);

		let lastSoundTime = Date.now();
		hasStartedSpeaking = false;

		console.log('🔊 Sound detection started', lastSoundTime, 'ctx=', audioContext.state);

		const detectSound = () => {
			const processFrame = () => {
				if (!mediaRecorder || !$showCallOverlay) {
					return;
				}

				if (muted || (assistantSpeaking && !($settings?.voiceInterruption ?? false))) {
					// Suppress mic input when muted or when assistant is speaking without interruption enabled
					analyser.maxDecibels = 0;
					analyser.minDecibels = -1;
				} else {
					analyser.minDecibels = MIN_DECIBELS;
					analyser.maxDecibels = -30;
				}

				analyser.getByteTimeDomainData(timeDomainData);
				analyser.getByteFrequencyData(domainData);

				// Calculate RMS level from time domain data
				rmsLevel = calculateRMS(timeDomainData);

				if (muted || (assistantSpeaking && !($settings?.voiceInterruption ?? false))) {
					rmsLevel = 0;
				}

				// Real speech vs ambient: gate on the RMS amplitude, not "any
				// non-zero frequency bin" (which ambient noise satisfies every
				// frame, so the silence timer below never fired and the call
				// listened forever without responding).
				const hasSound = rmsLevel > SPEECH_RMS_THRESHOLD;
				if (hasSound) {
					if (mediaRecorder && mediaRecorder.state !== 'recording') {
						mediaRecorder.start();
					}

					if (!hasStartedSpeaking) {
						hasStartedSpeaking = true;
						stopAllAudio();
					}

					lastSoundTime = Date.now();
				}

				// Once the user has begun speaking, a gap of silence (RMS below
				// threshold for SILENCE_DURATION_MS) ends the turn → transcribe.
				if (hasStartedSpeaking) {
					if (Date.now() - lastSoundTime > SILENCE_DURATION_MS) {
						confirmed = true;

						if (mediaRecorder) {
							console.log('%c%s', 'color: red; font-size: 20px;', '🔇 Silence gap — ending turn');
							mediaRecorder.stop();
							return;
						}
					}
				}

				window.requestAnimationFrame(processFrame);
			};

			window.requestAnimationFrame(processFrame);
		};

		detectSound();
	};

	let finishedMessages = {};
	let currentMessageId = null;
	let currentUtterance = null;

	// Get voice: model-specific > user settings > config default
	const getVoiceId = () => {
		// Check for model-specific TTS voice first
		if (model?.info?.meta?.tts?.voice) {
			return model.info.meta.tts.voice;
		}
		// Fall back to user settings or config default
		if ($settings?.audio?.tts?.defaultVoice === $config.audio.tts.voice) {
			return $settings?.audio?.tts?.voice ?? $config?.audio?.tts?.voice;
		}
		return $config?.audio?.tts?.voice;
	};

	const speakSpeechSynthesisHandler = (content) => {
		if ($showCallOverlay) {
			return new Promise((resolve) => {
				let voices = [];
				const getVoicesLoop = setInterval(async () => {
					voices = await speechSynthesis.getVoices();
					if (voices.length > 0) {
						clearInterval(getVoicesLoop);

						const voiceId = getVoiceId();
						const voice = voices?.filter((v) => v.voiceURI === voiceId)?.at(0) ?? undefined;

						currentUtterance = new SpeechSynthesisUtterance(content);
						currentUtterance.rate = $settings.audio?.tts?.playbackRate ?? 1;

						if (voice) {
							currentUtterance.voice = voice;
						}

						speechSynthesis.speak(currentUtterance);
						currentUtterance.onend = async (e) => {
							await new Promise((r) => setTimeout(r, 200));
							resolve(e);
						};
					}
				}, 100);
			});
		} else {
			return Promise.resolve();
		}
	};

	const playAudio = (audio) => {
		if ($showCallOverlay) {
			return new Promise((resolve) => {
				const audioElement = document.getElementById('audioElement') as HTMLAudioElement;

				if (audioElement) {
					audioElement.src = audio.src;
					// Do NOT mute: the overlay opens on a user gesture so autoplay is
					// allowed, and muting here (the old autoplay trick) could leave the
					// SHARED #audioElement muted if play()/unmute was interrupted —
					// silently killing both the overlay voice AND message Read-Aloud.
					audioElement.muted = false;
					// Server-rendered audio already came back at the requested speed
					// (see fetchAudio) — resampling it again would compound the two.
					audioElement.playbackRate =
						$settings.audio?.tts?.engine === 'browser-kokoro'
							? ($settings.audio?.tts?.playbackRate ?? 1)
							: 1;

					audioElement.play().catch((error) => {
						console.error(error);
					});

					audioElement.onended = async (e) => {
						await new Promise((r) => setTimeout(r, 100));
						resolve(e);
					};
				}
			});
		} else {
			return Promise.resolve();
		}
	};

	const stopAllAudio = async () => {
		assistantSpeaking = false;
		interrupted = true;

		if (chatStreaming) {
			stopResponse();
		}

		if (currentUtterance) {
			speechSynthesis.cancel();
			currentUtterance = null;
		}

		const audioElement = document.getElementById('audioElement');
		if (audioElement) {
			audioElement.muted = true;
			audioElement.pause();
			audioElement.currentTime = 0;
		}
	};

	let audioAbortController = new AbortController();

	// Audio cache map where key is the content and value is the Audio object.
	const audioCache = new Map();
	const emojiCache = new Map();

	const fetchAudio = async (content) => {
		if (!audioCache.has(content)) {
			try {
				// Set the emoji for the content if needed
				if ($settings?.showEmojiInCall ?? false) {
					const emoji = await generateEmoji(localStorage.token, modelId, content, chatId);
					if (emoji) {
						emojiCache.set(content, emoji);
					}
				}

				if ($settings.audio?.tts?.engine === 'browser-kokoro') {
					const url = await $TTSWorker
						.generate({
							text: content,
							voice: getVoiceId()
						})
						.catch((error) => {
							console.error(error);
							toast.error(`${error}`);
						});

					if (url) {
						audioCache.set(content, new Audio(url));
					}
				} else if ($config.audio.tts.engine !== '') {
					const res = await synthesizeOpenAISpeech(
						localStorage.token,
						getVoiceId(),
						content,
						undefined,
						$settings.audio?.tts?.playbackRate ?? 1
					).catch((error) => {
						console.error(error);
						return null;
					});

					if (res) {
						const blob = await res.blob();
						const blobUrl = URL.createObjectURL(blob);
						audioCache.set(content, new Audio(blobUrl));
					}
				} else {
					audioCache.set(content, true);
				}
			} catch (error) {
				console.error('Error synthesizing speech:', error);
			}
		}

		return audioCache.get(content);
	};

	let messages = {};

	const monitorAndPlayAudio = async (id, signal) => {
		while (!signal.aborted) {
			if (messages[id] && messages[id].length > 0) {
				// Retrieve the next content string from the queue
				const content = messages[id].shift(); // Dequeues the content for playing

				if (audioCache.has(content)) {
					// If content is available in the cache, play it

					// Set the emoji for the content if available
					if (($settings?.showEmojiInCall ?? false) && emojiCache.has(content)) {
						emoji = emojiCache.get(content);
					} else {
						emoji = null;
					}

					if ($config.audio.tts.engine !== '') {
						try {
							console.log(
								'%c%s',
								'color: red; font-size: 20px;',
								`Playing audio for content: ${content}`
							);

							const audio = audioCache.get(content);
							await playAudio(audio); // Here ensure that playAudio is indeed correct method to execute
							console.log(`Played audio for content: ${content}`);
							await new Promise((resolve) => setTimeout(resolve, 200)); // Wait before retrying to reduce tight loop
						} catch (error) {
							console.error('Error playing audio:', error);
						}
					} else {
						await speakSpeechSynthesisHandler(content);
					}
				} else {
					// If not available in the cache, push it back to the queue and delay
					messages[id].unshift(content); // Re-queue the content at the start
					console.log(`Audio for "${content}" not yet available in the cache, re-queued...`);
					await new Promise((resolve) => setTimeout(resolve, 200)); // Wait before retrying to reduce tight loop
				}
			} else if (finishedMessages[id] && messages[id] && messages[id].length === 0) {
				// If the message is finished and there are no more messages to process, break the loop
				assistantSpeaking = false;
				break;
			} else {
				// No messages to process, sleep for a bit
				await new Promise((resolve) => setTimeout(resolve, 200));
			}
		}
		console.log(`Audio monitoring and playing stopped for message ID ${id}`);
	};

	const chatStartHandler = async (e) => {
		const { id } = e.detail;

		chatStreaming = true;

		if (currentMessageId !== id) {
			console.log(`Received chat start event for message ID ${id}`);

			currentMessageId = id;
			if (audioAbortController) {
				audioAbortController.abort();
			}
			audioAbortController = new AbortController();

			assistantSpeaking = true;
			// Start monitoring and playing audio for the message ID
			monitorAndPlayAudio(id, audioAbortController.signal);
		}
	};

	const chatEventHandler = async (e) => {
		const { id, content } = e.detail;
		// "id" here is message id
		// if "id" is not the same as "currentMessageId" then do not process
		// "content" here is a sentence from the assistant,
		// there will be many sentences for the same "id"

		if (currentMessageId === id) {
			console.log(`Received chat event for message ID ${id}: ${content}`);

			try {
				if (messages[id] === undefined) {
					messages[id] = [content];
				} else {
					messages[id].push(content);
				}

				console.log(content);

				fetchAudio(content);
			} catch (error) {
				console.error('Failed to fetch or play audio:', error);
			}
		}
	};

	const chatFinishHandler = async (e) => {
		const { id, content } = e.detail;
		// "content" here is the entire message from the assistant
		finishedMessages[id] = true;

		chatStreaming = false;
	};

	const toggleMute = () => {
		muted = !muted;
		if (muted && hasStartedSpeaking) {
			// User muted mid-utterance → treat it as "I'm done talking": FINALIZE and
			// send what was captured (transcribe → respond), then stay muted so outside
			// noise can't start a new turn. (Previously this DISCARDED the partial —
			// confirmed=false + cleared chunks — which felt like the call just stopped.)
			// confirmed=true makes stopRecordingCallback transcribe instead of drop;
			// keep hasStartedSpeaking true so the recorder's final `ondataavailable`
			// still captures the audio before stop().
			confirmed = true;
			if (mediaRecorder && mediaRecorder.state === 'recording') {
				mediaRecorder.stop(); // → onstop → stopRecordingCallback → transcribe + submit
			}
		}
	};

	let wasAssistantSpeaking = false;
	$: {
		if (assistantSpeaking && !wasAssistantSpeaking) {
			wasAssistantSpeaking = true;
		} else if (!assistantSpeaking && wasAssistantSpeaking) {
			wasAssistantSpeaking = false;
			// Sticky mute: do NOT auto-unmute when the AI finishes. If the user
			// muted, the mic stays off so the assistant doesn't chain replies off
			// ambient noise / silence. The user re-enables listening explicitly.
		}
	}

	const handleKeydown = (e: KeyboardEvent) => {
		// Only handle M key when not typing in an input/textarea
		if (e.key === 'm' || e.key === 'M') {
			const target = e.target as HTMLElement;
			if (
				target.tagName !== 'INPUT' &&
				target.tagName !== 'TEXTAREA' &&
				!target.isContentEditable
			) {
				e.preventDefault();
				toggleMute();
			}
		}
	};

	onMount(async () => {
		// Unlock the shared #audioElement for autoplay. The overlay opens on a user
		// gesture (the Voice/call button), so a muted silent play() here "blesses" the
		// element — without it the assistant's TTS (played later from an async SSE
		// callback with NO active gesture) stays autoplay-blocked until the user
		// manually taps a per-message Read-Aloud button to unlock the element.
		try {
			const el = document.getElementById('audioElement') as HTMLAudioElement;
			if (el) {
				const N = 8; // tiny 8-bit/8kHz mono silent WAV (self-contained, no asset)
				const buf = new ArrayBuffer(44 + N);
				const dv = new DataView(buf);
				const wr = (o: number, s: string) => {
					for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i));
				};
				wr(0, 'RIFF'); dv.setUint32(4, 36 + N, true); wr(8, 'WAVE'); wr(12, 'fmt ');
				dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true);
				dv.setUint32(24, 8000, true); dv.setUint32(28, 8000, true);
				dv.setUint16(32, 1, true); dv.setUint16(34, 8, true); wr(36, 'data');
				dv.setUint32(40, N, true);
				for (let i = 0; i < N; i++) dv.setUint8(44 + i, 128); // 128 = 8-bit silence
				const url = URL.createObjectURL(new Blob([buf], { type: 'audio/wav' }));
				el.muted = true;
				el.src = url;
				await el.play().catch(() => {});
				el.pause();
				el.currentTime = 0;
				el.muted = false;
				URL.revokeObjectURL(url);
			}
		} catch (e) {
			// Non-fatal — worst case is the old behavior (manual unlock once).
		}

		const setWakeLock = async () => {
			try {
				wakeLock = await navigator.wakeLock.request('screen');
			} catch (err) {
				// The Wake Lock request has failed - usually system related, such as battery.
				console.log(err);
			}

			if (wakeLock) {
				// Add a listener to release the wake lock when the page is unloaded
				wakeLock.addEventListener('release', () => {
					// the wake lock has been released
					console.log('Wake Lock released');
				});
			}
		};

		if ('wakeLock' in navigator) {
			await setWakeLock();

			document.addEventListener('visibilitychange', async () => {
				// Re-request the wake lock if the document becomes visible
				if (wakeLock !== null && document.visibilityState === 'visible') {
					await setWakeLock();
				}
			});
		}

		model = $models.find((m) => m.id === modelId);

		startRecording();

		eventTarget.addEventListener('chat:start', chatStartHandler);
		eventTarget.addEventListener('chat', chatEventHandler);
		eventTarget.addEventListener('chat:finish', chatFinishHandler);

		document.addEventListener('keydown', handleKeydown);

		return async () => {
			await stopAllAudio();

			stopAudioStream();

			eventTarget.removeEventListener('chat:start', chatStartHandler);
			eventTarget.removeEventListener('chat', chatEventHandler);
			eventTarget.removeEventListener('chat:finish', chatFinishHandler);

			document.removeEventListener('keydown', handleKeydown);

			audioAbortController.abort();
			await tick();

			await stopAllAudio();

			await stopRecordingCallback(false);
			await stopCamera();
		};
	});

	onDestroy(async () => {
		await stopAllAudio();
		await stopRecordingCallback(false);
		await stopCamera();

		await stopAudioStream();
		eventTarget.removeEventListener('chat:start', chatStartHandler);
		eventTarget.removeEventListener('chat', chatEventHandler);
		eventTarget.removeEventListener('chat:finish', chatFinishHandler);

		document.removeEventListener('keydown', handleKeydown);

		audioAbortController.abort();

		await tick();

		await stopAllAudio();
	});
</script>

{#if $showCallOverlay}
	<div class="max-w-lg w-full h-full max-h-[100dvh] flex flex-col justify-between p-3 md:p-6">
		{#if camera}
			<button
				type="button"
				class="flex justify-center items-center w-full h-20 min-h-20"
				on:click={() => {
					if (assistantSpeaking) {
						stopAllAudio();
					}
				}}
			>
				{#if emoji}
					<div
						class="  transition-all rounded-lg"
						style="font-size:{rmsLevel * 100 > 4
							? '4.5'
							: rmsLevel * 100 > 2
								? '4.25'
								: rmsLevel * 100 > 1
									? '3.75'
									: '3.5'}rem;width: 100%; text-align:center;"
					>
						{emoji}
					</div>
				{:else if loading}
					<svg
						class="size-12 text-gray-900 dark:text-gray-400"
						viewBox="0 0 24 24"
						fill="currentColor"
						xmlns="http://www.w3.org/2000/svg"
						><style>
							.spinner_qM83 {
								animation: spinner_8HQG 1.05s infinite;
							}
							.spinner_oXPr {
								animation-delay: 0.1s;
							}
							.spinner_ZTLf {
								animation-delay: 0.2s;
							}
							@keyframes spinner_8HQG {
								0%,
								57.14% {
									animation-timing-function: cubic-bezier(0.33, 0.66, 0.66, 1);
									transform: translate(0);
								}
								28.57% {
									animation-timing-function: cubic-bezier(0.33, 0, 0.66, 0.33);
									transform: translateY(-6px);
								}
								100% {
									transform: translate(0);
								}
							}
						</style><circle class="spinner_qM83" cx="4" cy="12" r="3" /><circle
							class="spinner_qM83 spinner_oXPr"
							cx="12"
							cy="12"
							r="3"
						/><circle class="spinner_qM83 spinner_ZTLf" cx="20" cy="12" r="3" /></svg
					>
				{:else}
					<div
						class=" {rmsLevel * 100 > 4
							? ' size-[4.5rem]'
							: rmsLevel * 100 > 2
								? ' size-16'
								: rmsLevel * 100 > 1
									? 'size-14'
									: 'size-12'}  {assistantSpeaking ? 'call-speaking-pulse ring-2 ring-blue-400/50 ring-offset-2 ring-offset-transparent' : ''} transition-all rounded-full bg-cover bg-center bg-no-repeat"
						style={`background-image: url('${WEBUI_API_BASE_URL}/models/model/profile/image?id=${model?.id}&lang=${$i18n.language}&voice=true');`}
					/>
				{/if}
				<!-- navbar -->
			</button>
		{/if}

		<div class="flex justify-center items-center flex-1 h-full w-full max-h-full">
			{#if !camera}
				<button
					type="button"
					on:click={() => {
						if (assistantSpeaking) {
							stopAllAudio();
						}
					}}
				>
					{#if emoji}
						<div
							class="  transition-all rounded-lg"
							style="font-size:{rmsLevel * 100 > 4
								? '13'
								: rmsLevel * 100 > 2
									? '12'
									: rmsLevel * 100 > 1
										? '11.5'
										: '11'}rem;width:100%;text-align:center;"
						>
							{emoji}
						</div>
					{:else if loading}
						<svg
							class="size-44 text-gray-900 dark:text-gray-400"
							viewBox="0 0 24 24"
							fill="currentColor"
							xmlns="http://www.w3.org/2000/svg"
							><style>
								.spinner_qM83 {
									animation: spinner_8HQG 1.05s infinite;
								}
								.spinner_oXPr {
									animation-delay: 0.1s;
								}
								.spinner_ZTLf {
									animation-delay: 0.2s;
								}
								@keyframes spinner_8HQG {
									0%,
									57.14% {
										animation-timing-function: cubic-bezier(0.33, 0.66, 0.66, 1);
										transform: translate(0);
									}
									28.57% {
										animation-timing-function: cubic-bezier(0.33, 0, 0.66, 0.33);
										transform: translateY(-6px);
									}
									100% {
										transform: translate(0);
									}
								}
							</style><circle class="spinner_qM83" cx="4" cy="12" r="3" /><circle
								class="spinner_qM83 spinner_oXPr"
								cx="12"
								cy="12"
								r="3"
							/><circle class="spinner_qM83 spinner_ZTLf" cx="20" cy="12" r="3" /></svg
						>
					{:else}
						<div
							class=" {rmsLevel * 100 > 4
								? ' size-52'
								: rmsLevel * 100 > 2
									? 'size-48'
									: rmsLevel * 100 > 1
										? 'size-44'
										: 'size-40'} {assistantSpeaking ? 'call-speaking-pulse ring-2 ring-blue-400/50 ring-offset-2 ring-offset-transparent' : ''} transition-all rounded-full bg-cover bg-center bg-no-repeat"
							style={`background-image: url('${WEBUI_API_BASE_URL}/models/model/profile/image?id=${model?.id}&lang=${$i18n.language}&voice=true');`}
						/>
					{/if}
				</button>
			{:else}
				<div class="relative flex video-container w-full max-h-full pt-2 pb-4 md:py-6 px-2 h-full">
					<!-- svelte-ignore a11y-media-has-caption -->
					<video
						id="camera-feed"
						autoplay
						class="rounded-2xl h-full min-w-full object-cover object-center"
						playsinline
					/>

					<canvas id="camera-canvas" style="display:none;" />

					<div class=" absolute top-4 md:top-8 left-4">
						<button
							type="button"
							class="p-1.5 text-white cursor-pointer backdrop-blur-xl bg-black/10 rounded-lg"
							on:click={() => {
								stopCamera();
							}}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 16 16"
								fill="currentColor"
								class="size-6"
							>
								<path
									d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 1 0 1.06 1.06L8 9.06l2.72 2.72a.75.75 0 1 0 1.06-1.06L9.06 8l2.72-2.72a.75.75 0 0 0-1.06-1.06L8 6.94 5.28 4.22Z"
								/>
							</svg>
						</button>
					</div>
				</div>
			{/if}
		</div>

		<div class="flex flex-col items-center gap-4 pb-4 w-full">
			<button
				type="button"
				class="z-10"
				on:click={() => {
					if (assistantSpeaking) {
						stopAllAudio();
					}
				}}
			>
				<div class="line-clamp-1 text-sm font-medium">
					{#if loading}
						{$i18n.t('Thinking...')}
					{:else if muted}
						{$i18n.t('Muted')}
					{:else if assistantSpeaking}
						{$i18n.t('Tap to interrupt')}
					{:else}
						{$i18n.t('Listening...')}
					{/if}
				</div>
			</button>

			<div class="flex items-center justify-center gap-4 z-10">
				{#if camera}
					<VideoInputMenu
						devices={videoInputDevices}
						on:change={async (e) => {
							console.log(e.detail);
							selectedVideoInputDeviceId = e.detail;
							localStorage.setItem('selectedVideoInputDeviceId', e.detail);
							await stopVideoStream();
							await startVideoStream();
						}}
					>
						<button class="p-3 rounded-lg bg-gray-50 dark:bg-gray-900" type="button">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 20 20"
								fill="currentColor"
								class="size-5"
							>
								<path
									fill-rule="evenodd"
									d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z"
									clip-rule="evenodd"
								/>
							</svg>
						</button>
					</VideoInputMenu>
				{:else}
					<Tooltip content={$i18n.t('Camera')}>
						<button
							class="p-3 rounded-lg bg-gray-50 dark:bg-gray-900"
							type="button"
							on:click={async () => {
								await navigator.mediaDevices.getUserMedia({ video: true });
								startCamera();
							}}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								stroke-width="1.5"
								stroke="currentColor"
								class="size-5"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="M6.827 6.175A2.31 2.31 0 0 1 5.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 0 0-1.134-.175 2.31 2.31 0 0 1-1.64-1.055l-.822-1.316a2.192 2.192 0 0 0-1.736-1.039 48.774 48.774 0 0 0-5.232 0 2.192 2.192 0 0 0-1.736 1.039l-.821 1.316Z"
								/>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="M16.5 12.75a4.5 4.5 0 1 1-9 0 4.5 4.5 0 0 1 9 0ZM18.75 10.5h.008v.008h-.008V10.5Z"
								/>
							</svg>
						</button>
					</Tooltip>
				{/if}

				<Tooltip content={muted ? $i18n.t('Unmute') + ' (M)' : $i18n.t('Mute') + ' (M)'}>
					<button
						class="p-3 rounded-lg transition-colors duration-200 {muted
							? 'bg-red-500 text-white'
							: 'bg-gray-50 dark:bg-gray-900'}"
						type="button"
						aria-label={muted ? $i18n.t('Unmute') : $i18n.t('Mute')}
						on:click={toggleMute}
					>
						{#if muted}
							<!-- Mic Off icon -->
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								stroke-width="1.5"
								stroke="currentColor"
								class="size-5"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="M12 18.75a6 6 0 0 0 6-6v-1.5m-6 7.5a6 6 0 0 1-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 0 1-3-3V4.5a3 3 0 1 1 6 0v8.25a3 3 0 0 1-3 3Z"
								/>
								<line
									x1="3"
									y1="3"
									x2="21"
									y2="21"
									stroke="currentColor"
									stroke-width="1.5"
									stroke-linecap="round"
								/>
							</svg>
						{:else}
							<!-- Mic On icon -->
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								stroke-width="1.5"
								stroke="currentColor"
								class="size-5"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="M12 18.75a6 6 0 0 0 6-6v-1.5m-6 7.5a6 6 0 0 1-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 0 1-3-3V4.5a3 3 0 1 1 6 0v8.25a3 3 0 0 1-3 3Z"
								/>
							</svg>
						{/if}
					</button>
				</Tooltip>

				<button
					class="p-3 rounded-lg bg-gray-50 dark:bg-gray-900"
					on:click={async () => {
						await stopAudioStream();
						await stopVideoStream();

						console.log(audioStream);
						console.log(cameraStream);

						showCallOverlay.set(false);
						dispatch('close');
					}}
					type="button"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="size-5"
					>
						<path
							d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z"
						/>
					</svg>
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	/* The call circle "vibrates" while the assistant is speaking — a clear
	   speaking indicator instead of the Thinking dots. :global() because the
	   class is applied via a dynamic {…} expression Svelte can't scope.
	   (Real audio-waveform reactivity is part of the later voice pass.) */
	:global(.call-speaking-pulse) {
		animation: call-speaking-pulse 0.62s ease-in-out infinite;
	}
	@keyframes call-speaking-pulse {
		0%,
		100% {
			transform: scale(1);
		}
		50% {
			transform: scale(1.06);
		}
	}
</style>
