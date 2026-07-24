<script lang="ts">
	import { t } from '$lib/i18n';
	import { LangToggle } from '$lib/components/ui';
</script>

<svelte:head>
	<title>{$t('site.meta_title')}</title>
	<meta name="description" content={$t('site.description')} />
</svelte:head>

<div class="landing">
	<header class="site-header">
		<a class="brand" href="/" aria-label="Privacy Router">
			<svg viewBox="0 0 24 24" aria-hidden="true">
				<path d="M12 3 4.5 6v5.25c0 4.4 2.9 8.1 7.5 9.75 4.6-1.65 7.5-5.35 7.5-9.75V6L12 3Z" />
				<path d="M8.25 9.25h3.5m0 0v5.5m0-5.5 3.75-1.5m-3.75 7 3.75 1.5" />
			</svg>
			<span>Privacy Router</span>
		</a>

		<nav class="primary-nav" aria-label={$t('landing.nav.primary')}>
			<a href="/demo">{$t('nav.demo')}</a>
			<a href="/docs">{$t('nav.docs')}</a>
		</nav>

		<div class="header-actions">
			<a class="admin-link" href="/admin">{$t('nav.admin')}</a>
			<LangToggle compact />
		</div>
	</header>

	<main>
		<section class="hero">
			<div class="hero-copy">
				<h1>{$t('landing.hero.title')}</h1>
				<p class="hero-description">{$t('landing.hero.subtitle')}</p>

				<div class="hero-actions">
					<a class="primary-action" href="/demo">
						{$t('landing.hero.primary')}
						<svg viewBox="0 0 20 20" aria-hidden="true">
							<path d="m7 4 6 6-6 6" />
						</svg>
					</a>
					<a class="secondary-action" href="/docs/detection">
						{$t('landing.hero.secondary')}
					</a>
				</div>

				<p class="compatibility">{$t('landing.hero.compatibility')}</p>
			</div>

			<article class="trace-panel" aria-labelledby="trace-title">
				<header class="trace-header">
					<h2 id="trace-title">{$t('landing.trace.title')}</h2>
					<span class="trace-state">
						<span aria-hidden="true"></span>
						{$t('landing.trace.state')}
					</span>
				</header>

				<div class="request-sample">
					<span class="field-label">{$t('landing.trace.request')}</span>
					<p>“{$t('landing.trace.request_text')}”</p>
				</div>

				<dl class="decision-list">
					<div>
						<dt>{$t('landing.trace.detected')}</dt>
						<dd class="signal-value">{$t('landing.trace.detected_value')}</dd>
					</div>
					<div>
						<dt>{$t('landing.trace.policy')}</dt>
						<dd>{$t('landing.trace.policy_value')}</dd>
					</div>
					<div>
						<dt>{$t('landing.trace.route')}</dt>
						<dd>{$t('landing.trace.route_value')}</dd>
					</div>
				</dl>

				<div class="route-strip" aria-hidden="true">
					<span>{$t('landing.trace.path.request')}</span>
					<i></i>
					<span>{$t('landing.trace.path.masked')}</span>
					<i></i>
					<span>{$t('landing.trace.path.external')}</span>
				</div>
			</article>
		</section>

		<section class="boundary" aria-labelledby="boundary-title">
			<div class="boundary-heading">
				<h2 id="boundary-title">{$t('landing.flow.title')}</h2>
				<p>{$t('landing.flow.subtitle')}</p>
			</div>

			<ol class="steps">
				<li>
					<span class="step-number">1</span>
					<div>
						<h3>{$t('landing.flow.detect.title')}</h3>
						<p>{$t('landing.flow.detect.desc')}</p>
					</div>
				</li>
				<li>
					<span class="step-number">2</span>
					<div>
						<h3>{$t('landing.flow.decide.title')}</h3>
						<p>{$t('landing.flow.decide.desc')}</p>
					</div>
				</li>
				<li>
					<span class="step-number">3</span>
					<div>
						<h3>{$t('landing.flow.route.title')}</h3>
						<p>{$t('landing.flow.route.desc')}</p>
					</div>
				</li>
			</ol>
		</section>
	</main>

	<footer class="site-footer">
		<p>{$t('landing.footer.compatibility')}</p>
		<a href="/docs/mcp-integration">
			{$t('landing.footer.guide')}
			<svg viewBox="0 0 20 20" aria-hidden="true">
				<path d="M4 10h12m-4-4 4 4-4 4" />
			</svg>
		</a>
	</footer>
</div>

<style>
	:global(html) {
		background: #050812;
	}

	:global(body) {
		margin: 0;
	}

	.landing {
		--background: #050812;
		--surface: #0b1120;
		--surface-raised: #10182a;
		--border: #27324a;
		--border-strong: #3a4968;
		--text: #f7f9fd;
		--muted: #aab5c8;
		--quiet: #7f8ba3;
		--brand: #83a7ff;
		--brand-strong: #5f8dff;
		--signal: #72e0b5;

		min-height: 100svh;
		overflow: hidden;
		background: var(--background);
		color: var(--text);
		font-family:
			ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
	}

	.site-header,
	main,
	.site-footer {
		width: min(1180px, calc(100% - 48px));
		margin-inline: auto;
	}

	.site-header {
		display: grid;
		grid-template-columns: minmax(max-content, 1fr) auto minmax(max-content, 1fr);
		align-items: center;
		min-height: 76px;
		border-bottom: 1px solid var(--border);
	}

	.brand {
		display: inline-flex;
		align-items: center;
		gap: 10px;
		width: fit-content;
		color: var(--text);
		font-size: 15px;
		font-weight: 700;
		letter-spacing: -0.01em;
		text-decoration: none;
	}

	.brand svg {
		width: 24px;
		height: 24px;
		fill: none;
		stroke: var(--brand);
		stroke-width: 1.5;
		stroke-linecap: round;
		stroke-linejoin: round;
	}

	.primary-nav {
		display: flex;
		align-items: center;
		gap: 30px;
	}

	.primary-nav a,
	.admin-link {
		color: var(--muted);
		font-size: 14px;
		font-weight: 500;
		text-decoration: none;
		transition:
			color 160ms ease,
			background-color 160ms ease;
	}

	.primary-nav a:hover,
	.admin-link:hover {
		color: var(--text);
	}

	.header-actions {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 16px;
	}

	.admin-link {
		padding-right: 16px;
		border-right: 1px solid var(--border);
	}

	.hero {
		display: grid;
		grid-template-columns: minmax(0, 1.15fr) minmax(380px, 0.85fr);
		gap: clamp(48px, 5.5vw, 80px);
		align-items: center;
		padding-block: clamp(80px, 11vw, 142px);
	}

	.hero-copy {
		max-width: 650px;
	}

	h1 {
		max-width: none;
		margin: 0;
		font-size: clamp(3.25rem, 5.55vw, 5rem);
		font-weight: 760;
		letter-spacing: -0.04em;
		line-height: 0.98;
		text-wrap: balance;
	}

	:global(html[lang="ko"]) h1,
	:global(html[lang="ko"]) .boundary-heading h2 {
		word-break: keep-all;
		overflow-wrap: normal;
	}

	.hero-description {
		max-width: 64ch;
		margin: 28px 0 0;
		color: var(--muted);
		font-size: clamp(1rem, 1.5vw, 1.15rem);
		line-height: 1.75;
		text-wrap: pretty;
	}

	.hero-actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 12px;
		margin-top: 34px;
	}

	.primary-action,
	.secondary-action {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-height: 46px;
		padding: 0 18px;
		border-radius: 8px;
		font-size: 14px;
		font-weight: 700;
		text-decoration: none;
		transition:
			background-color 180ms ease,
			border-color 180ms ease,
			color 180ms ease,
			transform 180ms cubic-bezier(0.25, 1, 0.5, 1);
	}

	.primary-action {
		gap: 10px;
		background: var(--brand-strong);
		color: #050812;
	}

	.primary-action:hover {
		background: #80a4ff;
		transform: translateY(-1px);
	}

	.primary-action svg,
	.site-footer svg {
		width: 17px;
		height: 17px;
		fill: none;
		stroke: currentColor;
		stroke-width: 1.8;
		stroke-linecap: round;
		stroke-linejoin: round;
	}

	.secondary-action {
		border: 1px solid var(--border-strong);
		color: var(--text);
	}

	.secondary-action:hover {
		border-color: #617294;
		background: var(--surface);
	}

	.compatibility {
		margin: 18px 0 0;
		color: var(--quiet);
		font-size: 13px;
		line-height: 1.5;
	}

	.trace-panel {
		position: relative;
		padding: 26px;
		border: 1px solid var(--border);
		border-radius: 16px;
		background: var(--surface);
		box-shadow: 0 28px 90px rgb(0 0 0 / 0.32);
	}

	.trace-panel::after {
		position: absolute;
		inset: 9px -10px -10px 9px;
		z-index: -1;
		border: 1px solid #172036;
		border-radius: 16px;
		content: "";
	}

	.trace-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 20px;
	}

	.trace-header h2 {
		margin: 0;
		font-size: 14px;
		font-weight: 700;
	}

	.trace-state {
		display: inline-flex;
		align-items: center;
		gap: 7px;
		color: var(--signal);
		font-size: 12px;
		font-weight: 650;
	}

	.trace-state > span {
		width: 7px;
		height: 7px;
		border-radius: 999px;
		background: var(--signal);
		box-shadow: 0 0 0 4px rgb(114 224 181 / 0.1);
	}

	.request-sample {
		margin-top: 24px;
		padding: 18px;
		border: 1px solid var(--border);
		border-radius: 10px;
		background: #070b14;
	}

	.field-label {
		display: block;
		margin-bottom: 9px;
		color: var(--quiet);
		font-size: 11px;
		font-weight: 650;
	}

	.request-sample p {
		margin: 0;
		color: #dce4f4;
		font-size: 14px;
		line-height: 1.6;
		overflow-wrap: anywhere;
	}

	.decision-list {
		margin: 20px 0 0;
	}

	.decision-list > div {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: 24px;
		padding: 12px 2px;
		border-bottom: 1px solid #1b2438;
	}

	.decision-list dt {
		color: var(--quiet);
		font-size: 12px;
	}

	.decision-list dd {
		margin: 0;
		color: #dce4f4;
		font-size: 12px;
		font-weight: 600;
		text-align: right;
	}

	.decision-list .signal-value {
		color: var(--signal);
	}

	.route-strip {
		display: grid;
		grid-template-columns: auto minmax(20px, 1fr) auto minmax(20px, 1fr) auto;
		align-items: center;
		gap: 10px;
		margin-top: 20px;
		color: var(--muted);
		font-size: 10px;
		font-weight: 700;
	}

	.route-strip i {
		height: 1px;
		background: var(--border-strong);
	}

	.boundary {
		display: grid;
		grid-template-columns: minmax(260px, 0.72fr) minmax(0, 1.28fr);
		gap: clamp(40px, 7vw, 92px);
		padding-block: clamp(48px, 7vw, 84px);
		border-top: 1px solid var(--border);
	}

	.boundary-heading h2 {
		max-width: 14ch;
		margin: 0;
		font-size: clamp(1.75rem, 3vw, 2.5rem);
		letter-spacing: -0.03em;
		line-height: 1.1;
		text-wrap: balance;
	}

	.boundary-heading p {
		max-width: 42ch;
		margin: 18px 0 0;
		color: var(--muted);
		font-size: 14px;
		line-height: 1.7;
	}

	.steps {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 0;
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.steps li {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 14px;
		align-content: start;
		padding: 2px 24px 0;
		border-left: 1px solid var(--border);
	}

	.steps li:first-child {
		padding-left: 0;
		border-left: 0;
	}

	.steps li:last-child {
		padding-right: 0;
	}

	.step-number {
		color: var(--brand);
		font-size: 13px;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
	}

	.steps h3 {
		margin: 0;
		font-size: 15px;
		line-height: 1.3;
	}

	.steps p {
		margin: 10px 0 0;
		color: var(--muted);
		font-size: 13px;
		line-height: 1.65;
		text-wrap: pretty;
	}

	.site-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		min-height: 76px;
		border-top: 1px solid var(--border);
		color: var(--quiet);
		font-size: 12px;
	}

	.site-footer p {
		margin: 0;
	}

	.site-footer a {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		color: var(--muted);
		font-weight: 600;
		text-decoration: none;
	}

	.site-footer a:hover {
		color: var(--text);
	}

	a:focus-visible {
		outline: 2px solid var(--brand);
		outline-offset: 4px;
	}

	@media (max-width: 900px) {
		.site-header {
			grid-template-columns: 1fr auto;
			padding-block: 14px;
		}

		.primary-nav {
			grid-column: 1 / -1;
			grid-row: 2;
			justify-content: center;
			margin-top: 14px;
			padding-top: 14px;
			border-top: 1px solid var(--border);
		}

		.hero {
			grid-template-columns: 1fr;
			gap: 56px;
			padding-block: 76px;
		}

		.hero-copy {
			max-width: 720px;
		}


		.trace-panel {
			width: min(100%, 620px);
			justify-self: center;
		}

		.boundary {
			grid-template-columns: 1fr;
		}

		.boundary-heading h2,
		.boundary-heading p {
			max-width: 620px;
		}
	}

	@media (max-width: 620px) {
		.site-header,
		main,
		.site-footer {
			width: min(100% - 32px, 1180px);
		}

		.site-header {
			min-height: 68px;
		}

		.brand span {
			font-size: 14px;
		}

		.header-actions {
			gap: 10px;
		}

		.admin-link {
			padding-right: 10px;
			font-size: 13px;
		}

		.primary-nav {
			justify-content: space-between;
			gap: 18px;
		}

		.primary-nav a {
			font-size: 13px;
		}

		.hero {
			gap: 44px;
			padding-block: 58px;
		}

		h1 {
			font-size: clamp(2.5rem, 11.5vw, 3.5rem);
		}

		.hero-description {
			margin-top: 22px;
			line-height: 1.65;
		}

		.hero-actions {
			align-items: stretch;
		}

		.primary-action,
		.secondary-action {
			flex: 1 1 100%;
		}

		.trace-panel {
			padding: 20px;
		}

		.request-sample {
			padding: 15px;
		}

		.route-strip {
			gap: 6px;
			font-size: 9px;
		}

		.steps {
			grid-template-columns: 1fr;
		}

		.steps li,
		.steps li:first-child,
		.steps li:last-child {
			padding: 22px 0;
			border-top: 1px solid var(--border);
			border-left: 0;
		}

		.steps li:first-child {
			border-top: 0;
		}

		.site-footer {
			flex-direction: column;
			align-items: flex-start;
			justify-content: center;
			gap: 10px;
			padding-block: 20px;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.primary-nav a,
		.admin-link,
		.primary-action,
		.secondary-action {
			transition: none;
		}

		.primary-action:hover {
			transform: none;
		}
	}
</style>
