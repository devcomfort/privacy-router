#!/usr/bin/env bash
# scripts/ci_sanity.sh -- Privacy Router CI/CD Sanity Check
#
# Usage:
#   bash scripts/ci_sanity.sh                  # full run
#   bash scripts/ci_sanity.sh --openai         # OpenAI compat only
#   bash scripts/ci_sanity.sh --openresponses  # OpenResponses only
#   bash scripts/ci_sanity.sh --cleanup        # cleanup only

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

API_PORT="${API_PORT:-8787}"
BASE_URL="http://localhost:${API_PORT}"
API_URL="${PRIVACY_ROUTER_URL:-${BASE_URL}/v1}"
OPENRESPONSES_DIR="${OPENRESPONSES_DIR:-/tmp/openresponses}"
BUN_BIN="${HOME}/.bun/bin/bun"
RESULTS_DIR="${PROJECT_DIR}/ci-results"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[ci]${NC} $*"; }
warn() { echo -e "${YELLOW}[ci]${NC} $*"; }
err()  { echo -e "${RED}[ci]${NC} $*" >&2; }

TEST_RAW_KEY=""
TEST_PROVIDER_ID=""

# ── Helpers ──────────────────────────────────────────────────────────────────

db_exec() {
    sg docker -c "docker exec privacy-router-db-1 psql -U privacy_router -d privacy_router -t -A -c \"$1\"" 2>/dev/null
}

extract_uuid() {
    grep -oP '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -1 || true
}

# ── Prerequisites ────────────────────────────────────────────────────────────

check_prerequisites() {
    log "Checking prerequisites..."
    command -v docker  >/dev/null || { err "docker not found";  exit 1; }
    command -v curl    >/dev/null || { err "curl not found";    exit 1; }
    command -v python3 >/dev/null || { err "python3 not found"; exit 1; }
    python3 -c "import openai" 2>/dev/null || { warn "Installing openai..."; pip install openai -q; }
    log "Prerequisites OK"
}

# ── Infrastructure ───────────────────────────────────────────────────────────

ensure_services() {
    log "Ensuring DB + API are running..."
    cd "$PROJECT_DIR"

    if sg docker -c "docker ps --format '{{.Names}}'" 2>/dev/null | grep -q "privacy-router-api"; then
        log "API container already running"
    else
        log "Starting DB + API..."
        sg docker -c "docker compose up -d db api" 2>&1 | tail -3
        sleep 5
    fi

    local retries=10
    while [ $retries -gt 0 ]; do
        if curl -s "${BASE_URL}/v1/models" >/dev/null 2>&1; then
            log "API is healthy"
            return 0
        fi
        retries=$((retries - 1))
        sleep 2
    done

    err "API failed to start"
    sg docker -c "docker logs privacy-router-api-1 --tail 20" 2>&1
    exit 1
}

# ── API Key Management ───────────────────────────────────────────────────────

create_test_api_key() {
    log "Creating test API key..."

    # Generate key
    local key_data key_hash prefix
    key_data=$(python3 << 'PYEOF'
from secrets import token_urlsafe
from hashlib import sha256
raw = "pr-" + token_urlsafe(32)
h = sha256(raw.encode()).hexdigest()
print(raw + "\t" + h + "\t" + raw[:12])
PYEOF
)
    TEST_RAW_KEY=$(echo "$key_data" | cut -f1)
    key_hash=$(echo "$key_data" | cut -f2)
    prefix=$(echo "$key_data" | cut -f3)

    # Find or create provider
    TEST_PROVIDER_ID=$(db_exec "SELECT id FROM providers WHERE name = 'ci-test-provider' LIMIT 1;" | extract_uuid)

    if [ -z "$TEST_PROVIDER_ID" ]; then
        TEST_PROVIDER_ID=$(python3 -c "import uuid; print(uuid.uuid4())")
        db_exec "INSERT INTO providers (id, name, provider_type, api_key_env, api_base, is_active, created_at, updated_at) VALUES ('${TEST_PROVIDER_ID}', 'ci-test-provider', 'openai', 'OPENROUTER_API_KEY', 'https://openrouter.ai/api/v1', true, now(), now());"
    fi

    # Insert API key
    local key_id
    key_id=$(python3 -c "import uuid; print(uuid.uuid4())")
    db_exec "INSERT INTO api_keys (id, provider_id, name, key_hash, prefix, is_active, created_at) VALUES ('${key_id}', '${TEST_PROVIDER_ID}', 'ci-test-key', '${key_hash}', '${prefix}', true, now());"

    export PRIVACY_ROUTER_API_KEY="$TEST_RAW_KEY"
    log "Test API key created: ${prefix}..."
}

cleanup_test_data() {
    log "Cleaning up test data..."
    cd "$PROJECT_DIR"
    db_exec "DELETE FROM api_keys WHERE name = 'ci-test-key';"
    db_exec "DELETE FROM providers WHERE name = 'ci-test-provider';"
    rm -rf "$RESULTS_DIR" 2>/dev/null || true
    log "Cleanup complete"
}

# ── Smoke Test ───────────────────────────────────────────────────────────────

run_smoke_test() {
    log "Running API smoke test..."

    local models_count
    models_count=$(curl -s "${BASE_URL}/v1/models" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['data']))" 2>/dev/null)
    if [ -n "$models_count" ] && [ "$models_count" -gt 0 ]; then
        log "  Models: OK (${models_count} models)"
    else
        err "  Models: FAILED"; return 1
    fi

    local classify_ok
    classify_ok=$(curl -s -X POST "${BASE_URL}/api/v1/classify" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${TEST_RAW_KEY}" \
        -d '{"text": "주민등록번호 901212-1234567"}' \
        | python3 -c "import sys,json; print(json.load(sys.stdin).get('is_sensitive', False))" 2>/dev/null)
    if [ "$classify_ok" = "True" ]; then
        log "  Classify: OK (sensitive=true)"
    else
        err "  Classify: FAILED"; return 1
    fi

    local chat_ok
    chat_ok=$(curl -s -X POST "${BASE_URL}/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${TEST_RAW_KEY}" \
        -d '{"model":"privacy-router","messages":[{"role":"user","content":"Say OK"}],"max_tokens":5}' \
        | python3 -c "import sys,json; d=json.load(sys.stdin); print(bool(d['choices'][0]['message']['content']))" 2>/dev/null)
    if [ "$chat_ok" = "True" ]; then
        log "  Chat Completions: OK"
    else
        err "  Chat Completions: FAILED"; return 1
    fi

    log "Smoke test: ALL PASSED"
}

# ── Test Runners ─────────────────────────────────────────────────────────────

run_openai_compat() {
    log "Running OpenAI compatibility tests..."
    mkdir -p "$RESULTS_DIR"
    cd "$PROJECT_DIR"

    PRIVACY_ROUTER_API_KEY="$TEST_RAW_KEY" \
    PRIVACY_ROUTER_URL="$API_URL" \
        python3 -m pytest tests/sanity/test_openai_compat.py -v --tb=short --no-header -q \
        2>&1 | tee "${RESULTS_DIR}/openai-compat.txt"

    local rc=${PIPESTATUS[0]}
    [ $rc -eq 0 ] && log "OpenAI compatibility: PASSED" || err "OpenAI compatibility: FAILED"
    return $rc
}

run_openresponses() {
    log "Running OpenResponses compliance tests..."

    if [ ! -d "$OPENRESPONSES_DIR" ]; then
        warn "Cloning OpenResponses..."
        git clone --depth 1 https://github.com/openresponses/openresponses.git "$OPENRESPONSES_DIR" 2>&1 | tail -3
    fi
    if [ ! -f "$BUN_BIN" ]; then
        warn "Installing bun..."
        curl -fsSL https://bun.sh/install | bash 2>&1 | tail -3
    fi

    export PATH="$(dirname "$BUN_BIN"):$PATH"
    cd "$OPENRESPONSES_DIR" && bun install --frozen 2>&1 | tail -3

    mkdir -p "$RESULTS_DIR"
    cd "$PROJECT_DIR"

    PRIVACY_ROUTER_API_KEY="$TEST_RAW_KEY" \
    PRIVACY_ROUTER_URL="$API_URL" \
        python3 -m pytest tests/sanity/test_openresponses.py -v --tb=short --no-header -q \
        2>&1 | tee "${RESULTS_DIR}/openresponses.txt"

    warn "OpenResponses: informational only (see results)"
    return 0
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
    local do_openai=false do_openresponses=false do_cleanup=false do_all=true

    for arg in "$@"; do
        case "$arg" in
            --openai)        do_openai=true;        do_all=false ;;
            --openresponses) do_openresponses=true;  do_all=false ;;
            --cleanup)       do_cleanup=true;        do_all=false ;;
            --help|-h) echo "Usage: $0 [--openai] [--openresponses] [--cleanup]"; exit 0 ;;
        esac
    done

    log "=== Privacy Router CI/CD Sanity Check ==="
    echo ""

    check_prerequisites
    ensure_services
    create_test_api_key
    trap cleanup_test_data EXIT

    if $do_cleanup; then cleanup_test_data; exit 0; fi

    local failed=0
    run_smoke_test || { err "Smoke test failed"; exit 1; }
    echo ""

    if $do_all || $do_openai; then
        run_openai_compat || failed=$((failed + 1))
        echo ""
    fi

    if $do_all || $do_openresponses; then
        run_openresponses
        echo ""
    fi

    log "=== Results ==="
    [ -d "$RESULTS_DIR" ] && { log "Results: ${RESULTS_DIR}/"; ls -la "$RESULTS_DIR/"; }

    if [ $failed -gt 0 ]; then
        err "=== $failed test suite(s) FAILED ==="; exit 1
    else
        log "=== All sanity checks PASSED ==="
    fi
}

main "$@"
