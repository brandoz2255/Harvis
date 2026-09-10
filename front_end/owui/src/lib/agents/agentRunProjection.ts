import type { WorkspaceEvent } from '$lib/apis/streaming/workspace-stream';

/**
 * Fold a teammate's run events into the state the run card draws.
 *
 * The reducer is pure and order-tolerant on purpose: the workspace stream
 * replays every stored event before it goes live, so the card must land on the
 * same state whether it opened at the start of a run or three refreshes later.
 *
 * Parent events (agent_start, plan, delivery, propose_next, done) carry the
 * parent run id. Step events carry the child run id, which is how a step's
 * ending is matched to the step that started it.
 */

export type AgentRunStatus =
	| 'starting'
	| 'planning'
	| 'running'
	| 'waiting'
	| 'done'
	| 'error'
	| 'cancelled';

export type AgentStepStatus = 'running' | 'done' | 'error';

export interface AgentStep {
	n: number;
	label: string;
	engine: string;
	runId: string;
	status: AgentStepStatus;
	summary: string;
	toolCalls: number;
	/** The model this step is thinking on — resolved server-side, so an "auto"
	 *  teammate still shows a real name here. */
	model: string;
	/** True when the engine running this step keeps its own shell inside the
	 *  sandbox clone, so Harvis did not see those commands one by one. */
	unsupervisedShell: boolean;
}

export interface AgentPlannedStep {
	label: string;
	role: string;
	model: string;
}

export interface AgentPendingApproval {
	actionId: string;
	tool: string;
	reason: string;
	risk: string;
	args: Record<string, unknown>;
}

export interface AgentDelivery {
	status: string;
	summary: string;
	artifacts: string[];
	touched: number;
}

export interface AgentRunState {
	runId: string;
	agentId: string;
	agentName: string;
	agentLabel: string;
	goal: string;
	status: AgentRunStatus;
	plan: AgentPlannedStep[];
	steps: AgentStep[];
	pending: AgentPendingApproval | null;
	delivery: AgentDelivery | null;
	suggestions: string[];
	logs: string[];
	/** null until the run ends. */
	success: boolean | null;
	/** True once any step ran on an engine with its own ungoverned shell. */
	unsupervisedShell: boolean;
	/** True once the teammate touched its browser (a computer_* tool call), so
	 *  the card can dock the screen without the user going to look for it. */
	usesComputer: boolean;
}

/** Engines that keep their own shell inside the throwaway clone. Harvis gates
 *  their browser actions but does not see each command, so the card says so. */
const UNSUPERVISED_ENGINES = new Set(['hermes', 'claude', 'codex', 'opencode']);

const asString = (value: unknown): string => (typeof value === 'string' ? value : '');
const asNumber = (value: unknown): number => (typeof value === 'number' && Number.isFinite(value) ? value : 0);
const asRecord = (value: unknown): Record<string, unknown> =>
	value && typeof value === 'object' && !Array.isArray(value)
		? (value as Record<string, unknown>)
		: {};
const asStringList = (value: unknown): string[] =>
	Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];

export function initialAgentRunState(): AgentRunState {
	return {
		runId: '',
		agentId: '',
		agentName: '',
		agentLabel: '',
		goal: '',
		status: 'starting',
		plan: [],
		steps: [],
		pending: null,
		delivery: null,
		suggestions: [],
		logs: [],
		success: null,
		unsupervisedShell: false,
		usesComputer: false
	};
}

const isParentEvent = (state: AgentRunState, event: WorkspaceEvent): boolean =>
	!state.runId || !event.run_id || event.run_id === state.runId;

/** Apply one event. Returns a new state; never mutates the one passed in. */
export function reduceAgentEvent(state: AgentRunState, event: WorkspaceEvent): AgentRunState {
	const next: AgentRunState = { ...state, steps: [...state.steps] };
	const type = asString(event.type);

	if (asString(event.agent_id) && !next.agentId) next.agentId = asString(event.agent_id);
	if (asString(event.agent_name) && !next.agentName) next.agentName = asString(event.agent_name);

	switch (type) {
		case 'agent_start': {
			// The first agent_start is the parent's; later ones belong to steps
			// and must not rewrite the run's identity.
			if (!next.runId) {
				next.runId = asString(event.run_id);
				next.agentLabel = asString(event.label) || asString(event.agent_label);
				next.status = 'starting';
			}
			return next;
		}

		case 'restated_goal': {
			next.goal = asString(event.restated_goal) || next.goal;
			next.status = 'planning';
			return next;
		}

		case 'plan': {
			const steps = Array.isArray(event.steps) ? event.steps : [];
			next.plan = steps.map((raw) => {
				const s = asRecord(raw);
				return {
					label: asString(s.label),
					role: asString(s.role),
					model: asString(s.model)
				};
			});
			next.status = 'running';
			return next;
		}

		case 'step_started': {
			// step_started rides the parent lane so the header renders in order;
			// the step's own run id travels under `step_run_id` because the SSE
			// writer overwrites `run_id` with the emitting lane's id.
			const engine = asString(event.engine) || 'native';
			const n = asNumber(event.n);
			const childId = asString(event.step_run_id);
			const existing = next.steps.findIndex((s) => s.n === n);
			const step: AgentStep = {
				n,
				label: asString(event.label),
				engine,
				runId: childId,
				status: 'running',
				summary: '',
				toolCalls: 0,
				model: asString(event.model),
				unsupervisedShell: UNSUPERVISED_ENGINES.has(engine)
			};
			if (existing >= 0) next.steps[existing] = { ...next.steps[existing], ...step };
			else next.steps.push(step);
			if (step.unsupervisedShell) next.unsupervisedShell = true;
			next.status = 'running';
			return next;
		}

		case 'tool_call': {
			if (asString(event.tool).startsWith('computer_')) next.usesComputer = true;
			const idx = next.steps.findIndex((s) => s.runId && s.runId === asString(event.run_id));
			if (idx >= 0) {
				next.steps[idx] = { ...next.steps[idx], toolCalls: next.steps[idx].toolCalls + 1 };
			}
			return next;
		}

		case 'agent_end': {
			if (isParentEvent(next, event)) return next;
			const idx = next.steps.findIndex((s) => s.runId && s.runId === asString(event.run_id));
			if (idx < 0) return next;
			const failed = event.success === false;
			next.steps[idx] = {
				...next.steps[idx],
				status: failed ? 'error' : 'done',
				summary: asString(event.summary) || next.steps[idx].summary
			};
			return next;
		}

		case 'approval_request': {
			next.pending = {
				actionId: asString(event.action_id),
				tool: asString(event.tool),
				reason: asString(event.reason),
				risk: asString(event.risk) || asString(event.tier),
				args: asRecord(event.args)
			};
			next.status = 'waiting';
			return next;
		}

		case 'approval_resolved': {
			if (next.pending && next.pending.actionId === asString(event.action_id)) next.pending = null;
			if (next.status === 'waiting') next.status = 'running';
			return next;
		}

		case 'delivery': {
			next.delivery = {
				status: asString(event.status) || 'done',
				summary: asString(event.summary),
				artifacts: asStringList(event.artifacts),
				touched: asNumber(event.touched)
			};
			return next;
		}

		case 'propose_next': {
			next.suggestions = asStringList(event.suggestions);
			// "waiting" here means waiting on the user to pick one, which is the
			// default. With an override the run keeps going on its own.
			next.status = asString(event.status) === 'running' ? 'running' : 'waiting';
			return next;
		}

		case 'log': {
			const message = asString(event.message);
			if (message) next.logs = [...next.logs, message];
			return next;
		}

		case 'done': {
			if (!isParentEvent(next, event)) return next;
			next.status = 'done';
			next.success = event.success !== false;
			next.pending = null;
			return next;
		}

		case 'error': {
			if (!isParentEvent(next, event)) return next;
			next.status = 'error';
			next.success = false;
			next.pending = null;
			return next;
		}

		case 'cancelled': {
			if (!isParentEvent(next, event)) return next;
			next.status = 'cancelled';
			next.success = false;
			next.pending = null;
			return next;
		}

		default:
			return next;
	}
}

/** Fold a whole event list, e.g. a replay on reload. */
export function projectAgentRun(events: WorkspaceEvent[]): AgentRunState {
	return (events || []).reduce(reduceAgentEvent, initialAgentRunState());
}

/** One line for the card header: what the teammate is doing right now. */
export function agentHeadline(state: AgentRunState): string {
	if (state.status === 'waiting' && state.pending) {
		return `Waiting on you: ${state.pending.tool}`;
	}
	if (state.status === 'waiting') return 'Waiting on you';
	if (state.status === 'done') return state.delivery?.status === 'partial' ? 'Finished, partly' : 'Finished';
	if (state.status === 'error') return 'Stopped on an error';
	if (state.status === 'cancelled') return 'Cancelled';
	if (state.status === 'planning') return 'Working out the steps';
	const running = state.steps.find((s) => s.status === 'running');
	if (running) return running.label || `Step ${running.n}`;
	return 'Starting';
}
