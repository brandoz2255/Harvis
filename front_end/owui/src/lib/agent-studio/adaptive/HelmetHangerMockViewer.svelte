<script lang="ts">
	// Helmet Hanger MOCK 3D viewer (proof of concept — runs on nothing real).
	// Procedural Three.js hanger (wall plate · support arm/hook · screws ·
	// translucent helmet placeholder) with mouse-orbit + zoom, a load arrow, and
	// a stress-spectrum heatmap painted per-vertex via a green→amber→red LUT.
	// The "stress" scalar is SYNTHETIC — a function of distance from the wall
	// joint and the assumed load. This is NOT FEA; it is an illustrative overlay,
	// labeled as such. No CAD engine, no simulation, no file import/export.
	import { getContext, onMount, onDestroy } from 'svelte';
	import * as THREE from 'three';
	import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
	import { Lut } from 'three/addons/math/Lut.js';
	import { STLLoader } from 'three/addons/loaders/STLLoader.js';

	const i18n: any = getContext('i18n');

	export let load = 5; // assumed helmet load (lb) — drives the heatmap intensity
	// When set, load a REAL parametric STL (build123d, Stage 2) instead of the
	// procedural mock. The heatmap overlay stays illustrative either way.
	export let meshUrl = '';

	let realMode = false;
	const authHdr = () => ({ Authorization: `Bearer ${localStorage.token}` });

	let container: HTMLDivElement;
	let ready = false;

	let renderer: THREE.WebGLRenderer;
	let scene: THREE.Scene;
	let camera: THREE.PerspectiveCamera;
	let controls: OrbitControls;
	let raf = 0;
	let ro: ResizeObserver;

	// The wall joint (base of the support arm) — the hottest point of the mock
	// stress field: a cantilever's bending moment peaks at the fixed end.
	const JOINT = new THREE.Vector3(-1.3, 0.35, 0);
	const lut = new Lut('stress', 32);
	// Harvis-blue-adjacent stress spectrum: green (low) → amber → red (high).
	lut.addColorMap('stress', [
		[0.0, 0x22c55e],
		[0.5, 0xfcd34d],
		[1.0, 0xf87171]
	]);
	lut.setColorMap('stress');

	// meshes whose vertex colors re-bake when the load changes
	const heatMeshes: THREE.Mesh[] = [];
	let maxDist = 1;

	const INIT_CAM = new THREE.Vector3(2.6, 1.9, 3.4);
	const INIT_TARGET = new THREE.Vector3(0.1, 0.15, 0);

	const reduced =
		typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

	// ── synthetic per-vertex stress scalar: hottest near the wall joint, scaled
	// by the assumed load. Deterministic; no physics. ──
	const loadFactor = (w: number) => Math.min(1.05, 0.55 + w * 0.08);

	const bakeStress = (mesh: THREE.Mesh, w: number) => {
		const geo = mesh.geometry as THREE.BufferGeometry;
		const pos = geo.getAttribute('position');
		const colors = new Float32Array(pos.count * 3);
		const v = new THREE.Vector3();
		const f = loadFactor(w);
		for (let i = 0; i < pos.count; i++) {
			v.fromBufferAttribute(pos, i).applyMatrix4(mesh.matrixWorld);
			const d = v.distanceTo(JOINT);
			// closer to the joint = hotter; gamma concentrates the heat at the base
			const near = Math.pow(1 - Math.min(1, d / maxDist), 1.6);
			const s = Math.max(0, Math.min(1, near * f));
			const c = lut.getColor(s);
			colors[i * 3] = c.r;
			colors[i * 3 + 1] = c.g;
			colors[i * 3 + 2] = c.b;
		}
		geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
	};

	// Real-mesh heatmap: color by geometry-local X (min X = wall root = hottest).
	// The recipe orients the arm along +X with the wall at min X, so this reads as
	// a cantilever whose bending stress peaks at the fixed end — illustrative, not FEA.
	const bakeStressReal = (mesh: THREE.Mesh, w: number) => {
		const geo = mesh.geometry as THREE.BufferGeometry;
		const pos = geo.getAttribute('position');
		if (!geo.boundingBox) geo.computeBoundingBox();
		const bb = geo.boundingBox!;
		const minx = bb.min.x;
		const span = bb.max.x - bb.min.x || 1;
		const colors = new Float32Array(pos.count * 3);
		const f = loadFactor(w);
		for (let i = 0; i < pos.count; i++) {
			const near = Math.pow(1 - (pos.getX(i) - minx) / span, 1.4);
			const s = Math.max(0, Math.min(1, near * f));
			const c = lut.getColor(s);
			colors[i * 3] = c.r;
			colors[i * 3 + 1] = c.g;
			colors[i * 3 + 2] = c.b;
		}
		geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
	};

	const applyStress = (w: number) => {
		for (const m of heatMeshes) (realMode ? bakeStressReal : bakeStress)(m, w);
		render();
	};

	// Load the real STL (auth'd blob → STLLoader), stand it up (build123d Z-up →
	// three Y-up), fit it to the scene, and heatmap it. Called only when meshUrl set.
	const loadRealMesh = async (url: string) => {
		try {
			const r = await fetch(url, { headers: authHdr(), credentials: 'include' });
			if (!r.ok) return;
			const geo = new STLLoader().parse(await r.arrayBuffer());
			geo.computeVertexNormals();
			geo.computeBoundingBox();
			const bb = geo.boundingBox!;
			const size = new THREE.Vector3();
			bb.getSize(size);
			const sc = 3.0 / (Math.max(size.x, size.y, size.z) || 1);
			const center = new THREE.Vector3();
			bb.getCenter(center);
			const mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ vertexColors: true }));
			mesh.scale.setScalar(sc);
			mesh.rotation.x = -Math.PI / 2; // Z-up (build123d) → Y-up (three)
			// After rotation local (x,y,z)→(x,z,-y), so recenter with local-Z on world-Y
			// (negated) and local-Y on world-Z — keeps the part centred for any dims.
			mesh.position.set(-center.x * sc, -center.z * sc, center.y * sc);
			scene.add(mesh);
			heatMeshes.length = 0;
			heatMeshes.push(mesh);
			realMode = true;
			applyStress(load);
			render();
		} catch {
			/* fall back to whatever is in the scene */
		}
	};

	const render = () => {
		if (renderer && scene && camera) renderer.render(scene, camera);
	};

	const resetView = () => {
		camera.position.copy(INIT_CAM);
		controls.target.copy(INIT_TARGET);
		controls.update();
		render();
	};

	const buildScene = () => {
		scene = new THREE.Scene();

		camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
		camera.position.copy(INIT_CAM);

		// lights — MeshLambertMaterial + vertexColors reads the heatmap honestly
		scene.add(new THREE.AmbientLight(0x7dd3fc, 0.55));
		const key = new THREE.DirectionalLight(0xffffff, 0.9);
		key.position.set(3, 5, 4);
		scene.add(key);
		const rim = new THREE.DirectionalLight(0x38bdf8, 0.35);
		rim.position.set(-4, 2, -3);
		scene.add(rim);

		// ── wall backdrop (static, not part of the tested object) ──
		const wall = new THREE.Mesh(
			new THREE.BoxGeometry(0.15, 3, 2.6),
			new THREE.MeshLambertMaterial({ color: 0x162236, transparent: true, opacity: 0.55 })
		);
		wall.position.set(-1.55, 0, 0);
		scene.add(wall);
		// faint wall grid lines
		const grid = new THREE.GridHelper(2.4, 10, 0x334155, 0x223047);
		grid.rotation.z = Math.PI / 2;
		grid.position.set(-1.47, 0, 0);
		(grid.material as THREE.Material).transparent = true;
		(grid.material as THREE.Material).opacity = 0.4;
		scene.add(grid);

		const heatMat = () => new THREE.MeshLambertMaterial({ vertexColors: true });

		if (!meshUrl) {
		// ── wall plate (heatmapped) ──
		const plate = new THREE.Mesh(new THREE.BoxGeometry(0.16, 1.5, 0.6, 2, 20, 8), heatMat());
		plate.position.set(-1.4, 0.15, 0);
		scene.add(plate);
		heatMeshes.push(plate);

		// ── mount screws (heatmapped — pull-out zone) ──
		for (const sy of [0.72, -0.42]) {
			const screw = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.07, 0.24, 16, 4), heatMat());
			screw.rotation.z = Math.PI / 2;
			screw.position.set(-1.28, sy, 0);
			scene.add(screw);
			heatMeshes.push(screw);
		}

		// ── support arm + hook: a tube along a curve, wall joint → out → up → curl ──
		const curve = new THREE.CatmullRomCurve3([
			new THREE.Vector3(-1.3, 0.35, 0),
			new THREE.Vector3(-0.4, 0.28, 0),
			new THREE.Vector3(0.5, 0.18, 0),
			new THREE.Vector3(1.05, 0.2, 0),
			new THREE.Vector3(1.28, 0.5, 0),
			new THREE.Vector3(1.05, 0.72, 0),
			new THREE.Vector3(0.82, 0.55, 0)
		]);
		const arm = new THREE.Mesh(new THREE.TubeGeometry(curve, 96, 0.095, 16, false), heatMat());
		scene.add(arm);
		heatMeshes.push(arm);
		// rounded caps
		for (const p of [curve.getPoint(0), curve.getPoint(1)]) {
			const cap = new THREE.Mesh(new THREE.SphereGeometry(0.095, 16, 12), heatMat());
			cap.position.copy(p);
			scene.add(cap);
			heatMeshes.push(cap);
		}

		// ── translucent helmet placeholder (NOT tested — hangs on the hook) ──
		const helmet = new THREE.Mesh(
			new THREE.SphereGeometry(0.42, 32, 20, 0, Math.PI * 2, 0, Math.PI * 0.62),
			new THREE.MeshLambertMaterial({
				color: 0xcbd5e1,
				transparent: true,
				opacity: 0.22,
				side: THREE.DoubleSide,
				wireframe: false
			})
		);
		helmet.position.set(0.95, -0.12, 0);
		scene.add(helmet);
		const helmetEdge = new THREE.Mesh(
			new THREE.SphereGeometry(0.43, 24, 6, 0, Math.PI * 2, 0, Math.PI * 0.62),
			new THREE.MeshBasicMaterial({ color: 0x94a3b8, wireframe: true, transparent: true, opacity: 0.25 })
		);
		helmetEdge.position.copy(helmet.position);
		scene.add(helmetEdge);

		// ── load arrow (downward, from the helmet) ──
		const arrow = new THREE.ArrowHelper(
			new THREE.Vector3(0, -1, 0),
			new THREE.Vector3(0.95, -0.55, 0),
			0.7,
			0x7dd3fc,
			0.2,
			0.13
		);
		scene.add(arrow);

		// bake initial stress once matrices are current
		scene.updateMatrixWorld(true);
		maxDist = 0;
		const v = new THREE.Vector3();
		for (const m of heatMeshes) {
			const pos = m.geometry.getAttribute('position');
			for (let i = 0; i < pos.count; i++) {
				v.fromBufferAttribute(pos, i).applyMatrix4(m.matrixWorld);
				maxDist = Math.max(maxDist, v.distanceTo(JOINT));
			}
		}
		applyStress(load);
		}
	};

	const loop = () => {
		raf = requestAnimationFrame(loop);
		if (controls.enableDamping) controls.update();
		renderer.render(scene, camera);
	};

	const resize = () => {
		if (!container || !renderer) return;
		const w = container.clientWidth;
		const h = container.clientHeight;
		renderer.setSize(w, h, false);
		camera.aspect = w / Math.max(1, h);
		camera.updateProjectionMatrix();
		render();
	};

	onMount(() => {
		renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
		renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		renderer.setClearColor(0x000000, 0);
		container.appendChild(renderer.domElement);

		buildScene();
		if (meshUrl) loadRealMesh(meshUrl);

		controls = new OrbitControls(camera, renderer.domElement);
		controls.target.copy(INIT_TARGET);
		controls.enableDamping = !reduced;
		controls.dampingFactor = 0.08;
		controls.enablePan = false;
		controls.minDistance = 2;
		controls.maxDistance = 8;
		controls.update();

		resize();
		ro = new ResizeObserver(resize);
		ro.observe(container);

		ready = true;
		if (reduced) {
			// user-driven orbit still works; just re-render on interaction, no rAF
			controls.addEventListener('change', render);
			render();
		} else {
			loop();
		}
	});

	onDestroy(() => {
		cancelAnimationFrame(raf);
		ro?.disconnect();
		controls?.dispose();
		if (scene) {
			scene.traverse((o: any) => {
				if (o.geometry) o.geometry.dispose();
				if (o.material) {
					const mats = Array.isArray(o.material) ? o.material : [o.material];
					mats.forEach((m: THREE.Material) => m.dispose());
				}
			});
		}
		renderer?.dispose();
	});

	// re-bake the heatmap when the assumed load changes (no reload)
	$: if (ready) applyStress(load);
</script>

<div class="relative w-full">
	<div bind:this={container} class="hh-canvas w-full rounded-lg overflow-hidden" aria-label={realMode ? $i18n.t('Real parametric 3D hanger with illustrative stress overlay') : $i18n.t('Mock 3D helmet hanger with stress heatmap')}></div>

	<!-- stress spectrum legend. In real-mesh mode the geometry is genuine, so the
	     colours must be explicitly flagged as illustrative, NOT a simulation of the part. -->
	<div class="pointer-events-none absolute top-2 right-2 flex flex-col items-end gap-0.5">
		<span class="text-[8px] uppercase tracking-widest text-gray-400">{realMode ? $i18n.t('Illustrative overlay — not FEA') : $i18n.t('Stress spectrum (mock)')}</span>
		<div class="h-1.5 w-28 rounded-full" style="background:linear-gradient(90deg,#22c55e,#fcd34d,#f87171);"></div>
		<div class="flex w-28 justify-between text-[8px] uppercase tracking-widest text-gray-500">
			<span>{$i18n.t('low')}</span><span>{$i18n.t('high')}</span>
		</div>
	</div>

	<!-- controls hint + reset -->
	<div class="absolute bottom-2 left-2 flex flex-col gap-0.5">
		<span class="text-[9px] uppercase tracking-widest text-cyan-300/60">{$i18n.t('Drag to orbit · scroll to zoom')}</span>
		{#if realMode}
			<span class="text-[8px] text-amber-300/70">{$i18n.t('Colours = a synthetic pattern, not a simulation of this part')}</span>
		{/if}
	</div>
	<button
		class="absolute bottom-2 right-2 text-[10px] px-2 py-1 rounded-lg border border-cyan-400/30 text-cyan-200 hover:bg-cyan-400/10 transition"
		on:click={resetView}>{$i18n.t('Reset view')}</button
	>
</div>

<style>
	.hh-canvas {
		height: 320px;
		background: radial-gradient(closest-side, rgba(56, 189, 248, 0.06), transparent 78%);
	}
	@media (min-width: 640px) {
		.hh-canvas {
			height: 380px;
		}
	}
	/* big stage on desktop (hybrid layout — the result is the star) */
	@media (min-width: 1024px) {
		.hh-canvas {
			height: 460px;
		}
	}
	.hh-canvas :global(canvas) {
		display: block;
		touch-action: none; /* let OrbitControls own the gesture */
	}
</style>
