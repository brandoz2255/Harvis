<script lang="ts">
	import { STATUS_META, type IntegrationStatus } from '$lib/integrations/catalog';
	export let status: IntegrationStatus = 'available';
	$: meta = STATUS_META[status] ?? STATUS_META.available;
</script>

<span class="inline-flex items-center gap-1.5 shrink-0 text-[11px] font-medium {meta.text}">
	<span class="size-1.5 rounded-full {meta.dot}"></span>{meta.label}
</span>
