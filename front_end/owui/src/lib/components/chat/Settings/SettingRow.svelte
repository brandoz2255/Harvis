<script lang="ts">
	// Shared presentational settings row: title + optional muted description on
	// the left, the control (default slot) on the right, vertically centered,
	// with a subtle bottom separator. Stacks into a column on narrow screens.
	// Purely presentational — bindings/handlers live in the slotted control.
	export let title = '';
	export let description = '';
	// Optional id placed on the title element so existing aria-labelledby
	// references keep resolving. Titles passed via the named slot carry their
	// own id instead.
	export let id: string | undefined = undefined;
	// stack: wide controls (textareas, lists, sliders) render below the text.
	export let stack = false;
	export let border = true;
</script>

<div
	class="w-full py-[1.125rem] {border
		? 'border-b border-gray-100 dark:border-gray-850 last:border-b-0'
		: ''} {stack
		? 'flex flex-col gap-2.5'
		: 'flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-6'}"
>
	<div class="min-w-0 {stack ? '' : 'sm:flex-1'}">
		<div {id} class="text-[15px] font-semibold leading-snug text-gray-900 dark:text-gray-100">
			{#if $$slots.title}<slot name="title" />{:else}{title}{/if}
		</div>
		{#if description || $$slots.description}
			<div class="mt-0.5 text-sm leading-snug text-gray-500 dark:text-gray-400">
				{#if $$slots.description}<slot name="description" />{:else}{description}{/if}
			</div>
		{/if}
	</div>
	<div class="flex items-center {stack ? 'w-full' : 'shrink-0 sm:justify-end'}">
		<slot />
	</div>
</div>
