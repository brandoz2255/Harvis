// Harvis Integrations — the capability layer (Phase A).
// Integrations belong to Harvis globally; every surface (Chat, Code, Notebook, Agent
// Studio, Automations) consumes them BY CAPABILITY. This file holds the typed capability
// vocabulary + display helpers. Pure data + pure functions, no fetch.
//
// Import direction is ONE-WAY to avoid a cycle: this module imports values from catalog.ts
// (STATUS_META, PREFERABLE_CAPABILITIES) + the IntegrationDefinition type; catalog.ts imports
// ONLY the union TYPES below (`import type`, erased at compile). So at runtime nothing in
// catalog.ts depends on this module.

import type { IntegrationDefinition } from './catalog';
import { STATUS_META, PREFERABLE_CAPABILITIES } from './catalog';

// What an integration provides. capability-first → engine second → adapter third.
export type IntegrationCapability =
	| 'model_provider'
	| 'tool_provider'
	| 'agent_runtime'
	| 'tool_runtime'
	| 'workflow_runtime'
	| 'code_engine_candidate'
	| 'repo_provider'
	| 'pr_provider'
	| 'notification_provider'
	| 'remote_execution_target'
	| 'local_execution_bridge'
	| 'document_provider'
	| 'research_runtime';

// Harvis surfaces that consume capabilities.
export type HarvisSurface = 'chat' | 'code' | 'notebook' | 'agent_studio' | 'automations';

// Where the integration comes from. `imported` = Phase B (never returned in Phase A).
export type IntegrationSource = 'static' | 'detected' | 'configured' | 'imported';

export const CAPABILITY_LABEL: Record<IntegrationCapability, string> = {
	model_provider: 'Model provider',
	tool_provider: 'Tool provider',
	agent_runtime: 'Agent runtime',
	tool_runtime: 'Tool runtime',
	workflow_runtime: 'Workflow runtime',
	code_engine_candidate: 'Code engine candidate',
	repo_provider: 'Repository provider',
	pr_provider: 'Pull-request provider',
	notification_provider: 'Notification provider',
	remote_execution_target: 'Remote execution target',
	local_execution_bridge: 'Local execution bridge',
	document_provider: 'Document provider',
	research_runtime: 'Research runtime'
};

export const SURFACE_LABEL: Record<HarvisSurface, string> = {
	chat: 'Chat',
	code: 'Build',
	notebook: 'Notebook',
	agent_studio: 'Agent Studio',
	automations: 'Automations'
};

const SOURCE_LABEL: Record<IntegrationSource, string> = {
	static: '',
	detected: 'Detected',
	configured: 'Configured',
	imported: 'Imported'
};

// Pure function of the MERGED def (status already overlaid by mergeLiveStatus). Fail-closed:
// a probe that didn't confirm presence stays `static` so we never imply a live connection.
export function deriveSource(def: IntegrationDefinition): IntegrationSource {
	const key = def.detect?.serviceKey;
	if (!key) return 'static';
	const live = def.status === 'ready' || def.status === 'running';
	// user-supplied connections
	if (key === 'github') return live ? 'configured' : 'static';
	if (key === 'mcp') return def.status !== 'available' && def.status !== 'error' ? 'configured' : 'static';
	// auto-probed services (no per-user config in Phase A)
	if (key === 'ollama' || key === 'openclaw' || key === 'discord' || key === 'hermes' || key === 'hermes-agent')
		return live ? 'detected' : 'static';
	return 'static';
}

// Single status/detail/source line (Card/Row drop their separate `· {detail}` in favor of this).
// e.g. "Ready · 12 models · Detected", "Ready · Connected · Configured", "Coming soon".
export function formatSourceLine(def: IntegrationDefinition): string {
	const statusLabel = STATUS_META[def.status]?.label ?? def.status;
	const src = deriveSource(def);
	const parts = [statusLabel];
	if (def.detail) parts.push(def.detail);
	if (src !== 'static') parts.push(SOURCE_LABEL[src]);
	return parts.join(' · ');
}

// Capabilities a user would pick a preferred provider for (drives the "Save preference" button).
export function preferableCapabilities(def: IntegrationDefinition): IntegrationCapability[] {
	return (def.provides ?? []).filter((c) => PREFERABLE_CAPABILITIES.includes(c));
}
