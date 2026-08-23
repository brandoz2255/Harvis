import { describe, expect, it } from 'vitest';

import { parseAnsiSegments, stripTerminalControls } from './terminalText';

describe('terminal text safety', () => {
	it('maps whitelisted ANSI colors without rendering terminal escape sequences', () => {
		expect(parseAnsiSegments('\u001b[31merror\u001b[0m ok')).toEqual([
			{ text: 'error', className: 'text-red-300' },
			{ text: ' ok', className: '' }
		]);
	});

	it('removes unsupported control characters while preserving whitespace', () => {
		expect(stripTerminalControls('one\tline\n\u0000two')).toBe('one\tline\ntwo');
	});

	it('removes non-color CSI and OSC terminal instructions without printable remnants', () => {
		const input = '\u001b[2Jbefore\u001b]0;secret title\u0007after';
		expect(stripTerminalControls(input)).toBe('beforeafter');
		expect(parseAnsiSegments(input)).toEqual([{ text: 'beforeafter', className: '' }]);
	});
});
