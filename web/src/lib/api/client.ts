import type {
	KeyOut,
	KeyCreated,
	KeyUpdate,
	BulkKeyToggle,
	BulkActionResult,
	RouterSettings,
	ChatCompletionRequest,
	ChatCompletionResponse,
	ClassifyRequest,
	ClassifyResponse
} from '$lib/types';

const BASE = '';

let adminKey = '';

class ApiError extends Error {
	constructor(
		public status: number,
		message: string
	) {
		super(message);
		this.name = 'ApiError';
	}
}

async function request<T>(path: string, init?: RequestInit, admin = false): Promise<T> {
	const headers = new Headers(init?.headers);
	if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
	if (admin && adminKey) headers.set('X-Privacy-Router-Admin-Key', adminKey);

	const res = await fetch(`${BASE}${path}`, { ...init, headers });
	if (!res.ok) {
		const body = await res.text();
		let message = body || res.statusText;
		try {
			const parsed = JSON.parse(body) as { detail?: unknown };
			if (typeof parsed.detail === 'string') message = parsed.detail;
		} catch {
			// Keep the response text when the server did not return JSON.
		}
		throw new ApiError(res.status, message);
	}
	if (res.status === 204) return undefined as T;
	return res.json() as Promise<T>;
}

function adminRequest<T>(path: string, init?: RequestInit): Promise<T> {
	return request<T>(path, init, true);
}

export const adminAuth = {
	setKey: (key: string) => {
		adminKey = key;
	},
	clear: () => {
		adminKey = '';
	}
};

// ── Keys ─────────────────────────────────────────────────────────────────

export const keys = {
	list: () => adminRequest<KeyOut[]>('/api/v1/keys'),

	create: (name: string) =>
		adminRequest<KeyCreated>('/api/v1/keys', {
			method: 'POST',
			body: JSON.stringify({ name })
		}),

	update: (id: string, patch: KeyUpdate) =>
		adminRequest<KeyOut>(`/api/v1/keys/${id}`, {
			method: 'PATCH',
			body: JSON.stringify(patch)
		}),

	renew: (id: string) =>
		adminRequest<KeyCreated>(`/api/v1/keys/${id}/renew`, { method: 'POST' }),

	delete: (id: string) =>
		adminRequest<void>(`/api/v1/keys/${id}`, { method: 'DELETE' }),

	bulkToggle: (ids: string[], is_active: boolean) =>
		adminRequest<BulkActionResult>('/api/v1/keys/bulk-toggle', {
			method: 'POST',
			body: JSON.stringify({ ids, is_active } satisfies BulkKeyToggle)
		}),

	bulkDelete: (ids: string[]) =>
		adminRequest<BulkActionResult>('/api/v1/keys/bulk-delete', {
			method: 'POST',
			body: JSON.stringify({ ids })
		})
};

// ── Settings ─────────────────────────────────────────────────────────────

export const settings = {
	get: () => adminRequest<RouterSettings>('/api/settings'),

	save: (s: RouterSettings) =>
		adminRequest<{ status: string }>('/api/settings', {
			method: 'POST',
			body: JSON.stringify(s)
		})
};

// ── Chat / Classify ──────────────────────────────────────────────────────

export const chat = {
	completions: (req: ChatCompletionRequest, apiKey?: string) =>
		request<ChatCompletionResponse>('/v1/chat/completions', {
			method: 'POST',
			headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
			body: JSON.stringify(req)
		}),

	classify: (req: ClassifyRequest, apiKey?: string) =>
		request<ClassifyResponse>('/api/v1/classify', {
			method: 'POST',
			headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
			body: JSON.stringify(req)
		})
};
