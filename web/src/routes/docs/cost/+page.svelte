<script lang="ts">
	import { t } from '$lib/i18n';
	import { DocPage } from '$lib/components/ui';
	import content from '$lib/docs/cost.md?raw';
</script>

<DocPage title={$t('docs.cost')} {content} />
