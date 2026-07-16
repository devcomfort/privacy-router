<script lang="ts">
	import type { Snippet } from 'svelte';
	import { t } from '$lib/i18n';

	interface Props {
		open: boolean;
		onclose: () => void;
		title?: string;
		children: Snippet;
		footer?: Snippet;
	}

	let { open = $bindable(false), onclose, title, children, footer }: Props = $props();
	const titleId = $props.id();

	function onkeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') onclose();
	}
</script>

<svelte:window {onkeydown} />

{#if open}
	<div class="fixed inset-0 z-50 flex items-center justify-center">
		<button
			type="button"
			class="absolute inset-0 bg-black/60 backdrop-blur-sm"
			aria-label={$t('common.close')}
			onclick={onclose}
		></button>
		<div
			class="relative w-full max-w-md rounded-xl border border-slate-700 bg-slate-900 p-6 shadow-2xl"
			role="dialog"
			aria-modal="true"
			aria-labelledby={title ? titleId : undefined}
			aria-label={title ? undefined : $t('common.dialog')}
			tabindex="-1"
		>
			{#if title}
				<h3 id={titleId} class="mb-4 text-lg font-semibold text-white">{title}</h3>
			{/if}
			{@render children()}
			{#if footer}
				<div class="mt-6 flex justify-end gap-3">
					{@render footer()}
				</div>
			{/if}
		</div>
		</div>
{/if}
