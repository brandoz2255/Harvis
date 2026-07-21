/** Paths that must not bounce to /auth (or yank the /setup wizard mid-flow). */
export const PUBLIC_ROUTES = ['/auth', '/setup', '/error', '/s/', '/watch'] as const;

export function isPublicRoute(pathname: string): boolean {
	const path = pathname || '/';
	return PUBLIC_ROUTES.some(
		(p) => path === p || path.startsWith(p.endsWith('/') ? p : `${p}/`) || path.startsWith(p)
	);
}
