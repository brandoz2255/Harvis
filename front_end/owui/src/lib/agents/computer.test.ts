import { describe, expect, it } from 'vitest';
import { vncUrl } from './computer';

describe('vncUrl', () => {
	const path = 'agents/vnc/websockify?token=81b297c14bb508a3ad8b83df2ac52956';

	it('points at the noVNC page on the app origin and encodes the token path', () => {
		const url = vncUrl(path, '');
		expect(url.startsWith('/agents/vnc/vnc.html?')).toBe(true);
		// The path carries its own `?token=`; unencoded it would split the outer query.
		expect(url).toContain(`path=${encodeURIComponent(path)}`);
		expect(url).not.toContain('path=agents/vnc/websockify?token');
	});

	it('connects on load and scales to the pane', () => {
		const url = vncUrl(path, '');
		expect(url).toContain('autoconnect=true');
		expect(url).toContain('resize=scale');
	});

	it('honours a non-empty base for dev servers', () => {
		expect(vncUrl(path, 'http://localhost:8080')).toMatch(/^http:\/\/localhost:8080\/agents\/vnc\//);
	});
});
