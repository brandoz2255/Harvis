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

// The two lenses over the one cron store: Routines (coding) and Schedules (chat).
export type CronContext = 'coding' | 'chat';

export const listCronJobs = async (context?: CronContext): Promise<CronJob[]> => {
	try {
		const url = context ? `${BASE}?context=${encodeURIComponent(context)}` : BASE;
		const r = await fetch(url, { headers: authHeaders(), credentials: 'include' });
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

export interface AutomationRun {
	id: string;
	task_brief: string | null;
	status: string;
	started_at: string | null;
	summary: string | null;
}

export interface AutomationStats {
	successful_7d: number;
	failed_7d: number;
	recent: AutomationRun[];
}

// Real run outcomes (Successful/Failed 7d + recent runs) aggregated from the
// workspace_runs the cron tick launched. Backend: GET /api/cron/stats.
export const getCronStats = async (): Promise<AutomationStats> => {
	try {
		const r = await fetch(`${BASE}/stats`, { headers: authHeaders(), credentials: 'include' });
		return r.ok ? await r.json() : { successful_7d: 0, failed_7d: 0, recent: [] };
	} catch (_) {
		return { successful_7d: 0, failed_7d: 0, recent: [] };
	}
};

// Human-readable schedule summary, e.g. "Every 30m", "Daily at 09:00", "Once".
const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const hhmm = (h: number, m: number) =>
	`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;

export const scheduleSummary = (j: Pick<CronJob, 'schedule_type' | 'schedule_expr'>): string => {
	if (j.schedule_type === 'interval') return `Every ${j.schedule_expr}`;
	if (j.schedule_type === 'once') return 'Once';
	// cron — friendly parse of the shapes the basic picker generates
	// ("M H * * *" daily, "M H * * D" weekly); anything else shows raw.
	// The stored cron is UTC (the picker converts local→UTC on save), so convert
	// back to the viewer's LOCAL time here — "Daily at 9:00" means the user's 9:00.
	const daily = j.schedule_expr.match(/^\s*(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+\*\s*$/);
	if (daily) {
		const d = new Date();
		d.setUTCHours(Number(daily[2]), Number(daily[1]), 0, 0);
		return `Daily at ${hhmm(d.getHours(), d.getMinutes())}`;
	}
	const weekly = j.schedule_expr.match(/^\s*(\d{1,2})\s+(\d{1,2})\s+\*\s+\*\s+([0-6])\s*$/);
	if (weekly) {
		const d = new Date();
		d.setUTCHours(Number(weekly[2]), Number(weekly[1]), 0, 0);
		// anchor to the stored UTC weekday, then read the local weekday (may differ
		// from the UTC one when the local time crosses midnight)
		d.setUTCDate(d.getUTCDate() + (((Number(weekly[3]) - d.getUTCDay()) + 7) % 7));
		return `Weekly on ${DAY_NAMES[d.getDay()]} at ${hhmm(d.getHours(), d.getMinutes())}`;
	}
	return j.schedule_expr;
};
