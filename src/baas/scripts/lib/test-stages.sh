source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
source "$(dirname "${BASH_SOURCE[0]}")/app-lifecycle.sh"

_merge_e2e_coverage() {
    if [[ -z "${COVERAGE_E2E_DIR:-}" || ! -d "$COVERAGE_E2E_DIR" ]]; then
        log_warn "COVERAGE_E2E_DIR not set or not found, skipping merge"
        return 0
    fi
    log_sub "E2E coverage summary"
    shopt -s nullglob
    local group_reports=("$COVERAGE_E2E_DIR"/*/.coverage)
    shopt -u nullglob
    if [[ ${#group_reports[@]} -eq 0 ]]; then
        log_warn "No group coverage reports found in $COVERAGE_E2E_DIR"
        return 0
    fi
    log_info "Found ${#group_reports[@]} group coverage reports"

    # Show per-group coverage percentage (total only — fast)
    log_info "Per-group coverage:"
    for report in "${group_reports[@]}"; do
        local group_dir=$(dirname "$report")
        local group_name=$(basename "$group_dir")
        local pct
        pct=$(COVERAGE_FILE="$report" uv run coverage report --format=total --ignore-errors 2>/dev/null | tail -1)
        log_info "  ${group_name}: ${pct}%  → file://${group_dir}/htmlcov/index.html"
    done

    # Merge all groups (--keep preserves per-group .coverage files)
    mkdir -p "$REPORT_DIR"
    COVERAGE_FILE="$REPORT_DIR/.coverage" uv run coverage combine --keep "${group_reports[@]}" || log_warn "Failed to combine coverage reports"
    COVERAGE_FILE="$REPORT_DIR/.coverage" uv run coverage html -i -d "$REPORT_DIR/htmlcov-e2e" >/dev/null 2>&1 || true
    COVERAGE_FILE="$REPORT_DIR/.coverage" uv run coverage xml -o "$REPORT_DIR/coverage-e2e.xml" >/dev/null 2>&1 || true
    COVERAGE_FILE="$REPORT_DIR/.coverage" uv run coverage json -o "$REPORT_DIR/coverage-e2e.json" >/dev/null 2>&1 || true

    # Show merged total and key paas files
    local merged_pct
    merged_pct=$(COVERAGE_FILE="$REPORT_DIR/.coverage" uv run coverage report --format=total --ignore-errors 2>/dev/null | tail -1)
    log_info "Merged E2E total: ${merged_pct}%"
    log_info "Reports: file://$REPORT_DIR/htmlcov-e2e/index.html"
    log_info "JSON:    $REPORT_DIR/coverage-e2e.json"

    # Show paas key files coverage (what we care about)
    COVERAGE_FILE="$REPORT_DIR/.coverage" uv run python -c "
import coverage, sys
cov = coverage.Coverage(data_file='$REPORT_DIR/.coverage')
cov.load()
results = []
for fp in cov.get_data().measured_files():
    short = fp.split('secbaas/community/')[-1] if 'secbaas/community/' in fp else fp
    # Skip test files, stubs, __init__.py, .pyx, protocols
    if '/tests/' in fp or '/spi/' in fp and '__init__' in fp:
        continue
    if fp.endswith('.pyx') or 'dependency_injector' in fp:
        continue
    # Skip stub/mock plugins — they exist only for test harness, not production code
    if '/stub/' in fp or '/mock/' in fp or '/real/' in fp:
        continue
    try:
        a = cov.analysis2(fp)
    except:
        continue
    s = set(a[1]) - set(a[2])
    m = set(a[3])
    total = len(s)
    if total == 0:
        continue
    cov_lines = total - len(m)
    pct = 100 * cov_lines / total
    if pct < 90:
        results.append((pct, cov_lines, total, short))
results.sort()
for pct, cov_lines, total, short in results:
    print(f'  {pct:5.1f}% ({cov_lines:>3}/{total:<3}) {short}')
print(f'\\n  Total sub-90% files: {len(results)}')
" 2>/dev/null
}

run_arch_tests() {
    log_stage
    echo "[ARCH] test-arch: architecture enforcement tests"
    mkdir -p "$REPORT_DIR"
    _run_pytest uv run pytest tests/architecture/ -v --junitxml="$REPORT_DIR/arch.xml" --color=yes
    local rc=$?
    if [[ $rc -ne 0 ]]; then log_error "test-arch failed"; fi
    return $rc
}

run_unit_tests() {
    log_stage
    echo "[UNIT] test-ut: unit tests"
    mkdir -p "$REPORT_DIR"
    _run_pytest uv run pytest tests/ \
        -m "not integration and not e2e" \
        --ignore=tests/architecture -v \
        --junitxml="$REPORT_DIR/ut.xml" \
        --cov=src/secbaas \
        --cov-report=xml:"$REPORT_DIR/coverage.xml" \
        --cov-report=html:"$REPORT_DIR/html" \
        --color=yes
    local rc=$?
    if [[ $rc -ne 0 ]]; then log_error "test-ut failed"; fi
    return $rc
}

run_integration_tests() {
    log_stage
    echo "[INTEGRATION] test-it: integration tests"
    mkdir -p "$REPORT_DIR"
    _run_pytest uv run pytest tests/integration/ -v -m integration \
        --junitxml="$REPORT_DIR/it.xml" \
        --cov=src/secbaas --cov-append \
        --cov-report=xml:"$REPORT_DIR/coverage.xml" \
        --cov-report=html:"$REPORT_DIR/html" \
        --color=yes
    local rc=$?
    if [[ $rc -ne 0 ]]; then log_error "test-it failed"; fi
    return $rc
}

run_ci_tests() {
    log_stage
    echo "[CI] test-ci: arch + unit (exclude e2e)"
    mkdir -p "$REPORT_DIR"
    _run_pytest uv run pytest tests/ \
        -m "not e2e" \
        -v \
        --junitxml="$REPORT_DIR/TEST-unit.xml" \
        --cov=src/secbaas \
        --cov-report=xml:"$REPORT_DIR/TEST-cov.xml" \
        --cov-report=html:"$REPORT_DIR/html" \
        --color=yes
    local rc=$?
    _clean_skipped_from_report "$REPORT_DIR/TEST-unit.xml"
    if [[ $rc -ne 0 ]]; then log_error "test-ci failed"; fi
    return $rc
}

run_e2e_baseline() {
    local mode="${1:-${_BAAS_MODE:-bare}}"
    local overlay="${2:-${_BAAS_OVERLAY:-e2e-sqlite}}"
    log_sub "E2E Baseline tests"
    mkdir -p "$REPORT_DIR"
    export _BAAS_MODE="$mode"
    export SESSION_LABEL="baseline"

    _start_app "$overlay"

    _run_pytest uv run pytest tests/e2e/baseline/ -v --durations=0 --log-cli-level=INFO \
        --tb=short -m "e2e and baseline" \
        --junitxml="$REPORT_DIR/e2e-baseline.xml" --color=yes
    local rc=$?

    _stop_app
    return $rc
}

run_one_e2e_test() {
    local test="$1"

    # If given just a filename (no directory separators), search for it under tests/
    if [[ "$test" != */* ]]; then
        local resolved
        resolved=$(find tests/ -name "$test" -type f 2>/dev/null | head -1)
        if [[ -n "$resolved" ]]; then
            test="$resolved"
            log_info "Resolved to: $test"
        else
            log_error "Could not find test file: $test"
            return 1
        fi
    fi

    log_sub "E2E single test: $test"
    mkdir -p "$REPORT_DIR"
    _run_pytest uv run pytest "$test" -v --durations=0 --log-cli-level=INFO \
        --tb=short -m "e2e" --color=yes
}




run_testclient_tests() {
    log_stage
    echo "[TESTCLIENT] test-testclient: in-process ASGI tests"
    mkdir -p "$REPORT_DIR"

    # TestClient does not need a running app — it runs against the ASGI app
    # in the same process using ASGITransport. The bootstrap_init fixture
    # initializes the full DI container with it-sqlite overlay.
    _run_pytest uv run pytest tests/testclient/ -v --durations=0 --log-cli-level=INFO \
        --tb=short \
        --cov=src/secbaas \
        --cov-report=xml:"$REPORT_DIR/coverage-testclient.xml" \
        --cov-report=html:"$REPORT_DIR/htmlcov-testclient" \
        --junitxml="$REPORT_DIR/testclient.xml" --color=yes
    local rc=$?
    if [[ $rc -ne 0 ]]; then log_error "test-testclient failed"; fi
    return $rc
}

run_e2e_tests() {
    local mode="${1:-${_BAAS_MODE:-bare}}"
    local overlay="${2:-${_BAAS_OVERLAY:-e2e-sqlite}}"
    log_stage
    echo "[E2E] test-e2e: end-to-end tests"
    mkdir -p "$REPORT_DIR"
    local ec=0

    rm -rf "$COVERAGE_E2E_DIR"

    run_e2e_baseline "$mode" "$overlay" || ec=$((ec + $?))

    run_testclient_tests || ec=$((ec + $?))

    _merge_e2e_coverage

    if [[ $ec -ne 0 ]]; then log_error "test-e2e: some sub-runs failed"; fi
    return $ec
}