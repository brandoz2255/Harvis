/**
 * Browser File System Access API — lets VibeCode read and write the user's REAL local
 * folder with no server-side path, no bind-mount, and no separate agent. Chromium only
 * (Chrome / Edge / Brave / Arc). The picked `FileSystemDirectoryHandle` is the source of
 * truth: we snapshot it to seed the backend session, then write the agent's changes back
 * into it after each turn. Handles are persisted in IndexedDB so "Recent" can re-open them.
 */

export interface LocalFolderFile {
	path: string; // relative POSIX path inside the picked folder
	content: string;
}

export interface RecentFolder {
	key: string;
	name: string;
	handle: any; // FileSystemDirectoryHandle (typed `any` — lib.dom coverage varies)
	lastUsed: number;
	sessionId?: string;
}

// Directories never worth uploading (vcs/deps/build) — mirrors the backend skip set.
const SKIP_DIRS = new Set([
	'.git',
	'node_modules',
	'.venv',
	'venv',
	'__pycache__',
	'dist',
	'.next',
	'build',
	'.cache',
	'.turbo',
	'.idea',
	'.vscode',
	'.svelte-kit',
	'coverage'
]);
const MAX_FILE_BYTES = 512 * 1024;

export const supportsLocalFs = (): boolean =>
	typeof window !== 'undefined' && 'showDirectoryPicker' in window;

/** Open the native OS directory picker (read-write). Throws if the user cancels. */
export const pickLocalDirectory = async (): Promise<any> => {
	// @ts-ignore — showDirectoryPicker isn't in every TS lib.dom version
	return await window.showDirectoryPicker({ mode: 'readwrite', id: 'harvis-vibecode' });
};

/** Ensure we still hold read-write permission for a (possibly persisted) handle. */
export const verifyPermission = async (handle: any, readWrite = true): Promise<boolean> => {
	const opts = { mode: readWrite ? 'readwrite' : 'read' } as any;
	try {
		if ((await handle.queryPermission?.(opts)) === 'granted') return true;
		if ((await handle.requestPermission?.(opts)) === 'granted') return true;
	} catch (_) {}
	return false;
};

const isProbablyBinary = (buf: Uint8Array): boolean => {
	const n = Math.min(buf.length, 8000);
	for (let i = 0; i < n; i++) if (buf[i] === 0) return true;
	return false;
};

/** Recursively read every (small, text) file in the folder → seed payload for the backend. */
export const readFolderSnapshot = async (
	dir: any,
	onProgress?: (count: number) => void
): Promise<LocalFolderFile[]> => {
	const out: LocalFolderFile[] = [];
	const decoder = new TextDecoder('utf-8', { fatal: false });
	const walk = async (handle: any, prefix: string): Promise<void> => {
		for await (const [name, child] of handle.entries()) {
			if (child.kind === 'directory') {
				if (SKIP_DIRS.has(name) || name.startsWith('.git')) continue;
				await walk(child, prefix ? `${prefix}/${name}` : name);
			} else {
				const rel = prefix ? `${prefix}/${name}` : name;
				try {
					const file = await child.getFile();
					if (file.size > MAX_FILE_BYTES) continue;
					const buf = new Uint8Array(await file.arrayBuffer());
					if (isProbablyBinary(buf)) continue;
					out.push({ path: rel, content: decoder.decode(buf) });
					onProgress?.(out.length);
				} catch (_) {}
			}
		}
	};
	await walk(dir, '');
	return out;
};

const fileHandleByPath = async (dir: any, path: string, create: boolean): Promise<any> => {
	const parts = path.split('/').filter(Boolean);
	const fname = parts.pop() as string;
	let cur = dir;
	for (const p of parts) cur = await cur.getDirectoryHandle(p, { create });
	return await cur.getFileHandle(fname, { create });
};

/** Write the agent's changed files back into the real folder. Returns count written. */
export const writeFilesToFolder = async (dir: any, files: LocalFolderFile[]): Promise<number> => {
	let written = 0;
	for (const f of files) {
		try {
			const fh = await fileHandleByPath(dir, f.path, true);
			const w = await fh.createWritable();
			await w.write(f.content ?? '');
			await w.close();
			written++;
		} catch (_) {}
	}
	return written;
};

/** Remove files the agent deleted. Prunes now-empty parent dirs best-effort. */
export const deleteFilesFromFolder = async (dir: any, paths: string[]): Promise<void> => {
	for (const path of paths) {
		try {
			const parts = path.split('/').filter(Boolean);
			const fname = parts.pop() as string;
			let cur = dir;
			for (const p of parts) cur = await cur.getDirectoryHandle(p);
			await cur.removeEntry(fname);
		} catch (_) {}
	}
};

// ─── IndexedDB persistence for the "Recent" list ─────────────────────────────
const DB_NAME = 'harvis-vibecode';
const STORE = 'folders';

const idb = (): Promise<IDBDatabase> =>
	new Promise((resolve, reject) => {
		const req = indexedDB.open(DB_NAME, 1);
		req.onupgradeneeded = () => {
			if (!req.result.objectStoreNames.contains(STORE)) {
				req.result.createObjectStore(STORE, { keyPath: 'key' });
			}
		};
		req.onsuccess = () => resolve(req.result);
		req.onerror = () => reject(req.error);
	});

const tx = async <T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest): Promise<T> => {
	const db = await idb();
	return new Promise<T>((resolve, reject) => {
		const store = db.transaction(STORE, mode).objectStore(STORE);
		const r = fn(store);
		r.onsuccess = () => resolve(r.result as T);
		r.onerror = () => reject(r.error);
	});
};

export const listRecentFolders = async (): Promise<RecentFolder[]> => {
	try {
		const all = (await tx<RecentFolder[]>('readonly', (s) => s.getAll())) || [];
		return all.sort((a, b) => (b.lastUsed || 0) - (a.lastUsed || 0));
	} catch (_) {
		return [];
	}
};

/** Persist a freshly-picked folder, de-duping against an existing entry for the SAME dir. */
export const rememberFolder = async (handle: any): Promise<RecentFolder> => {
	const existing = await listRecentFolders();
	for (const r of existing) {
		try {
			if (r.handle && (await handle.isSameEntry?.(r.handle))) {
				const updated = { ...r, lastUsed: Date.now() };
				await tx('readwrite', (s) => s.put(updated));
				return updated;
			}
		} catch (_) {}
	}
	const entry: RecentFolder = {
		key: `${handle.name}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
		name: handle.name,
		handle,
		lastUsed: Date.now()
	};
	await tx('readwrite', (s) => s.put(entry));
	return entry;
};

export const linkSessionToFolder = async (key: string, sessionId: string): Promise<void> => {
	try {
		const entry = await tx<RecentFolder | undefined>('readonly', (s) => s.get(key));
		if (entry) await tx('readwrite', (s) => s.put({ ...entry, sessionId, lastUsed: Date.now() }));
	} catch (_) {}
};

export const findFolderForSession = async (sessionId: string): Promise<RecentFolder | null> => {
	const all = await listRecentFolders();
	return all.find((r) => r.sessionId === sessionId) ?? null;
};

export const forgetFolder = async (key: string): Promise<void> => {
	try {
		await tx('readwrite', (s) => s.delete(key));
	} catch (_) {}
};
