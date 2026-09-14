/**
 * DE-8d — design activity as a chronological tree.
 *
 * The timeline is a flat, time-ordered list of rows, and read flat it hides the one
 * thing a reader actually wants: which tools the model reached for *while doing what*.
 * This groups those same rows into the shape the turn already had.
 *
 *   turn  ← a `started` row: one authoring turn
 *     step  ← a `say` row: what the model said it was about to do
 *       row   ← the tools, builds, revisions it did while saying it
 *
 * Two rules keep it honest:
 *
 *  - **Nothing is invented.** A step exists only where the model actually narrated one.
 *    Rows that arrive with no narration in front of them stay at the level above,
 *    headless — a group captioned "Working…" would be this file writing words and
 *    attributing them to the model.
 *  - **Nothing is dropped.** Every row in, every row out, in the same order. Grouping
 *    is a re-parenting of the list, not a filter over it, so a row that never found a
 *    parent still appears rather than vanishing into a bucket nobody renders.
 *
 * A turn closes on its `done` row, so a slider edit made after the model finished is a
 * top-level event rather than the tail of a turn it had no part in.
 */

/** The rows this understands. Deliberately structural rather than the full event type:
 *  the same walk serves the workspace timeline (`CadActivityEvent`) and the chat card
 *  (`CadJobEvent`), which carry different fields but the same turn shape. */
export type ActivityLike = { kind: string };

export type ActivityStep<T> = {
	key: string;
	/** The `say` row that opened this step, or null for rows that preceded any. */
	head: T | null;
	rows: T[];
};

export type ActivityTurn<T> = {
	key: string;
	/** The `started` row that opened this turn, or null for events outside a turn —
	 *  a parameter edit, a restore, anything the user did directly. */
	head: T | null;
	steps: ActivityStep<T>[];
	/** Rows nested under this turn, heads excluded — what a collapsed turn is hiding. */
	nested: number;
};

/** Group a time-ordered row list into turns and steps. `keyOf` must be stable and
 *  unique per row; it seeds the group keys that drive collapse state. */
export const buildActivityTree = <T extends ActivityLike>(
	rows: T[],
	keyOf: (row: T) => string
): ActivityTurn<T>[] => {
	const turns: ActivityTurn<T>[] = [];
	let turn: ActivityTurn<T> | null = null;
	let step: ActivityStep<T> | null = null;

	const openTurn = (head: T | null, seed: string) => {
		turn = { key: `turn:${seed}`, head, steps: [], nested: 0 };
		step = null;
		turns.push(turn);
		return turn;
	};

	// The step a row belongs to: whichever the model last opened, or — before it has
	// narrated anything — a headless one created on demand, so a turn whose rows are
	// all narrated never carries an empty one.
	const currentStep = (t: ActivityTurn<T>) => {
		if (!step) {
			step = { key: `${t.key}:loose:${t.steps.length}`, head: null, rows: [] };
			t.steps.push(step);
		}
		return step;
	};

	for (const row of rows) {
		const key = keyOf(row);

		if (row.kind === 'started') {
			openTurn(row, key);
			continue;
		}

		const t = turn ?? openTurn(null, key);

		if (row.kind === 'say') {
			step = { key: `step:${key}`, head: row, rows: [] };
			t.steps.push(step);
			t.nested += 1;
			continue;
		}

		// A thought ends the step before it. It is the working that produced the NEXT
		// narration, not a tool call belonging to the last one, and left inside the
		// previous step it would read as part of a piece of work already finished.
		// It gets no step of its own: heading a group with a thought would make the
		// model's private reasoning the caption for its public actions.
		if (row.kind === 'think') step = null;

		currentStep(t).rows.push(row);
		t.nested += 1;

		// The turn is over. Anything after this is the user's, not the model's.
		if (row.kind === 'done') {
			turn = null;
			step = null;
		}
	}

	return turns;
};

/** One rendered line, with the depth it sits at. Flattening back out is what lets the
 *  tree render through a single `{#each}` — nested `{#each}` blocks would need the row
 *  markup, and its whole detail panel, written three times. */
export type ActivityNode<T> = {
	row: T;
	depth: number;
	/** Set when this row heads a collapsible group; the key to toggle. */
	group: string | null;
	/** Rows hidden when this group is collapsed. Zero for leaves. */
	nested: number;
};

/** Walk the tree into render order, skipping the contents of collapsed groups. */
export const flattenActivityTree = <T extends ActivityLike>(
	turns: ActivityTurn<T>[],
	collapsed: Record<string, boolean>
): ActivityNode<T>[] => {
	const out: ActivityNode<T>[] = [];

	for (const turn of turns) {
		let base = 0;
		if (turn.head) {
			out.push({ row: turn.head, depth: 0, group: turn.key, nested: turn.nested });
			if (collapsed[turn.key]) continue;
			base = 1;
		}

		for (const step of turn.steps) {
			let rowDepth = base;
			if (step.head) {
				out.push({
					row: step.head,
					depth: base,
					group: step.key,
					nested: step.rows.length
				});
				if (collapsed[step.key]) continue;
				rowDepth = base + 1;
			}
			for (const row of step.rows) out.push({ row, depth: rowDepth, group: null, nested: 0 });
		}
	}

	return out;
};
