<script lang="ts">
	import type { Snippet } from 'svelte';
	import { page } from '$app/stores';
	import { t } from '$lib/i18n';
	import { LangToggle } from '$lib/components/ui';
	let { children }: { children: Snippet } = $props();

	const nav = [
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

	let sidebarOpen = $state(false);
</script>

<div class="min-h-screen bg-slate-950 text-slate-200">
	<!-- Top bar -->
	<header class="sticky top-0 z-40 border-b border-slate-800 bg-slate-950/95 backdrop-blur">
		<div class="flex items-center justify-between px-4 py-3 lg:px-6">
			<div class="flex items-center gap-3">
				<button
					type="button"
					class="lg:hidden p-2 rounded-lg hover:bg-slate-800 transition"
					onclick={() => sidebarOpen = !sidebarOpen}
					aria-label={$t('docs.navigation')}
					aria-expanded={sidebarOpen}
					aria-controls="docs-navigation"
				>
					<svg aria-hidden="true" class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
						<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
					</svg>
				</button>
				<a href="/" class="text-sm font-semibold text-white hover:text-blue-400 transition">{$t('site.title')}</a>
				<span class="text-xs text-slate-500">/</span>
				<a href="/docs" class="text-sm text-slate-400 hover:text-white transition">{$t('docs.title')}</a>
			</div>
			<div class="flex items-center gap-3">
				<a href="/demo" class="text-xs text-slate-400 hover:text-white transition">{$t('nav.demo')}</a>
				<a href="/admin" class="text-xs text-slate-400 hover:text-white transition">{$t('nav.admin')}</a>
				<LangToggle />
			</div>
		</div>
	</header>

	<div class="flex">
		<!-- Sidebar -->
		<aside id="docs-navigation" class="fixed inset-y-0 left-0 z-30 w-64 border-r border-slate-800 bg-slate-950 pt-14 transition-transform lg:translate-x-0 {sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}">
			<nav class="p-4 space-y-1 overflow-y-auto h-[calc(100vh-3.5rem)]" aria-label={$t('docs.navigation')}>
				{#each nav as item}
					{@const active = $page.url.pathname === item.href}
					<a
						href={item.href}
						class="flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition {active ? 'bg-blue-500/10 text-blue-400' : 'text-slate-400 hover:text-white hover:bg-slate-800/50'}"
						onclick={() => sidebarOpen = false}
					>
						<span class="text-base">{item.icon}</span>
						<span>{$t(`docs.${item.key}`)}</span>
					</a>
				{/each}
			</nav>
		</aside>

		<!-- Backdrop (mobile) -->
		{#if sidebarOpen}
			<button
				type="button"
				aria-label={$t('docs.navigation')}
				class="fixed inset-0 z-20 bg-black/50 lg:hidden"
				onclick={() => sidebarOpen = false}
			></button>
		{/if}

		<!-- Main content -->
		<main class="flex-1 lg:ml-64">
			<div class="max-w-4xl mx-auto px-6 py-10">
				{@render children()}
			</div>
		</main>
	</div>
</div>
