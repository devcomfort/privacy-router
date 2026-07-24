<script lang="ts">
	import { tick } from 'svelte';
	import { Button } from '$lib/components/ui';
	import { t } from '$lib/i18n';

	interface Props {
		onsend: (text: string) => void | Promise<void>;
		disabled?: boolean;
	}

	let { onsend, disabled = false }: Props = $props();

	let text = $state('');
	let submitting = $state(false);
	let textarea = $state<HTMLTextAreaElement | null>(null);
	let unavailable = $derived(disabled || submitting);

	async function handleSubmit() {
		const trimmed = text.trim();
		if (!trimmed || unavailable) return;
		text = '';
		submitting = true;
		try {
			await onsend(trimmed);
		} finally {
			submitting = false;
			await tick();
			textarea?.focus();
		}
	}

	function onsubmit(event: SubmitEvent) {
		event.preventDefault();
		void handleSubmit();
	}

	function onkeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
			event.preventDefault();
			void handleSubmit();
		}
	}
</script>

<form class="flex flex-col gap-3 sm:flex-row" {onsubmit}>
	<label for="demo-message" class="sr-only">{$t('demo.input.label')}</label>
	<textarea
		id="demo-message"
		bind:this={textarea}
		bind:value={text}
		{onkeydown}
		disabled={unavailable}
		placeholder={$t('demo.input.placeholder')}
		rows="2"
		class="min-h-12 flex-1 resize-none rounded-xl border border-slate-700 bg-slate-900 px-4 py-3 text-sm text-slate-200 placeholder-slate-400 transition focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/40 disabled:cursor-not-allowed disabled:opacity-50"
	></textarea>
	<Button type="submit" disabled={unavailable || !text.trim()}>
		{$t('demo.input.send')}
	</Button>
</form>
