// Agent Studio surface registry — feeds both the dynamic full-page route
// (`/harvis/agent-studio/[surface]`) and (Wave 2) the ChatControls dock-router.
// "One component, two mounts": each surface takes a `mode: 'full' | 'dock'` prop.

import Automations from './Automations.svelte';
import Schedules from './Schedules.svelte';
import Brain from './Brain.svelte';
import GlobalMap from './GlobalMap.svelte';
import ModelComparison from './ModelComparison.svelte';
import TuningPanel from './TuningPanel.svelte';
import GlobalArtifacts from './GlobalArtifacts.svelte';
import Cookbook from './Cookbook.svelte';
import Customize from './Customize.svelte';
import ConnectorsPanel from './customize/ConnectorsPanel.svelte';
import SkillsPanel from './customize/SkillsPanel.svelte';

export interface Surface {
	key: string;
	label: string;
	component: any;
	modes: ('full' | 'dock')[];
	// Marks a surface as not-yet-finished. One flag drives every entry point: the
	// full-page route shows a banner, and nav entries show a "WIP" chip so you know
	// before you click. Flip to false (or delete the line) when the surface is ready.
	underConstruction?: boolean;
}

export const surfaces: Surface[] = [
	// Renamed Automations → Routines (2026-07-12, coding lens of the cron store);
	// key stays 'automations' — VibeCodeNav + the ops page link to it. 'routines'
	// is an alias below. 'schedules' = the main-chat lens (same component with
	// context='chat' — fires post the reply into a chat instead of running).
	{ key: 'automations', label: 'Routines', component: Automations, modes: ['full'] },
	{ key: 'schedules', label: 'Schedules', component: Schedules, modes: ['full'] },
	{ key: 'brain', label: 'Brain', component: Brain, modes: ['full', 'dock'] },
	// Renamed Neural Map (2026-06-11); key stays 'global-map' — the dock bridge
	// values and the existing route depend on it. '/neural-map' is an alias below.
	{
		key: 'global-map',
		label: 'Neural Map',
		component: GlobalMap,
		modes: ['full', 'dock'],
		underConstruction: true
	},
	{ key: 'model-comparison', label: 'Model Comparison', component: ModelComparison, modes: ['full'] },
	{ key: 'activity', label: 'Artifacts', component: GlobalArtifacts, modes: ['full', 'dock'] },
	{ key: 'cookbook', label: 'Models', component: Cookbook, modes: ['full', 'dock'] },
	{ key: 'tuning', label: 'Tuning', component: TuningPanel, modes: ['full', 'dock'] },
	{ key: 'customize', label: 'Customize', component: Customize, modes: ['full'] },
	{ key: 'mcp-shop', label: 'Plugins', component: ConnectorsPanel, modes: ['full'] },
	// The other half of "what your agents can do" — paired with mcp-shop by the
	// Plugins | Skills switch at the top of both surfaces.
	{ key: 'skills', label: 'Skills', component: SkillsPanel, modes: ['full'] }
];

const KEY_ALIASES: Record<string, string> = {
	'neural-map': 'global-map',
	routines: 'automations'
};

export const surfaceByKey = (key: string): Surface | undefined =>
	surfaces.find((s) => s.key === (KEY_ALIASES[key] ?? key));
