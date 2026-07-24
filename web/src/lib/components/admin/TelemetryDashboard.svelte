<script lang="ts">
	import type { TelemetryExport, TelemetryRequest } from '$lib/types';
	import { Card } from '$lib/components/ui';
	import { locale, t } from '$lib/i18n';

	interface Props {
		data: TelemetryExport | null;
	}

	interface ModelSummary {
		name: string;
		calls: number;
		tokens: number;
		cost: number;
	}

	let { data }: Props = $props();
	let search = $state('');
	let routeFilter = $state('all');
	let modelFilter = $state('all');
	let statusFilter = $state('all');

	let requests = $derived(data?.requests ?? []);
	let terminalRequests = $derived(
		requests.filter((request) => request.status === 'completed' || request.status === 'failed')
	);
	let routeOptions = $derived(
		[...new Set(requests.map((request) => request.route || 'unresolved'))].sort()
	);
	let modelOptions = $derived(
		[...new Set(requests.map((request) => request.model_used).filter((model): model is string => Boolean(model)))].sort()
	);
	let filteredRequests = $derived.by(() => {
		const query = search.trim().toLowerCase();
		return requests.filter((request) => {
			if (routeFilter !== 'all' && (request.route || 'unresolved') !== routeFilter) return false;
			if (modelFilter !== 'all' && request.model_used !== modelFilter) return false;
			if (statusFilter !== 'all' && request.status !== statusFilter) return false;
			if (!query) return true;
			const searchable = [
				request.id,
				request.endpoint,
				request.route,
				request.model_used,
				request.policy_action,
				request.status,
				JSON.stringify(request.input_redacted)
			]
				.filter(Boolean)
				.join(' ')
				.toLowerCase();
			return searchable.includes(query);
		});
	});
	let visibleRequests = $derived(filteredRequests.slice(0, 100));
	let summary = $derived.by(() => {
		const sensitive = requests.filter((request) => request.is_sensitive).length;
		const successful = terminalRequests.filter((request) => request.status === 'completed').length;
		const latencies = terminalRequests.map((request) => request.latency_ms).sort((a, b) => a - b);
		const p95Index = Math.max(0, Math.ceil(latencies.length * 0.95) - 1);
		return {
			total: requests.length,
			sensitiveRate: requests.length ? Math.round((sensitive / requests.length) * 100) : 0,
			successRate: terminalRequests.length
				? Math.round((successful / terminalRequests.length) * 100)
				: 0,
			p95Latency: latencies.length ? latencies[p95Index] : null,
			tokens: requests.reduce((sum, request) => sum + request.usage.total_tokens, 0),
			cost: requests.reduce((sum, request) => sum + request.usage.cost_usd, 0)
		};
	});
	let trends = $derived.by(() => {
		const days = new Map<string, { total: number; sensitive: number }>();
		for (const request of [...requests].reverse()) {
			const parsed = new Date(request.created_at);
			const day = Number.isNaN(parsed.getTime())
				? request.created_at.slice(0, 10)
				: parsed.toISOString().slice(0, 10);
			const bucket = days.get(day) ?? { total: 0, sensitive: 0 };
			bucket.total += 1;
			bucket.sensitive += request.is_sensitive ? 1 : 0;
			days.set(day, bucket);
		}
		return [...days.entries()].slice(-14);
	});
	let maxTrend = $derived(Math.max(1, ...trends.map(([, value]) => value.total)));
	let routes = $derived.by(() => {
		const counts = new Map<string, number>();
		for (const request of requests) {
			const route = request.route || 'unresolved';
			counts.set(route, (counts.get(route) ?? 0) + 1);
		}
		return [...counts.entries()].sort((a, b) => b[1] - a[1]);
	});
	let models = $derived.by(() => {
		const totals = new Map<string, ModelSummary>();
		for (const request of requests) {
			if (request.invocations.length) {
				for (const invocation of request.invocations) {
					const name = invocation.model || $t('admin.overview.unresolved');
					const current = totals.get(name) ?? { name, calls: 0, tokens: 0, cost: 0 };
					current.calls += 1;
					current.tokens += invocation.total_tokens;
					current.cost += invocation.cost_usd;
					totals.set(name, current);
				}
			} else if (request.model_used) {
				const current = totals.get(request.model_used) ?? {
					name: request.model_used,
					calls: 0,
					tokens: 0,
					cost: 0
				};
				current.calls += 1;
				current.tokens += request.usage.total_tokens;
				current.cost += request.usage.cost_usd;
				totals.set(request.model_used, current);
			}
		}
		return [...totals.values()].sort((a, b) => b.calls - a.calls);
	});
	let maxModelCalls = $derived(Math.max(1, ...models.map((model) => model.calls)));
	let latencyBuckets = $derived.by(() => {
		const buckets = [
			{ key: 'under500', label: '< 500 ms', min: 0, max: 500, count: 0 },
			{ key: 'under1s', label: '0.5–1 s', min: 500, max: 1000, count: 0 },
			{ key: 'under3s', label: '1–3 s', min: 1000, max: 3000, count: 0 },
			{ key: 'under10s', label: '3–10 s', min: 3000, max: 10000, count: 0 },
			{ key: 'over10s', label: '≥ 10 s', min: 10000, max: Number.POSITIVE_INFINITY, count: 0 }
		];
		for (const request of terminalRequests) {
			const bucket = buckets.find(
				(candidate) => request.latency_ms >= candidate.min && request.latency_ms < candidate.max
			);
			if (bucket) bucket.count += 1;
		}
		return buckets;
	});
	let maxLatencyCount = $derived(Math.max(1, ...latencyBuckets.map((bucket) => bucket.count)));

	function routeLabel(route: string | null): string {
		if (route === 'local_api') return $t('demo.meta.route.local');
		if (route === 'external_api') return $t('demo.meta.route.external');
		return $t('admin.overview.unresolved');
	}

	function statusLabel(request: TelemetryRequest): string {
		if (request.status === 'completed') return $t('admin.status.completed');
		if (request.status === 'failed') return $t('admin.status.failed');
		if (request.status === 'in_progress') return $t('admin.status.in_progress');
		return request.status || $t('admin.overview.unresolved');
	}

	function statusTone(request: TelemetryRequest): string {
		if (request.status === 'completed') {
			return 'border-emerald-400/20 bg-emerald-400/10 text-emerald-300';
		}
		if (request.status === 'failed') {
			return 'border-red-400/20 bg-red-400/10 text-red-300';
		}
		return 'border-amber-400/20 bg-amber-400/10 text-amber-300';
	}

	function formatDate(value: string): string {
		const parsed = new Date(value);
		if (Number.isNaN(parsed.getTime())) return value;
		return new Intl.DateTimeFormat($locale === 'ko' ? 'ko-KR' : 'en-US', {
			month: 'short',
			day: 'numeric',
			hour: '2-digit',
			minute: '2-digit',
			second: '2-digit'
		}).format(parsed);
	}

	function formatLatency(value: number | null): string {
		if (value === null) return '—';
		return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
	}
</script>

{#if data}
<div class="space-y-6">
	<div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
		{#each [
			{ label: $t('admin.metrics.requests'), value: summary.total.toLocaleString() },
			{ label: $t('admin.metrics.sensitive'), value: `${summary.sensitiveRate}%` },
			{ label: $t('admin.metrics.success'), value: `${summary.successRate}%` },
			{ label: $t('admin.metrics.p95_latency'), value: formatLatency(summary.p95Latency) },
			{ label: $t('admin.metrics.tokens'), value: summary.tokens.toLocaleString() },
			{ label: $t('admin.metrics.cost'), value: `$${summary.cost.toFixed(4)}` }
		] as metric}
			<Card>
				<div class="p-5">
					<p class="text-xs font-medium uppercase tracking-wide text-slate-400">{metric.label}</p>
					<p class="mt-3 text-2xl font-semibold tabular-nums text-white">{metric.value}</p>
				</div>
			</Card>
		{/each}
	</div>

	<div class="grid gap-6 2xl:grid-cols-2">
		<Card class="min-w-0">
			<div class="border-b border-slate-800 px-5 py-4">
				<h3 class="font-semibold text-white">{$t('admin.overview.trends')}</h3>
				<p class="mt-1 text-xs text-slate-400">{$t('admin.overview.trends_description')}</p>
			</div>
			<div class="p-5">
				{#if trends.length}
					<div class="flex h-44 items-end gap-2" aria-hidden="true">
						{#each trends as [day, value]}
							<div class="flex min-w-0 flex-1 flex-col items-center gap-2" title={`${day}: ${value.total}`}>
								<div class="flex h-32 w-full items-end justify-center gap-0.5">
									<div class="w-2/5 rounded-t-sm bg-blue-400" style={`height: ${Math.max(3, (value.total / maxTrend) * 100)}%`}></div>
									<div class="w-2/5 rounded-t-sm bg-violet-400" style={`height: ${value.sensitive ? Math.max(3, (value.sensitive / maxTrend) * 100) : 0}%`}></div>
								</div>
								<span class="max-w-full truncate text-[10px] text-slate-400">{day.slice(5)}</span>
							</div>
						{/each}
					</div>
					<table class="sr-only">
						<caption>{$t('admin.overview.trends')}</caption>
						<thead>
							<tr><th>{$t('admin.table.time')}</th><th>{$t('admin.overview.total_requests')}</th><th>{$t('admin.overview.sensitive_requests')}</th></tr>
						</thead>
						<tbody>
							{#each trends as [day, value]}
								<tr><td>{day}</td><td>{value.total}</td><td>{value.sensitive}</td></tr>
							{/each}
						</tbody>
					</table>
					<div class="mt-4 flex gap-5 text-xs text-slate-400"><span><span class="mr-1.5 inline-block h-2 w-2 rounded-sm bg-blue-400"></span>{$t('admin.overview.total_requests')}</span><span><span class="mr-1.5 inline-block h-2 w-2 rounded-sm bg-violet-400"></span>{$t('admin.overview.sensitive_requests')}</span></div>
				{:else}
					<p class="py-16 text-center text-sm text-slate-400">{$t('admin.overview.no_requests')}</p>
				{/if}
			</div>
		</Card>

		<Card>
			<div class="border-b border-slate-800 px-5 py-4"><h3 class="font-semibold text-white">{$t('admin.overview.routes')}</h3><p class="mt-1 text-xs text-slate-400">{$t('admin.overview.routes_description')}</p></div>
			<div class="space-y-4 p-5">
				{#each routes as [route, count]}
					<div><div class="mb-1.5 flex justify-between text-xs"><span class="text-slate-300">{routeLabel(route)}</span><span class="tabular-nums text-slate-400">{count} · {summary.total ? Math.round((count / summary.total) * 100) : 0}%</span></div><div class="h-2 overflow-hidden rounded-full bg-slate-800"><div class="h-full rounded-full bg-cyan-400" style={`width: ${summary.total ? (count / summary.total) * 100 : 0}%`}></div></div></div>
				{:else}
					<p class="py-16 text-center text-sm text-slate-400">{$t('admin.overview.no_requests')}</p>
				{/each}
			</div>
		</Card>

		<Card>
			<div class="border-b border-slate-800 px-5 py-4"><h3 class="font-semibold text-white">{$t('admin.overview.models')}</h3><p class="mt-1 text-xs text-slate-400">{$t('admin.overview.models_description')}</p></div>
			<div class="max-h-80 space-y-4 overflow-y-auto p-5">
				{#each models as model}
					<div><div class="mb-1.5 flex justify-between gap-4 text-xs"><span class="truncate text-slate-300" title={model.name}>{model.name}</span><span class="shrink-0 tabular-nums text-slate-400">{model.calls} {$t('admin.overview.calls')} · {model.tokens.toLocaleString()} tok · ${model.cost.toFixed(4)}</span></div><div class="h-2 overflow-hidden rounded-full bg-slate-800"><div class="h-full rounded-full bg-blue-400" style={`width: ${(model.calls / maxModelCalls) * 100}%`}></div></div></div>
				{:else}
					<p class="py-16 text-center text-sm text-slate-400">{$t('admin.overview.no_requests')}</p>
				{/each}
			</div>
		</Card>

		<Card>
			<div class="border-b border-slate-800 px-5 py-4"><h3 class="font-semibold text-white">{$t('admin.overview.latency')}</h3><p class="mt-1 text-xs text-slate-400">{$t('admin.overview.latency_description')}</p></div>
			<div class="space-y-4 p-5">
				{#each latencyBuckets as bucket}
					<div class="grid grid-cols-[4.5rem_minmax(0,1fr)_2rem] items-center gap-3 text-xs"><span class="text-slate-400">{bucket.label}</span><div class="h-2 overflow-hidden rounded-full bg-slate-800"><div class="h-full rounded-full bg-amber-400" style={`width: ${(bucket.count / maxLatencyCount) * 100}%`}></div></div><span class="text-right tabular-nums text-slate-300">{bucket.count}</span></div>
				{/each}
			</div>
		</Card>
	</div>

	<Card class="min-w-0">
		<div class="border-b border-slate-800 px-5 py-4">
			<h3 class="font-semibold text-white">{$t('admin.logs.title')}</h3>
			<p class="mt-1 text-xs leading-5 text-slate-400">{$t('admin.logs.description')}</p>
		</div>
		<div class="grid gap-3 border-b border-slate-800 p-5 sm:grid-cols-2 xl:grid-cols-[minmax(16rem,1fr)_12rem_14rem_10rem]">
			<label class="space-y-1.5 text-xs font-medium text-slate-300"><span>{$t('admin.logs.search')}</span><input bind:value={search} type="search" placeholder={$t('admin.logs.search_placeholder')} class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white placeholder:text-slate-500 focus:border-blue-500 focus:outline-none" /></label>
			<label class="space-y-1.5 text-xs font-medium text-slate-300"><span>{$t('admin.table.route')}</span><select bind:value={routeFilter} class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"><option value="all">{$t('admin.logs.all_routes')}</option>{#each routeOptions as route}<option value={route}>{routeLabel(route)}</option>{/each}</select></label>
			<label class="space-y-1.5 text-xs font-medium text-slate-300"><span>{$t('admin.table.model')}</span><select bind:value={modelFilter} class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"><option value="all">{$t('admin.logs.all_models')}</option>{#each modelOptions as model}<option value={model}>{model}</option>{/each}</select></label>
			<label class="space-y-1.5 text-xs font-medium text-slate-300"><span>{$t('admin.table.status')}</span><select bind:value={statusFilter} class="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-white focus:border-blue-500 focus:outline-none"><option value="all">{$t('admin.logs.all_statuses')}</option><option value="completed">{$t('admin.status.completed')}</option><option value="failed">{$t('admin.status.failed')}</option><option value="in_progress">{$t('admin.status.in_progress')}</option></select></label>
		</div>
		<div class="flex items-center justify-between border-b border-slate-800 px-5 py-3 text-xs text-slate-400"><span>{filteredRequests.length.toLocaleString()} {$t('admin.logs.results')}</span><span>{$t('admin.logs.redacted_only')}</span></div>
		<div class="min-w-0 divide-y divide-slate-800/80">
			{#each visibleRequests as request (request.id)}
				<details class="group min-w-0">
					<summary class="grid min-w-0 cursor-pointer list-none gap-2 px-5 py-4 transition hover:bg-slate-900/60 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-500/60 sm:grid-cols-[9rem_minmax(0,1fr)] sm:items-center xl:grid-cols-[9rem_minmax(10rem,1fr)_7rem_minmax(8rem,1fr)_6rem_7rem]">
						<span class="whitespace-nowrap text-xs text-slate-400">{formatDate(request.created_at)}</span><span class="truncate font-mono text-xs text-slate-200" title={request.endpoint}>{request.endpoint}</span><span class="text-xs text-slate-300">{routeLabel(request.route)}</span><span class="truncate text-xs text-slate-400" title={request.model_used ?? ''}>{request.model_used ?? '—'}</span><span class="text-xs tabular-nums text-slate-400">{formatLatency(request.status === 'in_progress' ? null : request.latency_ms)}</span><span class={`w-fit rounded-full border px-2 py-0.5 text-[11px] ${statusTone(request)}`}>{statusLabel(request)}</span>
					</summary>
					<div class="min-w-0 border-t border-slate-800/80 bg-slate-950/45 px-5 py-5">
						<dl class="grid gap-4 text-xs sm:grid-cols-2 xl:grid-cols-5"><div><dt class="text-slate-500">{$t('admin.logs.request_id')}</dt><dd class="mt-1 break-all font-mono text-slate-300">{request.id}</dd></div><div><dt class="text-slate-500">{$t('admin.logs.policy')}</dt><dd class="mt-1 text-slate-300">{request.policy_action ?? '—'}</dd></div><div><dt class="text-slate-500">{$t('admin.logs.sensitivity')}</dt><dd class="mt-1 text-slate-300">{request.is_sensitive ? $t('common.yes') : $t('common.no')} · {request.records_count}</dd></div><div><dt class="text-slate-500">{$t('admin.logs.usage')}</dt><dd class="mt-1 text-slate-300">{request.usage.total_tokens.toLocaleString()} tok · ${request.usage.cost_usd.toFixed(4)}</dd></div><div><dt class="text-slate-500">HTTP</dt><dd class="mt-1 text-slate-300">{request.status_code}</dd></div></dl>
						<div class="mt-5 grid min-w-0 grid-cols-[minmax(0,1fr)] gap-5 xl:grid-cols-[minmax(16rem,0.75fr)_minmax(0,1.25fr)]">
							<div><h4 class="text-xs font-semibold uppercase tracking-wide text-slate-400">{$t('admin.logs.redacted_input')}</h4><pre class="mt-2 max-h-64 overflow-auto rounded-lg border border-slate-800 bg-slate-950 p-3 text-[11px] leading-5 text-slate-300">{JSON.stringify(request.input_redacted, null, 2)}</pre></div>
							<div class="min-w-0"><h4 class="text-xs font-semibold uppercase tracking-wide text-slate-400">{$t('admin.logs.invocations')}</h4><div class="mt-2 overflow-x-auto rounded-lg border border-slate-800"><table class="w-full min-w-[44rem] text-left text-xs"><thead class="border-b border-slate-800 bg-slate-950/80 text-slate-400"><tr><th class="px-3 py-2 font-medium">{$t('admin.logs.component')}</th><th class="px-3 py-2 font-medium">{$t('admin.table.model')}</th><th class="px-3 py-2 font-medium">{$t('admin.providers.title')}</th><th class="px-3 py-2 text-right font-medium">{$t('admin.metrics.tokens')}</th><th class="px-3 py-2 text-right font-medium">{$t('admin.overview.latency')}</th><th class="px-3 py-2 text-right font-medium">{$t('admin.metrics.cost')}</th></tr></thead><tbody class="divide-y divide-slate-800/80">{#each request.invocations as invocation (invocation.id)}<tr><td class="px-3 py-2 text-slate-300">{invocation.component}</td><td class="max-w-56 truncate px-3 py-2 text-slate-300" title={invocation.model}>{invocation.model}</td><td class="px-3 py-2 text-slate-400">{invocation.provider ?? $t('admin.overview.unresolved')}</td><td class="px-3 py-2 text-right tabular-nums text-slate-400">{invocation.total_tokens.toLocaleString()}</td><td class="px-3 py-2 text-right tabular-nums text-slate-400">{formatLatency(invocation.latency_ms)}</td><td class="px-3 py-2 text-right tabular-nums text-slate-400">${invocation.cost_usd.toFixed(4)}</td></tr>{:else}<tr><td colspan="6" class="px-3 py-8 text-center text-slate-500">{$t('admin.logs.no_invocations')}</td></tr>{/each}</tbody></table></div></div>
						</div>
					</div>
				</details>
			{:else}
				<p class="px-5 py-16 text-center text-sm text-slate-400">{$t('admin.logs.no_results')}</p>
			{/each}
		</div>
		{#if filteredRequests.length > visibleRequests.length}
			<p class="border-t border-slate-800 px-5 py-3 text-center text-xs text-slate-400">{$t('admin.logs.first_hundred')}</p>
		{/if}
	</Card>
</div>
{:else}
	<Card>
		<p class="px-5 py-16 text-center text-sm text-slate-400">{$t('admin.overview.unavailable')}</p>
	</Card>
{/if}
