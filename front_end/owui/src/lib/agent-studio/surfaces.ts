// Agent Studio surface registry — feeds both the dynamic full-page route
// (`/harvis/agent-studio/[surface]`) and (Wave 2) the ChatControls dock-router.
// "One component, two mounts": each surface takes a `mode: 'full' | 'dock'` prop.

import Automations from './Automations.svelte';
import Brain from './Brain.svelte';
import GlobalMap from './GlobalMap.svelte';
import ModelComparison from './ModelComparison.svelte';
import TuningPanel from './TuningPanel.svelte';
import GlobalArtifacts from './GlobalArtifacts.svelte';
import Cookbook from './Cookbook.svelte';

export interface Surface {
	key: string;
	label: string;
	component: any;
	modes: ('full' | 'dock')[];
}

export const surfaces: Surface[] = [
	{ key: 'automations', label: 'Automations', component: Automations, modes: ['full'] },
	{ key: 'brain', label: 'Brain', component: Brain, modes: ['full', 'dock'] },
	// Renamed Neural Map (2026-06-11); key stays 'global-map' — the dock bridge
	// values and the existing route depend on it. '/neural-map' is an alias below.
	{ key: 'global-map', label: 'Neural Map', component: GlobalMap, modes: ['full', 'dock'] },
	{ key: 'model-comparison', label: 'Model Comparison', component: ModelComparison, modes: ['full'] },
	{ key: 'activity', label: 'Artifacts', component: GlobalArtifacts, modes: ['full', 'dock'] },
	{ key: 'cookbook', label: 'Cookbook', component: Cookbook, modes: ['full', 'dock'] },
	{ key: 'tuning', label: 'Tuning', component: TuningPanel, modes: ['full', 'dock'] }
];

export const surfaceByKey = (key: string): Surface | undefined =>
	surfaces.find((s) => s.key === (key === 'neural-map' ? 'global-map' : key));
