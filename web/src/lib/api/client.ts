import type {
	KeyOut,
	KeyCreated,
	KeyUpdate,
	BulkKeyToggle,
	BulkActionResult,
	RouterSettings,
	SettingsUpdate,
	RuntimeCapabilities,
	ProviderListResponse,
	ModelCreate,
	ModelUpdate,
	ModelOut,
	ModelValidationResult,
	ProfileListResponse,
	ProfileActivationResult,
	TelemetryExport,
	TelemetryRetention,
	TelemetryPurgeResult,
	ChatCompletionRequest,
	ChatCompletionResponse,
	ModelListResponse,
	PrivacyRouterMeta,
	ClassifyRequest,
	ClassifyResponse
} from '$lib/types';

const BASE = '';
let adminCsrfToken = '';

export class ApiError extends Error {
	public status: number;

	constructor(status: number, message: string) {
		super(message);
		this.name = 'ApiError';
		this.status = status;
	}
}

export interface ChatCompletionStreamHandlers {
	onMeta: (meta: PrivacyRouterMeta) => void;
	onContent: (content: string) => void;
}

interface ChatCompletionStreamChunk {
	choices?: { delta?: { content?: unknown } }[];
	privacy_router?: PrivacyRouterMeta;
	error?: { message?: string } | string;
}

interface AdminSessionResponse {
	authenticated: boolean;
	expires_in?: number;
	csrf_token?: string;
}

async function fetchResponse(path: string, init?: RequestInit, admin = false): Promise<Response> {
	const headers = new Headers(init?.headers);
	if (init?.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
	const method = (init?.method ?? 'GET').toUpperCase();
	if (admin && adminCsrfToken && !['GET', 'HEAD', 'OPTIONS'].includes(method)) {
		headers.set('X-Privacy-Router-CSRF-Token', adminCsrfToken);
	}

	const response = await fetch(`${BASE}${path}`, {
		...init,
		headers,
		credentials: init?.credentials ?? 'same-origin'
	});
	if (!response.ok) {
		const body = await response.text();
		let message = body || response.statusText;
		try {
			const parsed = JSON.parse(body) as { detail?: unknown };
			if (typeof parsed.detail === 'string') message = parsed.detail;
		} catch {
			// Keep non-JSON server details intact.
		}
		throw new ApiError(response.status, message);
	}
	return response;
}

async function request<T>(path: string, init?: RequestInit, admin = false): Promise<T> {
	const response = await fetchResponse(path, init, admin);
	if (response.status === 204) return undefined as T;
	return response.json() as Promise<T>;
}

async function streamChatCompletion(
	req: ChatCompletionRequest,
	apiKey: string | undefined,
	handlers: ChatCompletionStreamHandlers
): Promise<void> {
	const response = await fetchResponse('/v1/chat/completions', {
		method: 'POST',
		headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
		body: JSON.stringify({ ...req, stream: true })
	});
	const reader = response.body?.getReader();
	if (!reader) throw new ApiError(502, 'Streaming response body is unavailable');

	const decoder = new TextDecoder();
	let buffer = '';
	let receivedDone = false;

	const consumeEvent = (event: string) => {
		const payload = event
			.split(/\r?\n/)
			.filter((line) => line.startsWith('data:'))
			.map((line) => line.slice(5).trimStart())
			.join('\n');
		if (!payload) return;
		if (payload === '[DONE]') {
			receivedDone = true;
			return;
		}

		let chunk: ChatCompletionStreamChunk;
		try {
			chunk = JSON.parse(payload) as ChatCompletionStreamChunk;
		} catch {
			throw new ApiError(502, 'Invalid streaming response');
		}
		if (chunk.error) {
			const message = typeof chunk.error === 'string'
				? chunk.error
				: (chunk.error.message ?? 'Streaming request failed');
			throw new ApiError(502, message);
		}
		if (chunk.privacy_router) handlers.onMeta(chunk.privacy_router);
		const content = chunk.choices?.[0]?.delta?.content;
		if (typeof content === 'string' && content) handlers.onContent(content);
	};

	const drainEvents = () => {
		let boundary = /\r?\n\r?\n/.exec(buffer);
		while (boundary) {
			const event = buffer.slice(0, boundary.index);
			buffer = buffer.slice(boundary.index + boundary[0].length);
			consumeEvent(event);
			boundary = /\r?\n\r?\n/.exec(buffer);
		}
	};

	while (!receivedDone) {
		const { value, done } = await reader.read();
		if (done) break;
		buffer += decoder.decode(value, { stream: true });
		drainEvents();
	}
	buffer += decoder.decode();
	drainEvents();
	if (buffer.trim()) consumeEvent(buffer);
	if (!receivedDone) throw new ApiError(502, 'Streaming response ended before completion');
}

function adminRequest<T>(path: string, init?: RequestInit): Promise<T> {
	return request<T>(path, init, true);
}

export const runtime = {
	get: () => request<RuntimeCapabilities>('/api/runtime')
};

export const demoAuth = {
	create: () =>
		request<{ expires_in: number }>('/api/demo/session', {
			method: 'POST'
		})
};


export const adminAuth = {
	login: async (password: string): Promise<void> => {
		adminCsrfToken = '';
		const session = await request<AdminSessionResponse>('/api/admin/session', {
			method: 'POST',
			body: JSON.stringify({ password })
		});
		if (!session.authenticated || !session.csrf_token) {
			throw new ApiError(502, 'Invalid administrator session response');
		}
		adminCsrfToken = session.csrf_token;
	},
	restore: async (): Promise<boolean> => {
		adminCsrfToken = '';
		try {
			const session = await request<AdminSessionResponse>('/api/admin/session');
			if (!session.authenticated || !session.csrf_token) return false;
			adminCsrfToken = session.csrf_token;
			return true;
		} catch (error) {
			if (error instanceof ApiError && error.status === 401) {
				adminCsrfToken = '';
				return false;
			}
			throw error;
		}
	},
	logout: async (): Promise<void> => {
		await adminRequest<AdminSessionResponse>('/api/admin/session', { method: 'DELETE' });
		adminCsrfToken = '';
	},
	clear: () => {
		adminCsrfToken = '';
	}
};

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
	renew: (id: string) => adminRequest<KeyCreated>(`/api/v1/keys/${id}/renew`, { method: 'POST' }),
	delete: (id: string) => adminRequest<void>(`/api/v1/keys/${id}`, { method: 'DELETE' }),
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

export const settings = {
	get: () => adminRequest<RouterSettings>('/api/settings'),
	save: (update: SettingsUpdate) =>
		adminRequest<{ status: string }>('/api/settings', {
			method: 'POST',
			body: JSON.stringify(update)
		})
};

export const providers = {
	list: () => adminRequest<ProviderListResponse>('/api/providers')
};

export const profiles = {
	list: () => adminRequest<ProfileListResponse>('/api/profiles'),
	activate: (profile: string) =>
		adminRequest<ProfileActivationResult>('/api/profiles/activate', {
			method: 'POST',
			body: JSON.stringify({ profile })
		})
};

export const models = {
	list: () => request<ModelListResponse>('/v1/models'),
	adminList: (includeInactive = true) =>
		adminRequest<ModelOut[]>(`/api/v1/models?include_inactive=${includeInactive}`),
	validate: (model: ModelCreate) =>
		adminRequest<ModelValidationResult>('/api/v1/models/validate', {
			method: 'POST',
			body: JSON.stringify(model)
		}),
	create: (model: ModelCreate) =>
		adminRequest<ModelOut>('/api/v1/models', {
			method: 'POST',
			body: JSON.stringify(model)
		}),
	update: (recordId: string, patch: ModelUpdate) =>
		adminRequest<ModelOut>(`/api/v1/models/${encodeURIComponent(recordId)}`, {
			method: 'PATCH',
			body: JSON.stringify(patch)
		}),
	activate: (recordId: string) =>
		adminRequest<ModelOut>(`/api/v1/models/${encodeURIComponent(recordId)}/activate`, { method: 'POST' }),
	delete: (recordId: string) =>
		adminRequest<void>(`/api/v1/models/${encodeURIComponent(recordId)}`, { method: 'DELETE' })
};

export const telemetry = {
	retention: () => adminRequest<TelemetryRetention>('/api/v1/telemetry/retention'),
	dashboard: () => adminRequest<TelemetryExport>('/api/v1/dashboard-data'),
	export: () => adminRequest<TelemetryExport>('/api/v1/telemetry/export?format=json'),
	download: async (format: 'json' | 'csv') => {
		const response = await fetchResponse(`/api/v1/telemetry/export?format=${format}`, undefined, true);
		const disposition = response.headers.get('content-disposition') ?? '';
		const match = disposition.match(/filename="?([^";]+)"?/i);
		return {
			blob: await response.blob(),
			filename: match?.[1] ?? `privacy-router-telemetry.${format}`
		};
	},
	purge: (body: { scope: 'expired' | 'before' | 'all'; before?: string; confirm?: boolean }) =>
		adminRequest<TelemetryPurgeResult>('/api/v1/telemetry/purge', {
			method: 'POST',
			body: JSON.stringify(body)
		})
};

export const chat = {
	completions: (req: ChatCompletionRequest, apiKey?: string) =>
		request<ChatCompletionResponse>('/v1/chat/completions', {
			method: 'POST',
			headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
			body: JSON.stringify(req)
		}),
	completionsStream: (
		req: ChatCompletionRequest,
		apiKey: string | undefined,
		handlers: ChatCompletionStreamHandlers
	) => streamChatCompletion(req, apiKey, handlers),
	classify: (req: ClassifyRequest, apiKey?: string) =>
		request<ClassifyResponse>('/api/v1/classify', {
			method: 'POST',
			headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : {},
			body: JSON.stringify(req)
		})
};
