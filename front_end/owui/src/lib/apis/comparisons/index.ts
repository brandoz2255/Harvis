// Agent Studio model-comparison persistence + analytics (Harvis facade).
// Backend: python_back_end/owui_compat/router.py → /api/owui/comparisons*.
// One row per (run_id, slot); the Analytics surface reads runs + per-model stats.

const BASE = '/api/owui/comparisons';
const headers = () => ({
	Authorization: `Bearer ${localStorage.token}`,
	'Content-Type': 'application/json'
});

export interface CmpResult {
	slot: number;
	model_id: string;
	status: string;
	ttft_ms: number | null;
	total_ms: number | null;
	tokens: number | null;
	tokens_estimated: boolean;
	tok_per_sec: number | null;
	chars: number;
	answer?: string;
}

export interface CmpStat {
	model_id: string;
	runs: number;
	avg_tok_per_sec: number | null;
	avg_total_ms: number | null;
	avg_ttft_ms: number | null;
	avg_judge_score: number | null;
	judged_runs: number;
}

export interface CmpRow {
	run_id: string;
	slot: number;
	prompt: string;
	model_id: string;
	status: string;
	ttft_ms: number | null;
	total_ms: number | null;
	tokens: number | null;
	tokens_estimated: boolean;
	tok_per_sec: number | null;
	chars: number;
	judge_score: number | null;
	judge_model: string | null;
	created_at: number;
}

export const saveComparison = async (run_id: string, prompt: string, results: CmpResult[]) => {
	try {
		const res = await fetch(BASE, {
			method: 'POST',
			headers: headers(),
			credentials: 'include',
			body: JSON.stringify({ run_id, prompt, results })
		});
		return res.ok ? await res.json() : null;
	} catch (_) {
		return null;
	}
};

export const judgeComparison = async (
	run_id: string,
	judge_model: string,
	scores: Record<string, number>
) => {
	try {
		const res = await fetch(`${BASE}/judge`, {
			method: 'POST',
			headers: headers(),
			credentials: 'include',
			body: JSON.stringify({ run_id, judge_model, scores })
		});
		return res.ok ? await res.json() : null;
	} catch (_) {
		return null;
	}
};

export const getComparisons = async (): Promise<{ runs: CmpRow[]; stats: CmpStat[] }> => {
	try {
		const res = await fetch(BASE, { headers: headers(), credentials: 'include' });
		return res.ok ? await res.json() : { runs: [], stats: [] };
	} catch (_) {
		return { runs: [], stats: [] };
	}
};
