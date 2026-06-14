// Curated open-source benchmark snapshot — the "theoretical" lane of Analytics.
//
// ⚠ These are MANUALLY-CURATED published figures, NOT fetched live (the K8s
// cluster blocks outbound DNS, and a snapshot keeps the offline/self-hosted
// ethos). Numbers MUST be real published results — never invent them. Add or
// verify entries as new models land (or via a future web-search task). Models
// without an entry simply render "—" in Analytics; the measured/real lane still
// works for every model regardless.
//
// Keyed by model FAMILY. benchKeyForModel() maps an Ollama tag (org/name:tag) →
// a family key.

export interface BenchScores {
	mmlu?: number; // general knowledge (5-shot, %)
	gpqa?: number; // graduate-level reasoning (%)
	humaneval?: number; // code generation pass@1 (%)
	gsm8k?: number; // grade-school math (%)
	math?: number; // competition math (%)
	ifeval?: number; // instruction following (%)
	source?: string; // provenance of the numbers
}

// Higher-is-better benchmark columns, in display order.
export const BENCH_COLS: { key: keyof BenchScores; label: string; title: string }[] = [
	{ key: 'mmlu', label: 'MMLU', title: 'General knowledge (5-shot)' },
	{ key: 'gpqa', label: 'GPQA', title: 'Graduate-level reasoning' },
	{ key: 'humaneval', label: 'HumanEval', title: 'Code generation (pass@1)' },
	{ key: 'gsm8k', label: 'GSM8K', title: 'Grade-school math' },
	{ key: 'math', label: 'MATH', title: 'Competition math' },
	{ key: 'ifeval', label: 'IFEval', title: 'Instruction following' }
];

// ── Curated snapshot. Intentionally minimal — only verifiable public figures.
// Everything else is left for manual/web-sourced population. ──
export const BENCHMARKS: Record<string, BenchScores> = {
	// Meta Llama 3.1 8B Instruct — from Meta's published model card.
	llama3_1: {
		mmlu: 69.4,
		humaneval: 72.6,
		gsm8k: 84.5,
		ifeval: 80.4,
		source: 'Meta Llama 3.1 model card (8B Instruct)'
	}
	// Add more verified families here, e.g. qwen3, gemma4, hermes3, granite4, …
};

// Family detection — order matters (more specific tags first so e.g. qwen3.5
// isn't swallowed by qwen3). Returns a key used for both the BENCHMARKS lookup
// and as a stable family label.
const FAMILY_PATTERNS: { key: string; benchKey: string; test: (s: string) => boolean }[] = [
	{ key: 'llama3.1', benchKey: 'llama3_1', test: (s) => s.includes('llama3.1') || s.includes('llama-3.1') },
	{ key: 'qwen3.6', benchKey: 'qwen3_6', test: (s) => s.includes('qwen3.6') },
	{ key: 'qwen3.5', benchKey: 'qwen3_5', test: (s) => s.includes('qwen3.5') },
	{ key: 'qwen3', benchKey: 'qwen3', test: (s) => s.includes('qwen3') },
	{ key: 'gemma4', benchKey: 'gemma4', test: (s) => s.includes('gemma4') || s.includes('gemma-4') },
	{ key: 'hermes4', benchKey: 'hermes4', test: (s) => s.includes('hermes-4') || s.includes('hermes4') },
	{ key: 'hermes3', benchKey: 'hermes3', test: (s) => s.includes('hermes-3') || s.includes('hermes3') },
	{ key: 'granite4', benchKey: 'granite4', test: (s) => s.includes('granite4') || s.includes('granite-4') },
	{ key: 'gpt-oss', benchKey: 'gpt_oss', test: (s) => s.includes('gpt-oss') },
	{ key: 'kimi-k2', benchKey: 'kimi_k2', test: (s) => s.includes('kimi') }
];

// Map a model id/tag (e.g. "batiai/qwen3.5-9b:latest", "gemma4:e4b") → family key.
export function benchKeyForModel(modelId: string): string | null {
	const s = (modelId || '').toLowerCase();
	for (const f of FAMILY_PATTERNS) if (f.test(s)) return f.key;
	return null;
}

// The published benchmark scores for a model, or null if the family is unknown
// or not yet curated.
export function benchScoresForModel(modelId: string): BenchScores | null {
	const s = (modelId || '').toLowerCase();
	for (const f of FAMILY_PATTERNS) {
		if (f.test(s)) return BENCHMARKS[f.benchKey] ?? null;
	}
	return null;
}
