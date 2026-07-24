import assert from 'node:assert/strict';
import test from 'node:test';

import { chat } from './client.ts';

const meta = {
	is_sensitive: false,
	extraction_records: [],
	policy_action: 'allow',
	route: 'external_api',
	model_used: 'external-model'
};

test('chat stream exposes privacy metadata before content deltas', async () => {
	const originalFetch = globalThis.fetch;
	const events: string[] = [];
	const requestBodies: Record<string, unknown>[] = [];

	globalThis.fetch = async (_input, init) => {
		requestBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
		const encoder = new TextEncoder();
		const metaEvent = `data: ${JSON.stringify({ choices: [{ delta: {} }], privacy_router: meta })}\n\n`;
		const contentEvent = `data: ${JSON.stringify({ choices: [{ delta: { content: '안녕' } }] })}\n\n`;
		const tail = [
			`data: ${JSON.stringify({ choices: [{ delta: { content: ' world' } }] })}\n\n`,
			'data: [DONE]\n\n'
		].join('');
		const metaBytes = encoder.encode(metaEvent);
		const contentBytes = encoder.encode(contentEvent);
		const koreanByteOffset = encoder.encode(contentEvent.slice(0, contentEvent.indexOf('안녕'))).length;
		return new Response(
			new ReadableStream({
				start(controller) {
					controller.enqueue(metaBytes.slice(0, 7));
					controller.enqueue(metaBytes.slice(7, -1));
					controller.enqueue(metaBytes.slice(-1));
					controller.enqueue(contentBytes.slice(0, koreanByteOffset + 1));
					controller.enqueue(contentBytes.slice(koreanByteOffset + 1));
					controller.enqueue(encoder.encode(tail));
					controller.close();
				}
			}),
			{ status: 200, headers: { 'Content-Type': 'text/event-stream' } }
		);
	};

	try {
		const completionsStream = Reflect.get(chat, 'completionsStream');
		assert.equal(typeof completionsStream, 'function');
		await completionsStream(
			{ model: 'privacy-router', messages: [{ role: 'user', content: 'Hello' }] },
			undefined,
			{
				onMeta: () => events.push('meta'),
				onContent: (content: string) => events.push(content)
			}
		);
	} finally {
		globalThis.fetch = originalFetch;
	}

	assert.equal(requestBodies[0]?.stream, true);
	assert.deepEqual(events, ['meta', '안녕', ' world']);
});
