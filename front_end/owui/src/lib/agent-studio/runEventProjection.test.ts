import { describe, expect, it } from 'vitest';

import type { WorkspaceEvent } from '$lib/apis/streaming/workspace-stream';
import { buildRunActivity, projectTerminalRuns } from './runEventProjection';

const events = (value: unknown[]) => value as WorkspaceEvent[];

describe('projectTerminalRuns', () => {
	it('folds real streamed stdout and stderr into one stable completed command', () => {
		const runs = projectTerminalRuns(
			events([
				{
					type: 'tool_call',
					tool: 'harvis-terminal',
					args: { command: 'npm test', cwd: '/workspace/app' }
				},
				{ type: 'terminal_output', stream: 'stdout', content: 'first\n' },
				{ type: 'terminal_output', stream: 'stderr', content: 'warning\n' },
				{
					type: 'tool_result',
					tool: 'harvis-terminal',
					success: true,
					output: { exit_code: 0, duration_ms: 3210, truncated: false }
				}
			]),
			'workspace-1'
		);

		expect(runs).toHaveLength(1);
		expect(runs[0]).toMatchObject({
			id: 'workspace-1:command:0',
			command: 'npm test',
			cwd: '/workspace/app',
			status: 'succeeded',
			exitCode: 0,
			durationMs: 3210,
			stdout: 'first\n',
			stderr: 'warning\n',
			truncated: false
		});
	});

	it('preserves a successful command with no output', () => {
		const runs = projectTerminalRuns(
			events([
				{ type: 'tool_call', tool: 'exec', args: { command: 'true' } },
				{
					type: 'tool_result',
					tool: 'exec',
					success: true,
					output: { exit_code: 0, duration_ms: 18 }
				}
			]),
			'workspace-2'
		);

		expect(runs[0]).toMatchObject({
			command: 'true',
			status: 'succeeded',
			exitCode: 0,
			stdout: '',
			stderr: ''
		});
	});

	it('uses text payloads and keeps failed stderr with the nonzero exit code', () => {
		const runs = projectTerminalRuns(
			events([
				{ type: 'tool_call', tool: 'run_code', args: { command: 'python broken.py' } },
				{ type: 'terminal_output', stream: 'stderr', text: 'Traceback\nboom\n' },
				{
					type: 'tool_result',
					tool: 'run_code',
					success: false,
					output: { exit_code: 1, duration_ms: 1840 }
				}
			]),
			'workspace-3'
		);

		expect(runs[0]).toMatchObject({
			status: 'failed',
			exitCode: 1,
			durationMs: 1840,
			stderr: 'Traceback\nboom\n'
		});
	});

	it('marks only the active command cancelled and retains prior completed output', () => {
		const runs = projectTerminalRuns(
			events([
				{ type: 'tool_call', tool: 'exec', args: { command: 'printf first' } },
				{ type: 'terminal_output', stream: 'stdout', content: 'first' },
				{
					type: 'tool_result',
					tool: 'exec',
					success: true,
					output: { exit_code: 0, duration_ms: 50 }
				},
				{ type: 'tool_call', tool: 'exec', args: { command: 'sleep 30' } },
				{ type: 'cancelled' }
			]),
			'workspace-4'
		);

		expect(runs).toHaveLength(2);
		expect(runs[0]).toMatchObject({ status: 'succeeded', stdout: 'first' });
		expect(runs[1]).toMatchObject({ status: 'cancelled', command: 'sleep 30' });
		expect(new Set(runs.map((run) => run.id)).size).toBe(2);
	});

	it('retains real final-only string output when no terminal chunks were emitted', () => {
		const runs = projectTerminalRuns(
			events([
				{
					type: 'tool_result',
					tool: 'exec',
					args: { command: 'printf final' },
					success: true,
					output: 'final'
				}
			]),
			'workspace-final'
		);

		expect(runs[0]).toMatchObject({
			command: 'printf final',
			status: 'succeeded',
			stdout: 'final'
		});
	});

	it('scopes explicit ids by workspace and lane', () => {
		const runs = projectTerminalRuns(
			events([
				{
					type: 'tool_call',
					tool: 'exec',
					command_id: 'same-id',
					run_id: 'lane-a',
					args: { command: 'echo a' }
				},
				{
					type: 'tool_call',
					tool: 'exec',
					command_id: 'same-id',
					run_id: 'lane-b',
					args: { command: 'echo b' }
				}
			]),
			'workspace-scoped'
		);

		expect(new Set(runs.map((run) => run.id)).size).toBe(2);
		expect(runs.map((run) => run.id)).toEqual([
			'workspace-scoped:lane-a:command:same-id',
			'workspace-scoped:lane-b:command:same-id'
		]);
	});

	it('does not guess when output cannot be correlated between concurrent commands', () => {
		const runs = projectTerminalRuns(
			events([
				{ type: 'tool_call', tool: 'exec', args: { command: 'first' } },
				{ type: 'tool_call', tool: 'exec', args: { command: 'second' } },
				{ type: 'terminal_output', stream: 'stdout', content: 'ambiguous' }
			]),
			'workspace-ambiguous'
		);

		expect(runs.map((run) => run.stdout)).toEqual(['', '']);
	});
});

describe('buildRunActivity', () => {
	it('uses one live sentence and a Cursor-style final summary from real tool calls', () => {
		const input = events([
			{ type: 'tool_call', tool: 'read', args: { path: '/workspace/a.ts' } },
			{ type: 'tool_result', tool: 'read', success: true },
			{ type: 'tool_call', tool: 'file_fetch', args: { path: '/workspace/b.ts' } },
			{ type: 'tool_result', tool: 'file_fetch', success: true },
			{ type: 'tool_call', tool: 'web_search', args: { query: 'Svelte terminal card' } },
			{ type: 'tool_result', tool: 'web_search', success: true },
			{ type: 'tool_call', tool: 'local_rag', args: { query: 'run events' } },
			{ type: 'tool_result', tool: 'local_rag', success: true },
			{ type: 'tool_call', tool: 'exec', args: { command: 'npm run check' } }
		]);

		const running = buildRunActivity(input, 'executing', 'workspace-5');
		expect(running.headline).toBe('Running command');
		expect(running.items).toHaveLength(5);

		const completed = buildRunActivity([...input, { type: 'done' }], 'done', 'workspace-5');
		expect(completed.summary).toBe('Explored 2 files, 2 searches, ran 1 command');
		expect(completed.counts).toEqual({ files: 2, searches: 2, commands: 1, other: 0 });
	});

	it('keeps repeated backend ids unique across concurrent activity lanes', () => {
		const activity = buildRunActivity(
			events([
				{ type: 'tool_call', tool: 'exec', command_id: 'shared', run_id: 'coder' },
				{ type: 'tool_call', tool: 'exec', command_id: 'shared', run_id: 'reviewer' }
			]),
			'executing',
			'workspace-lanes'
		);

		expect(activity.items.map((item) => item.id)).toEqual([
			'workspace-lanes:coder:activity:shared',
			'workspace-lanes:reviewer:activity:shared'
		]);
	});
});
