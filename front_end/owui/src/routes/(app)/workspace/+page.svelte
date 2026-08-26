<script lang="ts">
	import { goto } from '$app/navigation';
	import { config, user } from '$lib/stores';
	import { onMount } from 'svelte';

	// Landing tab for /workspace. Models and Prompts are skipped unless their
	// feature flag turns them back on — they are unbacked in the Harvis facade,
	// so landing there would open a page that cannot load or save anything.
	const modelsOn = () => $config?.features?.enable_workspace_models ?? false;
	const promptsOn = () => $config?.features?.enable_workspace_prompts ?? false;

	onMount(() => {
		if ($user?.role !== 'admin') {
			if (modelsOn() && $user?.permissions?.workspace?.models) {
				goto('/workspace/models');
			} else if ($user?.permissions?.workspace?.knowledge) {
				goto('/workspace/knowledge');
			} else if (promptsOn() && $user?.permissions?.workspace?.prompts) {
				goto('/workspace/prompts');
			} else if ($user?.permissions?.workspace?.skills) {
				goto('/workspace/skills');
			} else if ($user?.permissions?.workspace?.tools) {
				goto('/workspace/tools');
			} else {
				goto('/');
			}
		} else {
			goto(modelsOn() ? '/workspace/models' : '/workspace/knowledge');
		}
	});
</script>
