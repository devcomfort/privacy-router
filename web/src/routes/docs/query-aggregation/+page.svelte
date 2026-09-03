<script lang="ts">
	import { t } from '$lib/i18n';
	import { Badge, Card } from '$lib/components/ui';

	type BadgeVariant = 'default' | 'success' | 'warning' | 'danger' | 'info';

	const flowSteps = [
		{
			label: '1. Extract',
			ko: '스팬 증거 추출',
			artifact: 'ExtractionRecord[]',
		detail: '정확한 스팬, 동적 카테고리, 오프셋, 신뢰도, is_essential.',
		},
		{
			label: '2. Aggregate',
			ko: '쿼리 수준 요약',
			artifact: 'QueryDecisionSummary',
		detail: '카운트, 필수성, 마스킹 가능 여부, 추출 실패 상태.',
		},
		{
			label: '3. Judge',
			ko: '정책 결정',
			artifact: 'policy_action',
		detail: '규칙 기반 작업: allow, selective_mask, 또는 block.',
		},
		{
			label: '4. Route',
			ko: '실행 경로 선택',
			artifact: 'RouteResult',
		detail: '외부 원문, 외부 마스킹, 로컬 모델, 또는 사용자 확인.',
		},
	];

	const componentCards = [
	{
		title: 'Route 결정 컴포넌트',
		ko: 'route 결정 컴포넌트',
		owner: 'QueryAggregator + Judge + Router',
		input: 'ExtractionResult + extraction status',
		output: 'policy_action + RouteResult',
		rule: '판단을 위해 레코드를 집계한 뒤 가장 안전한 엔드포인트를 선택합니다.',
		color: 'border-blue-500/30 bg-blue-500/5',
	},
	{
		title: 'Mask 결정 컴포넌트',
		ko: 'mask 결정 컴포넌트',
		owner: 'Masker + MaskingContract + Hydrator',
		input: 'Original text + ExtractionRecord[]',
		output: 'masked_text + placeholder_map + hydrated response',
		rule: '작업에는 스팬 증거를 사용하고, 쿼리 요약에서 마스킹 스팬을 절대 도출하지 않습니다.',
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
		condition: '추출 실패 또는 출력 무효',
			ko: '추출 실패 또는 구조화 실패',
			action: 'block',
			endpoint: 'local_api',
		exposure: '외부 원문 프롬프트 없음',
			variant: 'danger',
		},
		{
		condition: '검증된 민감 레코드 없음',
			ko: '검증된 민감 스팬 없음',
			action: 'allow',
			endpoint: 'external_api',
		exposure: '원문 프롬프트 허용',
			variant: 'success',
		},
		{
		condition: '모든 민감 레코드가 비필수',
			ko: '모든 민감 스팬이 비필수',
			action: 'selective_mask',
			endpoint: 'external_api',
		exposure: '마스킹된 프롬프트만 전달',
			variant: 'info',
		},
		{
		condition: '최소 하나의 민감 레코드가 필수',
			ko: '필수 민감 스팬 하나 이상',
			action: 'block',
			endpoint: 'local_api',
		exposure: '외부 프롬프트 없음',
			variant: 'warning',
		},
	];

	const schemas = [
		{
			name: 'ExtractionRecord',
		role: '마스킹과 감사를 위한 스팬 증거',
			fields: ['span', 'category', 'start', 'end', 'confidence', 'is_essential'],
		note: 'Span은 정확히 민감 엔터티만 포함합니다. Category는 SCREAMING_SNAKE_CASE 형식으로 동적 생성됩니다.',
		},
		{
			name: 'QueryDecisionSummary',
		role: '쿼리 단위 결정 아티팩트',
			fields: [
				'extraction_failed',
				'is_sensitive',
				'has_essential',
				'is_maskable',
				'record_count',
				'category_counts',
				'mask_indices',
			],
		note: '이 아티팩트는 라우팅만을 제어합니다. 하이드레이션의 진실 소스로 사용되지 않습니다.',
		},
		{
			name: 'MaskingContract',
		role: '하이드레이션 진실 소스',
			fields: ['placeholder_map', 'count'],
		note: '런타임 플레이스홀더는 bare deterministic CATEGORY#hash8 형식(예: PERSONAL_IDENTIFIER#7f3a9c2d)을 사용합니다.',
		},
	];

	const examples = [
	{
		name: '안전한 요청',
		input: '일반적인 프로젝트 현황 업데이트를 작성해 주세요.',
		summary: 'record_count=0, is_sensitive=false',
		action: 'allow',
		output: '외부 모델이 원문 요청을 받습니다.',
	},
	{
		name: '마스킹 가능한 요청',
		input: '<personal-id>와 <phone-number>를 사용해 메시지를 작성해 주세요.',
		summary: 'record_count=2, has_essential=false, mask_indices=[0,1]',
		action: 'selective_mask',
		output: '외부 모델은 PERSONAL_IDENTIFIER#7f3a9c2d와 MOBILE_PHONE_NUMBER#5f69b7a8 플레이스홀더를 받습니다.',
	},
	{
		name: '필수 민감 요청',
		input: '<unpublished-research-concept>가 새로운지 설명해 주세요.',
		summary: 'record_count=1, has_essential=true',
		action: 'block',
		output: '외부 모델은 아무것도 받지 않고, 라우팅은 로컬로 유지되거나 사용자에게 확인을 요청합니다.',
	},
];

	const downloads = [
		{
		name: '비식별 Ground Truth 데이터셋',
			ko: '비식별 Ground Truth 데이터셋',
			href: '/docs/ground_truth.json',
			type: 'JSON',
		detail: '민감 값이 플레이스홀더로 대체된 공개 사본입니다. 데모와 페이지 다운로드에 사용하세요.',
		},
		{
		name: '비식별 개발 리포트',
			ko: '비식별 개발 리포트',
			href: '/docs/developments/REPORT.md',
			type: 'Markdown',
		detail: '식별자 형태의 예시가 비식별 처리된 데이터셋 조사 노트와 실험 구성을 정리한 문서입니다.',
		},
		{
		name: '비식별 감사 리포트',
			ko: '비식별 감사 리포트',
			href: '/docs/AUDIT_REPORT.md',
			type: 'Markdown',
		detail: 'API 키 형태의 예시가 비식별 처리된 공개 감사 요약입니다.',
		},
	];
</script>

<svelte:head>
	<title>{$t('docs.query_aggregation')} — {$t('site.title')} {$t('nav.docs')}</title>
</svelte:head>

<div class="space-y-10">
	<section class="space-y-4">
		<div class="flex flex-wrap items-center gap-2">
			<Badge variant="info">스펙 시각화</Badge>
			<Badge variant="default">HTML 페이지</Badge>
			<Badge variant="success">비식별 다운로드</Badge>
		</div>
		<div>
			<h1 class="text-3xl font-bold text-white">쿼리 통합과 마스킹 워크플로우</h1>
			<p class="mt-3 max-w-3xl text-slate-400">
			Privacy Router는 두 가지 별개의 결정을 내립니다. route 결정은 프롬프트가 어디로 전달될 수 있는지 정하고,
			mask 결정은 외부 모델 호출 전에 어떤 원문 스팬이 결정적 플레이스홀더로 바뀌는지 정합니다. 한국어 요약:
			route는 전송 경로를 고르고, mask는 어떤 스팬을 가릴지 결정한다.
		</p>
		</div>
	</section>

	<section class="grid gap-4 lg:grid-cols-2">
		{#each componentCards as component}
			<Card class={`p-6 ${component.color}`}>
				<div class="space-y-4">
					<div>
						<p class="text-xs uppercase tracking-[0.2em] text-slate-400">컴포넌트</p>
						<h2 class="mt-1 text-xl font-semibold text-white">{component.title}</h2>
						<p class="text-sm text-slate-400">{component.ko}</p>
					</div>
					<div class="rounded-lg border border-slate-800 bg-slate-950/60 p-4 text-sm">
						<div class="grid gap-3">
							<div>
								<span class="text-slate-400">소유자</span>
								<p class="font-mono text-slate-200">{component.owner}</p>
							</div>
							<div>
								<span class="text-slate-400">입력</span>
								<p class="font-mono text-slate-200">{component.input}</p>
							</div>
							<div>
								<span class="text-slate-400">출력</span>
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
		<h2 class="mb-4 text-2xl font-semibold text-white">엔드투엔드 흐름</h2>
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
				<h2 class="text-xl font-semibold text-white">결정 매트릭스</h2>
				<p class="mt-1 text-sm text-slate-400">
					공식 레이블은 새 문서와 코드가 사용해야 할 유일한 레이블입니다.
				</p>
			</div>
			<div class="overflow-x-auto">
				<table class="w-full text-left text-sm">
					<thead class="bg-slate-950/70 text-xs uppercase tracking-wide text-slate-400">
						<tr>
							<th class="px-4 py-3">조건</th>
							<th class="px-4 py-3">조치</th>
							<th class="px-4 py-3">엔드포인트</th>
							<th class="px-4 py-3">외부 노출</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-slate-800">
						{#each decisionRows as row}
							<tr class="align-top">
								<td class="px-4 py-3">
									<p class="text-slate-200">{row.condition}</p>
									<p class="mt-1 text-xs text-slate-400">{row.ko}</p>
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
			<h2 class="text-xl font-semibold text-white">런타임 플레이스홀더 계약</h2>
			<p class="mt-3 text-sm leading-relaxed text-slate-400">
				런타임 Masker는 <code class="rounded bg-slate-800 px-1.5 py-0.5 text-purple-300">CATEGORY#hash8</code>
				같은 bare deterministic 플레이스홀더를 출력합니다. 대괄호 플레이스홀더는 호환 경계에서만
				허용되며 이 페이지가 따르는 모델이 아닙니다.
			</p>
			<div class="mt-4 rounded-lg border border-slate-800 bg-slate-950 p-4 font-mono text-xs text-slate-300">
				<p>masked_text: "Use PERSONAL_IDENTIFIER#7f3a9c2d in the draft."</p>
				<p>placeholder_map:</p>
				<p class="pl-4">PERSONAL_IDENTIFIER#7f3a9c2d → &lt;personal-id&gt;</p>
			</div>
		</Card>
	</section>

	<section>
		<h2 class="mb-4 text-2xl font-semibold text-white">아티팩트와 스키마</h2>
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
		<h2 class="mb-4 text-2xl font-semibold text-white">시나리오 상세 해설</h2>
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
								<span class="text-slate-400">요약</span>
								<p class="font-mono text-slate-200">{example.summary}</p>
							</div>
							<div class="rounded-lg bg-slate-950/70 p-3">
								<span class="text-slate-400">조치</span>
								<p class="font-mono text-blue-300">{example.action}</p>
							</div>
							<div class="rounded-lg bg-slate-950/70 p-3">
								<span class="text-slate-400">효과</span>
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
			<h2 class="text-xl font-semibold text-white">데이터셋 조사 요약</h2>
			<p class="mt-3 text-sm leading-relaxed text-slate-400">
				평가 데이터는 스팬 단위 증거와 쿼리 단위 결과를 분리합니다. 개인 정보, 기업 비밀, 연구 맥락,
				명시적 기밀 표시, 안전 프롬프트를 모두 포함합니다. 아래 공개 아티팩트는 데모와 검토용
				비식별 사본입니다. 원본 비공개 데이터셋은 저장소에 유지되며 공개 페이지에 복사하면
				안 됩니다.
			</p>
			<ul class="mt-4 space-y-2 text-sm text-slate-300">
				<li><span class="text-slate-400">레이블:</span> allow, selective_mask, block.</li>
				<li><span class="text-slate-400">검사 항목:</span> sensitivity, essentiality, maskability, policy action.</li>
				<li><span class="text-slate-400">개인정보 보호 규칙:</span> 예시에는 원본 식별자가 아닌 플레이스홀더를 사용합니다.</li>
			</ul>
		</Card>

		<Card class="p-5">
			<h2 class="text-xl font-semibold text-white">다운로드</h2>
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
								<p class="text-xs text-slate-400">{download.ko}</p>
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
