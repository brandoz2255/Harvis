// Per-user, per-model profiles for CLOUD chat models (Claude + OpenAI): default reasoning effort,
// thinking budget, and a custom display name. Backed by /api/owui/model-profiles (see
// python_back_end/owui_compat/model_profiles.py). Local (Ollama) models carry no profile.

export type ModelProfile = {
	effort?: string | null; // 'low' | 'medium' | 'high' | 'max' | null
	thinking_budget?: number | null;
	display_name?: string | null;
};

export const getModelProfiles = async (token: string): Promise<Record<string, ModelProfile>> => {
	let error = null;
	const res = await fetch('/api/owui/model-profiles', {
		method: 'GET',
		headers: { Accept: 'application/json', Authorization: `Bearer ${token}` }
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = err;
			return null;
		});
	if (error) throw error;
	return res?.profiles ?? {};
};

export const saveModelProfile = async (
	token: string,
	modelId: string,
	profile: ModelProfile
): Promise<{ model_id: string; profile: ModelProfile | null }> => {
	let error = null;
	const res = await fetch('/api/owui/model-profiles', {
		method: 'PUT',
		headers: {
			'Content-Type': 'application/json',
			Accept: 'application/json',
			Authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ model_id: modelId, ...profile })
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = err;
			return null;
		});
	if (error) throw error;
	return res;
};

// Reset a model to default (clears its profile). Model ids contain a '/' — pass it unencoded so the
// backend's {model_id:path} route matches.
export const deleteModelProfile = async (token: string, modelId: string) => {
	let error = null;
	const res = await fetch(`/api/owui/model-profiles/${modelId}`, {
		method: 'DELETE',
		headers: { Accept: 'application/json', Authorization: `Bearer ${token}` }
	})
		.then(async (r) => {
			if (!r.ok) throw await r.json();
			return r.json();
		})
		.catch((err) => {
			error = err;
			return null;
		});
	if (error) throw error;
	return res;
};
