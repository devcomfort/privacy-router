<script lang="ts">
	import { t } from '$lib/i18n';
	import { DocPage } from '$lib/components/ui';
	import content from '$lib/docs/getting-started.md?raw';
</script>

<DocPage title={$t('docs.getting_started')} {content} />
