'use strict';

const $ = (id) => document.getElementById(id);
const state = { bootstrap: null, busy: false, lastRequest: null, intent: null, explanations: null, resultVersion: 0, shareText: null, selectedExample: null };
const roleLabels = { user: '사용자', assistant: '어시스턴트', system: '시스템' };
const actionLabels = { share_original: '공개 가능 · 원문 전달', mask_then_share: '마스킹 후 공개 가능', keep_local: '마스킹 시 의미 소실 · 로컬 처리' };
const stageLabels = { run: '전체 검사', validation: '입력 검증', annotation: '의도 분석', cache: '캐시 확인', extraction: '정보 항목 추출', policy: '행동 권고', masking: '마스킹·복원 확인' };
const stageOrder = ['validation', 'annotation', 'cache', 'extraction', 'policy', 'masking'];
const stageStates = { started: '진행 중', completed: '완료', skipped: '건너뜀', failed: '실패' };
const judgmentLabels = { confidentiality: { public: '공개 · public', private: '비공개 · private' }, necessity: { required: '필수 · required', optional: '선택 · optional' } };

function node(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined && text !== null) element.textContent = String(text);
  if (className) element.className = className;
  return element;
}
function status(text) { $('status').textContent = text; }
function number(value, digits = 0) { return Number.isFinite(value) ? value.toLocaleString('ko-KR', { maximumFractionDigits: digits }) : '기록 없음'; }
function duration(ms) { return Number.isFinite(ms) ? `${number(ms / 1000, 2)}초` : '기록 없음'; }
function messages() {
  const prior = [...$('context-list').children].map((row) => ({ role: row.querySelector('select').value, content: row.querySelector('textarea').value }));
  return [...prior, { role: $('input-role').value, content: $('input-text').value }];
}
function requestKey() { return JSON.stringify({ messages: messages() }); }
function updateControls() {
  const ready = Boolean(state.bootstrap);
  const current = messages();
  const count = current.reduce((total, item) => total + Array.from(item.content).length, 0);
  const valid = count <= 16000 && current.length <= 12 && current.every((item) => item.content.trim().length > 0);
  $('character-count').textContent = `${number(count)} / 16,000자`;
  $('character-count').classList.toggle('invalid', count > 16000);
  $('run').disabled = !ready || state.busy || !valid;
  $('repeat').disabled = !ready || state.busy || !valid || !state.intent || state.lastRequest !== requestKey();
  $('reset').disabled = !ready || state.busy;
  $('add-context').disabled = state.busy || current.length >= 12;
  $('input-text').disabled = state.busy;
  $('input-role').disabled = state.busy;
  $('context-list').querySelectorAll('textarea, select, button').forEach((control) => { control.disabled = state.busy; });
  $('example-list').querySelectorAll('button').forEach((control) => { control.disabled = state.busy; });
}
function clearResults({ keepProgress = false, keepExplanations = false } = {}) {
  state.lastRequest = null;
  state.intent = null;
  if (!keepExplanations) state.explanations = null;
  state.resultVersion++;
  $('results').hidden = true;
  state.shareText = null;
  $('copy').disabled = true;
  $('copy').textContent = '미리보기 복사';
  for (const id of ['source-text', 'records', 'masked-text', 'restored-text', 'sharing-text', 'sharing-reason', 'outcome-current', 'recommended-actions', 'run-metadata', 'intent-fields', 'intent-origin', 'record-count', 'round-trip']) $(id).replaceChildren();
  $('sharing-text').hidden = true;
  $('restoration').open = false;
  if (!keepProgress) {
    $('loading').hidden = true;
    $('loading-title').textContent = '';
    $('loading-detail').textContent = '';
    $('progress-stages').replaceChildren();
  }
}
function clearError() { $('error').hidden = true; $('error').replaceChildren(); }
function showError(message, explanation) {
  clearResults({ keepProgress: true });
  $('empty-state').hidden = true;
  const title = node('strong', '검사 미완료 · 권장 행동 보류 · 공유 차단');
  $('error').replaceChildren(title, node('p', message), node('p', explanation || '검사를 완료하지 못했습니다. 현재 입력은 유지되며, 이전 결과와 공유 미리보기는 표시하지 않습니다.', 'help'));
  $('error').hidden = false;
}
function inputChanged() {
  clearResults();
  clearError();
  $('empty-state').hidden = false;
  state.selectedExample = null;
  $('example-expectation').hidden = true;
  $('example-list').querySelectorAll('button').forEach((button) => button.setAttribute('aria-pressed', 'false'));
  updateControls();
  status('입력이 변경되었습니다. 검사 실행을 눌러 새 결과를 확인하세요.');
}

let contextId = 0;
function addContext(message = { role: 'user', content: '' }) {
  if ($('context-list').children.length >= 11) return;
  const id = ++contextId;
  const row = node('div', null, 'context-row');
  const toolbar = node('div', null, 'context-toolbar');
  const label = node('label', '이전 메시지');
  label.htmlFor = `context-text-${id}`;
  const roleLabel = node('label', '역할 ', 'role-label');
  const role = node('select');
  role.setAttribute('aria-label', '이전 메시지 역할');
  for (const [value, name] of Object.entries(roleLabels)) { const option = node('option', name); option.value = value; role.append(option); }
  role.value = message.role;
  roleLabel.append(role);
  const remove = node('button', '삭제', 'quiet small');
  remove.type = 'button';
  remove.setAttribute('aria-label', '이전 메시지 삭제');
  remove.addEventListener('click', () => { row.remove(); inputChanged(); $('add-context').focus(); });
  toolbar.append(label, roleLabel, remove);
  const input = node('textarea');
  input.id = `context-text-${id}`;
  input.rows = 3;
  input.spellcheck = false;
  input.value = message.content;
  input.addEventListener('input', inputChanged);
  role.addEventListener('change', inputChanged);
  row.append(toolbar, input);
  $('context-list').append(row);
  $('context-details').open = true;
  updateControls();
  return input;
}
function selectExample(example) {
  clearResults(); clearError();
  $('empty-state').hidden = false;
  state.selectedExample = example.id;
  $('context-list').replaceChildren();
  const items = example.messages;
  for (const item of items.slice(0, -1)) addContext(item);
  const current = items[items.length - 1];
  $('input-text').value = current.content;
  $('input-role').value = current.role;
  $('context-details').open = items.length > 1;
  $('example-list').querySelectorAll('button').forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.exampleId === example.id)));
  const expectation = $('example-expectation');
  expectation.replaceChildren(node('strong', '설명용 기대 · 실제 검출 결과 아님'), node('p', `예상 권장 행동: ${actionLabels[example.expected_action] ?? '권장 행동 보류'}`));
  if (example.expected_spans.length) expectation.append(node('p', `기대 구간: ${example.expected_spans.join(' / ')}`));
  if (example.note) expectation.append(node('p', example.note, 'help'));
  expectation.hidden = false;
  updateControls();
  status(`“${example.title}” 예제를 불러왔습니다. 아직 모델을 호출하지 않았습니다.`);
}
function renderExamples(examples) {
  $('example-list').replaceChildren();
  for (const example of examples) {
    const button = node('button', null, 'example-button');
    button.type = 'button';
    button.dataset.exampleId = example.id;
    button.setAttribute('aria-pressed', 'false');
    button.append(node('strong', example.title), node('span', example.description));
    button.addEventListener('click', () => selectExample(example));
    $('example-list').append(button);
  }
}

function judgmentValue(judgment, axis) {
  return judgment?.status === 'assessed' && Object.hasOwn(judgmentLabels[axis], judgment.value) ? judgment.value : null;
}
function confidentialityClass(record) {
  return judgmentValue(record.confidentiality, 'confidentiality') ?? 'unassessed';
}
function receivedReason(reason) {
  return typeof reason === 'string' && reason.trim() ? reason : null;
}
function explanationsForResult(result, serialized) {
  const key = JSON.stringify({
    request: serialized, source: result.source_text, intent: result.intent, model: result.model,
    status: result.status, recommendation: result.recommendation,
    preservesTask: result.masking_assessment.preserves_task,
    records: result.records.map((record) => [
      record.start, record.end, record.category, record.confidence,
      record.confidentiality.value, record.confidentiality.status,
      record.necessity.value, record.necessity.status,
    ]),
  });
  const previous = result.cache.hit === true && state.explanations?.key === key ? state.explanations : null;
  function explanation(reason, prior) {
    const text = receivedReason(reason);
    if (text !== null) return { text, origin: 'response' };
    if (prior !== null && prior !== undefined) return { text: prior, origin: 'browser' };
    return { text: null, origin: null };
  }
  const records = result.records.map((record, index) => ({
    confidentiality: explanation(record.confidentiality.reason, previous?.records[index]?.confidentiality),
    necessity: explanation(record.necessity.reason, previous?.records[index]?.necessity),
  }));
  const masking = explanation(result.masking_assessment.reason, previous?.masking);
  state.explanations = {
    key,
    records: records.map((record) => ({ confidentiality: record.confidentiality.text, necessity: record.necessity.text })),
    masking: masking.text,
  };
  return { records, masking };
}
function appendExplanation(container, explanation, cacheHit) {
  container.append(node('p', explanation.text ?? (cacheHit ? '캐시에는 근거 문장을 저장하지 않습니다. 이 브라우저에도 같은 판정의 이전 설명이 없습니다.' : '이번 응답에 근거 문장이 없습니다.'), 'judgment-reason'));
  if (explanation.origin) container.append(node('p', explanation.origin === 'browser' ? '근거 출처 · 이 브라우저에서 받은 이전 응답 (캐시가 반환한 설명 아님)' : '근거 출처 · 이번 응답', 'explanation-origin'));
}
function renderJudgment(axis, judgment, explanation, cacheHit) {
  const value = judgmentValue(judgment, axis);
  const section = node('div', null, `judgment judgment-${value ?? 'unassessed'}`);
  const heading = node('h3', axis === 'confidentiality' ? '기밀성' : '작업 필수성', 'judgment-heading');
  const status = node('p', value === null ? '미판정' : judgmentLabels[axis][value], 'judgment-value');
  section.append(heading, status);
  appendExplanation(section, explanation, cacheHit);
  return section;
}

// Expand protected values exactly as masking does, preserving Python code-point
// offsets and the original judgment's identity at every repeated occurrence.
function highlightSource(text, records) {
  const points = Array.from(text);
  const ranges = [];
  let codePointOffsets;
  for (const [index, record] of records.entries()) {
    if (!Number.isInteger(record.start) || !Number.isInteger(record.end) || record.start < 0 || record.end > points.length || record.start >= record.end) continue;
    const confidentiality = confidentialityClass(record);
    if (confidentiality === 'public') {
      ranges.push({ record, index, confidentiality, start: record.start, end: record.end });
      continue;
    }
    // indexOf returns UTF-16 offsets; only non-BMP text needs a conversion map.
    if (text.length !== points.length && !codePointOffsets) {
      codePointOffsets = new Map();
      for (let point = 0, unit = 0; point < points.length; point++) {
        codePointOffsets.set(unit, point);
        unit += points[point].length;
      }
    }
    const value = points.slice(record.start, record.end).join('');
    let previous;
    for (let offset = text.indexOf(value); offset !== -1; offset = text.indexOf(value, offset + 1)) {
      const start = codePointOffsets ? codePointOffsets.get(offset) : offset;
      if (start === undefined) continue;
      const end = start + record.end - record.start;
      // Merge a value's touching matches before rendering overlapping repeats.
      if (previous && start <= previous.end) previous.end = end;
      else {
        previous = { record, index, confidentiality, start, end };
        ranges.push(previous);
      }
    }
  }
  ranges.sort((left, right) => left.start - right.start);
  const boundaries = [...new Set([0, points.length, ...ranges.flatMap((record) => [record.start, record.end])])].sort((a, b) => a - b);
  const fragment = document.createDocumentFragment();
  let active = [], nextRange = 0;
  for (let i = 0; i < boundaries.length - 1; i++) {
    const start = boundaries[i], end = boundaries[i + 1];
    // Scan only active ranges, not every occurrence at every source boundary.
    active = active.filter((range) => range.end > start);
    while (nextRange < ranges.length && ranges[nextRange].start === start) active.push(ranges[nextRange++]);
    const textPart = points.slice(start, end).join('');
    if (active.length) {
      const confidentiality = active.some((range) => range.confidentiality === 'private') ? 'private' : active.some((range) => range.confidentiality === 'unassessed') ? 'unassessed' : 'public';
      const mark = node('mark', textPart, `information-${confidentiality}`);
      const label = confidentiality === 'unassessed' ? '기밀성 미판정 · 보호 대상' : judgmentLabels.confidentiality[confidentiality];
      const repeated = active.some((range) => range.start !== range.record.start || range.end !== range.record.end);
      mark.setAttribute('aria-label', `${label}${repeated ? ' · 동일 값 반복 위치 포함' : ''}: ${textPart}`);
      mark.title = active.map(({ record, index, start, end, confidentiality }) => `#${index + 1} ${record.category} · ${judgmentLabels.confidentiality[confidentiality] ?? '기밀성 미판정'} [${start}, ${end})${start !== record.start || end !== record.end ? ` · 동일 값 반복 포함 (판정 위치 [${record.start}, ${record.end}))` : ''}`).join(' · ');
      fragment.append(mark);
    } else fragment.append(document.createTextNode(textPart));
  }
  $('source-text').replaceChildren(fragment);
}
function renderRecords(records, source, cacheHit, explanations) {
  const container = $('records');
  container.replaceChildren();
  const counts = { public: 0, private: 0, unassessed: 0 };
  for (const record of records) counts[confidentialityClass(record)]++;
  $('record-count').textContent = `정보 항목 ${number(records.length)}개 · 공개 ${number(counts.public)} · 비공개 ${number(counts.private)} · 기밀성 미판정 ${number(counts.unassessed)}`;
  if (cacheHit) container.append(node('p', '캐시 적중: 위치·범주·기밀성·필수성 판정을 재사용했습니다. 캐시에는 원문이나 근거 문장이 없습니다. 이전 설명이 표시되면 이 브라우저 메모리에만 남아 있던 응답이며, 입력·의도·판정이 모두 같을 때만 사용합니다.', 'cache-note'));
  if (!records.length) { container.append(node('p', '반환된 정보 항목이 없습니다. 이 결과는 모든 비공개 정보의 부재를 보장하지 않습니다.', 'help')); return; }
  const points = Array.from(source);
  const list = node('ol', null, 'record-list');
  for (const [index, record] of records.entries()) {
    const item = node('li', null, 'record');
    const heading = node('div', null, 'record-heading');
    heading.append(node('strong', `#${index + 1} ${record.category}`), node('span', `[${record.start}, ${record.end})`, 'offset'));
    item.append(heading, node('pre', points.slice(record.start, record.end).join(''), 'record-value'));
    const confidence = Number.isFinite(record.confidence) ? `${number(record.confidence * 100, 1)}%` : '기록 없음';
    item.append(node('p', `모델이 제시한 신뢰도 ${confidence} (실측 정확도 아님)`, 'record-meta'));
    const judgments = node('div', null, 'record-judgments');
    for (const axis of ['confidentiality', 'necessity']) judgments.append(renderJudgment(axis, record[axis], explanations[index][axis], cacheHit));
    item.append(judgments); list.append(item);
  }
  container.append(list);
}
function renderOutcome(recommendation, session, assessment, cacheHit, explanation) {
  const action = recommendation.action;
  const current = $('outcome-current');
  current.replaceChildren(node('strong', action === null ? '권장 행동 보류' : actionLabels[action], `outcome-label${action === null ? '' : ` action-${action}`}`), node('p', recommendation.explanation), node('p', `검사한 세션: ${number(session.message_count)}개 메시지 · 권고는 정보 등급이나 전송 허가가 아닙니다.`, 'help'));
  const masking = node('dl', null, 'masking-assessment');
  const preservation = action === 'share_original' ? '비공개 정보로 판단된 보호 대상이 없어 원문 전달을 권고합니다. 공개 정보는 그대로 유지합니다.' : assessment.preserves_task === true ? '완료 가능 · 보호 대상 정보를 모두 가려도 작업이 성립합니다.' : assessment.preserves_task === false ? '완료 불가 · 보호 대상 정보를 모두 가리면 작업이 성립하지 않습니다.' : '미판정 · 전체 마스킹이 작업에 미치는 영향이 확인되지 않았습니다.';
  masking.append(node('dt', '보호 대상 정보를 모두 가리고 공개 정보를 유지해도 작업을 완료할 수 있나요?'), node('dd', preservation));
  const reason = node('dd');
  appendExplanation(reason, explanation, cacheHit);
  masking.append(node('dt', '전체 마스킹 판단 근거'), reason);
  current.append(masking);
  $('action-guide').open = false;
  const list = $('recommended-actions');
  list.replaceChildren();
  for (const recommendation of state.bootstrap.recommended_actions) {
    const item = node('li');
    if (recommendation.value === action) { item.className = 'current'; item.setAttribute('aria-current', 'true'); }
    item.append(node('strong', `${recommendation.value === action ? '현재 권고 · ' : ''}${recommendation.label}`), node('span', recommendation.description));
    list.append(item);
  }
}
function renderIntent(intent, origin) {
  $('intent-origin').textContent = origin === 'analyzed' ? '출처 · 이번 요청에서 모델이 분석' : origin === 'provided' ? '출처 · 요청에 제공된 어노테이션' : '출처 · 확인되지 않음';
  const fields = $('intent-fields');
  fields.replaceChildren();
  for (const [label, value] of [['목표', intent.goal], ['행동', intent.action], ['완료 조건', intent.completion_condition], ['선택된 채널', intent.channel ?? '미확정 · 지정되지 않음']]) {
    fields.append(node('dt', label), node('dd', value));
  }
  const unresolved = node('dd');
  if (intent.unresolved.length) {
    const questions = node('ul', null, 'intent-questions');
    for (const question of intent.unresolved) questions.append(node('li', question));
    unresolved.append(questions);
  } else unresolved.textContent = '반환된 미해결 질문 없음';
  fields.append(node('dt', '미해결 질문'), unresolved);
}
function renderResult(result, serialized) {
  const explanations = explanationsForResult(result, serialized);
  renderOutcome(result.recommendation, result.session, result.masking_assessment, result.cache.hit, explanations.masking);
  renderIntent(result.intent, result.intent_source);
  const metadata = $('run-metadata');
  metadata.replaceChildren(node('span', `전체 ${duration(result.timings.total_ms)}`), node('span', `모델 응답 ${duration(result.timings.model_ms)}`), node('strong', `모델 호출 합계 ${number(result.model_calls)}회`), node('span', `의도 분석 ${number(result.stage_calls.annotation)}회 · ${duration(result.timings.annotation_ms)}`), node('span', `추출 ${number(result.stage_calls.extraction)}회 · ${duration(result.timings.extraction_ms)}`), node('strong', result.cache.hit ? '추출 캐시 적중' : '추출 캐시 미적중'), node('span', `캐시 ${number(result.cache.entries)}건`));
  metadata.title = result.cache.note;
  metadata.append(node('span', `${result.model.name} · ${result.model.backend}`, 'metadata-model'));
  highlightSource(result.source_text, result.records);
  renderRecords(result.records, result.source_text, result.cache.hit, explanations.records);
  $('masked-text').textContent = result.masking.text;
  $('restored-text').textContent = result.masking.hydrated_text;
  $('round-trip').textContent = result.masking.round_trip_ok ? '원문 일치' : '원문 불일치 · 확인 필요';
  $('round-trip').classList.toggle('invalid', !result.masking.round_trip_ok);
  const permitted = result.status === 'complete' && ['share_original', 'mask_then_share'].includes(result.recommendation.action) && result.masking.round_trip_ok === true && result.sharing.permitted === true && typeof result.sharing.text === 'string';
  state.shareText = permitted ? result.sharing.text : null;
  $('sharing-text').textContent = permitted ? result.sharing.text : '';
  $('sharing-text').hidden = !permitted;
  $('copy').disabled = !permitted;
  $('sharing-reason').textContent = `${permitted ? '공유 전 검토용 미리보기' : '공유 차단'} · ${result.sharing.reason || result.recommendation.explanation}`;
  $('results').hidden = false;
  $('empty-state').hidden = true;
}

async function api(path, body) {
  const response = await fetch(path, { method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store', headers: body === undefined ? { Accept: 'application/json' } : { Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': state.bootstrap.csrf_token }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  let data;
  try { data = await response.json(); } catch { throw new Error('서버 응답을 읽을 수 없습니다. 연결 상태를 확인한 뒤 다시 실행하세요.'); }
  if (!response.ok) {
    const error = new Error(data.error?.message || `요청을 완료하지 못했습니다 (HTTP ${response.status}).`);
    error.explanation = data.recommendation?.explanation;
    throw error;
  }
  return data;
}

function renderProgress(progress, event) {
  const detailLabels = { intent_provided: '제공된 의도 사용', cache_hit: '캐시 적중', cache_miss: '캐시 미적중' };
  $('loading').dataset.state = event.state;
  $('loading-title').textContent = event.stage === 'run'
    ? event.state === 'completed' ? '검사 완료' : event.state === 'failed' ? '검사 실패' : '검사 시작'
    : `${stageLabels[event.stage]} · ${stageStates[event.state]}`;
  $('loading-detail').textContent = `마지막 상태 수신 시점 · 시작 후 ${duration(event.elapsed_ms)}${event.detail ? ` · ${detailLabels[event.detail]}` : ''}`;
  const list = $('progress-stages');
  list.replaceChildren();
  for (const stage of stageOrder) {
    const update = progress.stages.get(stage);
    const row = node('li', null, `progress-step ${update?.state || 'pending'}`);
    row.dataset.stage = stage;
    if (update?.state === 'started') row.setAttribute('aria-current', 'step');
    row.append(node('span', stageLabels[stage]), node('strong', update ? `${stageStates[update.state]}${update.detail ? ` · ${detailLabels[update.detail]}` : ''}` : '대기'));
    list.append(row);
  }
  status($('loading-title').textContent);
}

function acceptProgress(progress, event) {
  const invalid = () => { throw new Error('실행 상태 순서를 확인할 수 없습니다. 공유를 차단합니다.'); };
  if (!event || typeof event.run_id !== 'string' || !event.run_id || !Number.isSafeInteger(event.sequence) ||
      event.sequence !== progress.sequence + 1 || !Object.hasOwn(stageLabels, event.stage) ||
      !Object.hasOwn(stageStates, event.state) || !Number.isFinite(event.elapsed_ms) ||
      event.elapsed_ms < progress.elapsed || ![null, 'intent_provided', 'cache_hit', 'cache_miss'].includes(event.detail)) invalid();
  if (progress.runId === null) {
    if (event.stage !== 'run' || event.state !== 'started') invalid();
    progress.runId = event.run_id;
    progress.runState = 'started';
  } else {
    if (progress.runId !== event.run_id || progress.runState !== 'started') invalid();
    if (event.stage === 'run') {
      if (!['completed', 'failed'].includes(event.state)) invalid();
      if (event.state === 'completed' && !stageOrder.every(stage => ['completed', 'skipped'].includes(progress.stages.get(stage)?.state))) invalid();
      progress.runState = event.state;
    } else {
      const previous = progress.stages.get(event.stage);
      if (previous) {
        if (previous.state !== 'started' || !['completed', 'failed'].includes(event.state)) invalid();
      } else {
        const position = stageOrder.indexOf(event.stage);
        if (!['started', 'skipped'].includes(event.state) ||
            !stageOrder.slice(0, position).every(stage => ['completed', 'skipped'].includes(progress.stages.get(stage)?.state))) invalid();
        if (event.state === 'skipped' && !((event.stage === 'annotation' && event.detail === 'intent_provided') ||
            (event.stage === 'extraction' && event.detail === 'cache_hit'))) invalid();
      }
      progress.stages.set(event.stage, event);
    }
  }
  progress.sequence = event.sequence;
  progress.elapsed = event.elapsed_ms;
  renderProgress(progress, event);
}

async function analyzeStream(body, version) {
  const response = await fetch('/api/analyze', {
    method: 'POST', credentials: 'same-origin', cache: 'no-store',
    headers: { Accept: 'application/x-ndjson', 'Content-Type': 'application/json', 'X-CSRF-Token': state.bootstrap.csrf_token },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let data;
    try { data = await response.json(); } catch { throw new Error(`검사 요청을 처리하지 못했습니다 (HTTP ${response.status}).`); }
    const error = new Error(data.error?.message || `검사 요청 실패 (HTTP ${response.status}).`);
    error.explanation = data.recommendation?.explanation;
    throw error;
  }
  if (!response.body || !response.headers.get('Content-Type')?.startsWith('application/x-ndjson')) throw new Error('실행 상태 스트림을 받지 못했습니다.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8', { fatal: true });
  const progress = { runId: null, sequence: 0, elapsed: 0, runState: null, stages: new Map() };
  let buffer = '';
  let terminal = null;
  let ended = false;
  function consume(line) {
    if (!line.trim()) return;
    if (terminal) throw new Error('검사 종료 뒤 예상하지 못한 응답이 도착했습니다.');
    const envelope = JSON.parse(line);
    if (envelope.type === 'status') acceptProgress(progress, envelope.event);
    else if (envelope.type === 'result') {
      if (progress.runState !== 'completed' || envelope.result?.status !== 'complete') throw new Error('검사 완료를 확인하지 못했습니다.');
      const result = envelope.result;
      const action = result.recommendation?.action;
      if (action !== null && !Object.hasOwn(actionLabels, action)) throw new Error('권장 행동을 확인하지 못했습니다.');
      if ((action === null || action === 'keep_local') && (result.sharing?.permitted !== false || result.sharing.text !== null)) throw new Error('권장 행동과 공유 결과가 일치하지 않습니다.');
      terminal = envelope;
    } else if (envelope.type === 'error') {
      if (envelope.recommendation?.action !== null || envelope.sharing?.permitted !== false) throw new Error('실패 응답을 확인하지 못했습니다.');
      terminal = envelope;
    } else throw new Error('알 수 없는 실행 상태 응답입니다.');
  }
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (version !== state.resultVersion) throw new Error('입력이 변경되어 이전 검사 결과를 사용하지 않습니다.');
      buffer += decoder.decode(value, { stream: !done });
      if (buffer.length > 2 * 1024 * 1024) throw new Error('검사 응답이 허용된 크기를 초과했습니다.');
      let newline;
      while ((newline = buffer.indexOf('\n')) !== -1) {
        consume(buffer.slice(0, newline));
        buffer = buffer.slice(newline + 1);
      }
      if (done) { ended = true; break; }
    }
    if (buffer.trim()) throw new Error('검사 응답이 중간에 끊겼습니다.');
    if (!terminal) throw new Error('최종 검사 결과를 받지 못했습니다. 다시 검사하세요.');
    if (terminal.type === 'error') {
      const error = new Error(terminal.error?.message || '검사를 완료하지 못했습니다.');
      error.explanation = terminal.recommendation.explanation;
      throw error;
    }
    return terminal.result;
  } finally {
    if (!ended) {
      try { await reader.cancel(); } catch { /* The disconnected reader is already unusable. */ }
    }
    reader.releaseLock();
  }
}
async function analyze(repeat = false) {
  if (state.busy || !state.bootstrap) return;
  const serialized = repeat ? state.lastRequest : requestKey();
  if (!serialized || (repeat && (!state.intent || serialized !== requestKey()))) return;
  const body = JSON.parse(serialized);
  if (state.lastRequest === serialized && state.intent) body.intent = state.intent;
  if (body.messages.some((message) => !message.content.trim()) || body.messages.reduce((n, message) => n + Array.from(message.content).length, 0) > 16000) return;
  state.busy = true;
  clearError(); clearResults({ keepExplanations: state.lastRequest === serialized && Boolean(body.intent) });
  const version = state.resultVersion;
  $('empty-state').hidden = true;
  $('loading').hidden = false;
  $('loading-title').textContent = '요청 접수 대기';
  $('loading-detail').textContent = '서버의 첫 실행 상태를 기다립니다. 아직 어느 단계가 시작됐는지 확인되지 않았습니다.';
  $('panel-live').setAttribute('aria-busy', 'true');
  $('run').textContent = '검사 중…';
  updateControls();
  status('검사 요청을 보냈습니다. 서버의 실제 실행 상태를 기다립니다.');
  try {
    const result = await analyzeStream(body, version);
    if (version !== state.resultVersion || serialized !== requestKey()) return;
    if (result.status !== 'complete') throw new Error('검사가 완료되지 않았습니다. 공유는 차단됩니다.');
    renderResult(result, serialized);
    state.lastRequest = serialized;
    state.intent = result.intent;
    status(`검사 완료. ${actionLabels[result.recommendation.action] ?? '권장 행동 보류'}. ${result.cache.hit ? '추출 캐시 적중' : '추출 캐시 미적중'}, 의도 분석 ${number(result.stage_calls.annotation)}회 · 추출 ${number(result.stage_calls.extraction)}회 · 모델 호출 합계 ${number(result.model_calls)}회.`);
  } catch (error) {
    if (version !== state.resultVersion) return;
    showError(error.message, error.explanation);
    $('loading-title').textContent = '검사 결과를 확정하지 못했습니다';
    $('loading').dataset.state = 'failed';
    $('loading-detail').textContent = '아래는 마지막으로 받은 실행 상태입니다. 권장 행동을 보류하고 공유를 차단합니다.';
    status('검사를 완료하지 못했습니다. 권장 행동 보류 · 공유 차단. 입력은 유지됩니다.');
  } finally {
    state.busy = false;
    $('panel-live').removeAttribute('aria-busy');
    $('run').textContent = '검사 실행';
    updateControls();
  }
}
async function reset() {
  if (state.busy || !state.bootstrap) return;
  state.busy = true;
  clearError(); clearResults();
  updateControls();
  status('현재 세션의 메타데이터 캐시를 초기화하고 있습니다.');
  try {
    const result = await api('/api/reset', {});
    if (result.cleared !== true) throw new Error('캐시 초기화 여부를 확인하지 못했습니다. 다시 시도하세요.');
    $('input-text').value = '';
    $('input-role').value = 'user';
    $('context-list').replaceChildren();
    $('context-details').open = false;
    inputChanged();
    status('입력, 검사 결과, 현재 세션의 메타데이터 캐시를 초기화했습니다.');
  } catch (error) {
    showError(error.message, '초기화를 완료하지 못했습니다. 입력은 유지되며 이전 결과와 공유 미리보기는 숨겼습니다.');
    status('초기화 실패. 입력은 유지됩니다. 다시 시도하세요.');
  } finally { state.busy = false; updateControls(); }
}
async function copyPreview() {
  const text = state.shareText;
  if (text === null) return;
  try {
    await navigator.clipboard.writeText(text);
    if (state.shareText === text) $('copy').textContent = '복사 완료';
    status('허용된 미리보기를 클립보드에 복사했습니다. 클립보드에는 텍스트가 남으므로 공유 후 관리해 주세요.');
  } catch {
    status('브라우저에서 클립보드 복사를 허용하지 않았습니다. 허용된 미리보기를 직접 선택해 복사하세요.');
    if (state.shareText !== null) $('sharing-text').focus();
  }
}

function renderBenchmark(benchmark) {
  $('benchmark-provenance').textContent = `의도 분석 도입 전 · 추출 단독 측정 · ${benchmark.model} · ${benchmark.implementation}`;
  const summary = $('benchmark-summary');
  summary.replaceChildren();
  const lines = [
    ['측정 범위', benchmark.scope],
    ['저장된 측정 쌍', `${number(benchmark.completed_pairs)}쌍`],
    ['기대 구간 정확 일치', `${number(benchmark.exact_hits)} / ${number(benchmark.expected_spans)}`],
    ['기대 구간 포함 일치', `${number(benchmark.contained_hits)} / ${number(benchmark.expected_spans)}`],
    ['정확 일치 미충족', `${number(benchmark.expected_spans - benchmark.exact_hits)}건`],
    ['포함 일치에서도 미충족', `${number(benchmark.expected_spans - benchmark.contained_hits)}건`],
    ['평균 추출 실행 시간', duration(benchmark.mean_ms)],
    ['실패', `${number(benchmark.failures)}회`],
  ];
  const description = node('dl');
  for (const [label, value] of lines) description.append(node('dt', label), node('dd', value));
  summary.append(description);
  $('benchmark-caveat').replaceChildren(node('strong', '과거 추출 단독 실험 · 현재 2단계 파이프라인의 성능 아님'), node('p', '10개 합성 사례를 2회 반복한 기록입니다. 의도 분석 시간이나 어노테이션을 사용하는 현재 추출의 정확도·필수성 판단을 평가하지 않았습니다.'), node('p', '같은 예제의 반복은 독립적인 통계 근거가 아닙니다. 기대 구간에 대한 coverage이며, 포괄적인 정밀도·재현율이 아닙니다. 오탐이나 기대 목록 밖의 누락을 모두 평가하지 않습니다.'), node('p', benchmark.caveat, 'help'));
  $('benchmark-cases').replaceChildren();
  for (const item of benchmark.cases) {
    const details = node('details', null, 'benchmark-case');
    const caseSummary = node('summary');
    const exactMisses = item.runs.reduce((total, run) => total + Math.max(0, run.expected_count - run.exact_hits), 0);
    caseSummary.append(node('strong', item.title || item.id), node('span', `정확 일치 미충족 ${number(exactMisses)}건 · ${number(item.runs.length)}회`, exactMisses ? 'miss-count' : 'minor'));
    details.append(caseSummary);
    const wrapper = node('div', null, 'table-wrap');
    const table = node('table');
    const caption = node('caption', '실행별 기대 구간 coverage와 실행 시간');
    const thead = node('thead');
    const header = node('tr');
    for (const label of ['실행', '정확 일치', '포함 일치', '정확 미충족', '포함 미충족', '실행 시간']) { const th = node('th', label); th.scope = 'col'; header.append(th); }
    thead.append(header);
    const tbody = node('tbody');
    for (const run of item.runs) {
      const row = node('tr');
      const values = [`${run.repeat + 1}회`, `${run.exact_hits} / ${run.expected_count}`, `${run.contained_hits} / ${run.expected_count}`, number(Math.max(0, run.expected_count - run.exact_hits)), number(Math.max(0, run.expected_count - run.contained_hits)), duration(run.latency_ms)];
      values.forEach((value, index) => { const cell = node(index === 0 ? 'th' : 'td', value); if (index === 0) cell.scope = 'row'; row.append(cell); });
      tbody.append(row);
    }
    table.append(caption, thead, tbody); wrapper.append(table); details.append(wrapper);
    details.append(node('p', '미충족 수는 기대 구간 수에서 일치 수를 뺀 값입니다. 이 집계에는 개별 검출 위치가 없어 어떤 구간을 놓쳤는지 특정하지 않습니다.', 'help'));
    details.append(node('h4', '저장된 합성 원문'), node('pre', item.text, 'text-view'));
    details.append(node('h4', '저장된 기대 구간 · 실제 검출 아님'));
    const expected = node('ul', null, 'expected-list');
    for (const span of item.expected_spans) expected.append(node('li', span));
    if (!item.expected_spans.length) expected.append(node('li', '기대 민감 구간 없음'));
    details.append(expected);
    $('benchmark-cases').append(details);
  }
  $('benchmark-loading').hidden = true;
  $('benchmark').hidden = false;
}
async function bootstrap() {
  $('bootstrap-retry').hidden = true;
  clearResults();
  clearError();
  status('로컬 서버에서 예제와 모델 연결 정보를 불러오고 있습니다. 모델 추론은 실행하지 않습니다.');
  try {
    const data = await api('/api/bootstrap');
    if (!Array.isArray(data.recommended_actions) || data.recommended_actions.length !== 3 || Object.keys(actionLabels).some((action) => data.recommended_actions.filter((item) => item.value === action).length !== 1)) throw new Error('권장 행동 설정을 읽을 수 없습니다.');
    state.bootstrap = data;
    $('model-status').textContent = `${data.model.available ? '연결 가능' : '연결 확인 필요'} · ${data.model.name}`;
    $('model-status').title = `${data.model.backend} · ${data.model.detail}`;
    renderExamples(data.examples);
    renderBenchmark(data.benchmark);
    status(data.model.available ? '준비되었습니다. 예제를 선택하거나 입력한 뒤 검사를 실행하세요.' : '모델 연결 확인이 필요합니다. 입력은 준비할 수 있지만 실행 시 연결 오류가 발생할 수 있습니다.');
  } catch {
    state.bootstrap = null;
    $('model-status').textContent = '연결 정보를 불러오지 못함';
    $('error').replaceChildren(node('strong', '도구를 준비하지 못했습니다'), node('p', '로컬 서버 연결을 확인하고 다시 불러오세요. 모델을 호출하지 않았으며 입력은 유지됩니다.'));
    $('error').hidden = false;
    $('bootstrap-retry').hidden = false;
    $('benchmark-loading').textContent = '저장된 측정값을 불러오지 못했습니다. 연결 정보를 다시 불러오세요.';
    status('연결 정보 불러오기 실패. 아직 검사하지 않았습니다.');
  } finally { updateControls(); }
}

const tabs = [$('tab-live'), $('tab-history')];
function activateTab(tab) {
  for (const item of tabs) { const active = item === tab; item.setAttribute('aria-selected', String(active)); item.tabIndex = active ? 0 : -1; $(item.getAttribute('aria-controls')).hidden = !active; }
}
for (const tab of tabs) {
  tab.addEventListener('click', () => activateTab(tab));
  tab.addEventListener('keydown', (event) => {
    let next;
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') next = tabs[1 - tabs.indexOf(tab)];
    else if (event.key === 'Home') next = tabs[0];
    else if (event.key === 'End') next = tabs[tabs.length - 1];
    if (next) { event.preventDefault(); activateTab(next); next.focus(); }
  });
}
$('analyze-form').addEventListener('submit', (event) => { event.preventDefault(); if (!$('run').disabled) analyze(); });
$('repeat').addEventListener('click', () => analyze(true));
$('reset').addEventListener('click', reset);
$('copy').addEventListener('click', copyPreview);
$('input-text').addEventListener('input', inputChanged);
$('input-role').addEventListener('change', inputChanged);
$('add-context').addEventListener('click', () => { const input = addContext(); inputChanged(); if (input) input.focus(); });
$('bootstrap-retry').addEventListener('click', bootstrap);
bootstrap();
