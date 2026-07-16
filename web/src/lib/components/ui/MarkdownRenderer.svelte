<script lang="ts">
	import { marked } from 'marked';

	let { content }: { content: string } = $props();

	const html = $derived(marked.parse(content, { breaks: true }) as string);
</script>

{@html html}

<style>
	:global(.prose) {
		color: #cbd5e1;
		line-height: 1.75;
	}
	:global(.prose h1) {
		color: #f1f5f9;
		font-size: 1.875rem;
		font-weight: 700;
		margin-top: 2rem;
		margin-bottom: 1rem;
	}
	:global(.prose h2) {
		color: #f1f5f9;
		font-size: 1.5rem;
		font-weight: 600;
		margin-top: 1.5rem;
		margin-bottom: 0.75rem;
		border-bottom: 1px solid #1e293b;
		padding-bottom: 0.5rem;
	}
	:global(.prose h3) {
		color: #f1f5f9;
		font-size: 1.25rem;
		font-weight: 600;
		margin-top: 1.25rem;
		margin-bottom: 0.5rem;
	}
	:global(.prose p) {
		margin-bottom: 1rem;
	}
	:global(.prose a) {
		color: #60a5fa;
		text-decoration: underline;
	}
	:global(.prose a:hover) {
		color: #93c5fd;
	}
	:global(.prose code) {
		color: #a78bfa;
		background: #1e293b;
		padding: 0.125rem 0.375rem;
		border-radius: 0.25rem;
		font-size: 0.875rem;
	}
	:global(.prose pre) {
		background: #0f172a;
		border: 1px solid #1e293b;
		border-radius: 0.5rem;
		padding: 1rem;
		overflow-x: auto;
		margin-bottom: 1rem;
	}
	:global(.prose pre code) {
		color: #e2e8f0;
		background: transparent;
		padding: 0;
	}
	:global(.prose table) {
		width: 100%;
		border-collapse: collapse;
		margin-bottom: 1rem;
	}
	:global(.prose th) {
		text-align: left;
		padding: 0.5rem 0.75rem;
		border-bottom: 2px solid #334155;
		color: #f1f5f9;
		font-weight: 600;
	}
	:global(.prose td) {
		padding: 0.5rem 0.75rem;
		border-bottom: 1px solid #1e293b;
	}
	:global(.prose tr:hover) {
		background: #1e293b;
	}
	:global(.prose ul) {
		list-style: disc;
		padding-left: 1.5rem;
		margin-bottom: 1rem;
	}
	:global(.prose ol) {
		list-style: decimal;
		padding-left: 1.5rem;
		margin-bottom: 1rem;
	}
	:global(.prose li) {
		margin-bottom: 0.25rem;
	}
	:global(.prose blockquote) {
		border-left: 4px solid #3b82f6;
		padding-left: 1rem;
		margin-left: 0;
		margin-bottom: 1rem;
		color: #94a3b8;
		font-style: italic;
	}
	:global(.prose strong) {
		color: #f1f5f9;
		font-weight: 600;
	}
	:global(.prose hr) {
		border: none;
		border-top: 1px solid #1e293b;
		margin: 2rem 0;
	}
</style>
