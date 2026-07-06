// Adaptive Workspace SURFACE ROUTER — the main canvas reshapes into the workbench
// the task needs, instead of showing the same static boards for everything. The
// Resource Board + Tool Dock become SUPPORT rails; the surface is the hero.
//
//   physical_3d_stage → 3D viewer + criteria + analysis (fabrication / image→3d)
//   repo_runner       → terminal workbench + file tree + setup tracker
//   generic_output    → the method's output slots (integration / content / research…)
//
// The surface comes from the detected method (template_key). Dedicated surfaces
// for integration/content/research can graduate from generic_output over time.

export type SurfaceId = 'physical_3d_stage' | 'repo_runner' | 'generic_output';

const SURFACE_BY_TEMPLATE: Record<string, SurfaceId> = {
	fabrication: 'physical_3d_stage',
	'image-to-3d': 'physical_3d_stage',
	'repo-runner': 'repo_runner'
};

export const surfaceFor = (templateKey: string): SurfaceId =>
	SURFACE_BY_TEMPLATE[templateKey] ?? 'generic_output';
