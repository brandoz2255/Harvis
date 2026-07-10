import { WEBUI_API_BASE_URL, WEBUI_BASE_URL } from '$lib/constants';

export const createNewSkill = async (token: string, skill: object) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/create`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			...skill
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? err.message ?? 'Request failed';
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getSkills = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail ?? err.message ?? 'Request failed';
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getSkillList = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/list`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail ?? err.message ?? 'Request failed';
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getSkillItems = async (
	token: string = '',
	query: string | null = null,
	viewOption: string | null = null,
	page: number | null = null
) => {
	let error = null;

	const searchParams = new URLSearchParams();
	if (query) searchParams.append('query', query);
	if (viewOption) searchParams.append('view_option', viewOption);
	if (page) searchParams.append('page', page.toString());

	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/list?${searchParams.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const exportSkills = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/export`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail ?? err.message ?? 'Request failed';
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getSkillById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/id/${id}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail ?? err.message ?? 'Request failed';
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateSkillById = async (token: string, id: string, skill: object) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/id/${id}/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			...skill
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? err.message ?? 'Request failed';
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateSkillAccessGrants = async (token: string, id: string, accessGrants: any[]) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/id/${id}/access/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			access_grants: accessGrants
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? err.message ?? 'Request failed';
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const toggleSkillById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/id/${id}/toggle`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail ?? err.message ?? 'Request failed';
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

// ── Skill governance (Execution Core Phase 5) — audit / self-edit / verdict ──
// Backend: python_back_end/owui_compat/skill_audit.py

export const auditSkill = async (token: string, id: string) => {
	let error = null;

	// Response: { run_id, runnable, findings: string[], analysis_md }
	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/id/${id}/audit`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? err.message ?? 'Request failed';
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const selfEditSkill = async (token: string, id: string) => {
	let error = null;

	// Response: { ok, revision_count, note } — 409 if already self-edited this audit cycle
	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/id/${id}/self-edit`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? err.message ?? 'Request failed';
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const setSkillVerdict = async (
	token: string,
	id: string,
	// FactCheckVerdict vocabulary — only 'supported' makes the skill publishable
	verdict:
		| 'supported'
		| 'partially_supported'
		| 'unsupported'
		| 'contradicted'
		| 'insufficient_evidence',
	notes: string | null = null
) => {
	let error = null;

	// Response: { ok, verdict, publishable }
	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/id/${id}/verdict`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			verdict,
			notes
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? err.message ?? 'Request failed';
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

// ── OpenClaw skill/MCP sync — dry-run preview + explicit apply ──
// Backend: python_back_end/owui_compat/mcp_wizard.py

export const getSkillSyncPreview = async (token: string) => {
	let error = null;

	// Response: { flag, enabled, config_set, skills: { target_dir, items }, mcp, notes }
	// notes includes the skipped-unverified summary when skills lack a 'supported' verdict
	const res = await fetch(`${WEBUI_BASE_URL}/api/owui/openclaw/sync/preview`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? err.message ?? 'Request failed';
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const saveRunAsSkill = async (token: string, runId: string) => {
	// Phase F: distill a completed, user-owned run into a DRAFT skill (disabled +
	// unaudited). Response: { skill_id, name, enabled:false, note }.
	let error = null;
	const res = await fetch(`${WEBUI_BASE_URL}/api/harvis/runs/${runId}/save-as-skill`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? err.message ?? 'Request failed';
			return null;
		});
	if (error) throw error;
	return res;
};

export const applySkillSync = async (token: string, override: boolean = false) => {
	let error = null;

	// Response: { applied: { skills: [...], mcp }, config_set, note } — 403 when the
	// server-side sync flag is off. override=true includes skills without a
	// 'supported' verdict (explicit human choice).
	const res = await fetch(
		`${WEBUI_BASE_URL}/api/owui/openclaw/sync/apply${override ? '?override=true' : ''}`,
		{
			method: 'POST',
			headers: {
				Accept: 'application/json',
				'Content-Type': 'application/json',
				authorization: `Bearer ${token}`
			}
		}
	)
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail ?? err.message ?? 'Request failed';
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteSkillById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/skills/id/${id}/delete`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail ?? err.message ?? 'Request failed';
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
