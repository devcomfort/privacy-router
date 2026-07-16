<script lang="ts">
	import { t } from '$lib/i18n';
	import { DocPage } from '$lib/components/ui';
	import content from '$lib/docs/api-keys.md?raw';
</script>

<DocPage title={$t('docs.api_keys')} {content} />
