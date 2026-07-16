<script lang="ts">
	import { t } from '$lib/i18n';
	import { MarkdownRenderer } from '$lib/components/ui';

	let { title, content }: { title: string; content: string } = $props();
</script>

<svelte:head>
	<title>{title} — {$t('site.title')} {$t('nav.docs')}</title>
</svelte:head>

<article class="prose">
	<MarkdownRenderer {content} />
</article>
