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
	import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
	import { STLLoader } from 'three/addons/loaders/STLLoader.js';

	const i18n: any = getContext('i18n');

	/** Authorized artifact URL. Changing it reloads the viewport. */
	export let url = '';
	export let format: 'glb' | 'stl' = 'glb';
	/** Height of the canvas. The panel is a narrow column; the chat card is shorter. */
	export let height = 340;

	const authHdr = () => ({ Authorization: `Bearer ${localStorage.token}` });

	let container: HTMLDivElement;
	let renderer: THREE.WebGLRenderer;
	let scene: THREE.Scene;
	let camera: THREE.PerspectiveCamera;
	let controls: OrbitControls;
	let ro: ResizeObserver;
	let raf = 0;
	let mounted = false;

	let part: THREE.Object3D | null = null;
	let loading = false;
	let error = '';
	let wireframe = false;
	let loadToken = 0; // guards against a slow load landing after a newer one

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
		if (!part) return;
		scene.remove(part);
		disposeObject(part);
		part = null;
	};

	// Normalize whatever came back into something centred and visible: build123d is
	// Z-up, three is Y-up, and a part's real size in millimetres ranges from a few to
	// a few hundred — so the object is rotated, scaled to a fixed world size, and
	// recentred rather than being shown at its literal coordinates.
	const placePart = (obj: THREE.Object3D) => {
		obj.rotation.x = -Math.PI / 2; // Z-up → Y-up
		obj.updateMatrixWorld(true);
		const box = new THREE.Box3().setFromObject(obj);
		const size = new THREE.Vector3();
		const center = new THREE.Vector3();
		box.getSize(size);
		box.getCenter(center);
		const scale = FIT / (Math.max(size.x, size.y, size.z) || 1);
		obj.scale.setScalar(scale);
		obj.updateMatrixWorld(true);
		const scaled = new THREE.Box3().setFromObject(obj);
		scaled.getCenter(center);
		obj.position.sub(center);
		applyWireframe();
		scene.add(obj);
		part = obj;
		render();
	};

	const applyWireframe = () => {
		part?.traverse((n: any) => {
			const mats = Array.isArray(n.material) ? n.material : n.material ? [n.material] : [];
			for (const m of mats) if ('wireframe' in m) m.wireframe = wireframe;
		});
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
				// The engine writes no materials, so a default one is added here rather
				// than letting three fall back to something that reads as untextured black.
				root.traverse((n: any) => {
					if (n.isMesh && (!n.material || !n.material.isMaterial)) {
						n.material = new THREE.MeshStandardMaterial({
							color: 0x9ec5e8,
							metalness: 0.1,
							roughness: 0.65
						});
					}
				});
				placePart(root);
			} else {
				const geo = new STLLoader().parse(buf);
				geo.computeVertexNormals();
				if (token !== loadToken || !mounted) return;
				placePart(
					new THREE.Mesh(
						geo,
						new THREE.MeshStandardMaterial({
							color: 0x9ec5e8,
							metalness: 0.1,
							roughness: 0.65
						})
					)
				);
			}
		} catch (e: any) {
			if (token === loadToken) error = e?.message ?? String(e);
		} finally {
			if (token === loadToken) loading = false;
		}
	};

	const setView = (v: 'iso' | 'front' | 'top' | 'right') => {
		const d = camera.position.length() || INIT_CAM.length();
		const p =
			v === 'front'
				? new THREE.Vector3(0, 0, d)
				: v === 'top'
					? new THREE.Vector3(0, d, 0.001)
					: v === 'right'
						? new THREE.Vector3(d, 0, 0)
						: INIT_CAM.clone();
		camera.position.copy(p);
		controls.target.set(0, 0, 0);
		controls.update();
		render();
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
		camera.aspect = w / Math.max(1, h);
		camera.updateProjectionMatrix();
		render();
	};

	const loop = () => {
		raf = requestAnimationFrame(loop);
		if (controls.enableDamping) controls.update();
		renderer.render(scene, camera);
	};

	onMount(() => {
		renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
		renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
		renderer.setClearColor(0x000000, 0);
		container.appendChild(renderer.domElement);

		scene = new THREE.Scene();
		camera = new THREE.PerspectiveCamera(42, 1, 0.05, 200);
		camera.position.copy(INIT_CAM);

		scene.add(new THREE.AmbientLight(0xffffff, 0.55));
		const key = new THREE.DirectionalLight(0xffffff, 1.0);
		key.position.set(4, 6, 5);
		scene.add(key);
		const fill = new THREE.DirectionalLight(0x88b6ff, 0.35);
		fill.position.set(-5, 2, -4);
		scene.add(fill);

		const grid = new THREE.GridHelper(8, 16, 0x64748b, 0x334155);
		(grid.material as THREE.Material).transparent = true;
		(grid.material as THREE.Material).opacity = 0.35;
		grid.position.y = -FIT / 2 - 0.05;
		scene.add(grid);

		controls = new OrbitControls(camera, renderer.domElement);
		controls.enableDamping = !reduced;
		controls.dampingFactor = 0.08;
		controls.minDistance = 1.2;
		controls.maxDistance = 30;
		controls.update();

		resize();
		ro = new ResizeObserver(resize);
		ro.observe(container);

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
		controls?.dispose();
		if (scene) {
			clearPart();
			scene.traverse((o: any) => {
				o.geometry?.dispose?.();
				const mats = Array.isArray(o.material) ? o.material : o.material ? [o.material] : [];
				mats.forEach((m: THREE.Material) => m.dispose());
			});
		}
		renderer?.dispose();
	});

	$: if (mounted) load(url, format);
	$: if (mounted) {
		wireframe;
		applyWireframe();
	}
</script>

<div class="relative w-full">
	<div
		bind:this={container}
		class="cad-canvas w-full rounded-lg overflow-hidden border border-gray-100 dark:border-gray-850"
		style="height:{height}px"
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

	{#if url && !error}
		<div class="absolute bottom-2 left-2 flex flex-wrap items-center gap-1">
			{#each [['iso', 'Iso'], ['front', 'Front'], ['top', 'Top'], ['right', 'Right']] as [v, label]}
				<button
					class="text-[10px] px-1.5 py-0.5 rounded-md bg-white/70 dark:bg-gray-850/70 border border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 transition"
					on:click={() => setView(v as any)}>{$i18n.t(label)}</button
				>
			{/each}
			<button
				class="text-[10px] px-1.5 py-0.5 rounded-md border transition {wireframe
					? 'bg-gray-900 text-white border-gray-900 dark:bg-white dark:text-gray-900 dark:border-white'
					: 'bg-white/70 dark:bg-gray-850/70 border-gray-200 dark:border-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800'}"
				on:click={() => (wireframe = !wireframe)}>{$i18n.t('Wireframe')}</button
			>
		</div>
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
