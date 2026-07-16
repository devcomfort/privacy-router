<script lang="ts">
	import { onMount } from 'svelte';
	import { t } from '$lib/i18n';
	import { LangToggle } from '$lib/components/ui';

	let elapsed = $state(0);

	onMount(() => {
		const start = Date.now();
		const interval = setInterval(() => {
			elapsed = Math.floor((Date.now() - start) / 1000);
		}, 1000);
		return () => clearInterval(interval);
	});

	function fmt(s: number) {
		const h = String(Math.floor(s / 3600)).padStart(2, '0');
		const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
		const sec = String(Math.floor(s % 60)).padStart(2, '0');
		return `${h}:${m}:${sec}`;
	}
</script>

<svelte:head>
	<title>{$t('site.title')}</title>
	<meta name="description" content={$t('site.description')} />
</svelte:head>

<div class="min-h-screen bg-slate-950 text-slate-200 flex items-center justify-center">
	<div class="max-w-2xl mx-auto px-6 py-16 text-center">
		<div class="mb-4 flex justify-end">
			<LangToggle />
		</div>

		<div class="mb-12">
			<h1 class="text-5xl font-bold tracking-tight text-white mb-4">
				{$t('landing.hero.title')}
			</h1>
			<p class="text-lg text-slate-400">
				{$t('landing.hero.subtitle')}
			</p>
		</div>

		<div class="grid gap-4 sm:grid-cols-2">
			<a
				href="/admin"
				class="group rounded-xl border border-slate-800 bg-slate-900/50 p-6 text-left transition hover:border-slate-700 hover:bg-slate-900"
			>
				<div class="text-2xl mb-2">⚙️</div>
				<h2 class="font-semibold text-white group-hover:text-blue-400 transition">
					{$t('landing.card.admin')}
				</h2>
				<p class="text-sm text-slate-400">{$t('landing.card.admin.desc')}</p>
			</a>

			<div class="rounded-xl border border-dashed border-slate-800 p-6 text-left opacity-60">
				<div class="text-2xl mb-2">📊</div>
				<h2 class="font-semibold text-white">
					{$t('landing.card.dashboard')}
					<span class="ml-2 inline-block rounded-full bg-amber-500/20 px-2 py-0.5 text-xs text-amber-400">
						{$t('landing.card.coming_soon')}
					</span>
				</h2>
				<p class="text-sm text-slate-400">{$t('landing.card.dashboard.desc')}</p>
			</div>
			<a
			href="/docs"
				class="group rounded-xl border border-slate-800 bg-slate-900/50 p-6 text-left transition hover:border-slate-700 hover:bg-slate-900"
			>
				<div class="text-2xl mb-2">📚</div>
				<h2 class="font-semibold text-white group-hover:text-blue-400 transition">
					{$t('nav.docs')}
				</h2>
				<p class="text-sm text-slate-400">{$t('landing.card.docs.desc')}</p>
			</a>
			<a
				href="/demo"
				class="group rounded-xl border border-slate-800 bg-slate-900/50 p-6 text-left transition hover:border-slate-700 hover:bg-slate-900 sm:col-span-2"
			>
				<div class="text-2xl mb-2">💬</div>
				<h2 class="font-semibold text-white group-hover:text-blue-400 transition">
					{$t('landing.card.demo')}
				</h2>
				<p class="text-sm text-slate-400">{$t('landing.card.demo.desc')}</p>
			</a>
		</div>

		<footer class="mt-16 flex items-center justify-center gap-4 text-xs text-slate-500">
			<span class="flex items-center gap-1.5">
				<span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
				{$t('landing.footer.version')}
			</span>
			<span>{$t('landing.footer.session_time')}: {fmt(elapsed)}</span>
		</footer>
	</div>
</div>
