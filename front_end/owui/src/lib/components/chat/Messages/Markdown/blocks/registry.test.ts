import { describe, it, expect } from 'vitest';
import { normalizeStatus, safeHref, unwrapCodeFence } from './registry';

describe('normalizeStatus', () => {
	it('maps known synonyms onto the three real states', () => {
		expect(normalizeStatus('in_progress', false)).toBe('running');
		expect(normalizeStatus('done', false)).toBe('complete');
		expect(normalizeStatus('failed', false)).toBe('error');
	});

	it('treats an unterminated block as still running', () => {
		expect(normalizeStatus(undefined, true)).toBe('running');
		expect(normalizeStatus(undefined, false)).toBe('complete');
	});

	it('drops a value the model invented rather than showing it', () => {
		expect(normalizeStatus('exploding', false)).toBe('complete');
	});
});

describe('safeHref', () => {
	it('allows a same-origin path', () => {
		expect(safeHref('/api/workspace/artifact/ab12')).toBe('/api/workspace/artifact/ab12');
	});

	it('rejects anything that could leave this origin or execute', () => {
		expect(safeHref('https://evil.test/x')).toBeNull();
		expect(safeHref('//evil.test/x')).toBeNull();
		expect(safeHref('javascript:alert(1)')).toBeNull();
		expect(safeHref('data:text/html,<script>')).toBeNull();
		expect(safeHref(undefined)).toBeNull();
	});
});

describe('unwrapCodeFence', () => {
	it('removes a fence that wraps the whole body', () => {
		expect(unwrapCodeFence('```\n$ npm run dev\nready\n```')).toBe('$ npm run dev\nready');
		expect(unwrapCodeFence('```bash\n$ ls\n```')).toBe('$ ls');
	});

	it('leaves backticks that are part of real output alone', () => {
		const out = 'use `--host` to expose';
		expect(unwrapCodeFence(out)).toBe(out);
	});
});
