import { describe, it, expect } from 'vitest';
import { marked } from 'marked';
import colonFenceExtension from './colon-fence-extension';

// This marked build predates the Marked class, so the extension registers on
// the shared instance — the same way Markdown.svelte does it at runtime.
marked.use(colonFenceExtension({}));
const lex = (src: string) => marked.lexer(src) as any[];
const fence = (src: string) => lex(src).find((t) => t.type === 'colonFence');

describe('colon fence tokenizer', () => {
	it('tokenizes a closed fence and marks it complete', () => {
		const t = fence(':::writing\nhello there\n:::\n');
		expect(t.fenceType).toBe('writing');
		expect(t.text).toBe('hello there');
		expect(t.open).toBe(false);
	});

	it('parses bare, quoted and unquoted attributes', () => {
		const t = fence(':::terminal status=running title="npm run dev" cwd=/app\n$ ls\n:::\n');
		expect(t.attrs).toEqual({ status: 'running', title: 'npm run dev', cwd: '/app' });
	});

	it('keeps a fence with no attributes working exactly as before', () => {
		const t = fence(':::writing\nbody\n:::\n');
		expect(t.attrs).toEqual({});
		expect(t.tokens.length).toBeGreaterThan(0);
	});

	it('emits an OPEN block for an unterminated fence so it can stream', () => {
		const t = fence(':::terminal status=running\n$ npm run dev\n> vite');
		expect(t).toBeTruthy();
		expect(t.open).toBe(true);
		expect(t.text).toContain('vite');
	});

	it('closes that same block once the terminator arrives', () => {
		const t = fence(':::terminal status=running\n$ npm run dev\n> vite\n:::\n');
		expect(t.open).toBe(false);
	});

	it('does NOT swallow prose after a stray ::: mid-paragraph', () => {
		// The stray marker is not at a block start with an info line, so no
		// colonFence token may be produced — otherwise ordinary text would get
		// eaten into a card the moment a model typed three colons.
		expect(fence('some prose\n\nthen ::: a stray marker\n')).toBeUndefined();
	});

	it('lexes nested markdown inside the fence', () => {
		const t = fence(':::writing\n# Title\n\n- one\n- two\n:::\n');
		expect(t.tokens.map((x: any) => x.type)).toContain('heading');
		expect(t.tokens.map((x: any) => x.type)).toContain('list');
	});
});
