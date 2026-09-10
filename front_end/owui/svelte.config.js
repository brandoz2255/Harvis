import adapter from '@sveltejs/adapter-static';
import * as child_process from 'node:child_process';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import fs from 'node:fs';
import crypto from 'node:crypto';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	// Consult https://kit.svelte.dev/docs/integrations#preprocessors
	// for more information about preprocessors
	preprocess: vitePreprocess(),
	kit: {
		// adapter-auto only supports some environments, see https://kit.svelte.dev/docs/adapter-auto for a list.
		// If your environment is not supported or you settled on a specific environment, switch out the adapter.
		// See https://kit.svelte.dev/docs/adapters for more information about adapters.
		adapter: adapter({
			pages: 'build',
			assets: 'build',
			fallback: 'index.html'
		}),
		// poll for new version name every 60 seconds (to trigger reload mechanic in +layout.svelte)
		//
		// The working tree is part of the name on purpose. Keying this on the
		// commit alone meant a rebuild from a dirty tree produced a byte-identical
		// version.json, so a tab open across that rebuild never learned it was
		// stale: it kept the old content-hashed chunk names, which the new build
		// had already deleted, and the next lazy-loaded route 404'd. That is most
		// of a working day in this repo, where the tree is dirty by definition.
		//
		// It must be a hash of the tree and NOT a timestamp. SvelteKit derives the
		// `__sveltekit_<hash>` bootstrap global from this name, and Vite evaluates
		// this config once per build pass (client, then server). A Date.now() here
		// gave the two passes different names, so app.html declared
		// `__sveltekit_denurp` while the client runtime read
		// `__sveltekit_txodb1` — undefined.data, thrown inside kit.start(), and
		// the app never left the splash screen. Hashing content instead is stable
		// within a build and still changes whenever the output would.
		version: {
			name: (() => {
				const treeHash = (input) =>
					crypto.createHash('sha256').update(input).digest('hex').slice(0, 12);
				try {
					const head = child_process.execSync('git rev-parse --short HEAD').toString().trim();
					// Tracked edits (staged and not) plus the porcelain list, which is
					// what makes an untracked file appearing or disappearing count.
					const tree = child_process
						.execSync('git status --porcelain=v1 && git diff HEAD', {
							maxBuffer: 128 * 1024 * 1024
						})
						.toString();
					return `${head}-${treeHash(tree)}`;
				} catch {
					// if git is not available, fallback to package.json version
					try {
						const pkg = fs.readFileSync(new URL('./package.json', import.meta.url), 'utf8');
						return `${JSON.parse(pkg)?.version ?? 'dev'}-${treeHash(pkg)}`;
					} catch {
						return 'dev';
					}
				}
			})(),
			pollInterval: 60000
		}
	},
	vitePlugin: {
		// inspector: {
		// 	toggleKeyCombo: 'meta-shift', // Key combination to open the inspector
		// 	holdMode: false, // Enable or disable hold mode
		// 	showToggleButton: 'always', // Show toggle button ('always', 'active', 'never')
		// 	toggleButtonPos: 'bottom-right' // Position of the toggle button
		// }
	},
	onwarn: (warning, handler) => {
		const { code } = warning;
		if (code === 'css-unused-selector') return;

		handler(warning);
	}
};

export default config;
