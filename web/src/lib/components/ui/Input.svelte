<script lang="ts">
	const generatedId = $props.id();
	interface Props {
		id?: string;
		value?: string;
		placeholder?: string;
		type?: string;
		disabled?: boolean;
		label?: string;
		error?: string;
		oninput?: (e: Event) => void;
		onkeydown?: (e: KeyboardEvent) => void;
	}

	let {
		id = generatedId,
		value = $bindable(''),
		placeholder = '',
		type = 'text',
		disabled = false,
		label,
		error,
		oninput,
		onkeydown
	}: Props = $props();
</script>

<div class="space-y-1.5">
	{#if label}
		<label for={id} class="block text-sm font-medium text-slate-300">{label}</label>
	{/if}
	<input
		{id}
		{type}
		{placeholder}
		{disabled}
		bind:value
		{oninput}
		{onkeydown}
		aria-invalid={error ? 'true' : undefined}
		aria-describedby={error ? `${id}-error` : undefined}
		class="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 transition focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50"
		class:border-red-500={error}
	/>
	{#if error}
		<p id={`${id}-error`} class="text-xs text-red-400">{error}</p>
	{/if}
</div>
