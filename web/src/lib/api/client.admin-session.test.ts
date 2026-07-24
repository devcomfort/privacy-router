import assert from 'node:assert/strict';
import test from 'node:test';

import { adminAuth, keys } from './client.ts';

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

test('admin login exchanges password for cookie session and sends CSRF on writes', async () => {
	const originalFetch = globalThis.fetch;
	const requests: CapturedRequest[] = [];
	globalThis.fetch = async (input, init = {}) => {
		const path = String(input);
		requests.push({ path, init });
		if (path === '/api/admin/session' && init.method === 'POST') {
			return jsonResponse({ authenticated: true, expires_in: 1800, csrf_token: 'csrf-token' });
		}
		if (path === '/api/v1/keys' && init.method === 'POST') {
			return jsonResponse({ id: 'key-id', key: 'pr-created', prefix: 'pr-created' });
		}
		if (path === '/api/admin/session' && init.method === 'DELETE') {
			return jsonResponse({ authenticated: false });
		}
		throw new Error(`Unexpected request: ${init.method} ${path}`);
	};

	try {
		await adminAuth.login('administrator-password');
		await keys.create('demo-client');
		await adminAuth.logout();
	} finally {
		globalThis.fetch = originalFetch;
		adminAuth.clear();
	}

	assert.equal(requests.length, 3);
	assert.equal(requests[0].path, '/api/admin/session');
	assert.equal(requests[0].init.credentials, 'same-origin');
	assert.deepEqual(JSON.parse(String(requests[0].init.body)), {
		password: 'administrator-password'
	});
	assert.equal(new Headers(requests[0].init.headers).has('X-Privacy-Router-Admin-Key'), false);
	assert.equal(
		new Headers(requests[1].init.headers).get('X-Privacy-Router-CSRF-Token'),
		'csrf-token'
	);
	assert.equal(
		new Headers(requests[2].init.headers).get('X-Privacy-Router-CSRF-Token'),
		'csrf-token'
	);
});

test('admin session restore supplies CSRF token to subsequent writes', async () => {
	const originalFetch = globalThis.fetch;
	const requests: CapturedRequest[] = [];
	globalThis.fetch = async (input, init = {}) => {
		const path = String(input);
		requests.push({ path, init });
		if (path === '/api/admin/session') {
			return jsonResponse({ authenticated: true, csrf_token: 'restored-csrf' });
		}
		if (path === '/api/v1/keys/key-id' && init.method === 'PATCH') {
			return jsonResponse({ id: 'key-id', name: 'updated', is_active: true });
		}
		throw new Error(`Unexpected request: ${init.method} ${path}`);
	};

	try {
		assert.equal(await adminAuth.restore(), true);
		await keys.update('key-id', { name: 'updated' });
	} finally {
		globalThis.fetch = originalFetch;
		adminAuth.clear();
	}

	assert.equal(requests[0].init.credentials, 'same-origin');
	assert.equal(
		new Headers(requests[1].init.headers).get('X-Privacy-Router-CSRF-Token'),
		'restored-csrf'
	);
});

test('incomplete session restore clears stale CSRF state', async () => {
	const originalFetch = globalThis.fetch;
	const requests: CapturedRequest[] = [];
	globalThis.fetch = async (input, init = {}) => {
		const path = String(input);
		requests.push({ path, init });
		if (path === '/api/admin/session' && init.method === 'POST') {
			return jsonResponse({ authenticated: true, csrf_token: 'stale-csrf' });
		}
		if (path === '/api/admin/session') {
			return jsonResponse({ authenticated: true });
		}
		if (path === '/api/v1/keys' && init.method === 'POST') {
			return jsonResponse({ id: 'key-id', key: 'pr-created', prefix: 'pr-created' });
		}
		throw new Error(`Unexpected request: ${init.method} ${path}`);
	};

	try {
		await adminAuth.login('administrator-password');
		assert.equal(await adminAuth.restore(), false);
		await keys.create('demo-client');
	} finally {
		globalThis.fetch = originalFetch;
		adminAuth.clear();
	}

	assert.equal(
		new Headers(requests[2].init.headers).has('X-Privacy-Router-CSRF-Token'),
		false
	);
});
