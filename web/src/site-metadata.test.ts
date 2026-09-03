import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('built landing page uses the Privacy Router title and routing favicon', async () => {
	const [indexHtml, favicon] = await Promise.all([
		readFile(new URL('../build/index.html', import.meta.url), 'utf8'),
		readFile(new URL('../static/favicon.svg', import.meta.url), 'utf8')
	]);

	const titles = indexHtml.match(/<title>[^<]*<\/title>/g) ?? [];
	assert.deepEqual(titles, [
		'<title>Privacy Router — AI 민감정보 보호</title>'
	]);
	assert.match(favicon, /<title[^>]*>Privacy Router 라우팅 마크<\/title>/);
	assert.doesNotMatch(favicon, /svelte-logo/i);
});
