import { describe, expect, it } from 'vitest';
import type { WorkspaceEvent } from '$lib/apis/streaming/workspace-stream';
import {
	agentHeadline,
	initialAgentRunState,
	projectAgentRun,
	reduceAgentEvent
} from './agentRunProjection';

const PARENT = 'ws-parent';
const STEP1 = 'ws-parent-s1';
const STEP2 = 'ws-parent-s2';

const ev = (type: string, extra: Record<string, unknown> = {}): WorkspaceEvent =>
	({ type, ...extra }) as WorkspaceEvent;

const start = (): WorkspaceEvent[] => [
	ev('agent_start', { run_id: PARENT, label: 'Scout', agent_id: 'a1', agent_name: 'Scout' }),
	ev('restated_goal', {
		run_id: PARENT,
		restated_goal: 'Find three laptops under $800',
		status: 'planning'
	}),
	ev('plan', {
		run_id: PARENT,
		steps: [
			{ role: 'step', label: 'Search', model: 'm', task: 'search' },
			{ role: 'step', label: 'Write sheet', model: 'm', task: 'write' }
		]
	})
];

describe('agentRunProjection', () => {
	it('reads identity, goal and plan off the parent events', () => {
		const state = projectAgentRun(start());
		expect(state.runId).toBe(PARENT);
		expect(state.agentId).toBe('a1');
		expect(state.agentName).toBe('Scout');
		expect(state.agentLabel).toBe('Scout');
		expect(state.goal).toBe('Find three laptops under $800');
		expect(state.plan.map((p) => p.label)).toEqual(['Search', 'Write sheet']);
		expect(state.status).toBe('running');
	});

	it('matches a step ending to the step that started it', () => {
		const state = projectAgentRun([
			...start(),
			ev('step_started', { run_id: PARENT, step_run_id: STEP1, n: 1, label: 'Search', engine: 'native' }),
			ev('tool_call', { run_id: STEP1, tool: 'web_search' }),
			ev('tool_call', { run_id: STEP1, tool: 'web_fetch' }),
			ev('agent_end', { run_id: STEP1, summary: 'Found five candidates', success: true })
		]);
		expect(state.steps).toHaveLength(1);
		expect(state.steps[0].runId).toBe(STEP1);
		expect(state.steps[0].status).toBe('done');
		expect(state.steps[0].summary).toBe('Found five candidates');
		expect(state.steps[0].toolCalls).toBe(2);
	});

	it('does not let the parent agent_end close a step', () => {
		const state = projectAgentRun([
			...start(),
			ev('step_started', { run_id: PARENT, step_run_id: STEP1, n: 1, label: 'Search', engine: 'native' }),
			ev('agent_end', { run_id: PARENT, summary: 'parent', success: true })
		]);
		expect(state.steps[0].status).toBe('running');
	});

	it('marks a failed step as an error without failing the run', () => {
		const state = projectAgentRun([
			...start(),
			ev('step_started', { run_id: PARENT, step_run_id: STEP1, n: 1, label: 'Search', engine: 'native' }),
			ev('agent_end', { run_id: STEP1, summary: 'error: timed out', success: false })
		]);
		expect(state.steps[0].status).toBe('error');
		expect(state.success).toBeNull();
	});

	it('holds a pending approval and clears it when resolved', () => {
		let state = projectAgentRun([
			...start(),
			ev('step_started', { run_id: PARENT, step_run_id: STEP1, n: 1, label: 'Search', engine: 'native' }),
			ev('approval_request', {
				run_id: STEP1,
				action_id: 'a-1',
				tool: 'browser_type',
				risk: 'hard',
				reason: 'That is a sign-in.',
				args: { text: 'x' }
			})
		]);
		expect(state.status).toBe('waiting');
		expect(state.pending?.actionId).toBe('a-1');
		expect(state.pending?.tool).toBe('browser_type');
		expect(agentHeadline(state)).toBe('Waiting on you: browser_type');

		state = reduceAgentEvent(state, ev('approval_resolved', { run_id: STEP1, action_id: 'a-1', approved: true }));
		expect(state.pending).toBeNull();
		expect(state.status).toBe('running');
	});

	it('ignores a resolution for an approval it is not holding', () => {
		let state = reduceAgentEvent(
			initialAgentRunState(),
			ev('approval_request', { action_id: 'a-1', tool: 't', reason: 'r', risk: 'hard' })
		);
		state = reduceAgentEvent(state, ev('approval_resolved', { action_id: 'other', approved: true }));
		expect(state.pending?.actionId).toBe('a-1');
	});

	it('collects the deliverable and the suggestions', () => {
		const state = projectAgentRun([
			...start(),
			ev('delivery', {
				run_id: PARENT,
				status: 'done',
				artifacts: ['laptops.csv', 'notes.md'],
				touched: 2,
				summary: 'Wrote the sheet.'
			}),
			ev('propose_next', { run_id: PARENT, suggestions: ['Add prices', 'Check stock'], status: 'waiting' })
		]);
		expect(state.delivery?.artifacts).toEqual(['laptops.csv', 'notes.md']);
		expect(state.delivery?.touched).toBe(2);
		expect(state.suggestions).toEqual(['Add prices', 'Check stock']);
		expect(state.status).toBe('waiting');
	});

	it('keeps running through its own suggestions under an override', () => {
		const state = projectAgentRun([
			...start(),
			ev('propose_next', { run_id: PARENT, suggestions: ['Add prices'], status: 'running' })
		]);
		expect(state.status).toBe('running');
	});

	it('flags an unsupervised shell when a step runs on an external engine', () => {
		const native = projectAgentRun([
			...start(),
			ev('step_started', { run_id: PARENT, step_run_id: STEP1, n: 1, label: 'A', engine: 'native' })
		]);
		expect(native.unsupervisedShell).toBe(false);

		const external = projectAgentRun([
			...start(),
			ev('step_started', { run_id: PARENT, step_run_id: STEP1, n: 1, label: 'A', engine: 'native' }),
			ev('step_started', { run_id: PARENT, step_run_id: STEP2, n: 2, label: 'B', engine: 'hermes' })
		]);
		expect(external.unsupervisedShell).toBe(true);
		expect(external.steps[1].unsupervisedShell).toBe(true);
		expect(external.steps[0].unsupervisedShell).toBe(false);
	});

	it('ends the run on the parent done event only', () => {
		let state = projectAgentRun([
			...start(),
			ev('step_started', { run_id: PARENT, step_run_id: STEP1, n: 1, label: 'A', engine: 'native' }),
			ev('done', { run_id: STEP1, success: true })
		]);
		expect(state.status).toBe('running');

		state = reduceAgentEvent(state, ev('done', { run_id: PARENT, success: true }));
		expect(state.status).toBe('done');
		expect(state.success).toBe(true);
		expect(agentHeadline(state)).toBe('Finished');
	});

	it('reports a partial delivery in the headline', () => {
		const state = projectAgentRun([
			...start(),
			ev('delivery', { run_id: PARENT, status: 'partial', artifacts: [], touched: 0, summary: '' }),
			ev('done', { run_id: PARENT, success: false })
		]);
		expect(agentHeadline(state)).toBe('Finished, partly');
		expect(state.success).toBe(false);
	});

	it('lands on the same state whether events arrive live or as a replay', () => {
		const events = [
			...start(),
			ev('step_started', { run_id: PARENT, step_run_id: STEP1, n: 1, label: 'A', engine: 'native' }),
			ev('tool_call', { run_id: STEP1, tool: 'read' }),
			ev('agent_end', { run_id: STEP1, summary: 'ok', success: true }),
			ev('delivery', { run_id: PARENT, status: 'done', artifacts: ['a.txt'], touched: 1, summary: 's' }),
			ev('done', { run_id: PARENT, success: true })
		];
		const replayed = projectAgentRun(events);
		const live = events.reduce(reduceAgentEvent, initialAgentRunState());
		expect(replayed).toEqual(live);
	});

	it('never mutates the state it is given', () => {
		const before = projectAgentRun(start());
		const snapshot = JSON.parse(JSON.stringify(before));
		reduceAgentEvent(
			before,
			ev('step_started', { run_id: PARENT, step_run_id: STEP1, n: 1, label: 'A', engine: 'native' })
		);
		expect(before).toEqual(snapshot);
	});

	it('collects log lines in order and ignores unknown events', () => {
		const state = projectAgentRun([
			...start(),
			ev('log', { run_id: PARENT, message: 'Retrying: Search.' }),
			ev('log', { run_id: PARENT, message: 'Budget reached — stopping here.' }),
			ev('something_new', { run_id: PARENT })
		]);
		expect(state.logs).toEqual(['Retrying: Search.', 'Budget reached — stopping here.']);
	});

	it('shows the running step in the headline', () => {
		const state = projectAgentRun([
			...start(),
			ev('step_started', { run_id: PARENT, step_run_id: STEP1, n: 1, label: 'Search', engine: 'native' })
		]);
		expect(agentHeadline(state)).toBe('Search');
	});
});

describe('the computer', () => {
	it('is noted the first time a step calls a computer_* tool', () => {
		const state = projectAgentRun([
			...start(),
			ev('step_started', { run_id: PARENT, n: 1, label: 'Search', engine: 'native', step_run_id: STEP1 }),
			ev('tool_call', { run_id: STEP1, tool: 'computer_open', args: { url: 'https://duckduckgo.com' } })
		]);
		expect(state.usesComputer).toBe(true);
		expect(state.steps[0].toolCalls).toBe(1);
	});

	it('is not assumed from ordinary tools', () => {
		const state = projectAgentRun([
			...start(),
			ev('step_started', { run_id: PARENT, n: 1, label: 'Read', engine: 'native', step_run_id: STEP1 }),
			ev('tool_call', { run_id: STEP1, tool: 'read_file', args: { path: 'a.md' } })
		]);
		expect(state.usesComputer).toBe(false);
		expect(initialAgentRunState().usesComputer).toBe(false);
	});
});
