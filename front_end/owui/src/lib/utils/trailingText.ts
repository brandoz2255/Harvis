import { writable, type Readable } from 'svelte/store';

/**
 * A string store that catches up to its target instead of jumping to it.
 *
 * Some things arrive whole: a workspace run's written analysis lands in one `done`
 * event, and a file the agent wrote lands one tool call at a time. Both read as text
 * being dumped on the page. Trailing the target at a readable pace makes them type
 * themselves out, and costs nothing but a frame loop that stops as soon as it catches up.
 *
 * It always finishes. `feed(text, true)` means no more text is coming, so the loop
 * ends once the tail is shown; `feed(text, true, true)` is for replaying something that
 * already happened (a reloaded run), which shows whole rather than re-typing history.
 *
 * The pace matches ResponseMessage's own smooth-streaming loop: never slower than
 * `minCps`, and fast enough to drain whatever backlog exists in `drainSeconds`, so a
 * long burst types quickly rather than queuing up into a visible lag.
 */
export interface TrailingText extends Readable<string> {
	feed(raw: string, done?: boolean, snap?: boolean): void;
	stop(): void;
}

export const trailingText = (minCps = 45, drainSeconds = 0.4): TrailingText => {
	const { subscribe, set } = writable('');

	let shown = '';
	let target = '';
	let finished = false;
	let raf: number | null = null;
	let lastMs = 0;

	const show = (s: string) => {
		shown = s;
		set(s);
	};

	const step = (t: number) => {
		raf = null;
		const dt = lastMs ? Math.min(0.2, (t - lastMs) / 1000) : 1 / 60;
		lastMs = t;
		const behind = target.length - shown.length;
		if (behind > 0) {
			const cps = Math.max(minCps, behind / drainSeconds);
			show(target.slice(0, Math.min(target.length, shown.length + Math.max(1, Math.ceil(cps * dt)))));
		} else if (finished) {
			lastMs = 0;
			return;
		}
		raf = requestAnimationFrame(step);
	};

	const start = () => {
		if (raf !== null || typeof requestAnimationFrame === 'undefined') return;
		lastMs = 0;
		raf = requestAnimationFrame(step);
	};

	return {
		subscribe,
		feed(raw: string, done = false, snap = false) {
			const next = raw ?? '';
			finished = done;
			if (snap || typeof requestAnimationFrame === 'undefined') {
				target = next;
				if (next !== shown) show(next);
				return;
			}
			// The text was replaced rather than appended to — the agent rewrote the file.
			// Type the new version from the start; continuing from a stale offset would
			// splice two different files together.
			if (!next.startsWith(shown)) show('');
			target = next;
			if (shown.length < target.length) start();
		},
		stop() {
			if (raf !== null) cancelAnimationFrame(raf);
			raf = null;
		}
	};
};
