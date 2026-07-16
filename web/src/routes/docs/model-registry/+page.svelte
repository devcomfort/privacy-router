<script lang="ts">
	import { t } from '$lib/i18n';
	import { DocPage } from '$lib/components/ui';
	import content from '$lib/docs/model-registry.md?raw';
</script>

<DocPage title={$t('docs.model_registry')} {content} />
