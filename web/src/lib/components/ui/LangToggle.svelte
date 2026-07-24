<script lang="ts">
	import { locale, toggleLocale } from '$lib/i18n';

	let { compact = false }: { compact?: boolean } = $props();
</script>

<button
	onclick={toggleLocale}
	aria-label={$locale === 'en' ? '한국어로 전환' : 'Switch to English'}
	title={$locale === 'en' ? '한국어' : 'English'}
	class={compact
		? 'flex h-9 min-w-9 cursor-pointer items-center justify-center rounded-md border border-slate-700 bg-transparent px-2.5 text-xs font-semibold tracking-wide text-slate-300 transition hover:border-slate-500 hover:text-white'
		: 'cursor-pointer rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-slate-300 transition hover:bg-slate-700 hover:text-white'}
>
	{compact ? ($locale === 'en' ? 'KO' : 'EN') : $locale === 'en' ? '🇰🇷 한국어' : '🇺🇸 English'}
</button>
