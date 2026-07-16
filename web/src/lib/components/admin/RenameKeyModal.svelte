<script lang="ts">
	import { keys as keysApi } from '$lib/api';
	import { Modal, Input, Button } from '$lib/components/ui';
	import { t } from '$lib/i18n';
	import { get } from 'svelte/store';

	interface Props {
		open: boolean;
		onclose: () => void;
		keyId: string;
		currentName: string;
		onsaved: () => void;
	}

	let { open = $bindable(false), onclose, keyId, currentName, onsaved }: Props = $props();

	let name = $state('');
	let loading = $state(false);
	let error = $state('');

	$effect(() => {
		if (open) name = currentName;
	});

	async function handleSave() {
		loading = true;
		error = '';
		try {
			await keysApi.update(keyId, { name });
			onsaved();
			onclose();
		} catch (e) {
			error = e instanceof Error ? e.message : String(e);
		} finally {
			loading = false;
		}
	}

	function onkeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') handleSave();
	}
</script>

<svelte:window {onkeydown} />

<Modal bind:open {onclose} title={$t("modal.rename.title")}>
	<Input bind:value={name} label={$t("modal.rename.name")} placeholder={$t("modal.rename.name")} />
	{#if error}
		<p class="mt-2 text-sm text-red-400">{error}</p>
	{/if}

	{#snippet footer()}
		<Button variant="secondary" onclick={onclose}>{$t("modal.rename.cancel")}</Button>
		<Button variant="primary" onclick={handleSave} disabled={loading || !name.trim()}>
			{loading ? get(t)('modal.rename.saving') : get(t)('modal.rename.save')}
		</Button>
	{/snippet}
</Modal>
