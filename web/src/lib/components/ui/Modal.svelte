<script lang="ts">
	import type { Snippet } from 'svelte';
	import { onDestroy, tick } from 'svelte';
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
	let dialog = $state<HTMLDivElement | null>(null);
	let previousFocus: HTMLElement | null = null;
	let wasOpen = false;
	const focusableSelector =
		'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';

	$effect(() => {
		if (open && !wasOpen) {
			previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
			void tick().then(() => {
				if (!open || !dialog) return;
				const first = Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector)).find(
					(element) => element.getClientRects().length > 0
				);
				(first ?? dialog).focus();
			});
		} else if (!open && wasOpen) {
			const target = previousFocus;
			previousFocus = null;
			void tick().then(() => {
				if (target?.isConnected) target.focus();
			});
		}
		wasOpen = open;
	});

	onDestroy(() => {
		if (wasOpen && previousFocus?.isConnected) previousFocus.focus();
	});

	function onkeydown(event: KeyboardEvent) {
		if (!open || !dialog) return;
		if (event.key === 'Escape') {
			event.preventDefault();
			onclose();
			return;
		}
		if (event.key !== 'Tab') return;

		const focusable = Array.from(
			dialog.querySelectorAll<HTMLElement>(focusableSelector)
		).filter((element) => element.getClientRects().length > 0);
		if (!focusable.length) {
			event.preventDefault();
			dialog.focus();
			return;
		}
		const first = focusable[0];
		const last = focusable[focusable.length - 1];
		if (event.shiftKey && document.activeElement === first) {
			event.preventDefault();
			last.focus();
		} else if (!event.shiftKey && document.activeElement === last) {
			event.preventDefault();
			first.focus();
		}
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
			bind:this={dialog}
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
