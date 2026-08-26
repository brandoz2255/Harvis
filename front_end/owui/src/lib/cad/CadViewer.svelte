<script lang="ts">
	// Viewport for a real, authorized CAD artifact. No procedural geometry, no
	// synthetic overlays — what renders here is the bytes the engine produced.
	//
	// The artifact route requires an Authorization header, so the file cannot be
	// handed to a loader by URL: it is fetched into an ArrayBuffer and parsed from
	// memory. That is also what makes the self-containment check below possible.
	//
	// GLB is the display format. STL is the fallback for a build whose formats did
	// not include GLB — it carries no material or node information, which is fine for
	// looking at a part and useless for anything else.
	import { getContext, onMount, onDestroy } from 'svelte';
	import * as THREE from 'three';
	import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
	import { TransformControls } from 'three/addons/controls/TransformControls.js';
	import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
	import { STLLoader } from 'three/addons/loaders/STLLoader.js';
	import { mergeVertices } from 'three/addons/utils/BufferGeometryUtils.js';
	import CadViewportToolbar, { CAD_DISPLAY_MODES } from './CadViewportToolbar.svelte';
	import type { CadDisplayMode, CadSectionAxis, CadTool } from './CadViewportToolbar.svelte';

	const i18n: any = getContext('i18n');

	/** Authorized artifact URL. Changing it reloads the viewport. */
	export let url = '';
	export let format: 'glb' | 'stl' = 'glb';
	/** Height of the canvas. The panel is a narrow column; the chat card is shorter. */
	export let height = 340;

	/** Node id selected elsewhere in the workspace. The matching body is highlighted;
	 *  an id this GLB does not carry highlights nothing, which is the honest result —
	 *  a feature row or a node from another revision has no geometry of its own here. */
	export let selectedNodeId = '';
	/** Called with the node id under the pointer, or '' when the click landed on empty
	 *  space. Null disables picking, so the STL fallback and the read-only chat card
	 *  do not offer a selection the rest of the surface cannot honour. */
	export let onPick: ((id: string) => void) | null = null;

	/** Node id → hex colour, straight from the scene manifest (CS-2). The engine
	 *  decides which part is which colour so the tree swatch and the body on screen
	 *  cannot drift apart; a body missing from the map falls back to `DEFAULT_COLOR`,
	 *  which is also what an STL — carrying no node information at all — gets. */
	export let nodeColors: Record<string, string> = {};

	/** How the part is drawn (CS-5, extended in CS-7). `illustrated` is the default:
	 *  banded toon shading, a silhouette, and feature lines — the look of a technical
	 *  illustration rather than a render.
	 *
	 *  This is presentation and nothing else. It changes materials on the meshes three
	 *  already built; it never touches vertices, and the STEP/STL/GLB the engine wrote
	 *  are untouched by it. A part that measures 32 mm still measures 32 mm with the
	 *  outline on.
	 *
	 *  `solid` is the lit surface, kept because smooth shading reads a curve better than
	 *  a banded one. `technical` is flat drafting ink on pale faces. `wireframe` shows
	 *  the mesh itself. `xray` makes the bodies translucent so an interior part can be
	 *  seen through the ones in front of it. */
	export let displayMode: CadDisplayMode = 'illustrated';

	/** Called when the toolbar's snapshot button is pressed. The viewport can render a
	 *  picture but has nowhere to put one — the host owns renders — so this is a
	 *  callback rather than a local action, and the button is absent when there is no
	 *  host to take it. */
	export let onSnapshot: (() => void) | null = null;
	/** Called with the selected node id when "Edit with Harvis" is pressed. Same reason:
	 *  the composer belongs to the workspace, not to the canvas. */
	export let onEditSelected: ((id: string) => void) | null = null;
	/** Called when a move/rotate preview is accepted (CS-8). The viewport never writes a
	 *  revision itself — it hands the host a placement in the document's own millimetres
	 *  and degrees, and the host turns that into a CadIR proposal that the engine rebuilds
	 *  and validates. Absent means no gizmo: the chat card and the artifact preview have
	 *  no revision to propose against. Rejecting the promise leaves the preview standing
	 *  so the drag is not lost to a failed request. */
	export let onPropose:
		| ((p: {
				nodeId: string;
				translate: [number, number, number];
				rotate: [number, number, number];
		  }) => Promise<void>)
		| null = null;
	/** Why the move/rotate tools are unavailable, when the host knows a more specific
	 *  reason than "this view cannot propose changes" — an older revision, or a part built
	 *  from a recipe rather than a document. Blank falls back to the general wording. */
	export let gizmoNote = '';
	/** The floating toolbar (CS-7). Off for the read-only chat card and the artifact
	 *  preview, which have no workspace around them to act on. */
	export let toolbar = false;

	/** The build's own bounding box in millimetres, from `validation.bbox_mm`. The
	 *  measure tool needs one true length to calibrate against, because a mesh file does
	 *  not agree with itself about units: glTF is metres by specification, STL carries no
	 *  units at all, and this engine writes it in millimetres. Rather than hard-code that
	 *  per format, the viewer scales its own geometry against a number the engine
	 *  measured — so the readout is a real measurement of the mesh, expressed in the same
	 *  units the rest of the workspace already shows. Null falls back to the format
	 *  convention and is only reached where no build is attached. */
	export let bboxMm: { x: number; y: number; z: number } | null = null;

	const authHdr = () => ({ Authorization: `Bearer ${localStorage.token}` });

	let shell: HTMLDivElement;
	let container: HTMLDivElement;
	let renderer: THREE.WebGLRenderer;
	let scene: THREE.Scene;
	// Both cameras exist for the life of the component and share a pose. Switching
	// projection is a swap, not a rebuild — rebuilding would drop the user's orbit.
	let perspCam: THREE.PerspectiveCamera;
	let orthoCam: THREE.OrthographicCamera;
	let camera: THREE.Camera;
	let controls: OrbitControls;
	let grid: THREE.GridHelper;
	let ro: ResizeObserver;
	let raf = 0;
	let mounted = false;

	let part: THREE.Object3D | null = null;
	/** World units per model unit, from `placePart`. Every millimetre readout divides
	 *  by this, so the measure tool and the engine's own bbox agree. */
	let partScale = 1;
	/** Longest edge of the loaded file in the file's own units, before `placePart`
	 *  normalizes it. Paired with `bboxMm` this is what turns a mesh extent into a
	 *  millimetre, whatever the file thought it was measuring in. */
	let sourceMax = 0;
	let loading = false;
	let error = '';
	let loadToken = 0; // guards against a slow load landing after a newer one

	// ---- Toolbar state (CS-7) ----------------------------------------------
	let tool: CadTool = 'select';
	let orthographic = false;
	let showGrid = true;
	let showOutlines = true;
	let fullscreen = false;

	/** Bodies the user hid, and the one body isolation is showing. Isolation wins
	 *  while it is on — that is what makes "show all" a single honest reset. */
	let hiddenIds = new Set<string>();
	let isolatedId = '';

	let sectionOn = false;
	let sectionAxis: CadSectionAxis = 'x';
	let sectionOffset = 0;
	let sectionFlipped = false;
	const clipPlane = new THREE.Plane(new THREE.Vector3(1, 0, 0), 0);

	let measureOn = false;
	let measureText = '';

	// Selection (UX-D). `bodies` is built once per load from the ids the engine wrote
	// into the GLB; nothing here infers a part from triangles.
	let bodies = new Map<string, THREE.Mesh[]>();
	let highlighted: { mesh: THREE.Mesh; material: THREE.Material | THREE.Material[] }[] = [];
	let appliedSelection = '';
	const raycaster = new THREE.Raycaster();
	const ndc = new THREE.Vector2();
	let pointerStart: { x: number; y: number } | null = null;

	const FIT = 3.0; // world units the longest edge is scaled to
	const INIT_CAM = new THREE.Vector3(3.4, 2.6, 4.2);

	const reduced =
		typeof window !== 'undefined' &&
		window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

	const render = () => {
		if (renderer && scene && camera) renderer.render(scene, camera);
	};

	// A GLB that references an external buffer or image would render as a silent
	// hole — GLTFLoader.parse with an empty path cannot resolve one, and the failure
	// arrives as an unhelpful network error. Reading the JSON chunk first turns that
	// into a specific, true statement about the file.
	const assertSelfContained = (buf: ArrayBuffer) => {
		const dv = new DataView(buf);
		if (buf.byteLength < 20 || dv.getUint32(0, true) !== 0x46546c67) return; // not GLB
		let off = 12;
		while (off + 8 <= buf.byteLength) {
			const len = dv.getUint32(off, true);
			const type = dv.getUint32(off + 4, true);
			if (type === 0x4e4f534a) {
				const json = JSON.parse(
					new TextDecoder().decode(new Uint8Array(buf, off + 8, len))
				);
				const external = [...(json.buffers ?? []), ...(json.images ?? [])].some(
					(r: any) => typeof r?.uri === 'string' && !r.uri.startsWith('data:')
				);
				if (external) {
					throw new Error('this GLB references an external file and cannot be rendered');
				}
				return;
			}
			off += 8 + len + ((4 - (len % 4)) % 4);
		}
	};

	const disposeObject = (o: THREE.Object3D) => {
		o.traverse((n: any) => {
			n.geometry?.dispose?.();
			const mats = Array.isArray(n.material) ? n.material : n.material ? [n.material] : [];
			for (const m of mats) {
				for (const k of Object.keys(m)) {
					const v = (m as any)[k];
					if (v && v.isTexture) v.dispose();
				}
				m.dispose?.();
			}
		});
	};

	const clearPart = () => {
		// The highlight list is dropped rather than restored: its meshes belong to the
		// object about to be disposed, and putting materials back on it first would only
		// give `disposeObject` two sets to free instead of one.
		highlighted = [];
		appliedSelection = '';
		bodies = new Map();
		// The decorations are children of the meshes being disposed below, so they go
		// with them; only the bookkeeping needs clearing.
		decorations = [];
		// The pivot and everything reparented under it are descendants of `part`, so the
		// dispose below reaches them; only the gizmo itself lives in the scene and has to
		// be taken down explicitly. Reparenting first would be wasted work.
		teardownGizmo();
		if (!part) return;
		scene.remove(part);
		disposeObject(part);
		part = null;
	};

	// ------------------------------------------------------------------
	// Selection (UX-D)
	//
	// The engine writes the same opaque node id into `node.name` and into
	// `node.extras.harvis_node_id` for every mesh-bearing node of a selectable body
	// (`cad-engine/manifest.py:tag_glb`). GLTFLoader surfaces those as `object.name`
	// and `object.userData.harvis_node_id`. Reading either is what makes a viewport
	// click and a tree row agree on what was selected — nothing is reconstructed from
	// geometry, so a click either lands on a body the manifest named or on nothing.
	// ------------------------------------------------------------------
	const NODE_ID_RE = /^node_[0-9a-f]{16}$/;

	const nodeIdOf = (o: THREE.Object3D | null): string => {
		// A glTF mesh with several primitives arrives as a group whose children are the
		// meshes, so the id can sit one or more levels above the hit object.
		for (let n: any = o; n; n = n.parent) {
			const extra = n.userData?.harvis_node_id;
			if (typeof extra === 'string' && extra) return extra;
			if (typeof n.name === 'string' && NODE_ID_RE.test(n.name)) return n.name;
		}
		return '';
	};

	/** The blue a body gets when the manifest has nothing to say about it — an STL, or a
	 *  build whose engine predates per-part colours. */
	const DEFAULT_COLOR = '#9EC5E8';

	// ------------------------------------------------------------------
	// Illustrated presentation (CS-5)
	//
	// Three pieces make the look, all of them ordinary three.js:
	//
	//   1. `MeshToonMaterial` with a four-step gradient, so light lands in bands
	//      instead of a gradient. The bands are what stop it reading as a render.
	//   2. An inverted hull — the same geometry drawn back-faces-only, pushed out
	//      along its normals — which is the silhouette. This is the part
	//      `EdgesGeometry` cannot do: the outline of a cylinder is not an edge of the
	//      mesh, it moves as the camera moves.
	//   3. `EdgesGeometry` feature lines at a 30° threshold, which draws the real
	//      creases (a fillet's boundary, a pocket's rim) and leaves tessellation
	//      facets alone.
	//
	// The offset is scaled by view depth so the silhouette keeps roughly the same
	// screen thickness whether the part is near or far — a constant world-space offset
	// looks like a hairline when zoomed out and a fat border when zoomed in.
	//
	// The thickness is stated in *pixels* and converted, because the raw view-space
	// number is unreadable and the first version of this got it badly wrong: 0.008 on a
	// 42° camera over a 700px canvas is 7px of outline, and 7px of back-face on a flat
	// CAD face does not read as a line — it reads as a slab standing beside the part.
	// An inverted hull is only an outline while it is thin.
	// ------------------------------------------------------------------
	// Two inks, because the two lines are drawn against different things. The feature
	// lines sit on the part's own surface, which is always a pale body colour, so they
	// are dark in every theme. The silhouette is drawn *outside* the part, against the
	// viewport background — a dark rim on a dark viewport is invisible, which is exactly
	// what the first build of this looked like. It follows the theme instead.
	const EDGE_INK = 0x1f2937;
	// Near-white rather than the mid-grey this used to be. The old value sat between the
	// body colour and the background, so at any honest line width it read as an
	// anti-aliasing artefact rather than as a line someone drew — the outline was
	// present and still looked missing. Ink has to be the furthest thing on screen from
	// what it is drawn against.
	const SILHOUETTE_ON_DARK = 0xeef2f8;
	const SILHOUETTE_ON_LIGHT = 0x111827;
	const EDGE_ANGLE = 30;
	/** Target silhouette width on screen.
	 *
	 *  This was 1.6px, which is a hairline: technically an outline, but nothing anyone
	 *  would call a cartoon. The look being aimed at is an inked drawing, and ink is
	 *  heavy — so it sits at five, which reads as a deliberate line at every zoom without
	 *  swallowing small features. Measured on the live jar: past about eight the hull
	 *  stops reading as a line around the part and starts reading as a second, larger
	 *  part standing behind it. */
	const OUTLINE_PX = 5.0;

	/** Pixels → the view-space offset the hull shader wants.
	 *
	 *  Under perspective, a point at view depth `d` moved by `t * d` along the view-space
	 *  normal lands `t * (h/2) / tan(fov/2)` pixels away after projection — the depth
	 *  cancels, which is what makes the outline depth-independent. Inverting that gives `t`.
	 *
	 *  An orthographic projection has no depth divide, so the same `t * d` scaling would
	 *  make the outline grow with distance. There the offset is a flat view-space number:
	 *  frustum height over canvas height, times the pixels wanted. The shader is told which
	 *  case it is in rather than guessing from the matrix. */
	const outlineThickness = () => {
		const h = container?.clientHeight ?? 0;
		if (h < 2) return 0.0018;
		if (orthographic && orthoCam) {
			const frustumH = (orthoCam.top - orthoCam.bottom) / (orthoCam.zoom || 1);
			return (OUTLINE_PX * frustumH) / h;
		}
		if (!perspCam) return 0.0018;
		return (OUTLINE_PX * Math.tan((perspCam.fov * Math.PI) / 360)) / (h / 2);
	};

	let darkTheme = true;
	let themeWatch: MutationObserver | null = null;
	const readTheme = () =>
		typeof document !== 'undefined' && document.documentElement.classList.contains('dark');

	/** Four flat steps. A DataTexture with nearest filtering is the standard way to
	 *  give MeshToonMaterial hard bands; anything smoother defeats the point. */
	let toonGradient: THREE.DataTexture | null = null;
	const gradientMap = () => {
		if (!toonGradient) {
			toonGradient = new THREE.DataTexture(
				new Uint8Array([88, 145, 200, 255]),
				4,
				1,
				THREE.RedFormat
			);
			toonGradient.minFilter = THREE.NearestFilter;
			toonGradient.magFilter = THREE.NearestFilter;
			toonGradient.generateMipmaps = false;
			toonGradient.needsUpdate = true;
		}
		return toonGradient;
	};

	/** The surface material for one body under the current display mode.
	 *
	 *  Every branch keeps `color` on the material, because `recolor()` writes the
	 *  manifest colour straight onto it when the map changes — a mode whose material had
	 *  no colour channel would silently stop tracking the tree's swatches. */
	const bodyMaterial = (id: string) => {
		const color = new THREE.Color(nodeColors[id] || DEFAULT_COLOR);
		switch (displayMode) {
			case 'solid':
				return new THREE.MeshStandardMaterial({ color, metalness: 0.1, roughness: 0.65 });
			case 'technical':
				// Drafting ink wants pale faces: the body colour is kept, but washed most of
				// the way to white so the lines carry the drawing.
				return new THREE.MeshBasicMaterial({
					color: color.clone().lerp(new THREE.Color(0xffffff), 0.72)
				});
			case 'wireframe':
				return new THREE.MeshBasicMaterial({ color, wireframe: true });
			case 'xray':
				// depthWrite off is what lets a part behind another one show through; with it
				// on, the front body still fills the depth buffer and hides everything.
				return new THREE.MeshStandardMaterial({
					color,
					metalness: 0.0,
					roughness: 0.9,
					transparent: true,
					opacity: 0.28,
					depthWrite: false,
					side: THREE.DoubleSide
				});
			default:
				return new THREE.MeshToonMaterial({ color, gradientMap: gradientMap() });
		}
	};

	const outlineMaterial = () =>
		new THREE.ShaderMaterial({
			uniforms: {
				thickness: { value: outlineThickness() },
				perspective: { value: orthographic ? 0 : 1 },
				outlineColor: {
					value: new THREE.Color(darkTheme ? SILHOUETTE_ON_DARK : SILHOUETTE_ON_LIGHT)
				}
			},
			vertexShader: `
				uniform float thickness;
				uniform float perspective;
				void main() {
					vec4 mv = modelViewMatrix * vec4(position, 1.0);
					vec3 n = normalize(normalMatrix * normal);
					mv.xyz += n * thickness * mix(1.0, -mv.z, perspective);
					gl_Position = projectionMatrix * mv;
				}`,
			fragmentShader: `
				uniform vec3 outlineColor;
				void main() { gl_FragColor = vec4(outlineColor, 1.0); }`,
			side: THREE.BackSide
		});

	const indexBodies = (root: THREE.Object3D) => {
		const map = new Map<string, THREE.Mesh[]>();
		root.traverse((n: any) => {
			if (!n.isMesh) return;
			const id = nodeIdOf(n);
			if (!id) return;
			const list = map.get(id);
			if (list) list.push(n);
			else map.set(id, [n]);
		});
		bodies = map;
	};

	const HILITE = new THREE.Color(0x1f6f4a);

	const clearHighlight = () => {
		for (const { mesh, material } of highlighted) {
			const live = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
			for (const m of live) (m as THREE.Material)?.dispose?.();
			mesh.material = material;
		}
		highlighted = [];
	};

	/** Tint the selected body. The original material is put back on deselect, so a
	 *  highlight never becomes the part's real appearance in a capture of another
	 *  revision. */
	const applySelection = () => {
		if (!part || appliedSelection === selectedNodeId) return;
		clearHighlight();
		appliedSelection = selectedNodeId;
		const meshes = selectedNodeId ? bodies.get(selectedNodeId) : undefined;
		for (const mesh of meshes ?? []) {
			const original = mesh.material;
			const tinted = (Array.isArray(original) ? original : [original]).map((m: any) => {
				const c = m.clone();
				if (c.emissive) c.emissive.copy(HILITE);
				if ('emissiveIntensity' in c) c.emissiveIntensity = 0.6;
				return c;
			});
			highlighted.push({ mesh, material: original });
			mesh.material = Array.isArray(original) ? tinted : tinted[0];
		}
		render();
	};

	/** Repaint the loaded bodies from the current map.
	 *
	 *  The manifest and the artifact travel together in the workspace snapshot, but not
	 *  always in the same frame — and a part that stayed fallback-blue until the next
	 *  load would contradict the swatches in the tree beside it. The highlight is
	 *  dropped first because its stored originals belong to the materials being
	 *  recoloured, and reapplied after. */
	const recolor = () => {
		if (!part || bodies.size === 0) return;
		clearHighlight();
		for (const [id, meshes] of bodies) {
			const want = nodeColors[id] || DEFAULT_COLOR;
			for (const mesh of meshes) {
				const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
				for (const m of mats) (m as any)?.color?.set(want);
			}
		}
		appliedSelection = '';
		applySelection();
		render();
	};

	$: if (part && nodeColors) recolor();

	// Decorations hang off the body meshes so they inherit every transform without
	// being tracked separately, and they are excluded from picking and from `bodies` —
	// a click has to land on the part, not on the line drawn around it.
	let decorations: THREE.Object3D[] = [];

	const clearDecorations = () => {
		for (const d of decorations as any[]) {
			d.parent?.remove(d);
			// A decoration that borrowed the body's geometry must never dispose it — that
			// would take the part with it and leave an empty viewport. Nothing shares
			// today (the hull builds its own), but the flag keeps the rule enforceable.
			if (!d.userData?.harvisSharedGeometry) d.geometry?.dispose?.();
			const mats = Array.isArray(d.material) ? d.material : d.material ? [d.material] : [];
			for (const m of mats) m?.dispose?.();
		}
		decorations = [];
	};

	/** Geometry for the inverted hull: the same shape with *averaged* vertex normals.
	 *
	 *  A CAD body has split normals at every hard edge, so pushing each vertex along
	 *  its own normal tears the shell apart at the corners and the outline reads as
	 *  disconnected slabs rather than a line. Merging by position and recomputing the
	 *  normals gives one normal per corner, and the expanded shell stays closed. */
	const hullGeometry = (src: THREE.BufferGeometry): THREE.BufferGeometry => {
		// Position only — mergeVertices compares every attribute, and the split normals
		// are exactly what has to be discarded for the merge to do anything.
		const bare = new THREE.BufferGeometry();
		bare.setAttribute('position', src.getAttribute('position').clone());
		if (src.index) bare.setIndex(src.index.clone());
		const merged = mergeVertices(bare, 1e-4);
		merged.computeVertexNormals();
		if (merged !== bare) bare.dispose();
		return merged;
	};

	/** Re-derive the hull offset after the canvas changes size. The shader's offset is
	 *  view-space, so it is only pixel-constant for the height it was computed against —
	 *  dragging the panel wider without this leaves the outline at the old width. */
	const syncOutlineThickness = () => {
		const t = outlineThickness();
		for (const d of decorations as any[]) {
			const u = d.material?.uniforms;
			if (!u?.thickness) continue;
			u.thickness.value = t;
			if (u.perspective) u.perspective.value = orthographic ? 0 : 1;
		}
	};

	const decorate = (mesh: THREE.Mesh, silhouette: boolean, edges: boolean) => {
		if (silhouette) {
			const hull = new THREE.Mesh(hullGeometry(mesh.geometry), outlineMaterial());
			hull.raycast = () => {};
			hull.userData.harvisDecoration = true;
			hull.userData.harvisSilhouette = true;
			mesh.add(hull);
			decorations.push(hull);
		}
		if (edges) {
			const lines = new THREE.LineSegments(
				new THREE.EdgesGeometry(mesh.geometry, EDGE_ANGLE),
				new THREE.LineBasicMaterial({ color: EDGE_INK })
			);
			lines.raycast = () => {};
			lines.userData.harvisDecoration = true;
			mesh.add(lines);
			decorations.push(lines);
		}
	};

	/** Which decorations each mode wants.
	 *
	 *  `solid` used to get none, on the reasoning that smooth shading was the point of
	 *  it. That left the lit "Outlines" button doing nothing at all in the one mode a
	 *  saved preference is most likely to strand you in — a control switched on with no
	 *  effect, which reads as the outline being broken rather than absent by design.
	 *  Shaded-with-edges is an ordinary CAD display, so solid now builds the same
	 *  decorations as the rest and lets the toggle decide.
	 *
	 *  `wireframe` still gets none: a silhouette around a see-through part fills it in
	 *  and reads as a solid one. `xray` keeps its creases but not the hull, for the same
	 *  reason — an opaque shell defeats the mode. */
	const decorationsFor = (m: CadDisplayMode) => ({
		silhouette: m !== 'wireframe' && m !== 'xray',
		edges: m !== 'wireframe'
	});

	/** The outline toggle is visibility, not construction — rebuilding every hull to
	 *  turn a switch off would re-merge and re-normal every body for nothing.
	 *
	 *  It governs the feature lines as well as the silhouette. The button says
	 *  "Outlines", and leaving every crease drawn after it is switched off makes that a
	 *  half-truth; the silhouette was never the only line on screen. */
	const applyOutlineVisibility = () => {
		for (const d of decorations) {
			d.visible = d.userData?.harvisSilhouette ? showOutlines && !sectionOn : showOutlines;
		}
		render();
	};

	/** Collect the meshes that are the part itself — never the outline or the feature
	 *  lines, which would otherwise be restyled into decorations of themselves. */
	const bodyMeshes = (): THREE.Mesh[] => {
		const out: THREE.Mesh[] = [];
		part?.traverse((n: any) => {
			if (n.isMesh && !n.userData?.harvisDecoration) out.push(n);
		});
		return out;
	};

	/** Apply the current display mode to a loaded part. Called on load and whenever the
	 *  mode changes, so switching does not refetch bytes that have not changed. */
	const styleBodies = () => {
		if (!part) return;
		clearHighlight();
		clearDecorations();
		const { silhouette, edges } = decorationsFor(displayMode);
		for (const mesh of bodyMeshes()) {
			// Imported reference geometry ships its own materials and keeps them — the
			// illustrated pass is Harvis's opinion about parts Harvis built, not a
			// repaint of a file someone else authored. It still gets the outline.
			if (!mesh.userData?.harvisAuthoredMaterial) {
				const old = mesh.material;
				mesh.material = bodyMaterial(nodeIdOf(mesh));
				for (const m of Array.isArray(old) ? old : [old]) (m as any)?.dispose?.();
			}
			decorate(mesh, silhouette, edges);
		}
		appliedSelection = '';
		applySelection();
		applyOutlineVisibility();
		applyVisibility();
		render();
	};

	$: if (part && displayMode) styleBodies();

	/** Does the loaded file already sit in three's Y-up frame?
	 *
	 *  glTF is Y-up *by specification*, so a conformant writer has already converted —
	 *  OCCT emits the conversion as a rotation node wrapping the whole scene, and three
	 *  loads it with everything else. STL has no scene graph and no units at all:
	 *  `export_stl` writes the document's own Z-up millimetres straight out, so that one
	 *  still has to be turned.
	 *
	 *  Turning a file that was already turned is silent and was live until CS-8. The part
	 *  lands 90° back, which reads as an odd default camera rather than as a bug, and then
	 *  every named view shows a different face than its label — "Top" was the front
	 *  elevation. Measured on a two-body document 50 mm apart in Z: loaded straight, the
	 *  upper body sat at world (−5, 45, 5); with the second rotation it sat at (−5, 5, −45). */
	const fileIsYUp = () => format !== 'stl';

	/** A vector in the loaded part's own local frame, read back as the document's X/Y/Z.
	 *
	 *  One place decides this because three surfaces depend on it — the measure readout,
	 *  the section axes, and the CS-8 gizmo — and a disagreement between them would show
	 *  up as a number that is right and a drag that goes sideways. In a Y-up file the
	 *  document's Z is the file's Y and its Y is the file's −Z; an STL is already the
	 *  document's own axes. */
	const toDocumentAxes = (v: THREE.Vector3): [number, number, number] =>
		fileIsYUp() ? [v.x, -v.z, v.y] : [v.x, v.y, v.z];

	// Normalize whatever came back into something centred and visible: three is Y-up, and
	// a part's real size in millimetres ranges from a few to a few hundred — so the object
	// is turned when the file needs it, scaled to a fixed world size, and recentred rather
	// than being shown at its literal coordinates. Both formats end in the same world
	// frame, which is what lets the section axes below name one mapping.
	const placePart = (obj: THREE.Object3D) => {
		obj.rotation.x = fileIsYUp() ? 0 : -Math.PI / 2;
		obj.updateMatrixWorld(true);
		const box = new THREE.Box3().setFromObject(obj);
		const size = new THREE.Vector3();
		const center = new THREE.Vector3();
		box.getSize(size);
		box.getCenter(center);
		sourceMax = Math.max(size.x, size.y, size.z);
		const scale = FIT / (sourceMax || 1);
		partScale = scale;
		obj.scale.setScalar(scale);
		obj.updateMatrixWorld(true);
		const scaled = new THREE.Box3().setFromObject(obj);
		scaled.getCenter(center);
		obj.position.sub(center);
		scene.add(obj);
		part = obj;
		syncSection();
		render();
	};

	const load = async (u: string, fmt: string) => {
		if (!mounted || !u) return;
		const token = ++loadToken;
		loading = true;
		error = '';
		clearPart();
		try {
			const res = await fetch(u, { headers: authHdr(), credentials: 'include' });
			if (!res.ok) {
				let msg = `${res.status}`;
				try {
					const b = await res.json();
					msg = b?.detail?.message ?? b?.detail ?? msg;
				} catch {
					/* status is all there is */
				}
				throw new Error(String(msg));
			}
			const buf = await res.arrayBuffer();
			if (token !== loadToken || !mounted) return;

			if (fmt === 'glb') {
				assertSelfContained(buf);
				const gltf = await new Promise<any>((resolve, reject) =>
					new GLTFLoader().parse(buf, '', resolve, reject)
				);
				if (token !== loadToken || !mounted) return;
				const root: THREE.Object3D = gltf.scene ?? gltf.scenes?.[0];
				if (!root) throw new Error('the GLB contained no scene');
				// The engine writes no materials, so one is added here rather than letting
				// three fall back to something that reads as untextured black. Which
				// colour is not this component's decision: it comes from the manifest by
				// node id, so two parts of one assembly are told apart the same way in the
				// viewport and in the tree.
				//
				// Every mesh gets its OWN material when the file declares none: GLTFLoader
				// hands one cached default instance to every primitive without a material,
				// so a per-body colour written onto that instance is written onto all of
				// them and the last part painted wins — which is how three distinct
				// manifest colours arrived in the viewport as one. A file that does carry
				// materials (imported reference geometry) keeps what it shipped with.
				const authored = (gltf.parser?.json?.materials?.length ?? 0) > 0;
				root.traverse((n: any) => {
					if (!n.isMesh) return;
					if (authored && n.material?.isMaterial) {
						// Remembered so a later display-mode switch leaves it alone.
						n.userData.harvisAuthoredMaterial = true;
					} else {
						n.material = bodyMaterial(nodeIdOf(n));
					}
				});
				indexBodies(root);
				placePart(root);
				styleBodies();
				applySelection();
			} else {
				const geo = new STLLoader().parse(buf);
				geo.computeVertexNormals();
				if (token !== loadToken || !mounted) return;
				// STL carries no node information, so there is nothing to colour by: one
				// body, the default colour, and no pretending otherwise.
				placePart(new THREE.Mesh(geo, bodyMaterial('')));
			}
		} catch (e: any) {
			if (token === loadToken) error = e?.message ?? String(e);
		} finally {
			if (token === loadToken) loading = false;
		}
	};

	// One place decides where a named view puts the camera, so the picture a render
	// carries is the same picture the user gets by clicking the button. A capture that
	// framed a part differently from the viewport would be a different photograph of
	// the same object presented as the view they chose.
	//
	// The part is Z-up rotated to Y-up in `placePart`, so +Z is the front face, +Y is
	// up and +X is the right side. `top`/`bottom` carry a 0.001 nudge because a camera
	// exactly on the up axis has no defined orientation and three flips it.
	type CadView =
		| 'iso'
		| 'front'
		| 'rear'
		| 'left'
		| 'right'
		| 'top'
		| 'bottom'
		| 'four_view';

	const cameraFor = (v: CadView, d: number): THREE.Vector3 => {
		switch (v) {
			case 'front':
				return new THREE.Vector3(0, 0, d);
			case 'rear':
				return new THREE.Vector3(0, 0, -d);
			case 'right':
				return new THREE.Vector3(d, 0, 0);
			case 'left':
				return new THREE.Vector3(-d, 0, 0);
			case 'top':
				return new THREE.Vector3(0, d, 0.001);
			case 'bottom':
				return new THREE.Vector3(0, -d, 0.001);
			default:
				return INIT_CAM.clone().setLength(d);
		}
	};

	const aimAt = (v: CadView) => {
		const d = camera.position.length() || INIT_CAM.length();
		camera.position.copy(cameraFor(v, d));
		controls.target.set(0, 0, 0);
		controls.update();
	};

	const setView = (v: CadView) => {
		aimAt(v);
		render();
	};

	// ------------------------------------------------------------------
	// Toolbar actions (CS-7)
	//
	// Everything below is viewport state. None of it edits the design, creates a
	// revision, or changes a single exported byte — the two actions that leave the
	// canvas (snapshot, edit) are host callbacks, and move/rotate are deliberately
	// absent until CS-8 gives them a proposal to become.
	// ------------------------------------------------------------------

	/** Visibility from the hide set and the isolation target. Isolation wins while it is
	 *  on, so "show all" is one reset rather than two. */
	const applyVisibility = () => {
		for (const [id, meshes] of bodies) {
			const visible = isolatedId ? id === isolatedId : !hiddenIds.has(id);
			for (const mesh of meshes) mesh.visible = visible;
		}
		render();
	};

	const hideSelected = () => {
		if (!selectedNodeId) return;
		hiddenIds = new Set(hiddenIds).add(selectedNodeId);
		isolatedId = '';
		applyVisibility();
	};

	const isolateSelected = () => {
		isolatedId = isolatedId === selectedNodeId ? '' : selectedNodeId;
		applyVisibility();
	};

	const showAll = () => {
		hiddenIds = new Set();
		isolatedId = '';
		applyVisibility();
	};

	/** Point the camera at a bounding box without changing which way it is looking —
	 *  framing a part should not also spin the view to some canonical angle. */
	const frameBox = (box: THREE.Box3) => {
		if (box.isEmpty()) return;
		const size = new THREE.Vector3();
		const center = new THREE.Vector3();
		box.getSize(size);
		box.getCenter(center);
		const radius = Math.max(size.length() / 2, 1e-3);
		const dir = camera.position.clone().sub(controls.target);
		if (dir.lengthSq() < 1e-8) dir.copy(INIT_CAM);
		dir.normalize();

		const dist = (radius / Math.sin((perspCam.fov * Math.PI) / 360)) * 1.15;
		controls.target.copy(center);
		camera.position.copy(center).addScaledVector(dir, dist);
		if (orthographic) {
			orthoCam.zoom = 1;
			syncOrthoFrustum(radius * 1.15);
		}
		controls.update();
		syncOutlineThickness();
		render();
	};

	const frameSelected = () => {
		const meshes = selectedNodeId ? bodies.get(selectedNodeId) : undefined;
		if (!meshes?.length) return;
		const box = new THREE.Box3();
		for (const m of meshes) box.expandByObject(m);
		frameBox(box);
	};

	const frameAll = () => {
		if (!part) return;
		frameBox(new THREE.Box3().setFromObject(part));
	};

	/** Size the orthographic frustum. Passing a radius sets it outright; otherwise it is
	 *  derived from the perspective camera's cone at the current distance, which is what
	 *  makes the projection switch look like a switch rather than a jump. */
	const syncOrthoFrustum = (radius?: number) => {
		if (!orthoCam || !container) return;
		const aspect = container.clientWidth / Math.max(1, container.clientHeight);
		const half =
			radius ??
			Math.tan((perspCam.fov * Math.PI) / 360) *
				(orthoCam.position.distanceTo(controls?.target ?? new THREE.Vector3()) ||
					INIT_CAM.length());
		orthoCam.top = half;
		orthoCam.bottom = -half;
		orthoCam.left = -half * aspect;
		orthoCam.right = half * aspect;
		orthoCam.updateProjectionMatrix();
	};

	/** Rebuild OrbitControls around a camera. Reassigning `controls.object` in place
	 *  would leave the dolly path branching on the old camera's type, so the controls are
	 *  replaced and the target carried across. */
	const makeControls = () => {
		const target = controls ? controls.target.clone() : new THREE.Vector3();
		if (controls) {
			controls.removeEventListener('change', render);
			controls.dispose();
		}
		controls = new OrbitControls(camera, renderer.domElement);
		controls.enableDamping = !reduced;
		controls.dampingFactor = 0.08;
		controls.minDistance = 1.2;
		controls.maxDistance = 30;
		controls.target.copy(target);
		if (reduced) controls.addEventListener('change', render);
		controls.update();
	};

	const setProjection = (ortho: boolean) => {
		if (ortho === orthographic || !perspCam || !orthoCam) return;
		const from = camera;
		const to = ortho ? orthoCam : perspCam;
		to.position.copy(from.position);
		to.up.copy(from.up);
		to.quaternion.copy(from.quaternion);
		orthographic = ortho;
		camera = to;
		if (ortho) {
			orthoCam.zoom = 1;
			syncOrthoFrustum();
		}
		makeControls();
		// The gizmo sizes and orients its handles from the camera it was built with, so a
		// projection switch has to hand it the new one or the handles keep pointing at the
		// old frustum.
		if (gizmo) gizmo.camera = camera;
		// The hull shader scales its offset by view depth under perspective and must not
		// under orthographic; the uniforms carry that, so they are rewritten here.
		syncOutlineThickness();
		resize();
	};

	// Section view. The axis names are the document's own — the world frame is the
	// viewport's business and is never shown to anyone, so `x` here means the X of the
	// same bounding box the validation footer reports. Both formats land in one world
	// frame after `placePart`, so this is a single mapping rather than a branch: the
	// document's Z is world +Y, and its Y is world −Z.
	const SECTION_WORLD_AXIS: Record<CadSectionAxis, THREE.Vector3> = {
		x: new THREE.Vector3(1, 0, 0),
		y: new THREE.Vector3(0, 0, -1),
		z: new THREE.Vector3(0, 1, 0)
	};

	const syncSection = () => {
		if (!renderer) return;
		if (!sectionOn || !part) {
			renderer.clippingPlanes = [];
			applyOutlineVisibility();
			render();
			return;
		}
		const box = new THREE.Box3().setFromObject(part);
		const size = new THREE.Vector3();
		box.getSize(size);
		const axis = SECTION_WORLD_AXIS[sectionAxis];
		const half = Math.max(Math.abs(axis.x * size.x + axis.y * size.y + axis.z * size.z) / 2, 1e-3);
		const normal = axis.clone().multiplyScalar(sectionFlipped ? -1 : 1);
		clipPlane.setFromNormalAndCoplanarPoint(
			normal,
			axis.clone().multiplyScalar(sectionOffset * half)
		);
		renderer.clippingPlanes = [clipPlane];
		// The silhouette is a custom shader with no clipping chunks, so it would survive
		// the cut as a floating shell around a part that is half gone. It stands down
		// while the section is on rather than lying about the geometry.
		applyOutlineVisibility();
		render();
	};

	const onSection = (
		next: Partial<{ on: boolean; axis: CadSectionAxis; offset: number; flipped: boolean }>
	) => {
		if (next.on !== undefined) sectionOn = next.on;
		if (next.axis !== undefined) sectionAxis = next.axis;
		if (next.offset !== undefined) sectionOffset = next.offset;
		if (next.flipped !== undefined) sectionFlipped = next.flipped;
		syncSection();
	};

	/** Millimetres per unit of the loaded file.
	 *
	 *  Calibrated against the engine's own bounding box: the longest edge the file
	 *  contains is the longest edge the engine measured, so one division fixes the units
	 *  no matter what the file meant by "1". Without a build to calibrate against, fall
	 *  back to what each format conventionally means — glTF is metres by specification,
	 *  and this engine writes STL in millimetres. */
	const mmPerUnit = () => {
		const known = bboxMm
			? Math.max(bboxMm.x ?? 0, bboxMm.y ?? 0, bboxMm.z ?? 0)
			: 0;
		if (known > 0 && sourceMax > 0) return known / sourceMax;
		return format === 'stl' ? 1 : 1000;
	};

	/** Bounding box of the selection, or of the whole model, in the part's own axes.
	 *
	 *  Measured in the loaded object's local frame rather than in world space, for two
	 *  reasons: `placePart` rotates and rescales the root, so world axes no longer line
	 *  up with the X/Y/Z every dimension in the conversation is stated in; and a body's
	 *  silhouette is a hull that has been pushed *outward*, so a world-space box around
	 *  the body would measure the outline instead of the part. */
	const measureBox = (roots: THREE.Object3D[]) => {
		const inv = new THREE.Matrix4().copy(part.matrixWorld).invert();
		const box = new THREE.Box3();
		const local = new THREE.Matrix4();
		for (const root of roots) {
			root.traverse((o: any) => {
				if (!o.isMesh || !o.geometry || o.userData?.harvisDecoration) return;
				if (!o.geometry.boundingBox) o.geometry.computeBoundingBox();
				box.union(o.geometry.boundingBox.clone().applyMatrix4(local.multiplyMatrices(inv, o.matrixWorld)));
			});
		}
		return box;
	};

	const measure = () => {
		if (!part || !measureOn) {
			measureText = '';
			return;
		}
		const meshes = selectedNodeId ? bodies.get(selectedNodeId) : undefined;
		part.updateMatrixWorld(true);
		const box = measureBox(meshes?.length ? meshes : [part]);
		const perUnit = mmPerUnit();
		if (box.isEmpty() || perUnit <= 0) {
			measureText = '';
			return;
		}
		const size = new THREE.Vector3();
		box.getSize(size);
		const mm = (v: number) => (Math.abs(v) * perUnit).toFixed(1);
		const scope = meshes?.length ? $i18n.t('selection') : $i18n.t('whole model');
		// Stated in the document's own X/Y/Z, because that is the frame the validation
		// bbox, the dimensions in the conversation, and the section axes all use.
		const [dx, dy, dz] = toDocumentAxes(size);
		measureText = `${scope} · ${mm(dx)} × ${mm(dy)} × ${mm(dz)} mm`;
	};

	const toggleMeasure = () => {
		measureOn = !measureOn;
		measure();
	};

	// ------------------------------------------------------------------
	// Move / rotate as a proposal (CS-8)
	//
	// A drag here changes nothing. It moves a preview, and pressing Apply hands the host
	// a `ComponentPlacement` — a translate in millimetres and a rotate in degrees, both in
	// the document's own frame — which becomes a CadIR revision the engine rebuilds and
	// validates. Escape restores the preview and creates nothing, so a drag the user
	// changed their mind about leaves no revision behind.
	//
	// Why a placement rather than editing the operations that built the body: an author
	// writes `at: [wall_t + bore/2, 0, 0]`, and rewriting that to a dragged number would
	// bake away the intent and break the next parameter change. The engine applies the
	// placement *after* the body is built (`cad-engine/cadir/interpret.py:_placed`), so
	// every formula survives.
	//
	// Scaling is deliberately absent. An arbitrary scale violates the exact dimensions the
	// document states, so resizing stays a chat instruction.
	// ------------------------------------------------------------------

	/** Matches `ComponentPlacement`'s bound in `cad-engine/cadir/schema.py`. Checked here
	 *  so a runaway drag is refused with a readable note instead of a 400 after the round
	 *  trip. The engine still enforces it — this is the honest mirror, not the gate. */
	const MAX_TRANSLATE_MM = 1000;
	const DEG = 180 / Math.PI;

	let gizmo: TransformControls | null = null;
	let pivot: THREE.Group | null = null;
	let gizmoNodeId = '';
	/** Where each reparented mesh came from, so Escape can put it back exactly.
	 *
	 *  The local matrix is saved alongside the parent, and that is the whole point.
	 *  `attach` preserves *world* transform, which is right on the way in and wrong on the
	 *  way out: reattaching to the original parent after a drag would preserve the dragged
	 *  world position and leave the body displaced with no gizmo and no revision — the
	 *  document saying one thing and the screen showing another. */
	let pivotHomes: { mesh: THREE.Object3D; parent: THREE.Object3D; local: THREE.Matrix4 }[] = [];
	let pending: { translate: [number, number, number]; rotate: [number, number, number] } | null =
		null;
	/** Where the pivot sat before the user touched it, so the preview reports a *drag* and
	 *  not a *coordinate*. The pivot is seeded at the body's bounding-box centre, which is
	 *  only the origin while the body has never been placed; once a placement moves it, a
	 *  gizmo opened on it read its own centre back as if that were a fresh displacement.
	 *  `proposePlacement` adds what it is handed to the placement already in the document,
	 *  so on the already-moved bottle a +22.2 mm part reported +22.2 mm before any drag and
	 *  Apply would have written +44.4 mm. */
	let pivotStart: THREE.Vector3 | null = null;
	let pendingNote = '';
	let applying = false;
	let applyError = '';

	/** The local→document basis change. A proper rotation (determinant +1), which is why a
	 *  rotation matrix can be conjugated by it: `M_doc = B · M_local · Bᵀ`. Permuting Euler
	 *  angles directly would be wrong — Euler triples do not transform like vectors. */
	const documentBasis = () => {
		const m = new THREE.Matrix4();
		if (fileIsYUp()) m.set(1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 0, 0, 1);
		return m;
	};

	/** A local-frame rotation restated as the document's own XYZ Euler angles in degrees.
	 *  XYZ because build123d's `Rotation` defaults to intrinsic XYZ — `Rx·Ry·Rz` — which is
	 *  exactly what three composes for `Euler(x, y, z, 'XYZ')`. The two agree by that fact,
	 *  not by coincidence, so changing either order breaks the contract silently. */
	const toDocumentRotation = (q: THREE.Quaternion): [number, number, number] => {
		const b = documentBasis();
		const m = new THREE.Matrix4().makeRotationFromQuaternion(q);
		m.premultiply(b).multiply(b.clone().transpose());
		const e = new THREE.Euler().setFromRotationMatrix(m, 'XYZ');
		return [e.x * DEG, e.y * DEG, e.z * DEG];
	};

	const readPending = () => {
		if (!pivot) {
			pending = null;
			pendingNote = '';
			return;
		}
		const perUnit = mmPerUnit();
		const round = (v: number) => Math.round(v * 1000) / 1000;
		// The displacement since `beginGizmo`, never the absolute position. `toDocumentAxes`
		// is an axis permutation with a sign flip — linear — so it maps a difference exactly
		// as it maps a point. The rotation needs no such subtraction: `pivot` is a fresh
		// Group each time, so its quaternion starts at identity and already *is* the delta.
		const moveBy = pivotStart ? pivot.position.clone().sub(pivotStart) : pivot.position;
		const t = toDocumentAxes(moveBy).map((v) => round(v * perUnit)) as [
			number,
			number,
			number
		];
		const r = toDocumentRotation(pivot.quaternion).map(round) as [number, number, number];
		const moved = t.some((v) => Math.abs(v) > 1e-3);
		const turned = r.some((v) => Math.abs(v) > 1e-3);
		pending = moved || turned ? { translate: t, rotate: r } : null;
		const sign = (v: number, unit: string) => `${v >= 0 ? '+' : ''}${v.toFixed(1)}${unit}`;
		pendingNote = [
			moved ? t.map((v) => sign(v, '')).join(' ') + ' mm' : '',
			turned ? r.map((v) => sign(v, '')).join(' ') + '°' : ''
		]
			.filter(Boolean)
			.join(' · ');
	};

	$: overReach = !!pending && pending.translate.some((v) => Math.abs(v) > MAX_TRANSLATE_MM);

	const onGizmoDrag = (e: any) => {
		if (controls) controls.enabled = !e.value;
	};

	const beginGizmo = () => {
		const meshes = selectedNodeId ? bodies.get(selectedNodeId) : undefined;
		if (!part || !meshes?.length || !renderer) return;
		part.updateMatrixWorld(true);
		const centre = new THREE.Vector3();
		const box = measureBox(meshes);
		if (box.isEmpty()) return;
		box.getCenter(centre);

		// The pivot sits at the body's own bounding-box centre because that is what the
		// engine rotates about. Anywhere else and a 45° preview would not match the 45°
		// the rebuild produces. One honest caveat: this centre is the *mesh* box and the
		// engine's is the *B-Rep* box, so they differ by the tessellation tolerance —
		// well under a tenth of a millimetre at the current deflection, but not zero.
		pivot = new THREE.Group();
		pivot.position.copy(centre);
		pivotStart = centre.clone();
		part.add(pivot);
		pivot.updateMatrixWorld(true);
		// `attach` preserves world transform, so the reparenting is invisible. The local
		// matrix is captured first — `part.updateMatrixWorld(true)` above has just made it
		// current — because it is the only record of where the body actually belongs once
		// the pivot starts moving.
		pivotHomes = meshes.map((mesh) => ({
			mesh,
			parent: mesh.parent ?? part!,
			local: mesh.matrix.clone()
		}));
		for (const mesh of meshes) pivot.attach(mesh);

		gizmo = new TransformControls(camera, renderer.domElement);
		gizmo.setMode(tool === 'rotate' ? 'rotate' : 'translate');
		gizmo.setSpace('local');
		gizmo.attach(pivot);
		gizmo.addEventListener('dragging-changed', onGizmoDrag);
		gizmo.addEventListener('objectChange', readPending);
		gizmo.addEventListener('change', render);
		scene.add(gizmo.getHelper());
		gizmoNodeId = selectedNodeId;
		applyError = '';
		readPending();
		render();
	};

	/** Drops the gizmo without touching the meshes. Used when the whole part is going
	 *  away, where reparenting into an object about to be disposed would only make more
	 *  work for `disposeObject`. */
	const teardownGizmo = () => {
		if (gizmo) {
			gizmo.removeEventListener('dragging-changed', onGizmoDrag);
			gizmo.removeEventListener('objectChange', readPending);
			gizmo.removeEventListener('change', render);
			const helper = gizmo.getHelper();
			gizmo.detach();
			scene?.remove(helper);
			gizmo.disconnect();
			// NOT `gizmo.dispose()`. In three 0.169 `TransformControls` moved off `Object3D`
			// onto the `Controls` base, but its `dispose()` still calls `this.traverse` — a
			// method the class no longer has — so it throws `this.traverse is not a
			// function` every time. The throw landed here, after the helper had already left
			// the scene and before `pivot` was cleared, which is why Escape, Cancel and
			// Apply all looked like they half-worked: the arrows vanished, the body stayed
			// dragged, and the "Preview — not saved" bar refused to go away.
			// Freeing the helper's own geometries and materials is all that method was for.
			disposeObject(helper);
			gizmo = null;
		}
		pivot = null;
		pivotStart = null;
		pivotHomes = [];
		gizmoNodeId = '';
		pending = null;
		pendingNote = '';
		if (controls) controls.enabled = true;
	};

	/** Ends the preview and puts the geometry back where it was. Every exit runs through
	 *  here — cancel, a changed selection, a new revision — so no path can leave a body
	 *  displaced on screen while the document says otherwise. */
	const endGizmo = () => {
		const homes = pivotHomes;
		const held = pivot;
		teardownGizmo();
		for (const { mesh, parent, local } of homes) {
			// `add`, not `attach` — then the saved local transform is written back. `attach`
			// would keep the dragged world position, which is the one thing this must undo.
			parent.add(mesh);
			local.decompose(mesh.position, mesh.quaternion, mesh.scale);
			mesh.updateMatrix();
		}
		if (held?.parent) held.parent.remove(held);
		render();
	};

	const cancelGizmo = () => {
		endGizmo();
		tool = 'select';
	};

	const applyGizmo = async () => {
		if (!pending || !onPropose || applying || overReach || !gizmoNodeId) return;
		applying = true;
		applyError = '';
		const proposal = { nodeId: gizmoNodeId, ...pending };
		try {
			await onPropose(proposal);
			// The host has a new revision on the way; the preview's job is done and the
			// reload will render the real geometry.
			endGizmo();
			tool = 'select';
		} catch (e: any) {
			// Keep the preview standing. A failed request should not also lose the drag.
			applyError = e?.message ?? String(e);
		} finally {
			applying = false;
		}
	};

	/** Keeps the gizmo in step with the toolbar and the selection. Switching between move
	 *  and rotate keeps the preview — someone who nudges a part and then turns it means
	 *  both — but changing body ends it, because a delta belongs to the body it was
	 *  dragged on. */
	const syncGizmo = () => {
		const wanted = (tool === 'move' || tool === 'rotate') && !!selectedNodeId && !!onPropose;
		if (!wanted || !part) {
			if (gizmo || pivot) endGizmo();
			return;
		}
		if (pivot && gizmoNodeId !== selectedNodeId) endGizmo();
		if (!pivot) beginGizmo();
		gizmo?.setMode(tool === 'rotate' ? 'rotate' : 'translate');
		render();
	};

	const onGizmoKey = (e: KeyboardEvent) => {
		if (e.key !== 'Escape' || !pivot) return;
		// Fullscreen owns Escape too, and the browser will exit it on the same press. The
		// preview still has to end, so this does not swallow the event.
		cancelGizmo();
	};

	const toggleGrid = () => {
		showGrid = !showGrid;
		if (grid) grid.visible = showGrid;
		render();
	};

	const toggleOutlines = () => {
		showOutlines = !showOutlines;
		applyOutlineVisibility();
	};

	const toggleFullscreen = () => {
		if (typeof document === 'undefined') return;
		// Both calls return promises that reject when the browser declines — no user
		// gesture, a permissions policy, an embedded frame. Swallowing the rejection here
		// keeps a refused request from surfacing as an unhandled error; the button's own
		// state is driven by `fullscreenchange`, so a refusal simply leaves it off.
		if (document.fullscreenElement) document.exitFullscreen?.()?.catch(() => {});
		else shell?.requestFullscreen?.()?.catch(() => {});
	};

	const onFullscreenChange = () => {
		fullscreen = typeof document !== 'undefined' && document.fullscreenElement === shell;
		// The container's height is a style binding, so the canvas only follows after the
		// class swap has landed.
		requestAnimationFrame(resize);
	};

	// ------------------------------------------------------------------
	// Capture (UX-3)
	//
	// The render is made here, from the buffer already on screen, because there is no
	// server-side renderer and adding one would mean a second GL stack that could
	// disagree with this one. The cost is that a render only exists when someone has
	// the viewport open — which is why the caller, not this component, decides when to
	// ask, and why the workspace says so plainly when a view is missing.
	// ------------------------------------------------------------------
	const CAPTURE_W = 1280;
	const CAPTURE_H = 960;
	// The four-view sheet's quadrants, reading order. Same four the filmstrip offers,
	// so the sheet is the contact sheet of the strip rather than a fifth opinion.
	const QUADRANTS: CadView[] = ['iso', 'front', 'right', 'top'];

	const toBlob = (canvas: HTMLCanvasElement): Promise<Blob | null> =>
		new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));

	/** Stop the loop and snapshot everything a capture is about to move. The returned
	 *  closure puts it all back — including the animation loop, which must not restart
	 *  before the readback or the buffer is overwritten mid-capture. */
	const beginCapture = (): (() => void) => {
		const prevPos = camera.position.clone();
		const prevTarget = controls.target.clone();
		const prevRatio = renderer.getPixelRatio();
		const looping = raf !== 0;
		if (looping) {
			cancelAnimationFrame(raf);
			raf = 0;
		}
		return () => {
			renderer.setPixelRatio(prevRatio);
			camera.position.copy(prevPos);
			controls.target.copy(prevTarget);
			controls.update();
			resize();
			if (looping) loop();
		};
	};

	/** Render one preset off the live scene into PNG bytes.
	 *
	 *  Caller-owned state: this changes the buffer size, the aspect and the camera, and
	 *  restores none of it. Every path into it goes through `beginCapture`. */
	const renderPreset = async (preset: CadView): Promise<Blob | null> => {
		const sheet = preset === 'four_view';
		const w = sheet ? CAPTURE_W / 2 : CAPTURE_W;
		const h = sheet ? CAPTURE_H / 2 : CAPTURE_H;
		// updateStyle off: this is a buffer resize for one frame, and letting it
		// touch the CSS size would make the panel visibly jump.
		renderer.setSize(w, h, false);
		setAspect(w, h);

		if (!sheet) {
			aimAt(preset);
			renderer.render(scene, camera);
			return await toBlob(renderer.domElement as HTMLCanvasElement);
		}

		const out = document.createElement('canvas');
		out.width = CAPTURE_W;
		out.height = CAPTURE_H;
		const ctx = out.getContext('2d');
		if (!ctx) return null;
		QUADRANTS.forEach((v, i) => {
			aimAt(v);
			renderer.render(scene, camera);
			ctx.drawImage(renderer.domElement, (i % 2) * w, Math.floor(i / 2) * h, w, h);
		});
		return await toBlob(out);
	};

	/** Render one preset off the live scene and hand back PNG bytes. Returns null when
	 *  there is nothing loaded — a picture of an empty scene is not a render of a part. */
	export const capture = async (preset: CadView): Promise<Blob | null> => {
		if (!renderer || !scene || !camera || !part) return null;
		const restore = beginCapture();
		try {
			renderer.setPixelRatio(1);
			return await renderPreset(preset);
		} catch {
			// A capture that fails must not take the viewport with it. The caller sees
			// null and reports no render, which is true.
			return null;
		} finally {
			restore();
		}
	};

	// ------------------------------------------------------------------
	// Recipe capture (HE-7)
	//
	// A recipe is a server-issued instruction for one picture: which of this viewer's
	// own presets to aim at, whether to cut, and — for the second pass — which colour
	// each body is painted so the backend can count it.
	//
	// The mask is not a prettier render. It is flat unlit colour on an opaque black
	// ground with every decoration stood down, because QC attributes each pixel to its
	// nearest palette entry: a cartoon outline, a gradient or a shadow would each land
	// somewhere in that attribution and the count would be of the illustration rather
	// than of the part.
	//
	// **Nothing captured here can decide a verdict.** The backend measures the mask and
	// keeps its findings beside the picture; conformance is decided by the engine's
	// measurements, and a build with no renders at all grades exactly the same.
	// ------------------------------------------------------------------
	type CadRecipeSection = {
		axis: CadSectionAxis;
		offset: number;
		flipped: boolean;
	};
	type CadRecipeRequest = {
		view: string;
		section?: CadRecipeSection | null;
		/** node id → `#rrggbb`. Empty means the server issued no mask for this build,
		 *  and the beauty pass ships unmeasured. */
		mask_palette?: Record<string, string>;
	};

	const VIEWS: CadView[] = ['iso', 'front', 'rear', 'left', 'right', 'top', 'bottom', 'four_view'];
	const viewOf = (v: string): CadView => (VIEWS.includes(v as CadView) ? (v as CadView) : 'iso');

	/** The object-mask pass. Returns null when no body carries a palette colour, which
	 *  is the honest version of "there was nothing here this mask could measure". */
	const renderMask = async (
		palette: Record<string, string>,
		preset: CadView
	): Promise<Blob | null> => {
		const swapped: { mesh: THREE.Mesh; material: THREE.Material | THREE.Material[] }[] = [];
		const hidden: THREE.Mesh[] = [];
		const decoVisible = decorations.map((d) => d.visible);
		const gridVisible = grid?.visible;
		const helper: any = (gizmo as any)?.getHelper?.() ?? null;
		const helperVisible = helper?.visible;
		const prevAlpha = renderer.getClearAlpha();

		try {
			for (const mesh of bodyMeshes()) {
				const hex = palette[nodeIdOf(mesh)];
				if (!hex) {
					// A body the recipe has no colour for cannot be counted, and leaving it
					// shaded would attribute its pixels to whichever palette entry they
					// happen to sit nearest. It is taken out of the frame instead, and QC
					// reports it as a body the picture is missing.
					if (mesh.visible) {
						mesh.visible = false;
						hidden.push(mesh);
					}
					continue;
				}
				swapped.push({ mesh, material: mesh.material });
				// toneMapped off so the palette hex round-trips exactly. Nothing in this
				// file sets `toneMapping` today, but a mapped colour would be off by
				// enough to change which palette entry a pixel is nearest to.
				mesh.material = new THREE.MeshBasicMaterial({
					color: new THREE.Color(hex),
					toneMapped: false
				});
			}
			if (!swapped.length) return null;

			// The one exemption `styleBodies` honours does not apply here: imported
			// reference geometry keeps its own materials in the illustrated pass, but a
			// mask needs every body flat-coloured or its silhouette is uncountable.
			for (const d of decorations) d.visible = false;
			if (grid) grid.visible = false;
			if (helper) helper.visible = false;
			// The canvas is normally transparent, so the PNG's ground would be whatever
			// the reader composites it against. QC's background is opaque black.
			renderer.setClearColor(0x000000, 1);

			return await renderPreset(preset);
		} finally {
			for (const { mesh, material } of swapped) {
				(mesh.material as any)?.dispose?.();
				mesh.material = material;
			}
			for (const mesh of hidden) mesh.visible = true;
			decorations.forEach((d, i) => {
				d.visible = decoVisible[i];
			});
			if (grid) grid.visible = gridVisible ?? true;
			if (helper) helper.visible = helperVisible ?? true;
			renderer.setClearColor(0x000000, prevAlpha);
		}
	};

	/** Both passes for one recipe. The beauty pass is the picture people see; the mask
	 *  is QC input the backend measures and discards. */
	export const captureRecipe = async (
		recipe: CadRecipeRequest
	): Promise<{ beauty: Blob | null; mask: Blob | null }> => {
		const nothing = { beauty: null, mask: null };
		if (!renderer || !scene || !camera || !part) return nothing;

		const restore = beginCapture();
		// Section and visibility are the user's viewport state, not the recipe's. The
		// recipe overrides both so the picture is the one that was asked for, and the
		// finally puts the viewport back the way it was found.
		const wasSection = {
			on: sectionOn,
			axis: sectionAxis,
			offset: sectionOffset,
			flipped: sectionFlipped
		};
		const wasHidden = hiddenIds;
		const wasIsolated = isolatedId;

		try {
			renderer.setPixelRatio(1);
			hiddenIds = new Set();
			isolatedId = '';
			applyVisibility();

			sectionOn = !!recipe.section;
			if (recipe.section) {
				sectionAxis = recipe.section.axis;
				sectionOffset = recipe.section.offset;
				sectionFlipped = recipe.section.flipped;
			}
			syncSection();

			const preset = viewOf(recipe.view);
			const beauty = await renderPreset(preset);
			const palette = recipe.mask_palette || {};
			const mask = Object.keys(palette).length ? await renderMask(palette, preset) : null;
			return { beauty, mask };
		} catch {
			return nothing;
		} finally {
			sectionOn = wasSection.on;
			sectionAxis = wasSection.axis;
			sectionOffset = wasSection.offset;
			sectionFlipped = wasSection.flipped;
			syncSection();
			hiddenIds = wasHidden;
			isolatedId = wasIsolated;
			applyVisibility();
			restore();
		}
	};

	// An orbit drag ends in a pointerup over the part, so a click is only a selection
	// when the pointer barely moved. Without this, letting go of a rotation would
	// silently re-select whatever happened to be under the cursor.
	const DRAG_SLOP_PX = 4;

	const onPointerDown = (e: PointerEvent) => {
		// `gizmo.axis` is non-null while a handle is under the pointer. Grabbing one is a
		// drag, not a selection, and without this a short pull on the X arrow would also
		// re-pick whatever body sat behind it.
		const onHandle = !!gizmo?.axis;
		pointerStart = e.button === 0 && !onHandle ? { x: e.clientX, y: e.clientY } : null;
	};

	const onPointerUp = (e: PointerEvent) => {
		const start = pointerStart;
		pointerStart = null;
		if (!onPick || !start || !part) return;
		if (Math.hypot(e.clientX - start.x, e.clientY - start.y) > DRAG_SLOP_PX) return;

		const rect = renderer.domElement.getBoundingClientRect();
		ndc.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
		ndc.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
		raycaster.setFromCamera(ndc, camera);
		const hit = raycaster.intersectObject(part, true)[0];
		onPick(hit ? nodeIdOf(hit.object) : '');
	};

	/** Aspect for whichever camera is active. The orthographic one has no `aspect` — its
	 *  shape is the frustum, so the same call has to mean two different things. */
	const setAspect = (w: number, h: number) => {
		const aspect = w / Math.max(1, h);
		if (orthographic && orthoCam) {
			const half = (orthoCam.top - orthoCam.bottom) / 2 || 1;
			orthoCam.left = -half * aspect;
			orthoCam.right = half * aspect;
			orthoCam.updateProjectionMatrix();
			return;
		}
		perspCam.aspect = aspect;
		perspCam.updateProjectionMatrix();
	};

	const resize = () => {
		if (!container || !renderer) return;
		const w = container.clientWidth;
		const h = container.clientHeight;
		// updateStyle must stay on: nothing else gives the canvas a CSS size, so
		// skipping it leaves the element at its intrinsic buffer size and the
		// overflow-hidden container crops to the top-left — a centred part then
		// renders low and to the right.
		renderer.setSize(w, h);
		setAspect(w, h);
		syncOutlineThickness();
		render();
	};

	const loop = () => {
		raf = requestAnimationFrame(loop);
		if (controls.enableDamping) controls.update();
		renderer.render(scene, camera);
	};

	onMount(() => {
		// preserveDrawingBuffer: without it the buffer may be cleared before `toBlob`
		// reads it back, and a capture returns a blank or torn frame on some drivers.
		renderer = new THREE.WebGLRenderer({
			antialias: true,
			alpha: true,
			preserveDrawingBuffer: true
		});
		renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		renderer.setClearColor(0x000000, 0);
		container.appendChild(renderer.domElement);

		scene = new THREE.Scene();
		perspCam = new THREE.PerspectiveCamera(42, 1, 0.05, 200);
		perspCam.position.copy(INIT_CAM);
		// The orthographic frustum is a placeholder until `syncOrthoFrustum` sizes it from
		// the perspective cone; it is never used before then.
		orthoCam = new THREE.OrthographicCamera(-2, 2, 2, -2, 0.05, 200);
		orthoCam.position.copy(INIT_CAM);
		camera = perspCam;

		scene.add(new THREE.AmbientLight(0xffffff, 0.55));
		const key = new THREE.DirectionalLight(0xffffff, 1.0);
		key.position.set(4, 6, 5);
		scene.add(key);
		const fill = new THREE.DirectionalLight(0x88b6ff, 0.35);
		fill.position.set(-5, 2, -4);
		scene.add(fill);

		grid = new THREE.GridHelper(8, 16, 0x64748b, 0x334155);
		(grid.material as THREE.Material).transparent = true;
		(grid.material as THREE.Material).opacity = 0.35;
		grid.position.y = -FIT / 2 - 0.05;
		grid.visible = showGrid;
		scene.add(grid);

		makeControls();

		resize();
		ro = new ResizeObserver(resize);
		ro.observe(container);

		renderer.domElement.addEventListener('pointerdown', onPointerDown);
		renderer.domElement.addEventListener('pointerup', onPointerUp);

		// One choice across every viewport in the app: switching to realistic in the
		// session room and then finding the chat card still outlined would read as two
		// unrelated settings.
		const saved = localStorage.getItem('cadDisplayMode');
		// `realistic` is the CS-5 name for what CS-7 calls `solid`; a stored preference
		// from before the toolbar has to keep meaning what the user chose.
		if (saved === 'realistic') displayMode = 'solid';
		else if (CAD_DISPLAY_MODES.some((m) => m.id === saved))
			displayMode = saved as CadDisplayMode;

		document.addEventListener('fullscreenchange', onFullscreenChange);
		window.addEventListener('keydown', onGizmoKey);

		// The `theme` store can hold 'system', which says nothing about what is actually
		// on screen. The `dark` class on <html> is the effective answer, and watching the
		// attribute means we react after it has changed rather than before.
		darkTheme = readTheme();
		themeWatch = new MutationObserver(() => {
			const now = readTheme();
			if (now === darkTheme) return;
			darkTheme = now;
			styleBodies();
		});
		themeWatch.observe(document.documentElement, {
			attributes: true,
			attributeFilter: ['class']
		});

		// Setting this fires the reactive load below — no explicit first call, which
		// would race its own duplicate.
		mounted = true;
		if (reduced) {
			controls.addEventListener('change', render);
			render();
		} else {
			loop();
		}
	});

	onDestroy(() => {
		mounted = false;
		loadToken++;
		cancelAnimationFrame(raf);
		ro?.disconnect();
		themeWatch?.disconnect();
		themeWatch = null;
		if (typeof document !== 'undefined') {
			document.removeEventListener('fullscreenchange', onFullscreenChange);
			window.removeEventListener('keydown', onGizmoKey);
		}
		controls?.removeEventListener('change', render);
		renderer?.domElement?.removeEventListener('pointerdown', onPointerDown);
		renderer?.domElement?.removeEventListener('pointerup', onPointerUp);
		controls?.dispose();
		if (scene) {
			clearPart();
			scene.traverse((o: any) => {
				o.geometry?.dispose?.();
				const mats = Array.isArray(o.material) ? o.material : o.material ? [o.material] : [];
				mats.forEach((m: THREE.Material) => m.dispose());
			});
		}
		toonGradient?.dispose();
		toonGradient = null;
		renderer?.dispose();
	});

	$: if (mounted) load(url, format);
	$: if (mounted) {
		selectedNodeId;
		applySelection();
		// A measurement is about whatever is selected, so it has to follow the selection
		// rather than wait for the button to be pressed again. `bboxMm` is in here for a
		// different reason: it is what the numbers are calibrated against, and it can
		// arrive after the geometry does.
		bboxMm;
		measure();
	}
	$: if (mounted) localStorage.setItem('cadDisplayMode', displayMode);

	// The gizmo follows the toolbar, the selection and the loaded part. `part` is in the
	// dependency list because a fresh revision replaces it, and a preview that outlived
	// its geometry would be a handle attached to nothing.
	$: if (mounted) {
		tool;
		selectedNodeId;
		part;
		onPropose;
		syncGizmo();
	}

	/** The toolbar disables its own buttons, but a body can also stop existing under it —
	 *  a new revision drops the hidden ids and the isolation with it. */
	$: if (part && bodies) {
		const live = new Set(bodies.keys());
		if (isolatedId && !live.has(isolatedId)) isolatedId = '';
		if ([...hiddenIds].some((id) => !live.has(id))) {
			hiddenIds = new Set([...hiddenIds].filter((id) => live.has(id)));
		}
	}
</script>

<div
	bind:this={shell}
	class="relative w-full {fullscreen ? 'h-full bg-white dark:bg-gray-900' : ''}"
>
	<div
		bind:this={container}
		class="cad-canvas w-full rounded-lg overflow-hidden border border-gray-100 dark:border-gray-850"
		style={fullscreen ? 'height:100%' : `height:${height}px`}
		aria-label={$i18n.t('3D view of the built part')}
	></div>

	{#if loading}
		<div
			class="absolute inset-0 flex items-center justify-center text-xs text-gray-500 dark:text-gray-400"
		>
			{$i18n.t('Loading geometry…')}
		</div>
	{:else if error}
		<div class="absolute inset-0 flex items-center justify-center px-6 text-center">
			<span class="text-xs text-red-500 dark:text-red-400">{error}</span>
		</div>
	{:else if !url}
		<div
			class="absolute inset-0 flex items-center justify-center text-xs text-gray-400 dark:text-gray-500"
		>
			{$i18n.t('No geometry for this revision yet.')}
		</div>
	{/if}

	{#if url && !error && toolbar}
		<CadViewportToolbar
			{tool}
			{displayMode}
			{orthographic}
			{showGrid}
			{showOutlines}
			{sectionOn}
			{sectionAxis}
			{sectionOffset}
			{sectionFlipped}
			{measureOn}
			{measureText}
			{fullscreen}
			hasSelection={!!selectedNodeId}
			isolated={!!isolatedId}
			hiddenCount={hiddenIds.size}
			gizmoEnabled={!!onPropose}
			gizmoNote={gizmoNote ||
				$i18n.t(
					'Moving and rotating a part need a revision to propose against, which this view does not have.'
				)}
			onTool={(t) => (tool = t)}
			onDisplayMode={(m) => (displayMode = m)}
			onView={(v) => setView(v as any)}
			onProjection={setProjection}
			onFrameSelected={frameSelected}
			onFrameAll={frameAll}
			onHide={hideSelected}
			onIsolate={isolateSelected}
			onShowAll={showAll}
			onToggleGrid={toggleGrid}
			onToggleOutlines={toggleOutlines}
			onToggleMeasure={toggleMeasure}
			{onSection}
			onSnapshot={onSnapshot ? () => onSnapshot?.() : null}
			onEdit={onEditSelected ? () => onEditSelected?.(selectedNodeId) : null}
			onFullscreen={toggleFullscreen}
		/>
	{:else if url && !error}
		<!-- Hosts without a workspace around them — the chat card, the artifact preview —
		     get the standard views and nothing that implies an edit. -->
		<div class="absolute bottom-2 left-2 flex flex-wrap items-center gap-1">
			{#each [['iso', 'Iso'], ['front', 'Front'], ['top', 'Top'], ['right', 'Right']] as [v, label]}
				<button
					class="text-[10px] px-1.5 py-0.5 rounded-md bg-white/70 dark:bg-gray-850/70 border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
					on:click={() => setView(v as any)}>{$i18n.t(label)}</button
				>
			{/each}
			<button
				class="text-[10px] px-1.5 py-0.5 rounded-md border transition {displayMode ===
				'illustrated'
					? 'bg-gray-900 text-white border-gray-900 dark:bg-white dark:text-gray-900 dark:border-white'
					: 'bg-white/70 dark:bg-gray-850/70 border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'}"
				title={$i18n.t(
					'Outlined, flat-shaded presentation. The geometry and every export are unchanged.'
				)}
				on:click={() => (displayMode = displayMode === 'illustrated' ? 'solid' : 'illustrated')}
				>{$i18n.t('Illustrated')}</button
			>
		</div>
	{/if}

	{#if pivot}
		<!-- The drag is a preview and this bar is what says so. Nothing has changed in the
		     document until Apply, and the wording has to carry that — a gizmo that looks
		     like a direct edit is exactly the surprise CS-8 exists to avoid. -->
		<div
			class="absolute bottom-12 left-1/2 -translate-x-1/2 flex items-center gap-2 rounded-lg border border-amber-300/70 dark:border-amber-500/40 bg-white/95 dark:bg-gray-900/95 shadow-lg px-2.5 py-1.5 text-[11px]"
			role="status"
		>
			<span class="text-amber-700 dark:text-amber-400 font-medium"
				>{$i18n.t('Preview — not saved')}</span
			>
			{#if pendingNote}
				<span class="tabular-nums text-gray-600 dark:text-gray-300">{pendingNote}</span>
			{:else}
				<span class="text-gray-500 dark:text-gray-400"
					>{tool === 'rotate' ? $i18n.t('Drag a ring to turn it.') : $i18n.t('Drag an arrow to move it.')}</span
				>
			{/if}

			{#if overReach}
				<span class="text-red-500 dark:text-red-400"
					>{$i18n.t('Beyond the {{max}} mm limit for a placement.', {
						max: MAX_TRANSLATE_MM
					})}</span
				>
			{:else if applyError}
				<span class="text-red-500 dark:text-red-400">{applyError}</span>
			{/if}

			<button
				class="px-2 py-0.5 rounded-md bg-gray-900 text-white dark:bg-white dark:text-gray-900 disabled:opacity-40 disabled:cursor-not-allowed transition"
				disabled={!pending || applying || overReach}
				title={$i18n.t('Rebuild this part with the new placement as a new revision.')}
				on:click={applyGizmo}>{applying ? $i18n.t('Applying…') : $i18n.t('Apply')}</button
			>
			<button
				class="px-2 py-0.5 rounded-md border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
				title={$i18n.t('Discard the preview. Escape does the same.')}
				on:click={cancelGizmo}>{$i18n.t('Cancel')}</button
			>
		</div>
	{/if}

	{#if url && !error}
		<span
			class="pointer-events-none absolute top-2 right-2 text-[9px] uppercase tracking-widest text-gray-400 dark:text-gray-500"
			>{format} · {$i18n.t('millimetres')}</span
		>
	{/if}
</div>

<style>
	.cad-canvas {
		background: radial-gradient(closest-side, rgba(120, 160, 220, 0.08), transparent 78%);
	}
	.cad-canvas :global(canvas) {
		display: block;
		touch-action: none; /* OrbitControls owns the gesture */
	}
</style>
