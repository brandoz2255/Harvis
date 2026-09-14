<script lang="ts" context="module">
	/** How a part is drawn. Presentation only — see the note on `displayMode` in
	 *  CadViewer. None of these touch geometry or any export. */
	export type CadDisplayMode = 'illustrated' | 'solid' | 'technical' | 'wireframe' | 'xray';

	export const CAD_DISPLAY_MODES: { id: CadDisplayMode; label: string; hint: string }[] = [
		{
			id: 'illustrated',
			label: 'Illustrated',
			hint: 'Flat bands, a silhouette and feature lines.'
		},
		{ id: 'solid', label: 'Solid', hint: 'Lit surfaces. Reads curvature best.' },
		{ id: 'technical', label: 'Technical', hint: 'Pale faces, drafting ink.' },
		{ id: 'wireframe', label: 'Wireframe', hint: 'The mesh itself.' },
		{ id: 'xray', label: 'X-ray', hint: 'Translucent, so an inner part shows through.' }
	];

	/** The clipping axis is named in the part's own frame — the same X/Y/Z the
	 *  validation bbox and every dimension in the conversation use. The viewport's
	 *  world axes are rotated from those and are never shown to anyone. */
	export type CadSectionAxis = 'x' | 'y' | 'z';

	/** Pointer tools. `move` and `rotate` drive the CS-8 gizmo, whose drag is a preview
	 *  and whose Apply creates a reviewed revision. They stay disabled wherever the host
	 *  cannot propose one — the chat card, the artifact preview — rather than rendering as
	 *  a control that silently does nothing. */
	export type CadTool = 'select' | 'move' | 'rotate';
</script>

<script lang="ts">
	// The floating viewport toolbar (CS-7).
	//
	// Every control here is a request to the viewer, which owns the camera, the meshes
	// and the clipping plane. This component holds no scene state of its own — it draws
	// buttons and reports presses — so there is exactly one place where "which view am I
	// on" can be answered.
	//
	// Two actions leave the canvas entirely: a snapshot has to be stored by whoever owns
	// renders, and "Edit with Harvis" has to reach the composer. Both arrive as
	// callbacks and their buttons are simply absent when the host passes none.
	import { getContext } from 'svelte';

	const i18n: any = getContext('i18n');

	export let tool: CadTool = 'select';
	export let displayMode: CadDisplayMode = 'illustrated';
	export let orthographic = false;
	export let showGrid = true;
	export let showOutlines = true;

	export let sectionOn = false;
	export let sectionAxis: CadSectionAxis = 'x';
	/** −1 … 1 across the part's extent on the chosen axis. */
	export let sectionOffset = 0;
	export let sectionFlipped = false;

	export let measureOn = false;
	/** Already-formatted millimetre readout, or '' when there is nothing to measure. */
	export let measureText = '';

	export let hasSelection = false;
	export let isolated = false;
	export let hiddenCount = 0;
	export let fullscreen = false;
	/** Tooltip for the move/rotate buttons wherever they cannot be used. */
	export let gizmoNote = '';
	/** Whether this host can turn a drag into a revision. False on the read-only surfaces,
	 *  where the buttons stay disabled and say why. */
	export let gizmoEnabled = false;

	export let onTool: (t: CadTool) => void = () => {};
	export let onDisplayMode: (m: CadDisplayMode) => void = () => {};
	export let onView: (v: string) => void = () => {};
	export let onProjection: (ortho: boolean) => void = () => {};
	export let onFrameSelected: () => void = () => {};
	export let onFrameAll: () => void = () => {};
	export let onHide: () => void = () => {};
	export let onIsolate: () => void = () => {};
	export let onShowAll: () => void = () => {};
	export let onToggleGrid: () => void = () => {};
	export let onToggleOutlines: () => void = () => {};
	export let onToggleMeasure: () => void = () => {};
	export let onSection: (
		next: Partial<{ on: boolean; axis: CadSectionAxis; offset: number; flipped: boolean }>
	) => void = () => {};
	export let onSnapshot: (() => void) | null = null;
	export let onEdit: (() => void) | null = null;
	export let onFullscreen: () => void = () => {};

	const VIEWS: { id: string; label: string }[] = [
		{ id: 'iso', label: 'Isometric' },
		{ id: 'front', label: 'Front' },
		{ id: 'rear', label: 'Rear' },
		{ id: 'left', label: 'Left' },
		{ id: 'right', label: 'Right' },
		{ id: 'top', label: 'Top' },
		{ id: 'bottom', label: 'Bottom' }
	];

	// One popover at a time: two open menus over a 3D canvas hide the thing they are
	// describing.
	let open: '' | 'views' | 'section' = '';
	const toggle = (which: typeof open) => (open = open === which ? '' : which);

	const btn =
		'size-7 flex items-center justify-center rounded-md border text-gray-600 dark:text-gray-300 transition disabled:opacity-40 disabled:cursor-not-allowed';
	// A separate base for the buttons that carry words, because `size-7 w-auto` is not a
	// reliable way to say "square unless there is text in it": `size-7` emits a real
	// `width`, and which of the two declarations wins is decided by their order in the
	// generated stylesheet rather than by their order in this attribute. It lost, so the
	// mode button was 1.75rem wide and "Solid" came out as "Soli" over "d". Height only,
	// and an explicit `whitespace-nowrap` so a label can never break across lines again.
	const textBtn =
		'h-7 px-2 flex items-center justify-center rounded-md border text-[10px] whitespace-nowrap text-gray-600 dark:text-gray-300 transition disabled:opacity-40 disabled:cursor-not-allowed';
	const idle =
		'bg-white/80 dark:bg-gray-850/80 border-gray-200 dark:border-gray-800 hover:bg-gray-100 dark:hover:bg-gray-800';
	const active =
		'bg-gray-900 text-white border-gray-900 dark:bg-white dark:text-gray-900 dark:border-white';
	const shell =
		'pointer-events-auto backdrop-blur-sm rounded-lg border border-gray-200 dark:border-gray-800 bg-white/70 dark:bg-gray-900/70 shadow-sm';
	const menu =
		'absolute z-20 min-w-[9.5rem] rounded-lg border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 shadow-lg p-1 text-[11px]';
	const item =
		'w-full text-left px-2 py-1 rounded-md hover:bg-gray-100 dark:hover:bg-gray-800 transition flex items-center justify-between gap-2';
</script>

<!-- The rail never eats pointer events on its own bounds; only the controls do, so a
     drag that starts beside a button still orbits the part. -->
<div class="pointer-events-none absolute inset-0">
	<!-- Tools, left edge. -->
	<div class="{shell} absolute left-2 top-2 flex flex-col gap-0.5 p-0.5">
		<button
			class="{btn} {tool === 'select' ? active : idle}"
			title={$i18n.t('Select a part')}
			aria-pressed={tool === 'select'}
			on:click={() => onTool('select')}
		>
			<svg viewBox="0 0 20 20" class="size-3.5" fill="currentColor"
				><path d="M4 3l11 6.2-4.6 1.1-1.6 4.5z" /></svg
			>
		</button>
		<button
			class="{btn} {tool === 'move' ? active : idle}"
			disabled={!gizmoEnabled || !hasSelection}
			aria-pressed={tool === 'move'}
			title={!gizmoEnabled
				? gizmoNote || $i18n.t('This view cannot propose changes.')
				: !hasSelection
					? $i18n.t('Select a part to move it.')
					: $i18n.t('Move the selected part. Apply creates a revision; Escape cancels.')}
			on:click={() => onTool('move')}
		>
			<svg viewBox="0 0 20 20" class="size-3.5" fill="none" stroke="currentColor" stroke-width="1.6"
				><path d="M10 3v14M3 10h14M10 3l-2 2M10 3l2 2M10 17l-2-2M10 17l2-2M3 10l2-2M3 10l2 2M17 10l-2-2M17 10l-2 2" /></svg
			>
		</button>
		<button
			class="{btn} {tool === 'rotate' ? active : idle}"
			disabled={!gizmoEnabled || !hasSelection}
			aria-pressed={tool === 'rotate'}
			title={!gizmoEnabled
				? gizmoNote || $i18n.t('This view cannot propose changes.')
				: !hasSelection
					? $i18n.t('Select a part to rotate it.')
					: $i18n.t('Rotate the selected part about its own centre. Apply creates a revision.')}
			on:click={() => onTool('rotate')}
		>
			<svg viewBox="0 0 20 20" class="size-3.5" fill="none" stroke="currentColor" stroke-width="1.6"
				><path d="M16 10a6 6 0 11-2.2-4.6" /><path d="M16 3v3h-3" /></svg
			>
		</button>

		<div class="h-px mx-1 my-0.5 bg-gray-200 dark:bg-gray-800"></div>

		<button
			class="{btn} {measureOn ? active : idle}"
			title={$i18n.t('Measure the selected part, or the whole model')}
			aria-pressed={measureOn}
			on:click={onToggleMeasure}
		>
			<svg viewBox="0 0 20 20" class="size-3.5" fill="none" stroke="currentColor" stroke-width="1.6"
				><rect x="2.5" y="6.5" width="15" height="7" rx="1" /><path
					d="M6 6.5v2M9 6.5v3M12 6.5v2M15 6.5v3"
				/></svg
			>
		</button>
		<div class="relative">
			<button
				class="{btn} {sectionOn ? active : idle}"
				title={$i18n.t('Section view')}
				aria-pressed={sectionOn}
				on:click={() => toggle('section')}
			>
				<svg
					viewBox="0 0 20 20"
					class="size-3.5"
					fill="none"
					stroke="currentColor"
					stroke-width="1.6"><path d="M3 15l7-11 7 11z" /><path d="M6 11h8" /></svg
				>
			</button>
			{#if open === 'section'}
				<div class="{menu} left-9 top-0 w-52">
					<label class="flex items-center justify-between px-2 py-1">
						<span>{$i18n.t('Section view')}</span>
						<input
							type="checkbox"
							checked={sectionOn}
							on:change={(e) => onSection({ on: e.currentTarget.checked })}
						/>
					</label>
					<div class="flex gap-1 px-2 py-1">
						{#each ['x', 'y', 'z'] as ax}
							<button
								class="flex-1 py-0.5 rounded-md border text-[10px] uppercase transition {sectionAxis ===
								ax
									? active
									: idle}"
								on:click={() => onSection({ on: true, axis: ax })}>{ax}</button
							>
						{/each}
						<button
							class="px-1.5 py-0.5 rounded-md border text-[10px] transition {sectionFlipped
								? active
								: idle}"
							title={$i18n.t('Keep the other half')}
							on:click={() => onSection({ on: true, flipped: !sectionFlipped })}>±</button
						>
					</div>
					<input
						class="w-full px-2"
						type="range"
						min="-1"
						max="1"
						step="0.01"
						value={sectionOffset}
						on:input={(e) => onSection({ on: true, offset: Number(e.currentTarget.value) })}
					/>
					<p class="px-2 pb-1 pt-0.5 text-[10px] leading-tight text-gray-400 dark:text-gray-500">
						{$i18n.t('A cut in the viewport only. Exports are unchanged.')}
					</p>
				</div>
			{/if}
		</div>
	</div>

	<!-- Display mode, top centre.
	     It lived in the bottom bar as a dropdown whose trigger printed the current mode's
	     name. Two things were wrong with that: the label wrapped, and a dropdown hides the
	     answer to "which mode am I looking at" behind a click at the exact moment the
	     viewport looks wrong and that is the first thing worth checking. Laid out flat and
	     put at the top, the current mode is readable without touching anything and any
	     other mode is one click away. -->
	<div
		class="{shell} absolute top-2 left-1/2 -translate-x-1/2 flex items-center gap-0.5 p-0.5"
		title={$i18n.t('Presentation only. Every export is byte-for-byte unchanged.')}
	>
		{#each CAD_DISPLAY_MODES as m}
			<button
				class="{textBtn} {m.id === displayMode ? active : idle}"
				title="{$i18n.t(m.label)} — {$i18n.t(m.hint)}"
				aria-pressed={m.id === displayMode}
				on:click={() => onDisplayMode(m.id)}>{$i18n.t(m.label)}</button
			>
		{/each}
	</div>

	{#if measureOn && measureText}
		<div
			class="{shell} absolute left-12 top-2 px-2 py-1 text-[10px] tabular-nums text-gray-600 dark:text-gray-300"
		>
			{measureText}
		</div>
	{/if}

	<!-- Camera, visibility and display, bottom centre. -->
	<div class="{shell} absolute bottom-2 left-1/2 -translate-x-1/2 flex items-center gap-0.5 p-0.5">
		<div class="relative">
			<button
				class="{btn} {idle}"
				title={$i18n.t('Standard views')}
				on:click={() => toggle('views')}
			>
				<svg
					viewBox="0 0 20 20"
					class="size-3.5"
					fill="none"
					stroke="currentColor"
					stroke-width="1.5"
					><path d="M10 2.5l6.5 3.7v7.6L10 17.5 3.5 13.8V6.2z" /><path
						d="M3.5 6.2L10 10l6.5-3.8M10 10v7.5"
					/></svg
				>
			</button>
			{#if open === 'views'}
				<div class="{menu} bottom-9 left-0">
					{#each VIEWS as v}
						<button class={item} on:click={() => (onView(v.id), (open = ''))}
							>{$i18n.t(v.label)}</button
						>
					{/each}
				</div>
			{/if}
		</div>
		<button
			class="{btn} {orthographic ? active : idle}"
			title={orthographic
				? $i18n.t('Orthographic. Click for perspective.')
				: $i18n.t('Perspective. Click for orthographic.')}
			aria-pressed={orthographic}
			on:click={() => onProjection(!orthographic)}
		>
			<svg viewBox="0 0 20 20" class="size-3.5" fill="none" stroke="currentColor" stroke-width="1.5"
				>{#if orthographic}<rect x="3" y="5" width="11" height="10" /><path
						d="M6 3h11v10M6 3L3 5M17 3l-3 2M17 13l-3 2"
					/>{:else}<path d="M3 4l14 3v6l-14 3z" /><path d="M3 7h14M3 13h14" />{/if}</svg
			>
		</button>
		<button
			class="{btn} {idle}"
			title={$i18n.t('Frame the selected part')}
			disabled={!hasSelection}
			on:click={onFrameSelected}
		>
			<svg viewBox="0 0 20 20" class="size-3.5" fill="none" stroke="currentColor" stroke-width="1.6"
				><path d="M3 7V3h4M17 7V3h-4M3 13v4h4M17 13v4h-4" /><rect x="8" y="8" width="4" height="4" /></svg
			>
		</button>
		<button class="{btn} {idle}" title={$i18n.t('Frame the whole model')} on:click={onFrameAll}>
			<svg viewBox="0 0 20 20" class="size-3.5" fill="none" stroke="currentColor" stroke-width="1.6"
				><path d="M3 7V3h4M17 7V3h-4M3 13v4h4M17 13v4h-4" /></svg
			>
		</button>

		<div class="w-px h-5 mx-0.5 bg-gray-200 dark:bg-gray-800"></div>

		<button
			class="{btn} {idle}"
			title={$i18n.t('Hide the selected part')}
			disabled={!hasSelection}
			on:click={onHide}
		>
			<svg viewBox="0 0 20 20" class="size-3.5" fill="none" stroke="currentColor" stroke-width="1.6"
				><path d="M3 10s2.8-4.5 7-4.5S17 10 17 10s-2.8 4.5-7 4.5S3 10 3 10z" /><path d="M4 4l12 12" /></svg
			>
		</button>
		<button
			class="{btn} {isolated ? active : idle}"
			title={$i18n.t('Show only the selected part')}
			disabled={!hasSelection && !isolated}
			aria-pressed={isolated}
			on:click={onIsolate}
		>
			<svg viewBox="0 0 20 20" class="size-3.5" fill="none" stroke="currentColor" stroke-width="1.6"
				><circle cx="10" cy="10" r="3" /><path d="M10 2v2M10 16v2M2 10h2M16 10h2" /></svg
			>
		</button>
		<button
			class="{btn} {idle}"
			title={$i18n.t('Show every part')}
			disabled={hiddenCount === 0 && !isolated}
			on:click={onShowAll}
		>
			<svg viewBox="0 0 20 20" class="size-3.5" fill="none" stroke="currentColor" stroke-width="1.6"
				><path d="M3 10s2.8-4.5 7-4.5S17 10 17 10s-2.8 4.5-7 4.5S3 10 3 10z" /><circle
					cx="10"
					cy="10"
					r="1.8"
				/></svg
			>
		</button>

		<div class="w-px h-5 mx-0.5 bg-gray-200 dark:bg-gray-800"></div>

		<button
			class="{btn} {showGrid ? active : idle}"
			title={$i18n.t('Grid')}
			aria-pressed={showGrid}
			on:click={onToggleGrid}
		>
			<svg viewBox="0 0 20 20" class="size-3.5" fill="none" stroke="currentColor" stroke-width="1.4"
				><path d="M3 3h14v14H3z" /><path d="M8 3v14M13 3v14M3 8h14M3 13h14" /></svg
			>
		</button>
		<button
			class="{btn} {showOutlines ? active : idle}"
			title={$i18n.t('Outlines')}
			aria-pressed={showOutlines}
			on:click={onToggleOutlines}
		>
			<svg viewBox="0 0 20 20" class="size-3.5" fill="none" stroke="currentColor" stroke-width="1.8"
				><rect x="3.5" y="5" width="13" height="10" rx="1.5" /></svg
			>
		</button>

		{#if onSnapshot || onEdit}
			<div class="w-px h-5 mx-0.5 bg-gray-200 dark:bg-gray-800"></div>
		{/if}
		{#if onSnapshot}
			<button class="{btn} {idle}" title={$i18n.t('Capture this view')} on:click={onSnapshot}>
				<svg
					viewBox="0 0 20 20"
					class="size-3.5"
					fill="none"
					stroke="currentColor"
					stroke-width="1.5"
					><path d="M3 6.5h3l1.2-2h5.6L14 6.5h3v9H3z" /><circle cx="10" cy="11" r="2.6" /></svg
				>
			</button>
		{/if}
		{#if onEdit}
			<button
				class="{textBtn} {idle}"
				title={$i18n.t('Send the selected part to the conversation')}
				disabled={!hasSelection}
				on:click={onEdit}
			>
				{$i18n.t('Edit with Harvis')}
			</button>
		{/if}
		<button
			class="{btn} {fullscreen ? active : idle}"
			title={fullscreen ? $i18n.t('Leave fullscreen') : $i18n.t('Fullscreen')}
			aria-pressed={fullscreen}
			on:click={onFullscreen}
		>
			<svg viewBox="0 0 20 20" class="size-3.5" fill="none" stroke="currentColor" stroke-width="1.6"
				>{#if fullscreen}<path d="M8 3v5H3M12 17v-5h5" />{:else}<path
						d="M3 7V3h4M17 7V3h-4M3 13v4h4M17 13v4h-4"
					/>{/if}</svg
			>
		</button>
	</div>
</div>
