/**
 * Marked extension for colon-fence blocks (:::type ... :::)
 *
 * A colon fence is how a model marks a span of its output as semantically
 * distinct — a terminal session, a search activity, a file, a piece of prose
 * meant to be kept. It emits the TYPE; Harvis alone decides what that type
 * looks like (see Markdown/blocks/registry.ts). The model never names a
 * component, a colour, or a size, so no model output can reshape the chat.
 *
 * Info line: `:::<type> [key=value ...]`
 *   :::terminal status=running title="npm run dev"
 *   :::search status=complete
 *   :::file name=architecture.md size=12.4KB href=/api/workspace/artifact/ab12
 *
 * Attributes are optional; a bare `:::writing` still tokenizes exactly as it
 * did before. Values may be quoted to contain spaces. Keys are lowercased;
 * the value is kept verbatim and treated as untrusted text by every renderer.
 *
 * Two tokenizers, because a block has to exist before it is finished:
 *   - closed fence  → `open: false`, the normal case
 *   - unterminated fence at the tail of the buffer → `open: true`, so a block
 *     streams in place and flips to closed when its `:::` arrives, rather than
 *     popping into existence only once the model stops talking.
 */

const INFO_LINE = /^:::([\w-]+)([^\n]*)\n/;
const ATTR = /([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|(\S+))/g;

function parseAttrs(info: string): Record<string, string> {
	const attrs: Record<string, string> = {};
	if (!info) return attrs;
	let m: RegExpExecArray | null;
	ATTR.lastIndex = 0;
	while ((m = ATTR.exec(info)) !== null) {
		attrs[m[1].toLowerCase()] = m[2] ?? m[3] ?? m[4] ?? '';
	}
	return attrs;
}

function build(this: any, fenceType: string, info: string, text: string, raw: string, open: boolean) {
	const tokens: any[] = [];
	// A still-open block is re-lexed on every animation frame while streaming.
	// That is the same cost the surrounding markdown already pays, and it keeps
	// nested content (a code block inside a :::writing) rendering correctly
	// mid-stream instead of showing raw backticks until the fence closes.
	this.lexer.blockTokens(text, tokens);
	return { type: 'colonFence', raw, fenceType, attrs: parseAttrs(info), text, tokens, open };
}

function colonFenceTokenizer(this: any, src: string) {
	const closed = /^:::([\w-]+)([^\n]*)\n([\s\S]*?)(?:\n:::(?:\s*(?:\n|$)))/.exec(src);
	if (closed) {
		return build.call(this, closed[1], closed[2], closed[3].trim(), closed[0], false);
	}

	// Unterminated. Only treat it as a block when the fence opens at the very
	// start of what is left AND nothing closes it anywhere ahead — that is the
	// streaming tail, not a stray ':::' sitting in the middle of prose.
	const head = INFO_LINE.exec(src);
	if (head) {
		const body = src.slice(head[0].length);
		if (!/\n:::(\s*(\n|$))/.test('\n' + body)) {
			return build.call(this, head[1], head[2], body.trim(), src, true);
		}
	}
}

function colonFenceStart(src: string) {
	const idx = src.match(/^:::\w/m);
	return idx ? idx.index! : -1;
}

function colonFenceRenderer(token: any) {
	return `<div class="colon-fence colon-fence-${token.fenceType}">${token.text}</div>`;
}

function colonFenceExtension() {
	return {
		name: 'colonFence',
		level: 'block' as const,
		start: colonFenceStart,
		tokenizer: colonFenceTokenizer,
		renderer: colonFenceRenderer
	};
}

export default function (options = {}) {
	return {
		extensions: [colonFenceExtension()]
	};
}
