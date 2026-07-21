// Shared formatting helpers for workspace/agent RUN objects — one source of truth for
// the Background-task cards, RunTable, and the vibecode page (dedupes the old `dot()` copies).

// Status → Tailwind dot classes (unified cockpit palette):
//   running = blue-500 (pulse) · done/passed = emerald-500 · failed = red-500 ·
//   waiting/approval = amber-500 (amber means "needs YOU") · cancelled = gray (inert;
//   deliberately NOT amber so it can't be misread as awaiting-approval) ·
//   idle/unknown = gray-400/gray-600.
export const statusDot = (s?: string): string =>
	s === 'done'
		? 'bg-emerald-500'
		: s === 'error'
			? 'bg-red-500'
			: s === 'cancelled'
				? 'bg-gray-400 dark:bg-gray-600'
				: s === 'running'
					? 'bg-blue-500 animate-pulse'
					: s === 'waiting' || s === 'pending_approval'
						? 'bg-amber-500'
						: 'bg-gray-400 dark:bg-gray-600';

// Status → human label (English; $i18n.t passes these through unchanged).
export const statusLabel = (s?: string): string =>
	s === 'done'
		? 'Completed'
		: s === 'error'
			? 'Failed'
			: s === 'cancelled'
				? 'Cancelled'
				: s === 'running'
					? 'Running'
					: s === 'waiting' || s === 'pending_approval'
						? 'Waiting'
						: 'Pending';

// A glyph for finished rows (✓ / × / □) per the spec's status-dot behavior.
export const statusGlyph = (s?: string): string =>
	s === 'done' ? '✓' : s === 'error' ? '×' : s === 'cancelled' ? '□' : s === 'running' ? '●' : '○';

// Derive a human-readable title for a run. Prefer the task brief/summary (already a
// sentence) and just normalise+capitalise it; otherwise de-kebab/snake a raw machine
// name ("build-workspace-components" → "Build workspace components"). Never expose IDs.
export function humanizeRunTitle(run: any): string {
	const raw = (run?.task_brief || run?.task || run?.final_summary || run?.summary || '')
		.toString()
		.trim();
	if (raw) {
		const s = raw.replace(/\s+/g, ' ');
		return s.charAt(0).toUpperCase() + s.slice(1);
	}
	const name = (run?.label || run?.name || run?.role || 'Run').toString();
	const dekebab = name.replace(/[-_]+/g, ' ').replace(/\s+/g, ' ').trim();
	return dekebab ? dekebab.charAt(0).toUpperCase() + dekebab.slice(1) : 'Run';
}

// Sentence-style task type. Multi-agent → "Workflow"; vibecode turn → "Agent run";
// otherwise a generic "Background task".
export function runTypeLabel(run: any, agentCount = 0): string {
	if ((agentCount || run?.child_count || 0) > 1) return 'Workflow';
	if (run?.source === 'vibecode') return 'Agent run';
	if (run?.source === 'workflow' || run?.role === 'orchestrator') return 'Workflow';
	return 'Background task';
}

// Agent/sub-run count if the backend supplied one (history → child_count); a vibecode
// turn is a single agent. Returns 0 when unknown (the card then omits "N agents").
export function agentCountOf(run: any): number {
	if (typeof run?.child_count === 'number') return run.child_count;
	if (typeof run?.agent_count === 'number') return run.agent_count;
	if (run?.source === 'vibecode') return 1;
	return 0;
}

// Compact duration: 9s / 22s / 2m / 1h 4m / 9h.
export function fmtDuration(ms?: number | null): string {
	if (!ms || ms < 0) return '';
	const s = Math.floor(ms / 1000);
	if (s < 60) return `${s}s`;
	const m = Math.floor(s / 60);
	if (m < 60) return `${m}m`;
	const h = Math.floor(m / 60);
	const rem = m % 60;
	return rem ? `${h}h ${rem}m` : `${h}h`;
}

// Compact token count: 51.5k / 1.2M.
export function fmtTokens(n?: number | null): string {
	if (!n || n < 0) return '0';
	if (n < 1000) return `${n}`;
	if (n < 1_000_000) return `${(n / 1000).toFixed(1).replace(/\.0$/, '')}k`;
	return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, '')}M`;
}
