export interface TerminalTextSegment {
	text: string;
	className: string;
}

const ANSI_PATTERN = /\u001B\[([0-9;]*)m/g;
const OTHER_ESCAPE_PATTERN = /\u001B\[[0-?]*[ -/]*[@-~]/g;
const OSC_PATTERN = /\u001B\][^\u0007]*(?:\u0007|\u001B\\|$)/g;
const CONTROL_PATTERN = /[\u0000-\u0008\u000B\u000C\u000E-\u001A\u001C-\u001F\u007F]/g;

const COLOR_CLASS: Record<number, string> = {
	30: 'text-gray-500',
	31: 'text-red-300',
	32: 'text-emerald-300',
	33: 'text-amber-300',
	34: 'text-blue-300',
	35: 'text-fuchsia-300',
	36: 'text-cyan-300',
	37: 'text-gray-200',
	90: 'text-gray-400',
	91: 'text-red-300',
	92: 'text-emerald-300',
	93: 'text-amber-300',
	94: 'text-blue-300',
	95: 'text-fuchsia-300',
	96: 'text-cyan-300',
	97: 'text-white'
};

const cleanTerminalText = (text: string): string =>
	text
		.replace(OSC_PATTERN, '')
		.replace(OTHER_ESCAPE_PATTERN, '')
		.replace(CONTROL_PATTERN, '')
		.replaceAll('\u001b', '');

export function stripTerminalControls(text: string): string {
	return cleanTerminalText(text);
}

export function parseAnsiSegments(text: string, fallbackClass = ''): TerminalTextSegment[] {
	const segments: TerminalTextSegment[] = [];
	let colorClass = fallbackClass;
	let bold = false;
	let cursor = 0;

	const push = (value: string) => {
		const clean = cleanTerminalText(value);
		if (!clean) return;
		segments.push({
			text: clean,
			className: [colorClass, bold ? 'font-semibold' : ''].filter(Boolean).join(' ')
		});
	};

	for (const match of text.matchAll(ANSI_PATTERN)) {
		push(text.slice(cursor, match.index));
		const codes = (match[1] || '0').split(';').map((code) => Number(code || 0));
		for (const code of codes) {
			if (code === 0) {
				colorClass = fallbackClass;
				bold = false;
			} else if (code === 1) {
				bold = true;
			} else if (code === 22) {
				bold = false;
			} else if (code === 39) {
				colorClass = fallbackClass;
			} else if (COLOR_CLASS[code]) {
				colorClass = COLOR_CLASS[code];
			}
		}
		cursor = (match.index ?? 0) + match[0].length;
	}
	push(text.slice(cursor));

	return segments;
}
