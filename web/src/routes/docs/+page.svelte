<script lang="ts">
	import { t } from '$lib/i18n';
	import { Card, Badge } from '$lib/components/ui';

	const sections = [
		{ key: 'getting_started', href: '/docs/getting-started', icon: '🚀' },
		{ key: 'detection', href: '/docs/detection', icon: '🔍' },
		{ key: 'masking', href: '/docs/masking', icon: '🔒' },
		{ key: 'query_aggregation', href: '/docs/query-aggregation', icon: '∑' },
		{ key: 'api_keys', href: '/docs/api-keys', icon: '🔑' },
		{ key: 'mcp_integration', href: '/docs/mcp-integration', icon: '🔌' },
		{ key: 'model_registry', href: '/docs/model-registry', icon: '🤖' },
		{ key: 'architecture', href: '/docs/architecture', icon: '🏗️' },
		{ key: 'security', href: '/docs/security', icon: '🛡️' },
		{ key: 'cost', href: '/docs/cost', icon: '💰' },
		{ key: 'experiments', href: '/docs/experiments', icon: '📊' },
	];
</script>

<svelte:head>
	<title>{$t('docs.title')} — Privacy Router</title>
</svelte:head>

<div class="space-y-10">
	<div>
		<h1 class="text-3xl font-bold text-white mb-2">{$t('docs.title')}</h1>
		<p class="text-slate-400">{$t('docs.overview.desc')}</p>
	</div>

	<div class="grid gap-4 sm:grid-cols-2">
		{#each sections as s}
			<a
				href={s.href}
				class="group block rounded-xl border border-slate-800 bg-slate-900/50 p-6 transition hover:border-slate-700 hover:bg-slate-900"
			>
				<div class="text-2xl mb-3">{s.icon}</div>
				<h2 class="font-semibold text-white group-hover:text-blue-400 transition mb-1">
					{$t(`docs.${s.key}`)}
				</h2>
				<p class="text-sm text-slate-400">{$t(`docs.${s.key}.title`)}</p>
			</a>
		{/each}
	</div>

	<div class="grid gap-4 sm:grid-cols-2">
		<Card>
			<div class="p-6">
				<div class="flex items-center gap-2 mb-3">
					<h3 class="font-semibold text-white">{$t('docs.overview.problem')}</h3>
					<Badge variant="danger">{$t('demo.meta.sensitive')}</Badge>
				</div>
				<p class="text-sm text-slate-400 leading-relaxed">{$t('docs.overview.problem.text')}</p>
			</div>
		</Card>
		<Card>
			<div class="p-6">
				<div class="flex items-center gap-2 mb-3">
					<h3 class="font-semibold text-white">{$t('docs.overview.solution')}</h3>
					<Badge variant="success">{$t('demo.meta.safe')}</Badge>
				</div>
				<p class="text-sm text-slate-400 leading-relaxed">{$t('docs.overview.solution.text')}</p>
			</div>
		</Card>
	</div>
</div>
