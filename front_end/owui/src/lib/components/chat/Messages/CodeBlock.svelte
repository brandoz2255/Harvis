<script lang="ts">
	import hljs from 'highlight.js';
	import { toast } from 'svelte-sonner';
	import { getContext, onMount, tick, onDestroy } from 'svelte';
	import { get } from 'svelte/store';
	import {
		artifactCode,
		artifactContents,
		config,
		pyodideWorker as pyodideWorkerStore,
		showArtifacts,
		showControls
	} from '$lib/stores';

	import PyodideWorker from '$lib/workers/pyodide.worker?worker';
	import { executeCode } from '$lib/apis/utils';
	import {
		copyToClipboard,
		initMermaid,
		renderMermaidDiagram,
		renderVegaVisualization,
		unescapeHtml
	} from '$lib/utils';

	import 'highlight.js/styles/github-dark.min.css';
	import equal from 'fast-deep-equal';

	import CodeEditor from '$lib/components/common/CodeEditor.svelte';
	import SvgPanZoom from '$lib/components/common/SVGPanZoom.svelte';
	import CanvasRenderer from '$lib/components/chat/Canvas/CanvasRenderer.svelte';

	import ChevronUp from '$lib/components/icons/ChevronUp.svelte';
	import ChevronUpDown from '$lib/components/icons/ChevronUpDown.svelte';
	import CommandLine from '$lib/components/icons/CommandLine.svelte';
	import Cube from '$lib/components/icons/Cube.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';

	const i18n = getContext('i18n');

	export let id = '';
	export let edit = true;

	export let onSave = (e) => {};
	export let onUpdate = (e) => {};
	export let onPreview = (e) => {};

	export let save = false;
	export let run = true;
	export let preview = false;
	export let collapsed = false;

	export let token = null;
	export let lang = '';
	export let code = '';
	export let attributes = {};
	export let done = true;
	export let filename = '';
// The artifact panel supplies its own chrome and wants the block flush against the
// pane edge, so it borrows this block's body without a second header or a card border.
export let header = true;
export let flush = false;

	export let className = '';
	export let editorClassName = '';

	let localPyodideWorker = null;

	let _code = '';
	$: if (code) {
		updateCode();
	}

	const updateCode = () => {
		_code = code;
	};

	let _token = null;

	let renderHTML = null;
	let renderError = null;

	let highlightedCode = null;
	let executing = false;

	let stdout = null;
	let stderr = null;
	let result = null;
	let files = null;

	let copied = false;
	let saved = false;

	const collapseCodeBlock = () => {
		collapsed = !collapsed;
	};

	const saveCode = () => {
		saved = true;

		code = _code;
		onSave(code);

		setTimeout(() => {
			saved = false;
		}, 1000);
	};

	const copyCode = async () => {
		copied = true;
		await copyToClipboard(_code);

		setTimeout(() => {
			copied = false;
		}, 1000);
	};

	const previewCode = () => {
		onPreview(code);
	};

	const checkPythonCode = (str) => {
		// Check if the string contains typical Python syntax characters
		const pythonSyntax = [
			'def ',
			'else:',
			'elif ',
			'try:',
			'except:',
			'finally:',
			'yield ',
			'lambda ',
			'assert ',
			'nonlocal ',
			'del ',
			'True',
			'False',
			'None',
			' and ',
			' or ',
			' not ',
			' in ',
			' is ',
			' with '
		];

		for (let syntax of pythonSyntax) {
			if (str.includes(syntax)) {
				return true;
			}
		}

		// If none of the above conditions met, it's probably not Python code
		return false;
	};

	const executePython = async (code) => {
		result = null;
		stdout = null;
		stderr = null;

		executing = true;

		if ($config?.code?.engine === 'jupyter') {
			const output = await executeCode(localStorage.token, code).catch((error) => {
				toast.error(`${error}`);
				return null;
			});

			if (output) {
				if (output['stdout']) {
					stdout = output['stdout'];
					const stdoutLines = stdout.split('\n');

					for (const [idx, line] of stdoutLines.entries()) {
						if (line.startsWith('data:image/png;base64')) {
							if (files) {
								files.push({
									type: 'image/png',
									data: line
								});
							} else {
								files = [
									{
										type: 'image/png',
										data: line
									}
								];
							}

							if (stdout.includes(`${line}\n`)) {
								stdout = stdout.replace(`${line}\n`, ``);
							} else if (stdout.includes(`${line}`)) {
								stdout = stdout.replace(`${line}`, ``);
							}
						}
					}
				}

				if (output['result']) {
					result = output['result'];
					const resultLines = result.split('\n');

					for (const [idx, line] of resultLines.entries()) {
						if (line.startsWith('data:image/png;base64')) {
							if (files) {
								files.push({
									type: 'image/png',
									data: line
								});
							} else {
								files = [
									{
										type: 'image/png',
										data: line
									}
								];
							}

							if (result.includes(`${line}\n`)) {
								result = result.replace(`${line}\n`, ``);
							} else if (result.includes(`${line}`)) {
								result = result.replace(`${line}`, ``);
							}
						}
					}
				}

				output['stderr'] && (stderr = output['stderr']);
			}

			executing = false;
		} else {
			executePythonAsWorker(code);
		}
	};

	const executePythonAsWorker = async (code) => {
		let packages = [
			/\bimport\s+requests\b|\bfrom\s+requests\b/.test(code) ? 'requests' : null,
			/\bimport\s+bs4\b|\bfrom\s+bs4\b/.test(code) ? 'beautifulsoup4' : null,
			/\bimport\s+numpy\b|\bfrom\s+numpy\b/.test(code) ? 'numpy' : null,
			/\bimport\s+pandas\b|\bfrom\s+pandas\b/.test(code) ? 'pandas' : null,
			/\bimport\s+matplotlib\b|\bfrom\s+matplotlib\b/.test(code) ? 'matplotlib' : null,
			/\bimport\s+seaborn\b|\bfrom\s+seaborn\b/.test(code) ? 'seaborn' : null,
			/\bimport\s+sklearn\b|\bfrom\s+sklearn\b/.test(code) ? 'scikit-learn' : null,
			/\bimport\s+scipy\b|\bfrom\s+scipy\b/.test(code) ? 'scipy' : null,
			/\bimport\s+re\b|\bfrom\s+re\b/.test(code) ? 'regex' : null,
			/\bimport\s+seaborn\b|\bfrom\s+seaborn\b/.test(code) ? 'seaborn' : null,
			/\bimport\s+sympy\b|\bfrom\s+sympy\b/.test(code) ? 'sympy' : null,
			/\bimport\s+tiktoken\b|\bfrom\s+tiktoken\b/.test(code) ? 'tiktoken' : null,
			/\bimport\s+pytz\b|\bfrom\s+pytz\b/.test(code) ? 'pytz' : null
		].filter(Boolean);

		console.log(packages);

		// Reuse the shared Pyodide worker when code interpreter is active,
		// so files written here are immediately visible in PyodideFileNav.
		// Otherwise fall back to a throwaway worker.
		const sharedWorker = $pyodideWorkerStore;
		const isShared = !!sharedWorker;
		const worker = sharedWorker ?? new PyodideWorker();

		if (!isShared) {
			localPyodideWorker = worker;
		}

		worker.postMessage({
			id: id,
			code: code,
			packages: packages
		});

		const timeoutId = setTimeout(() => {
			if (executing) {
				executing = false;
				stderr = 'Execution Time Limit Exceeded';
				if (!isShared) {
					worker.terminate();
					localPyodideWorker = null;
				}
			}
		}, 60000);

		const handler = (event) => {
			// Ignore messages from other requests on the shared worker
			if (event.data?.id !== id) return;

			console.log('pyodideWorker.onmessage', event);
			const { id: _id, ...data } = event.data;

			console.log(_id, data);

			if (data['stdout']) {
				stdout = data['stdout'];
				const stdoutLines = stdout.split('\n');

				for (const [idx, line] of stdoutLines.entries()) {
					if (line.startsWith('data:image/png;base64')) {
						if (files) {
							files.push({
								type: 'image/png',
								data: line
							});
						} else {
							files = [
								{
									type: 'image/png',
									data: line
								}
							];
						}

						if (stdout.includes(`${line}\n`)) {
							stdout = stdout.replace(`${line}\n`, ``);
						} else if (stdout.includes(`${line}`)) {
							stdout = stdout.replace(`${line}`, ``);
						}
					}
				}
			}

			if (data['result']) {
				result = data['result'];
				const resultLines = result.split('\n');

				for (const [idx, line] of resultLines.entries()) {
					if (line.startsWith('data:image/png;base64')) {
						if (files) {
							files.push({
								type: 'image/png',
								data: line
							});
						} else {
							files = [
								{
									type: 'image/png',
									data: line
								}
							];
						}

						if (result.startsWith(`${line}\n`)) {
							result = result.replace(`${line}\n`, ``);
						} else if (result.startsWith(`${line}`)) {
							result = result.replace(`${line}`, ``);
						}
					}
				}
			}

			data['stderr'] && (stderr = data['stderr']);
			data['result'] && (result = data['result']);

			clearTimeout(timeoutId);
			worker.removeEventListener('message', handler);
			executing = false;

			// Signal PyodideFileNav to auto-refresh after execution
			window.dispatchEvent(new Event('pyodide:files'));
		};

		worker.addEventListener('message', handler);

		worker.onerror = (event) => {
			console.log('pyodideWorker.onerror', event);
			clearTimeout(timeoutId);
			worker.removeEventListener('message', handler);
			executing = false;
		};
	};

	const executeJavaScript = async (src) => {
		result = null;
		stdout = null;
		stderr = null;
		files = null;
		executing = true;

		const blob = new Blob(
			[
				`
self.console = {
  log: (...a) => self.postMessage({ type: 'stdout', data: a.map(String).join(' ') }),
  info: (...a) => self.postMessage({ type: 'stdout', data: a.map(String).join(' ') }),
  warn: (...a) => self.postMessage({ type: 'stderr', data: a.map(String).join(' ') }),
  error: (...a) => self.postMessage({ type: 'stderr', data: a.map(String).join(' ') })
};
try {
  const result = (0, eval)(${JSON.stringify(src)});
  if (result !== undefined) {
    self.postMessage({ type: 'result', data: typeof result === 'string' ? result : JSON.stringify(result) });
  }
} catch (e) {
  self.postMessage({ type: 'stderr', data: String(e && e.stack ? e.stack : e) });
}
self.postMessage({ type: 'done' });
`
			],
			{ type: 'text/javascript' }
		);
		const url = URL.createObjectURL(blob);
		const worker = new Worker(url);
		const timeoutId = setTimeout(() => {
			worker.terminate();
			URL.revokeObjectURL(url);
			if (executing) {
				executing = false;
				stderr = 'Execution Time Limit Exceeded';
			}
		}, 15000);
		worker.onmessage = (event) => {
			const msg = event.data || {};
			if (msg.type === 'stdout') stdout = (stdout ? stdout + '\n' : '') + (msg.data || '');
			if (msg.type === 'stderr') stderr = (stderr ? stderr + '\n' : '') + (msg.data || '');
			if (msg.type === 'result') result = msg.data;
			if (msg.type === 'done') {
				clearTimeout(timeoutId);
				worker.terminate();
				URL.revokeObjectURL(url);
				executing = false;
			}
		};
		worker.onerror = (event) => {
			stderr = event.message || 'JavaScript worker failed';
			clearTimeout(timeoutId);
			worker.terminate();
			URL.revokeObjectURL(url);
			executing = false;
		};
	};

	const isPythonLang = () =>
		lang.toLowerCase() === 'python' ||
		lang.toLowerCase() === 'py' ||
		(lang === '' && checkPythonCode(code));

	const isJsLang = () => ['javascript', 'js', 'nodejs'].includes(lang.toLowerCase());

	let mermaid = null;
	const renderMermaid = async (code) => {
		if (!mermaid) {
			mermaid = await initMermaid();
		}
		return await renderMermaidDiagram(mermaid, code);
	};

	// Typed ```canvas panel — rendered inline once the block finished streaming
	// (same closing-fence check as mermaid/vega). While streaming, the raw JSON
	// shows through the normal code path below.
	$: canvasReady = lang === 'canvas' && (!token || (token?.raw ?? '').slice(-4).includes('```'));

	// "Open in panel ⤢" — push this canvas to the right-side Artifacts rail
	// (Chat.svelte's getContents also auto-adds it there; dedupe by content).
	const openCanvasInPanel = () => {
		const entries = get(artifactContents) ?? [];
		if (!entries.some((e) => e?.type === 'canvas' && e?.content === code)) {
			artifactContents.set([...entries, { type: 'canvas', content: code }]);
		}
		artifactCode.set(code);
		showControls.set(true);
		showArtifacts.set(true);
	};

	const render = async () => {
		onUpdate(token);
		if (lang === 'mermaid' && (token?.raw ?? '').slice(-4).includes('```')) {
			try {
				renderHTML = await renderMermaid(code);
			} catch (error) {
				console.error('Failed to render mermaid diagram:', error);
				const errorMsg = error instanceof Error ? error.message : String(error);
				renderError = $i18n.t('Failed to render diagram') + `: ${errorMsg}`;
				renderHTML = null;
			}
		} else if (
			(lang === 'vega' || lang === 'vega-lite') &&
			(token?.raw ?? '').slice(-4).includes('```')
		) {
			try {
				renderHTML = await renderVegaVisualization(code);
			} catch (error) {
				console.error('Failed to render Vega visualization:', error);
				const errorMsg = error instanceof Error ? error.message : String(error);
				renderError = $i18n.t('Failed to render visualization') + `: ${errorMsg}`;
				renderHTML = null;
			}
		}
	};

	$: if (token) {
		if (token.text !== _token?.text || token.raw !== _token?.raw) {
			_token = token;
		} else if (!equal(token, _token)) {
			_token = token;
		}
	}

	$: if (_token) {
		render();
	}

	$: if (attributes) {
		onAttributesUpdate();
	}

	const onAttributesUpdate = () => {
		if (attributes?.output) {
			try {
				const output = JSON.parse(unescapeHtml(attributes.output));
				stdout = output.stdout;
				stderr = output.stderr;
				result = output.result;
			} catch (error) {
				console.error('Error:', error);
			}
		}
	};

	onMount(async () => {
		if (token) {
			onUpdate(token);
		}
	});

	onDestroy(() => {
		if (localPyodideWorker) {
			localPyodideWorker.terminate();
			localPyodideWorker = null;
		}
	});
</script>

<div>
	<div
		class="relative {className} flex flex-col {flush
			? ''
			: 'rounded-lg border border-gray-200/80 dark:border-white/10 my-1'} overflow-hidden lms-codeblock"
		dir="ltr"
	>
		{#if canvasReady}
			<CanvasRenderer spec={code} mode="inline" onOpen={openCanvasInPanel} />
		{:else if ['mermaid', 'vega', 'vega-lite'].includes(lang)}
			{#if renderHTML}
				<SvgPanZoom
					className=" rounded-2xl max-h-fit overflow-hidden"
					svg={renderHTML}
					content={_token.text}
				/>
			{:else}
				<div class="p-3">
					{#if renderError}
						<div
							class="flex gap-2.5 border px-4 py-3 border-red-600/10 bg-red-600/10 rounded-2xl mb-2"
						>
							{renderError}
						</div>
					{/if}
					<pre>{code}</pre>
				</div>
			{/if}
		{:else}
			{#if header}
			<div
				class="py-1 px-3 gap-2 flex items-center justify-end w-full z-10 text-[11px] tracking-wide text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-[#1a1a1a] border-b border-gray-200/80 dark:border-white/10"
			>
				<div class="flex-1 truncate font-mono {filename ? 'normal-case' : 'uppercase'}">
					<Tooltip content={lang} placement="top-start">
						<span class="truncate text-ellipsis">
							{filename || lang || 'code'}
						</span>
					</Tooltip>
				</div>

				<div class="flex items-center gap-0.5 shrink-0">
					<!-- The Collapse control is gone by request. The Expand half stays, but only
					     when something already collapsed the block — the `collapseCodeBlocks`
					     setting does that on load, and without this there'd be no way back out. -->
					{#if collapsed}
						<button
							class="flex gap-1 items-center bg-none border-none transition rounded px-1.5 py-0.5 hover:text-gray-800 dark:hover:text-gray-100"
							on:click={collapseCodeBlock}
						>
							<div class=" -translate-y-[0.5px]">
								<ChevronUpDown className="size-3" />
							</div>

							<div>
								{$i18n.t('Expand')}
							</div>
						</button>
					{/if}

					{#if ($config?.features?.enable_code_execution ?? true) && (isPythonLang() || isJsLang())}
						{#if executing}
							<div class="run-code-button bg-none border-none p-0.5 cursor-not-allowed">
								{$i18n.t('Running')}
							</div>
						{:else if run}
							<button
								class="flex gap-1 items-center run-code-button bg-none border-none transition rounded px-1.5 py-0.5 hover:text-gray-800 dark:hover:text-gray-100"
								on:click={async () => {
									code = _code;
									await tick();
									if (isJsLang()) await executeJavaScript(code);
									else await executePython(code);
								}}
							>
								<div>
									{$i18n.t('Run')}
								</div>
							</button>
						{/if}
					{/if}

					{#if save}
						<button
							class="save-code-button bg-none border-none transition rounded px-1.5 py-0.5 hover:text-gray-800 dark:hover:text-gray-100"
							on:click={saveCode}
						>
							{saved ? $i18n.t('Saved') : $i18n.t('Save')}
						</button>
					{/if}

					<button
						class="copy-code-button bg-none border-none transition rounded px-1.5 py-0.5 hover:text-gray-800 dark:hover:text-gray-100"
						on:click={copyCode}>{copied ? $i18n.t('Copied') : $i18n.t('Copy')}</button
					>

					{#if preview && ['html', 'svg'].includes(lang)}
						<button
							class="flex gap-1 items-center run-code-button bg-none border-none transition rounded px-1.5 py-0.5 hover:text-gray-800 dark:hover:text-gray-100"
							on:click={previewCode}
						>
							<div>
								{$i18n.t('Preview')}
							</div>
						</button>
					{/if}
				</div>
			</div>
			{/if}

			<div
				class="language-{lang} {editorClassName
					? editorClassName
					: ''} overflow-hidden bg-gray-50 dark:bg-[#1e1e1e]"
			>
				{#if !collapsed}
					{#if edit}
						<CodeEditor
							value={code}
							{id}
							{lang}
							onSave={() => {
								saveCode();
							}}
							onChange={(value) => {
								_code = value;
							}}
						/>
					{:else}
						<pre
							class="hljs lms-code-pre p-3.5 px-4 overflow-x-auto mb-0"
							style="border-radius: 0; background: transparent;"><code
								class="language-{lang} rounded-none whitespace-pre text-[13px] leading-6"
								>{@html hljs.highlightAuto(code, hljs.getLanguage(lang)?.aliases).value ||
									code}</code
							>{#if !done}<span class="lms-caret" aria-hidden="true"></span>{/if}</pre>
					{/if}
				{:else}
					<div
						class="bg-gray-50 dark:bg-[#1e1e1e] dark:text-white pt-1 pb-2 px-4 flex flex-col gap-2 text-xs"
					>
						<span class="text-gray-500 italic">
							{$i18n.t('{{COUNT}} hidden lines', {
								COUNT: code.split('\n').length
							})}
						</span>
					</div>
				{/if}
			</div>

			{#if !collapsed}
				<div
					id="plt-canvas-{id}"
					class="bg-gray-50 dark:bg-black dark:text-white max-w-full overflow-x-auto scrollbar-hidden"
				/>

				{#if executing || stdout || stderr || result || files}
					<div
						class="bg-gray-50 dark:bg-[#161616] dark:text-white border-t border-gray-200/80 dark:border-white/10 pt-2 pb-3 px-3.5 flex flex-col gap-2"
					>
						{#if executing}
							<div class=" ">
								<div class=" text-gray-500 text-xs mb-1">{$i18n.t('STDOUT/STDERR')}</div>
								<div class="text-sm">{$i18n.t('Running...')}</div>
							</div>
						{:else}
							{#if stdout || stderr}
								<div class=" ">
									<div class=" text-gray-500 text-xs mb-1">{$i18n.t('STDOUT/STDERR')}</div>
									<div
										class="text-sm font-mono whitespace-pre-wrap {stdout?.split('\n')?.length > 100
											? `max-h-96`
											: ''}  overflow-y-auto"
									>
										{stdout || stderr}
									</div>
								</div>
							{/if}
							{#if result || files}
								<div class=" ">
									<div class=" text-gray-500 text-xs mb-1">{$i18n.t('RESULT')}</div>
									{#if result}
										<div class="text-sm">{`${JSON.stringify(result)}`}</div>
									{/if}
									{#if files}
										<div class="flex flex-col gap-2">
											{#each files as file}
												{#if file.type.startsWith('image')}
													<img src={file.data} alt="Output" class=" w-full max-w-[36rem]" />
												{/if}
											{/each}
										</div>
									{/if}
								</div>
							{/if}
						{/if}
					</div>
				{/if}
			{/if}
		{/if}
	</div>
</div>
