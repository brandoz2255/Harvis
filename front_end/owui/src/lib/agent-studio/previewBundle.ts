// Make a MULTI-FILE project previewable inside the sandboxed iframe.
//
// The preview renders model-written HTML through `srcdoc` with sandbox="allow-scripts" and
// deliberately NO allow-same-origin, so the page runs in an opaque origin. That is the right
// security posture and it is not up for negotiation — but it has a consequence nobody had
// accounted for: relative URLs in a srcdoc document resolve against `about:srcdoc`, which
// resolves to nothing. `<link href="styles.css">` and `<script src="js/main.js">` therefore
// CANNOT load, ever. A project split across files rendered as an unstyled, script-less page —
// a white screen showing only the <title> text — while the turn reported success.
//
// So the sibling files are folded INTO the document before it is handed to the iframe:
// stylesheets become <style>, classic scripts become inline <script>, and ES modules become a
// data: URL graph (leaves first, each importer's specifiers rewritten to its children's data
// URLs) because data: URLs are valid module specifiers in an opaque origin where blob: URLs
// minted by the parent are not.
//
// What it deliberately does NOT do: invent files. A reference with no matching file is left
// exactly as written and reported in `missing`, so the preview can say what the page is asking
// for instead of silently showing a blank frame.

export type PreviewFile = { name: string; content?: string; is_binary?: boolean };

export type BundleResult = {
	html: string;
	/** Refs the preview could not resolve — absent from the project, or part of a cycle. */
	missing: string[];
	/** Refs that were folded in — the evidence that the preview is showing the real project. */
	inlined: string[];
};

/** Resolve `ref` against the directory of `basePath`, collapsing `.` and `..`. */
export function resolvePath(basePath: string, ref: string): string {
	const clean = ref.split('#')[0].split('?')[0];
	if (!clean) return '';
	const baseDir = basePath.includes('/') ? basePath.replace(/\/[^/]*$/, '') : '';
	const start = clean.startsWith('/') ? [] : baseDir ? baseDir.split('/') : [];
	const out: string[] = [...start];
	for (const seg of clean.replace(/^\//, '').split('/')) {
		if (!seg || seg === '.') continue;
		if (seg === '..') out.pop();
		else out.push(seg);
	}
	return out.join('/');
}

/** Base64 that survives non-ASCII source (btoa alone throws on it). */
function b64(src: string): string {
	if (typeof TextEncoder !== 'undefined' && typeof btoa === 'function') {
		const bytes = new TextEncoder().encode(src);
		let bin = '';
		for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
		return btoa(bin);
	}
	// Node (tests) — Buffer is not present in the browser bundle path above.
	return (globalThis as any).Buffer.from(src, 'utf-8').toString('base64');
}

/** A rough cap so a pathological graph can't build a 100 MB string in the tab. */
const MAX_BUNDLE = 8 * 1024 * 1024;

/**
 * Index the project by path AND by basename, because a page and its assets do not always
 * agree on depth ("js/main.js" from the root, "./main.js" from inside js/). The path match
 * always wins; the basename is only consulted when it is unambiguous.
 */
function buildIndex(files: PreviewFile[]) {
	const byPath = new Map<string, string>();
	const byBase = new Map<string, string[]>();
	for (const f of files) {
		if (!f || f.is_binary || typeof f.content !== 'string') continue;
		const p = f.name.replace(/^\.?\//, '');
		byPath.set(p, f.content);
		const b = p.split('/').pop() || p;
		byBase.set(b, [...(byBase.get(b) ?? []), p]);
	}
	return { byPath, byBase };
}

function lookup(idx: ReturnType<typeof buildIndex>, path: string): { path: string; src: string } | null {
	const direct = idx.byPath.get(path);
	if (direct !== undefined) return { path, src: direct };
	const base = path.split('/').pop() || path;
	const cands = idx.byBase.get(base);
	if (cands && cands.length === 1) return { path: cands[0], src: idx.byPath.get(cands[0]) as string };
	return null;
}

// Relative module specifiers only. A bare specifier ("three") is a real dependency on a
// package the sandbox does not have — rewriting it would fake a resolution that isn't there.
const SPECIFIER = /((?:\bfrom|\bimport|\bexport)\s*(?:\(\s*)?)(['"])([^'"\n]+)\2/g;

/**
 * Turn a module into a data: URL, resolving its relative imports to data: URLs first.
 * Returns null on a cycle or a missing dependency — the caller reports rather than guesses.
 */
function moduleUrl(
	idx: ReturnType<typeof buildIndex>,
	path: string,
	stack: string[],
	memo: Map<string, string | null>,
	missing: Set<string>
): string | null {
	if (memo.has(path)) return memo.get(path) as string | null;
	if (stack.includes(path)) {
		// A data: URL graph is built leaves-first, so it cannot express a cycle. Say so
		// rather than leaving a dead <script src> and a blank frame with no explanation.
		missing.add(`${path} (import cycle)`);
		return null;
	}
	const hit = lookup(idx, path);
	if (!hit) {
		missing.add(path);
		return null;
	}
	let failed = false;
	const rewritten = hit.src.replace(SPECIFIER, (whole, lead, q, spec) => {
		if (!/^\.{0,2}\//.test(spec)) return whole; // bare or absolute-URL specifier: leave it
		const dep = resolvePath(hit.path, spec);
		const url = moduleUrl(idx, dep, [...stack, path], memo, missing);
		if (!url) {
			failed = true;
			return whole;
		}
		return `${lead}${q}${url}${q}`;
	});
	const out = failed ? null : `data:text/javascript;charset=utf-8;base64,${b64(rewritten)}`;
	memo.set(path, out);
	return out;
}

const ATTR = (name: string, tag: string): string => {
	const m = tag.match(new RegExp(`\\b${name}\\s*=\\s*("([^"]*)"|'([^']*)'|([^\\s>]+))`, 'i'));
	return (m ? (m[2] ?? m[3] ?? m[4]) : '') || '';
};

/**
 * Fold every sibling the page references into the document.
 * `basePath` is the previewed file's own workspace-relative path.
 */
export function bundlePreview(html: string, files: PreviewFile[], basePath = 'index.html'): BundleResult {
	const idx = buildIndex(files);
	const missing = new Set<string>();
	const inlined: string[] = [];
	const memo = new Map<string, string | null>();
	let out = html;

	// <link rel="stylesheet" href="…"> → <style>
	out = out.replace(/<link\b[^>]*>/gi, (tag) => {
		const rel = ATTR('rel', tag).toLowerCase();
		const href = ATTR('href', tag);
		if (!href || (rel && rel !== 'stylesheet')) return tag;
		if (/^(https?:)?\/\/|^data:/i.test(href)) return tag; // remote sheet — the CSP decides
		if (!rel && !/\.css(\?|#|$)/i.test(href)) return tag; // a favicon, not a sheet
		const hit = lookup(idx, resolvePath(basePath, href));
		if (!hit) {
			missing.add(href);
			return tag;
		}
		inlined.push(hit.path);
		return `<style data-harvis-inlined="${hit.path}">\n${hit.src}\n</style>`;
	});

	// <script src="…"> → inline (classic) or a data: URL module graph (type="module")
	out = out.replace(/<script\b([^>]*)>\s*<\/script>/gi, (whole, attrs) => {
		const tag = `<script ${attrs}>`;
		const src = ATTR('src', tag);
		if (!src || /^(https?:)?\/\/|^data:/i.test(src)) return whole;
		const path = resolvePath(basePath, src);
		const isModule = /\btype\s*=\s*["']?module/i.test(attrs);
		if (isModule) {
			const url = moduleUrl(idx, path, [], memo, missing);
			if (!url) return whole; // missing/cyclic — already reported
			inlined.push(path);
			return `<script type="module" src="${url}" data-harvis-inlined="${path}"></script>`;
		}
		const hit = lookup(idx, path);
		if (!hit) {
			missing.add(src);
			return whole;
		}
		inlined.push(hit.path);
		// `</script>` inside the source would close this tag early.
		return `<script data-harvis-inlined="${hit.path}">\n${hit.src.replace(/<\/script/gi, '<\\/script')}\n</script>`;
	});

	if (out.length > MAX_BUNDLE) return { html, missing: [...missing], inlined: [] };
	return { html: out, missing: [...missing], inlined };
}
