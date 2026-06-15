// Template catalog for the Automations gallery. Each template seeds an
// Orchestrate task: clicking "Use" opens a new chat in Orchestrate mode and
// sends the prompt (one click -> a running multi-agent run). "Schedule"
// turns the same prompt into a recurring automation (cron job).

export type TemplateCategory =
	| 'Code Review'
	| 'Security'
	| 'Incidents & Triage'
	| 'Data & Research';

export interface AutomationTemplate {
	id: string;
	title: string;
	description: string;
	category: TemplateCategory;
	popular?: boolean;
	prompt: string; // the Orchestrate task brief
}

// Tab order mirrors the reference dashboard. 'Popular' is a curated view.
export const TEMPLATE_TABS = [
	'Popular',
	'Code Review',
	'Security',
	'Incidents & Triage',
	'Data & Research'
] as const;
export type TemplateTab = (typeof TEMPLATE_TABS)[number];

export const AUTOMATION_TEMPLATES: AutomationTemplate[] = [
	{
		id: 'find-critical-bugs',
		title: 'Find critical bugs',
		description:
			'Analyze the recent changes for high-severity correctness bugs and propose safe fixes.',
		category: 'Code Review',
		popular: true,
		prompt:
			'Review the recent code changes in this project for high-severity correctness bugs (logic errors, race conditions, unhandled edge cases). For each, explain the bug and propose a safe, minimal fix.'
	},
	{
		id: 'add-test-coverage',
		title: 'Add test coverage',
		description: 'Review recent changes and add tests for high-risk logic that lacks coverage.',
		category: 'Code Review',
		popular: true,
		prompt:
			'Identify high-risk logic in the recent changes that lacks adequate test coverage, then write focused tests for it. Cover edge cases and failure paths.'
	},
	{
		id: 'review-simplify',
		title: 'Review & simplify',
		description: 'Review recent changes for reuse, dead code, and simplification opportunities.',
		category: 'Code Review',
		prompt:
			'Review the recent changes for reuse, simplification, dead code, and over-engineering. Propose concrete cleanups that reduce complexity without changing behavior.'
	},
	{
		id: 'scan-vulnerabilities',
		title: 'Scan codebase for vulnerabilities',
		description:
			'Review the repository and report validated high-impact security issues.',
		category: 'Security',
		popular: true,
		prompt:
			'Audit the codebase for high-impact security issues: injection, broken auth, SSRF, hardcoded secrets, unsafe deserialization, and path traversal. Report only validated findings with the file, the risk, and a fix.'
	},
	{
		id: 'audit-dependencies',
		title: 'Audit dependencies',
		description: 'Check dependencies for known vulnerabilities and risky/outdated packages.',
		category: 'Security',
		prompt:
			'Review the project dependencies for known vulnerabilities, unmaintained packages, and risky version pins. Summarize what to upgrade or replace and why.'
	},
	{
		id: 'generate-docs',
		title: 'Generate docs',
		description: 'Create and update developer documentation for recently changed code.',
		category: 'Data & Research',
		popular: true,
		prompt:
			'Create and update developer documentation for the recently changed or under-documented parts of this project. Write clear usage notes, parameters, and examples.'
	},
	{
		id: 'triage-failing-tests',
		title: 'Triage failing tests',
		description: 'Investigate failing tests, find root causes, and propose fixes.',
		category: 'Incidents & Triage',
		prompt:
			'Investigate the currently failing tests in this project. For each failure, find the root cause and propose a fix. Group related failures.'
	},
	{
		id: 'investigate-errors',
		title: 'Investigate recent errors',
		description: 'Review recent logs/errors, cluster them, and surface the top issues.',
		category: 'Incidents & Triage',
		prompt:
			'Review the recent error logs and exceptions in this project. Cluster them by root cause, rank by impact, and recommend the highest-leverage fixes.'
	},
	{
		id: 'research-topic',
		title: 'Research a topic',
		description: 'Research a topic across available sources and synthesize a cited summary.',
		category: 'Data & Research',
		prompt:
			"Research this project's domain for recent, relevant developments and best practices, then synthesize a concise, cited summary of the key findings and trade-offs."
	}
];

export const templatesForTab = (tab: TemplateTab): AutomationTemplate[] =>
	tab === 'Popular'
		? AUTOMATION_TEMPLATES.filter((t) => t.popular)
		: AUTOMATION_TEMPLATES.filter((t) => t.category === tab);
