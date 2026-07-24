import assert from 'node:assert/strict';
import test from 'node:test';

import { demoAuth, runtime } from './client.ts';

interface CapturedRequest {
	path: string;
	init: RequestInit;
}

function jsonResponse(body: unknown): Response {
	return new Response(JSON.stringify(body), {
		status: 200,
		headers: { 'Content-Type': 'application/json' }
	});
}

test('dev demo discovers capabilities and creates a cookie session without a bearer key', async () => {
	const originalFetch = globalThis.fetch;
	const requests: CapturedRequest[] = [];
	globalThis.fetch = async (input, init = {}) => {
		const path = String(input);
		requests.push({ path, init });
		if (path === '/api/runtime') {
			return jsonResponse({
				mode: 'dev',
				default_model: 'privacy-router',
				demo: { authentication: 'session', session_available: true }
			});
		}
		if (path === '/api/demo/session') {
			return jsonResponse({ expires_in: 900 });
		}
		throw new Error(`Unexpected request: ${init.method ?? 'GET'} ${path}`);
	};

	try {
		const capabilities = await runtime.get();
		assert.equal(capabilities.demo.session_available, true);
		await demoAuth.create();
	} finally {
		globalThis.fetch = originalFetch;
	}

	assert.deepEqual(
		requests.map(({ path, init }) => ({
			path,
			method: init.method ?? 'GET',
			credentials: init.credentials
		})),
		[
			{ path: '/api/runtime', method: 'GET', credentials: 'same-origin' },
			{ path: '/api/demo/session', method: 'POST', credentials: 'same-origin' }
		]
	);
});
