<script lang="ts">
	import { t } from '$lib/i18n';
	import { Badge, Card } from '$lib/components/ui';

	type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info';

	const flowSteps = [
		{
			label: '1. Extract',
			ko: '스팬 증거 추출',
			artifact: 'ExtractionRecord[]',
			detail: 'Exact spans, dynamic categories, offsets, confidence, is_essential.',
		},
		{
			label: '2. Aggregate',
			ko: '쿼리 수준 요약',
			artifact: 'QueryDecisionSummary',
			detail: 'Counts, essentiality, maskability, extraction-failure state.',
		},
		{
			label: '3. Judge',
			ko: '정책 결정',
			artifact: 'policy_action',
			detail: 'Rule-based action: allow, selective_mask, or block.',
		},
		{
			label: '4. Route',
			ko: '실행 경로 선택',
			artifact: 'RouteResult',
			detail: 'External raw, external masked, local model, or user confirmation.',
		},
	];

	const componentCards = [
		{
			title: 'Route decision component',
			ko: 'route 결정 컴포넌트',
			owner: 'QueryAggregator + Judge + Router',
			input: 'ExtractionResult + extraction status',
			output: 'policy_action + RouteResult',
			rule: 'Aggregate records for decisions, then choose the safest endpoint.',
			color: 'border-blue-500/30 bg-blue-500/5',
		},
		{
			title: 'Mask decision component',
			ko: 'mask 결정 컴포넌트',
			owner: 'Masker + MaskingContract + Hydrator',
			input: 'Original text + ExtractionRecord[]',
			output: 'masked_text + placeholder_map + hydrated response',
			rule: 'Use span evidence for action; never derive mask spans from the query summary.',
			color: 'border-emerald-500/30 bg-emerald-500/5',
		},
	];

	const decisionRows: {
		condition: string;
		ko: string;
		action: string;
		endpoint: string;
		exposure: string;
		variant: BadgeVariant;
	}[] = [
		{
			condition: 'Extraction failed or output invalid',
			ko: '추출 실패 또는 구조화 실패',
			action: 'block',
			endpoint: 'local_api',
			exposure: 'No external raw prompt',
			variant: 'danger',
		},
		{
			condition: 'No validated sensitive records',
			ko: '검증된 민감 스팬 없음',
			action: 'allow',
			endpoint: 'external_api',
			exposure: 'Raw prompt allowed',
			variant: 'success',
		},
		{
			condition: 'All sensitive records are non-essential',
			ko: '모든 민감 스팬이 비필수',
			action: 'selective_mask',
			endpoint: 'external_api',
			exposure: 'Masked prompt only',
			variant: 'info',
		},
		{
			condition: 'At least one sensitive record is essential',
			ko: '필수 민감 스팬 하나 이상',
			action: 'block',
			endpoint: 'local_api',
			exposure: 'No external prompt',
			variant: 'warning',
		},
	];

	const schemas = [
		{
			name: 'ExtractionRecord',
			role: 'Span evidence for masking and audit',
			fields: ['span', 'category', 'start', 'end', 'confidence', 'is_essential'],
			note: 'Span is the exact sensitive entity only. Category is generated dynamically as SCREAMING_SNAKE_CASE.',
		},
		{
			name: 'QueryDecisionSummary',
			role: 'Query-level decision artifact',
			fields: [
				'extraction_failed',
				'is_sensitive',
				'has_essential',
				'is_maskable',
				'record_count',
				'category_counts',
				'mask_indices',
			],
			note: 'This artifact controls routing only. It is never the source of truth for hydration.',
		},
		{
			name: 'MaskingContract',
			role: 'Hydration source of truth',
			fields: ['placeholder_map', 'count'],
			note: 'Runtime placeholders use bare deterministic CATEGORY#hash8 format, for example PERSONAL_IDENTIFIER#7f3a9c2d.',
		},
	];

	const examples = [
		{
			name: 'Safe request',
			input: 'Draft a general project status update.',
			summary: 'record_count=0, is_sensitive=false',
			action: 'allow',
			output: 'External model receives the original request.',
		},
		{
			name: 'Maskable request',
			input: 'Write a message using <personal-id> and <phone-number>.',
			summary: 'record_count=2, has_essential=false, mask_indices=[0,1]',
			action: 'selective_mask',
			output: 'External model receives PERSONAL_IDENTIFIER#7f3a9c2d and MOBILE_PHONE_NUMBER#5f69b7a8 placeholders.',
		},
		{
			name: 'Essential sensitive request',
			input: 'Explain whether <unpublished-research-concept> is novel.',
			summary: 'record_count=1, has_essential=true',
			action: 'block',
			output: 'External model receives nothing; route stays local or asks the user.',
		},
	];

	const downloads = [
		{
			name: 'Sanitized ground-truth dataset',
			ko: '비식별 Ground Truth 데이터셋',
			href: '/docs/ground_truth.json',
			type: 'JSON',
			detail: 'Public copy with sensitive values replaced by placeholders. Use this for demos and page downloads.',
		},
		{
			name: 'Sanitized development report',
			ko: '비식별 개발 리포트',
			href: '/docs/developments/REPORT.md',
			type: 'Markdown',
			detail: 'Dataset research notes and experiment framing with identifier-like examples redacted.',
		},
		{
			name: 'Sanitized audit report',
			ko: '비식별 감사 리포트',
			href: '/docs/AUDIT_REPORT.md',
			type: 'Markdown',
			detail: 'Public audit summary with API-key-like examples redacted.',
		},
	];
</script>

<svelte:head>
	<title>{$t('docs.query_aggregation')} — {$t('site.title')} {$t('nav.docs')}</title>
</svelte:head>

<div class="space-y-10">
	<section class="space-y-4">
		<div class="flex flex-wrap items-center gap-2">
			<Badge variant="info">Spec visualization</Badge>
			<Badge variant="default">HTML page</Badge>
			<Badge variant="success">Sanitized downloads</Badge>
		</div>
		<div>
			<h1 class="text-3xl font-bold text-white">Query aggregation and masking workflow</h1>
			<p class="mt-3 max-w-3xl text-slate-400">
				Privacy Router has two distinct decisions. The route decision decides where a prompt may go.
				The mask decision decides which original spans become deterministic placeholders before any
				external model call. 한국어 요약: route는 전송 경로를 고르고, mask는 어떤 스팬을
				가릴지 결정한다.
			</p>
		</div>
	</section>

	<section class="grid gap-4 lg:grid-cols-2">
		{#each componentCards as component}
			<Card class={`p-6 ${component.color}`}>
				<div class="space-y-4">
					<div>
						<p class="text-xs uppercase tracking-[0.2em] text-slate-500">Component</p>
						<h2 class="mt-1 text-xl font-semibold text-white">{component.title}</h2>
						<p class="text-sm text-slate-400">{component.ko}</p>
					</div>
					<div class="rounded-lg border border-slate-800 bg-slate-950/60 p-4 text-sm">
						<div class="grid gap-3">
							<div>
								<span class="text-slate-500">Owner</span>
								<p class="font-mono text-slate-200">{component.owner}</p>
							</div>
							<div>
								<span class="text-slate-500">Input</span>
								<p class="font-mono text-slate-200">{component.input}</p>
							</div>
							<div>
								<span class="text-slate-500">Output</span>
								<p class="font-mono text-slate-200">{component.output}</p>
							</div>
						</div>
					</div>
					<p class="text-sm leading-relaxed text-slate-300">{component.rule}</p>
				</div>
			</Card>
		{/each}
	</section>

	<section>
		<h2 class="mb-4 text-2xl font-semibold text-white">End-to-end flow</h2>
		<div class="grid gap-3 md:grid-cols-4">
			{#each flowSteps as step, index}
				<div class="relative rounded-xl border border-slate-800 bg-slate-900/60 p-4">
					{#if index < flowSteps.length - 1}
						<div class="absolute right-[-0.9rem] top-1/2 z-10 hidden h-px w-7 bg-slate-700 md:block"></div>
					{/if}
					<p class="text-xs uppercase tracking-[0.18em] text-blue-300">{step.label}</p>
					<h3 class="mt-2 font-semibold text-white">{step.ko}</h3>
					<p class="mt-2 font-mono text-sm text-emerald-300">{step.artifact}</p>
					<p class="mt-3 text-sm text-slate-400">{step.detail}</p>
				</div>
			{/each}
		</div>
	</section>

	<section class="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
		<Card class="overflow-hidden">
			<div class="border-b border-slate-800 p-5">
				<h2 class="text-xl font-semibold text-white">Decision matrix</h2>
				<p class="mt-1 text-sm text-slate-400">
					The canonical labels are the only labels new docs and code should emit.
				</p>
			</div>
			<div class="overflow-x-auto">
				<table class="w-full text-left text-sm">
					<thead class="bg-slate-950/70 text-xs uppercase tracking-wide text-slate-500">
						<tr>
							<th class="px-4 py-3">Condition</th>
							<th class="px-4 py-3">Action</th>
							<th class="px-4 py-3">Endpoint</th>
							<th class="px-4 py-3">External exposure</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-slate-800">
						{#each decisionRows as row}
							<tr class="align-top">
								<td class="px-4 py-3">
									<p class="text-slate-200">{row.condition}</p>
									<p class="mt-1 text-xs text-slate-500">{row.ko}</p>
								</td>
								<td class="px-4 py-3"><Badge variant={row.variant}>{row.action}</Badge></td>
								<td class="px-4 py-3 font-mono text-slate-300">{row.endpoint}</td>
								<td class="px-4 py-3 text-slate-300">{row.exposure}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</Card>

		<Card class="p-5">
			<h2 class="text-xl font-semibold text-white">Runtime placeholder contract</h2>
			<p class="mt-3 text-sm leading-relaxed text-slate-400">
				The runtime Masker emits bare deterministic placeholders such as
				<code class="rounded bg-slate-800 px-1.5 py-0.5 text-purple-300">CATEGORY#hash8</code>.
				Bracketed placeholders are tolerated only at compatibility boundaries and are not the model
				for this page.
			</p>
			<div class="mt-4 rounded-lg border border-slate-800 bg-slate-950 p-4 font-mono text-xs text-slate-300">
				<p>masked_text: "Use PERSONAL_IDENTIFIER#7f3a9c2d in the draft."</p>
				<p>placeholder_map:</p>
				<p class="pl-4">PERSONAL_IDENTIFIER#7f3a9c2d → &lt;personal-id&gt;</p>
			</div>
		</Card>
	</section>

	<section>
		<h2 class="mb-4 text-2xl font-semibold text-white">Artifacts and schemas</h2>
		<div class="grid gap-4 lg:grid-cols-3">
			{#each schemas as schema}
				<Card class="p-5">
					<h3 class="font-mono text-lg text-white">{schema.name}</h3>
					<p class="mt-2 text-sm text-slate-400">{schema.role}</p>
					<div class="mt-4 flex flex-wrap gap-2">
						{#each schema.fields as field}
							<span class="rounded-md bg-slate-800 px-2 py-1 font-mono text-xs text-slate-300">{field}</span>
						{/each}
					</div>
					<p class="mt-4 text-sm leading-relaxed text-slate-400">{schema.note}</p>
				</Card>
			{/each}
		</div>
	</section>

	<section>
		<h2 class="mb-4 text-2xl font-semibold text-white">Scenario walk-through</h2>
		<div class="space-y-3">
			{#each examples as example}
				<Card class="p-5">
					<div class="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
						<div>
							<h3 class="font-semibold text-white">{example.name}</h3>
							<p class="mt-2 rounded-lg border border-slate-800 bg-slate-950 p-3 font-mono text-sm text-slate-300">{example.input}</p>
						</div>
						<div class="grid gap-2 text-sm">
							<div class="rounded-lg bg-slate-950/70 p-3">
								<span class="text-slate-500">summary</span>
								<p class="font-mono text-slate-200">{example.summary}</p>
							</div>
							<div class="rounded-lg bg-slate-950/70 p-3">
								<span class="text-slate-500">action</span>
								<p class="font-mono text-blue-300">{example.action}</p>
							</div>
							<div class="rounded-lg bg-slate-950/70 p-3">
								<span class="text-slate-500">effect</span>
								<p class="text-slate-300">{example.output}</p>
							</div>
						</div>
					</div>
				</Card>
			{/each}
		</div>
	</section>

	<section class="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
		<Card class="p-5">
			<h2 class="text-xl font-semibold text-white">Dataset research summary</h2>
			<p class="mt-3 text-sm leading-relaxed text-slate-400">
				The evaluation data separates span-level evidence from query-level outcomes. It covers personal
				information, business secrets, research context, explicit confidentiality cues, and safe prompts.
				The public artifacts below are sanitized copies for demo and review. The private source dataset
				remains in the repository and should not be copied into public pages.
			</p>
			<ul class="mt-4 space-y-2 text-sm text-slate-300">
				<li><span class="text-slate-500">Labels:</span> allow, selective_mask, block.</li>
				<li><span class="text-slate-500">Checks:</span> sensitivity, essentiality, maskability, policy action.</li>
				<li><span class="text-slate-500">Privacy rule:</span> examples use placeholders, not raw identifiers.</li>
			</ul>
		</Card>

		<Card class="p-5">
			<h2 class="text-xl font-semibold text-white">Downloads</h2>
			<div class="mt-4 space-y-3">
				{#each downloads as download}
					<a
						class="block rounded-lg border border-slate-800 bg-slate-950/60 p-4 transition hover:border-blue-500/50 hover:bg-slate-900"
						href={download.href}
						download
					>
						<div class="flex flex-wrap items-center justify-between gap-2">
							<div>
								<h3 class="font-semibold text-white">{download.name}</h3>
								<p class="text-xs text-slate-500">{download.ko}</p>
							</div>
							<Badge variant="default">{download.type}</Badge>
						</div>
						<p class="mt-2 text-sm text-slate-400">{download.detail}</p>
					</a>
				{/each}
			</div>
		</Card>
	</section>
</div>
