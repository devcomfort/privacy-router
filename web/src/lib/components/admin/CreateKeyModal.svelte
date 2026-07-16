<script lang="ts">
	import { keys as keysApi } from '$lib/api';
	import type { KeyCreated } from '$lib/types';
	import { Modal, Input, Button } from '$lib/components/ui';
	import { t } from '$lib/i18n';
	import { get } from 'svelte/store';
	interface Props {
		open: boolean;
		onclose: () => void;
		oncreated: (key: KeyCreated) => void;
	}

	let { open = $bindable(false), onclose, oncreated }: Props = $props();

	let name = $state('');
	let loading = $state(false);
	let error = $state('');

	async function handleCreate() {
		loading = true;
		error = '';
		try {
			const data = await keysApi.create(name || 'default');
			name = '';
			oncreated(data);
			onclose();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}
</script>

<Modal bind:open {onclose} title={$t("modal.create.title")}>
	<div class="space-y-4">
		<Input bind:value={name} label={$t("modal.create.name")} placeholder="default" />
		{#if error}
			<p class="text-sm text-red-400">{error}</p>
		{/if}
	</div>

	{#snippet footer()}
		<Button variant="secondary" onclick={onclose}>{$t("modal.create.cancel")}</Button>
		<Button variant="primary" onclick={handleCreate} disabled={loading}>
			{loading ? get(t)('modal.create.creating') : get(t)('modal.create.submit')}
		</Button>
	{/snippet}
</Modal>
