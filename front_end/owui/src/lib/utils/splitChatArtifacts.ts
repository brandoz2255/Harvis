/** Lift fenced scripts/files out of chat prose so they render as cards under the answer. */

export type ChatArtifact = {
	lang: string;
	filename: string;
	code: string;
	open: boolean;
};

const KEEP_INLINE = new Set(['mermaid', 'vega', 'vega-lite', 'canvas']);

const LANG_FILE: Record<string, string> = {
	python: 'script.py',
	py: 'script.py',
	javascript: 'script.js',
	js: 'script.js',
	typescript: 'script.ts',
	ts: 'script.ts',
	tsx: 'component.tsx',
	jsx: 'component.jsx',
	html: 'index.html',
	css: 'styles.css',
	json: 'data.json',
	bash: 'script.sh',
	sh: 'script.sh',
	shell: 'script.sh',
	sql: 'query.sql',
	yaml: 'config.yaml',
	yml: 'config.yaml',
	md: 'notes.md',
	markdown: 'notes.md'
};

function takeDetails(s: string, start: number): number {
	const openTag = '<details';
	const closeTag = '</details>';
	let depth = 1;
	let idx = start + openTag.length;
	while (depth > 0 && idx < s.length) {
		if (s.startsWith(openTag, idx)) depth++;
		else if (s.startsWith(closeTag, idx)) depth--;
		if (depth > 0) idx++;
	}
	return depth === 0 ? idx + closeTag.length : s.length;
}

function parseInfo(info: string): { lang: string; filename: string } {
	const t = (info || '').trim();
	const titleM = t.match(/title=(?:"([^"]+)"|'([^']+)')/);
	if (titleM) {
		return { lang: t.split(/[\s:{]/)[0] || 'text', filename: titleM[1] || titleM[2] || '' };
	}
	const tagged = t.match(/^([\w.+-]+)[:\s]+(\S+\.\w[\w.-]*)$/);
	if (tagged) return { lang: tagged[1], filename: tagged[2] };
	const lang = t.split(/[\s{]/)[0] || '';
	return { lang, filename: '' };
}

function guessName(lang: string): string {
	const key = (lang || '').toLowerCase();
	return LANG_FILE[key] || (key ? `file.${key}` : 'artifact');
}

export function splitChatArtifacts(content: string): { prose: string; artifacts: ChatArtifact[] } {
	const s = content || '';
	const artifacts: ChatArtifact[] = [];
	let prose = '';
	let i = 0;
	while (i < s.length) {
		if (s.startsWith('<details', i)) {
			const end = takeDetails(s, i);
			prose += s.slice(i, end);
			i = end;
			continue;
		}
		if (s.startsWith('```', i) && (i === 0 || s[i - 1] === '\n')) {
			const afterTicks = i + 3;
			const nl = s.indexOf('\n', afterTicks);
			const infoLineEnd = nl === -1 ? s.length : nl;
			const info = s.slice(afterTicks, infoLineEnd);
			const { lang, filename } = parseInfo(info);
			const bodyStart = nl === -1 ? s.length : nl + 1;
			const close = s.indexOf('\n```', bodyStart);
			const open = close === -1;
			const bodyEnd = open ? s.length : close;
			const code = s.slice(bodyStart, bodyEnd).replace(/\n$/, '');
			const keep =
				KEEP_INLINE.has(lang.toLowerCase()) ||
				(!lang && code.split('\n').filter(Boolean).length < 4);
			if (keep) {
				const end = open ? s.length : close + 4;
				prose += s.slice(i, end);
				i = end;
				continue;
			}
			artifacts.push({
				lang: lang || 'text',
				filename: filename || guessName(lang),
				code,
				open
			});
			i = open ? s.length : close + 4;
			if (s[i] === '\n') i++;
			continue;
		}
		prose += s[i];
		i++;
	}
	return { prose: prose.replace(/\n{3,}/g, '\n\n').trimEnd(), artifacts };
}

type MetricQuality = 'confirmed' | 'measured' | 'estimated';

export type Metric = {
	value: number;
	quality: MetricQuality;
	/** 'provider' = the model/runtime reported it, 'harvis' = we timed it ourselves. */
	source: string;
	scope?: string;
};

function pick(m: any): Metric | null {
	if (!m || typeof m.value !== 'number' || !isFinite(m.value)) return null;
	return { value: m.value, quality: m.quality ?? 'confirmed', source: m.source ?? 'provider', scope: m.scope };
}

/** Prose length with tool cards removed — their markup is not generated prose. */
function proseLength(content: string): number {
	return content.replace(/<details[\s\S]*?<\/details>/gi, '').replace(/\s+/g, ' ').trim().length;
}

/**
 * Every number the message footer is allowed to show, with where each one came from.
 *
 * The contract, in one line: a metric exists only when somebody actually counted it.
 * Providers do not stream exact token counts — they send usage once, at the end — so
 * during a turn most of these are legitimately `null` and the UI renders an em dash.
 * The one number that is always live and always exact is elapsed time, because we hold
 * the clock ourselves.
 *
 * Two rules this replaces, both of which produced confident nonsense:
 *  - completion tokens were guessed from `content.length / 4`, counting tool-card markup
 *    as generated prose;
 *  - tokens/sec divided that guess by the WALL CLOCK, so writing a file, running it and
 *    waiting on a container all counted as generation time.
 */
export function messageTokenStats(message: {
	usage?: any;
	info?: any;
	harvisMetrics?: any;
	content?: string;
	done?: boolean;
	timestamp?: number;
	completedAt?: number;
	_now?: number;
}) {
	const u = message?.usage || {};
	const info = message?.info || {};
	const hm = message?.harvisMetrics || {};

	// ── Tokens ────────────────────────────────────────────────────────────────
	let context: Metric | null = pick(hm.context_tokens);
	if (!context) {
		const v = Number(u.prompt_tokens ?? info.prompt_tokens ?? u.prompt_eval_count ?? info.prompt_eval_count ?? 0);
		if (v > 0) context = { value: v, quality: 'confirmed', source: 'provider', scope: 'model_request' };
	}

	let output: Metric | null = pick(hm.output_tokens);
	if (!output) {
		const v = Number(u.completion_tokens ?? info.completion_tokens ?? u.eval_count ?? info.eval_count ?? 0);
		if (v > 0) output = { value: v, quality: 'confirmed', source: 'provider', scope: 'run' };
	}
	if (!output && !message?.done && message?.content) {
		// Nothing has been reported yet and the turn is still running. A rough count of
		// the prose so far is better than a frozen dash, but it is flagged as an estimate
		// and is never allowed to feed a rate.
		const chars = proseLength(String(message.content));
		if (chars > 0) output = { value: Math.round(chars / 4), quality: 'estimated', source: 'harvis', scope: 'run' };
	}

	const totalReported = Number(u.total_tokens ?? info.total_tokens ?? 0);
	let total: Metric | null = null;
	if (totalReported > 0) {
		total = { value: totalReported, quality: 'confirmed', source: 'provider' };
	} else if (context && output) {
		total = {
			value: context.value + output.value,
			quality: output.quality === 'estimated' ? 'estimated' : 'confirmed',
			source: 'derived'
		};
	} else if (output) {
		total = { ...output };
	}

	// Total billed input across an agentic run is a different, much larger number than
	// the context of any one call — Claude Code makes several model calls per chat turn.
	const billedInput: Metric | null = pick(hm.billed_input_tokens);
	const modelCalls: Metric | null = pick(hm.model_calls);
	const cost: Metric | null = pick(hm.cost_usd);

	// ── Time ──────────────────────────────────────────────────────────────────
	const ts = Number(message?.timestamp || 0);
	const started = ts > 1e12 ? ts : ts * 1000;
	const now = message?._now ?? Date.now();
	const wall = pick(hm.wall_ms);
	const totalNs = Number(info.total_duration ?? u.total_duration ?? 0);
	// A finished turn reports how long it took. It must never be re-derived from the
	// current clock, or reopening yesterday's chat claims the answer took 14 hours.
	let elapsedS: number | null = null;
	if (message?.done) {
		if (wall) elapsedS = wall.value / 1000;
		else if (totalNs > 1e6) elapsedS = totalNs / 1e9;
		else if (message.completedAt && started > 0)
			elapsedS = Math.max(0, (Number(message.completedAt) - started) / 1000);
	} else if (started > 0) {
		elapsedS = Math.max(0, (now - started) / 1000);
	}

	// Generation time only. Ollama reports it natively in nanoseconds; the Claude lane
	// reports the CLI's API time; otherwise the backend measures first token → last token.
	let generationS: number | null = null;
	const gen = pick(hm.generation_ms);
	const evalNs = Number(info.eval_duration ?? u.eval_duration ?? 0);
	if (gen) generationS = gen.value / 1000;
	else if (evalNs > 1e6) generationS = evalNs / 1e9;

	let tokPerSec: Metric | null = pick(hm.tokens_per_sec);
	if (!tokPerSec && output && output.quality !== 'estimated' && generationS && generationS > 0.15) {
		tokPerSec = {
			value: output.value / generationS,
			quality: 'confirmed',
			source: 'derived',
			scope: 'model_generation'
		};
	}

	return { context, output, total, billedInput, modelCalls, cost, elapsedS, generationS, tokPerSec };
}

export function formatElapsed(seconds: number): string {
	const s = Math.max(0, Math.round(seconds));
	if (s < 60) return `${s}s`;
	const m = Math.floor(s / 60);
	const r = s % 60;
	if (m < 60) return r ? `${m}m ${r}s` : `${m}m`;
	const h = Math.floor(m / 60);
	return `${h}h ${m % 60}m`;
}
