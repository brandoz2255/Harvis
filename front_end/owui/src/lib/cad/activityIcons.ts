// The stops on a CAD activity timeline: which glyph a row gets, what colour it is
// tinted, and how a duration reads.
//
// Shared because the timeline now appears on two surfaces — the workspace panel and
// the card in chat — and a wrench that means "tool" in one place and something else in
// the other is worse than no icon at all. One definition, both readers.

import ChatBubble from '$lib/components/icons/ChatBubble.svelte';
import CheckCircle from '$lib/components/icons/CheckCircle.svelte';
import Cube from '$lib/components/icons/Cube.svelte';
import Folder from '$lib/components/icons/Folder.svelte';
import Keyframes from '$lib/components/icons/Keyframes.svelte';
import LightBulb from '$lib/components/icons/LightBulb.svelte';
import PhotoSolid from '$lib/components/icons/PhotoSolid.svelte';
import SparklesSolid from '$lib/components/icons/SparklesSolid.svelte';
import TaskList from '$lib/components/icons/TaskList.svelte';
import WrenchSolid from '$lib/components/icons/WrenchSolid.svelte';

/** Only the fields the stop is decided from. Both `CadActivityEvent` (project-scoped)
 *  and `CadJobEvent` (one turn) satisfy it, which is the point — the two row types
 *  differ in what they carry, never in what a `tool` row means. */
export type ActivityStop = {
	kind: string;
	ok?: boolean;
	status?: string;
};

/** The icon at a row's stop. It says what KIND of event this is — a tool, a thought, a
 *  picture — and nothing about whether it went well; that is the tint's job below, and
 *  the verdict itself is written out in the row's own detail. */
export const activityIcon = (ev: ActivityStop) =>
	({
		started: SparklesSolid,
		spec: TaskList,
		say: ChatBubble,
		think: LightBulb,
		tool: WrenchSolid,
		project: Folder,
		build: Cube,
		done: CheckCircle,
		revision: Keyframes,
		accepted: CheckCircle,
		render: PhotoSolid
	})[ev.kind] ?? WrenchSolid;

/** The stop's colour, and nothing more than that. A row's verdict is written out in its
 *  own detail line — a colour is not a claim this timeline is willing to make on its
 *  own. */
export const activityTint = (ev: ActivityStop) => {
	if (ev.kind === 'build')
		return ev.status === 'succeeded'
			? 'text-emerald-500'
			: ev.status === 'failed'
				? 'text-red-500'
				: 'text-gray-400';
	if (ev.kind === 'accepted' || ev.kind === 'done') return 'text-emerald-500';
	if (ev.kind === 'revision') return 'text-sky-500';
	// The model talking, and the model thinking, which are a different sort of row from
	// anything the system records about it — hence their own colour.
	if (ev.kind === 'say' || ev.kind === 'think' || ev.kind === 'started') return 'text-violet-400';
	// The request as the server read it, before the model saw it. Its own colour because
	// it is the only row that is neither the model's doing nor the system's report of it
	// — it is the requirement the rest is judged against.
	if (ev.kind === 'spec') return 'text-teal-500';
	// A picture is neither a claim nor a step — it is a thing to look at.
	if (ev.kind === 'render') return 'text-gray-400';
	if (ev.kind === 'tool')
		return ev.ok === false ? 'text-amber-500' : 'text-gray-400 dark:text-gray-500';
	return 'text-gray-400 dark:text-gray-500';
};

/** Minutes above a minute and a half. A three-minute build reading "184.7 s" is
 *  arithmetic the reader has to finish themselves. */
export const formatDuration = (ms?: number | null) => {
	if (ms === undefined || ms === null) return '';
	if (ms < 1000) return `${ms} ms`;
	if (ms < 90_000) return `${(ms / 1000).toFixed(1)} s`;
	const total = Math.round(ms / 1000);
	const m = Math.floor(total / 60);
	const s = total % 60;
	return s ? `${m} min ${s} s` : `${m} min`;
};
