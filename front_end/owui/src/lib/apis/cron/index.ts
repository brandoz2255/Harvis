// Automations = per-user cron jobs that launch agent runs on a schedule.
// Backend: plugins/cron/routes.py → /api/cron (CRUD). A job's `prompt` is the
// task; `metadata.agent_id="orchestrated"` makes it a multi-agent run.

const BASE = '/api/cron';
const authHeaders = () => ({ Authorization: `Bearer ${localStorage.token}` });

export type ScheduleType = 'cron' | 'interval' | 'once';
export type JobStatus = 'scheduled' | 'running' | 'paused' | 'completed' | 'error';

export interface CronJob {
	id: string;
	name: string;
	schedule_type: ScheduleType;
	schedule_expr: string;
	prompt: string;
	delivery: string | null;
	status: JobStatus;
	next_run_at: string | null;
	last_run_at: string | null;
	run_count: number;
	error_message: string | null;
	metadata: Record<string, unknown>;
}

export const listCronJobs = async (): Promise<CronJob[]> => {
	try {
		const r = await fetch(BASE, { headers: authHeaders(), credentials: 'include' });
		return r.ok ? ((await r.json()).jobs ?? []) : [];
	} catch (_) {
		return [];
	}
};

export interface CreateCronJobInput {
	name: string;
	schedule_type: ScheduleType;
	schedule_expr: string;
	prompt: string;
	delivery?: string | null;
	metadata?: Record<string, unknown>;
}

export const createCronJob = async (
	input: CreateCronJobInput
): Promise<{ ok: boolean; job?: CronJob; error?: string }> => {
	try {
		const r = await fetch(BASE, {
			method: 'POST',
			headers: { ...authHeaders(), 'Content-Type': 'application/json' },
			credentials: 'include',
			body: JSON.stringify({ delivery: 'internal', metadata: {}, ...input })
		});
		if (!r.ok) return { ok: false, error: `HTTP ${r.status}` };
		const data = await r.json();
		return { ok: true, job: data.job };
	} catch (e: any) {
		return { ok: false, error: String(e?.message ?? e) };
	}
};

// status is a query param on the backend (PUT /{id}/status?status=paused).
export const setCronJobStatus = async (id: string, status: JobStatus): Promise<boolean> => {
	try {
		const r = await fetch(`${BASE}/${id}/status?status=${encodeURIComponent(status)}`, {
			method: 'PUT',
			headers: authHeaders(),
			credentials: 'include'
		});
		return r.ok;
	} catch (_) {
		return false;
	}
};

export const deleteCronJob = async (id: string): Promise<boolean> => {
	try {
		const r = await fetch(`${BASE}/${id}`, {
			method: 'DELETE',
			headers: authHeaders(),
			credentials: 'include'
		});
		return r.ok;
	} catch (_) {
		return false;
	}
};

// Human-readable schedule summary, e.g. "Every 30m", "Daily 9:00", "Once".
export const scheduleSummary = (j: Pick<CronJob, 'schedule_type' | 'schedule_expr'>): string => {
	if (j.schedule_type === 'interval') return `Every ${j.schedule_expr}`;
	if (j.schedule_type === 'once') return 'Once';
	// cron — show the raw expression (a friendlier parse can come later).
	return j.schedule_expr;
};
