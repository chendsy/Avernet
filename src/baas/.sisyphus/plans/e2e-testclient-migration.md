# E2E TestClient Migration Plan

## Goal

Migrate all E2E tests from `httpx.AsyncClient` (against a separate uvicorn process on `localhost:8888`) to `FastAPI TestClient` (ASGI in-process via `httpx.AsyncClient(transport=ASGITransport(app=app))`).

**Why**: Eliminate the ugly `nohup python main.py` + env var injection pattern. Gain full coverage traceability (coverage.py runs in-process). Reduce CI runtime from 15-20 min to 5-8 min. Clean DI-based mock injection instead of magic env vars.

**Key constraint**: Zero production code changes. All changes in test files and test infrastructure only.

## Architecture Decision

Use `httpx.AsyncClient(transport=ASGITransport(app=app))` — not raw `TestClient(app)`.

| Decision | Rationale |
|---|---|
| `ASGITransport` over `TestClient` | All 1,265 tests are `async def` with `await api.client.get()`. `ASGITransport` preserves the async API identically. Zero test function rewrites. |
| `bootstrap_init` fixture (session-scoped) | Already exists in `tests/integration/fixtures/bootstrap.py`. Creates one `ApplicationContainer` with `it-sqlite` overlay, replaces lifespan with noop, wires into `app`. |
| One container for all migrated tests | All TestClient tests share the session-scoped `bootstrap_init`. Per-module config differences use `app.dependency_overrides`. |
| `PAAS_MOCK_MODE` → `dependency_overrides` | The 23 hook test files that need PAAS_MOCK_MODE get mock `PaasServiceFactory` injected via `app.dependency_overrides` at the module level, not env vars. |

## What Changes vs. What Doesn't

### Changes (test infrastructure only)
- `tests/e2e/conftest.py`: Replace `http_client` fixture → `httpx.AsyncClient(transport=ASGITransport(app=app))` with `bootstrap_init` dependency
- New `tests/testclient/` directory (mirrors `tests/e2e/` structure)
- Per-module `app.dependency_overrides` for mock injection
- Remove `SOFAPY_CONFIG_OVERLAY=e2e-sqlite` + `nohup python main.py` from CI

### No Changes
- All test function bodies — `api.client.get()`, `api.client.post()`, assertion syntax unchanged
- `APITestHelper` class — same URL builders, same `params()` helper
- `find_existing_bot`, `create_test_bot`, `cleanup_bot` — same SQLite DB, same patterns
- All hooks helpers (`hook_helpers.py`) — polling loops work identically in-process

## Phase 0: Infrastructure (1 file, ~50 lines) **Week 1, Day 1**

**What**: Create the shared TestClient conftest that all subsequent phases depend on.

### Tasks
1. Create `tests/testclient/conftest.py`:
   - Load `bootstrap_init` from `tests.integration.fixtures.bootstrap` (already available via root `conftest.py`)
   - Create `api` fixture: instantiate `APITestHelper` with `httpx.AsyncClient(transport=ASGITransport(app=app))`
   - Reuse existing `APITestHelper`, `BotFactory.create_test_bot`, `find_existing_bot`, all cleanup helpers
   - Set `test_tenant = "team_claw_ew"` (matches e2e-sqlite/it-sqlite tenant in DB seed)
2. Create `tests/testclient/__init__.py`
3. Verify: `pytest --collect-only tests/testclient/` → "no tests" (expected — no test files yet)
4. Verify: `pytest -x tests/testclient/` → exit 5 (no tests, not failure)

**Success**: A single file that gives any test in `tests/testclient/` a working `api` fixture against the in-process app.

---

## Phase 1: health_check (4 files, 30 tests) **Week 1, Day 1-2**

**What**: First full test group migration. Establishes the pattern: copy → adjust imports → delete old → verify.

### Files to Migrate
| File | Tests | Migration Notes |
|---|---|---|
| `test_bot_health_service.py` | 7 | Read-only GET endpoints. Trivially migratable. |
| `test_bot_device_providers.py` | 7 | Uses `find_existing_bot` → `pytest.skip`. Same pattern works. |
| `test_sandbox_device_router.py` | 7 | Sandbox lookup endpoints. No resource creation. |
| `test_paas_health_providers.py` | 9 | PaaS overview/providers. No resource creation. |

### Tasks
1. Copy 4 files: `tests/e2e/health_check/*.py` → `tests/testclient/health_check/*.py`
2. Adjust imports: remove `tests.e2e.conftest` imports, use `tests.testclient.conftest` instead
3. Run `pytest tests/testclient/health_check/ -v`
4. Fix any failures caused by the in-process transport (unlikely — these are simple GET tests)
5. Verify tests pass: 23 pass, 7 skip (same as before)
6. Record baseline coverage for health check group

**Success**: 30 tests pass in `tests/testclient/health_check/` with identical results to httpx E2E.

---

## Phase 2: mock_paas_failure (9 files, 23 tests × 5 variants) **Week 1, Day 2-3**

**What**: Solve the `PAAS_MOCK_*` env var problem. This is the key architectural unlock — once solved, all hook tests can follow the same pattern.

### Current Problem
The 9 files are run 5 separate times with different env vars:
- `PAAS_MOCK_HOOK_FAILURE=true`
- `PAAS_MOCK_CREATE_FAILURE=true`
- `PAAS_MOCK_DESTROY_FAILURE=true`
- `PAAS_MOCK_DEVICE_NOT_FOUND=true`
- (standard mode — no extra var)

With TestClient, the container is session-scoped. Env vars set after `bootstrap_init` won't affect the running mock service.

### Solution: Module-Level Dependency Override
```python
# tests/testclient/mock_paas_failure/conftest.py
import pytest
from unittest.mock import Mock
from secbaas.community.adapters.web.app import app

@pytest.fixture(scope="module", autouse=True)
def inject_mock_paas_on_hook_failure():
    """Inject a MockPaasService that simulates hook execution failure."""
    from secbaas.community.core.service.paas._mock_paas_service import MockPaasService

    mock = MockPaasService()
    mock.execute_hook = Mock(side_effect=Exception("Mock hook failure"))

    # Override the PaasServiceFactory to return our mock
    # (exact DI path depends on container wiring — adjust)
    app.dependency_overrides[Provide[PaasServiceFactory]] = lambda: mock_factory(mock)
    yield
    app.dependency_overrides.clear()
```

Each variant gets its own conftest overriding a different mock behavior.

### Files to Migrate
| File | Tests |
|---|---|
| `test_create_device_failure.py` | 3 |
| `test_destroy_device_failure.py` | 4 |
| `test_destroy_device_not_found.py` | 3 |
| `test_hook_execution_failure.py` | 3 |
| `test_paas_facade_create_failure.py` | 2 |
| `test_paas_facade_destroy_failure.py` | 3 |
| `test_paas_facade_device_not_found.py` | 3 |
| `test_paas_facade_hook_failure.py` | 1 |
| `test_update_device_failure.py` | 1 |

### Tasks
1. Create `tests/testclient/mock_paas_failure/conftest.py` with 5 `module`-scoped fixtures, each overriding a different mock behavior
2. Create 5 pytest markers or 5 subdirectories, each loading the correct conftest override
3. Copy 9 test files → `tests/testclient/mock_paas_failure/`
4. Run each variant: `pytest tests/testclient/mock_paas_failure/ --variant=hook`
5. Verify all 23 tests × 5 variants pass
6. Remove env var injection from CI for mock_paas_failure

**Success**: 115 test runs pass without any process-level env var injection. Mock behavior controlled entirely by DI.

---

## Phase 3: bot_run_concurrency (2 files, 30 tests) **Week 1, Day 4**

**What**: Straightforward API tests — create bots concurrently, test pool exhaustion, rapid create-destroy. No special dependencies beyond SQLite.

### Files to Migrate
| File | Tests |
|---|---|
| `test_concurrency.py` | 10 |
| `test_worker.py` | 20 |

### Tasks
1. Copy 2 files → `tests/testclient/bot_run_concurrency/`
2. Run: `pytest tests/testclient/bot_run_concurrency/ -v`
3. Fix any race conditions from in-process execution (unlikely — these use `asyncio.gather` which works the same)
4. Verify resource cleanup between tests doesn't leak into other phases

**Success**: 30 tests pass, no state leakage.

---

## Phase 4: bot_run_lifecycle (4 files, 51 tests) **Week 1, Day 4-5**

**What**: Bot create → activate → session → error paths. Tests status transitions through the publish pipeline. Some tests reference WebSocket connection info endpoints.

### Files to Migrate
| File | Tests | Notes |
|---|---|---|
| `test_bot_start.py` | 13 | Create+verify bot, no hooks |
| `test_bot_runner.py` | 20 | WS info endpoints → test via HTTP only (same as current) |
| `test_bot_session.py` | 9 | Session CRUD, no hooks |
| `test_bot_run_errors.py` | 9 | Error paths via stub injection |

### Tasks
1. Copy 4 files → `tests/testclient/bot_run_lifecycle/`
2. Run: `pytest tests/testclient/bot_run_lifecycle/ -v`
3. Address `test_bot_run_errors.py` — may need `dependency_overrides` for `BAAS_STUB_BOT_BINDING_ERROR` / `BAAS_STUB_ENGINE_SESSION_ERROR` (these are checked at call-time in stub plugins, so `monkeypatch.setenv` should work without container rebuild — verify)
4. Run alongside Phase 3 to check cross-module resource isolation

**Success**: 51 tests pass. Bot lifecycle runs correctly in-process.

---

## Phase 5: paas_operations (6 files, 49 tests) **Week 1, Day 5**

**What**: PaaS device lifecycle for specific platforms (LOCAL, Docker/Standalone, TECLAW). Several `xfail` tests waiting for platform stub improvements.

### Files to Migrate
| File | Tests | Notes |
|---|---|---|
| `test_local_paas_create.py` | 5 | LOCAL platform device creation |
| `test_local_paas_errors.py` | 8 | LOCAL error paths |
| `test_local_paas_lifecycle.py` | 6 | Full create→info→command→destroy |
| `test_paas_facade.py` | 11 | Multi-platform facade dispatch |
| `test_standalone_paas.py` | 11 | Docker/Standalone platform |
| `test_teclaw_paas.py` | 8 | TECLAW platform |

### Tasks
1. Copy 6 files → `tests/testclient/paas_operations/`
2. Run: `pytest tests/testclient/paas_operations/ -v`
3. Preserve `xfail` markers — they document known stub limitations
4. Verify device cleanup works across test modules

**Success**: 49 tests pass (or xfail where expected). All PaaS platform stubs exercise correctly in-process.

---

## Baseline Split Strategy (~116 files, ~1,082 tests) → 6 sub-phases

The baseline is too big to migrate in one wave. Split by test category (from easiest to hardest):

### Phase 6a: READ-ONLY + VALIDATION (~35 files, ~300 tests) **Week 2, Day 1-2**

**Category**: Tests that never create/destroy resources. GET endpoints, validation, error format, health checks.

| Files | Tests |
|---|---|
| `test_validation.py`, `test_error_format.py`, `test_error_responses.py`, `test_invoke_errors.py`, `test_invoke_normal.py`, `test_api_models.py` | ~55 |
| `test_health_endpoints.py`, `test_health_errors.py`, `test_bot_health.py`, `test_paas_health.py`, `test_sandbox_health.py`, `test_internal_health.py` | ~25 |
| `test_health_checker_bot.py`, `test_health_checker_phase1_bot.py`, `test_health_checker_phase1_paas.py`, `test_health_checker_phase1_sandbox.py`, `test_health_checker_sandbox.py`, `test_bot_health_api.py` | ~60 |
| `test_device_edge.py`, `test_device_errors.py`, `test_device_normal.py`, `test_device_service_errors.py` | ~20 |
| `test_device_facade_config.py`, `test_device_template.py`, `test_device_template_api.py`, `test_device_template_status.py` | ~30 |
| `test_session_edge.py`, `test_session_errors.py`, `test_session_normal.py` | ~14 |
| `test_tenant_errors.py`, `test_tenant_config.py`, `test_tenant_isolation.py` | ~14 |
| `test_system_config_errors.py`, `test_system_config_api.py`, `test_system_config.py` | ~17 |
| `test_qpm_config.py`, `test_deploy_config.py`, `test_paas_config_overrides.py` | ~16 |
| `test_idempotency.py`, `test_cache_api.py`, `test_dispatchers.py`, `test_mock_operations.py` | ~14 |
| `README-ONLY misc`: `test_misc_api.py`, `test_misc_services.py`, `test_bootstrap.py`, `test_cm_initialization.py`, `test_repository_coverage.py` | ~18 |

**No PAAS_MOCK_MODE, no SSE, no WebSocket, no resource creation.** Trivially migratable.

### Phase 6b: CRUD (create/destroy resources) (~25 files, ~250 tests) **Week 2, Day 3-4**

**Category**: Tests that create bots, devices, tenants, API keys. Resource lifecycle with cleanup.

| Files | Tests |
|---|---|
| `test_bot_api.py`, `test_bot_operations.py`, `test_bot_start.py`, `test_bot_device_api.py`, `test_bot_service_routers.py` | ~100 |
| `test_device_api.py`, `test_device_start_hooks.py`, `test_sandbox_device_api.py` | ~20 |
| `test_tenant_api.py` | ~5 |
| `test_publish_api.py`, `test_publish_batch.py`, `test_publish_no_devices.py`, `test_publish_records.py` | ~45 |
| `test_publish_admin.py`, `test_publish_approval.py` | ~18 |
| `test_admin_force_success.py`, `test_admin_router.py` | ~35 |
| `test_start_progress_errors.py`, `test_re_upgrade_after_failure.py`, `test_restart_device_failure.py` | ~10 |
| `test_relay_session.py`, `test_http_relay.py` | ~15 |

**No PAAS_MOCK_MODE**, but create/destroy resources — needs `cleanup_bot`/`cleanup_paas_device` helpers reliable in-process.

### Phase 6c: ADMIN + CONFIG (~25 files, ~200 tests) **Week 2, Day 5**

| Files | Tests |
|---|---|
| `test_api_key_normal.py`, `test_api_key_errors.py`, `test_api_key_edge.py`, `test_api_key_grant_revoke.py`, `test_admin_api_keys.py` | ~80 |
| `test_api_gateway_admin.py` | ~22 |
| `test_internal_api.py`, `test_internal_routers.py` | ~12 |
| `test_coverage_gap.py`, `test_gap_closure.py` | ~65 |
| `test_device_facade_config.py`, `test_dispatchers.py`, `test_paas_platform_paths.py` (already counted in 6a — remainder here) | ~20 |

### Phase 6d: PAAS FACADE (~15 files, ~150 tests) **Week 3, Day 1-2**

| Files | Tests |
|---|---|
| `test_paas_facade_api.py`, `test_paas_facade_errors.py`, `test_paas_facade_extended.py`, `test_paas_facade_lifecycle.py`, `test_paas_facade_platforms.py` | ~70 |
| `test_local_paas.py`, `test_local_paas_api.py`, `test_arca_paas_extended.py`, `test_sigma_paas.py` | ~20 |
| `test_paas_services.py`, `test_paas_api.py`, `test_paas_platform_paths.py` | ~30 |
| `test_paas_config_overrides.py`, `test_paas_health.py` | ~10 |
| `test_open_api_dependencies.py` | ~13 |

### Phase 6e: HOOKS (~23 files, ~120 tests) **Week 3, Day 3-5**

**Category**: Hook callback simulation tests. Use `hook_helpers.py`. **Need PAAS_MOCK_MODE injection** (same pattern as Phase 2).

| Files | Tests | Notes |
|---|---|---|
| `test_async_device_hooks_for_create.py` | 8 | Per-test bot creation + hook polling |
| `test_async_device_hooks_for_destroy.py` | 4 | |
| `test_async_device_hooks_for_restart.py` | 12 | |
| `test_async_device_hooks_for_scale_down.py` | 4 | |
| `test_async_device_hooks_for_scale_up.py` | 6 | |
| `test_async_device_hooks_for_stop.py` | 6 | |
| `test_async_device_hooks_for_update.py` | 9 | |
| `test_async_device_hooks_for_update_device.py` | 3 | |
| `test_async_device_hooks_timeout.py` | 3 | |
| `test_async_device_hooks_edge_cases.py` | 3 | |
| `test_auto_approve_publish_create.py` | 8 | |
| `test_auto_approve_publish_destroy.py` | 1 | |
| `test_auto_approve_publish_restart.py` | 6 | |
| `test_auto_approve_publish_scale.py` | 4 | |
| `test_auto_approve_publish_stop.py` | 1 | |
| `test_auto_approve_publish_update.py` | 6 | |
| `test_auto_approve_publish_update_device.py` | 1 | |
| `test_admin_force_success.py` | 3 | |
| `test_publish_admin.py` | 9 | |
| `test_publish_approval.py` | 9 | |
| `test_re_upgrade_after_failure.py` | 2 | |
| `test_restart_device_failure.py` | 2 | |
| `test_bot_operations.py` (hook portions) | ~5 | Partial file |

**Requires**: Inject `MockPaasService` via `dependency_overrides` with `PAAS_MOCK_MODE` behavior. Hook polling loops (in `hook_helpers.py`) call `api.client.get()` / `api.client.post()` — these work identically with `ASGITransport`.

### Phase 6f: STREAMING + WEBSOCKET + BCN (~12 files, ~100 tests) **Week 4, Day 1-2**

**Category**: SSE streaming, WebSocket upgrade, BCN downlink. Most technically challenging.

| Files | Tests | Notes |
|---|---|---|
| `test_open_api_messages.py` | 18 | **SSE streaming** — uses `aiter_lines()` to consume event stream. `ASGITransport` supports this. |
| `test_open_api_runs.py` | 15 | May use streaming |
| `test_open_api_sessions.py` | 18 | May use streaming |
| `test_websocket_management.py` | 10 | **HTTP upgrade handshake only** (no bidirectional WS). `ASGITransport` handles this. |
| `test_bcn_downlink.py` | 28 | BCN endpoint tests |
| `test_bcn_downlink_extended.py` | 14 | BCN extended tests |
| `test_bot_device_api.py` (WS portions) | partial | WebSocket info endpoint |
| `test_bot_operations.py` (WS portions) | partial | WebSocket info endpoint |
| `test_cm_initialization.py` | 2 | Connection management |
| `test_paas_facade_api.py` (WS portions) | partial | WebSocket connections through PaaS |
| `test_paas_facade_lifecycle.py` (WS portions) | partial | |
| `test_paas_api.py` (WS portions) | partial | |
| `test_open_api_stub_adapter_boot.py` | 3 | **Already TestClient** — just move to `tests/testclient/` |

**Key concern**: SSE streaming with `ASGITransport`. The `test_open_api_messages.py` tests use `aiter_lines()` on an httpx streaming response. `ASGITransport` is documented to support streaming via `stream=True` → this should work. Need pilot verification.

---

## Phase 7: Reduce E2E Smoke Tests + Cleanup **Week 4, Day 3**

**What**: After all tests are migrated, keep a minimal set of process-based E2E tests that verify the app starts/stops correctly on a real port.

### Tasks
1. Select ~50 smoke tests (1-2 per endpoint family) that stay in `tests/e2e/`:
   - `/health` — app boots
   - `/api/v1/bots` — CRUD works end-to-end
   - `/api/v1/tenants` — tenant isolation
   - `/api/v1/openapi/v1/messages/stream` — SSE streaming works over TCP
   - `/ws/local/management` — WebSocket upgrade works
2. Delete or archive the remaining 1,200+ tests from `tests/e2e/baseline/`
3. Remove per-group `run_e2e_*` shell functions from `test-stages.sh` (keep only `run_e2e_smoke`)
4. Remove per-group Just targets from `justfiles/test-e2e.just` (keep only `test-e2e-smoke`)
5. Remove unused overlay configs
6. Run full suite: `pytest tests/testclient/` + `just test-e2e-smoke`

**Success**: ~1,200 TestClient tests run in 3-5 minutes. ~50 process-based smoke tests run in 2-3 minutes. Total: 5-8 minutes.

---

## Migration Pattern (Per-Phase Template)

For each phase, follow this exact template:

1. **Create directory**: `tests/testclient/{group}/` with `__init__.py`
2. **Copy conftest if needed**: Only for phases needing `dependency_overrides` (mock_paas_failure, hooks, streaming)
3. **Copy test files**: `tests/e2e/{group}/*.py` → `tests/testclient/{group}/*.py`
4. **Adjust imports**:
   - Old: `from tests.e2e.conftest import *` or implicit fixture injection
   - New: use `tests.testclient.conftest` fixtures (which wrap `bootstrap_init` + `ASGITransport`)
5. **Run**: `pytest tests/testclient/{group}/ -v`
6. **Fix failures**: Only fix test-assertion issues (status code, response body). Never change production code.
7. **Delete old**: Remove `tests/e2e/{group}/` after migration verified
8. **Update CI**: Remove `run_e2e_{group}` from `test-stages.sh`, remove Just target

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| SSE streaming doesn't work with ASGITransport | Medium | High (Phase 6f blocked) | Pilot `test_open_api_messages.py` early in Week 2. If blocked, keep SSE tests as process-based E2E. |
| Resource leak between TestClient modules | Medium | Medium | Run Phase 3+4+5 in sequence to detect cross-module state contamination. Add `cleanup_all_resources` fixture if needed. |
| APScheduler background tasks interfere | Low | Medium | `bootstrap_init` already starts cron tasks in integration tests — this is proven. Monitor for flaky tests. |
| `dependency_overrides` doesn't work for PaaS factory dispatch | Low | Medium | The factory is a `providers.Factory` in DI — verify `app.dependency_overrides` can override factories (not just singletons). Test in Phase 2. |
| `PAAS_MOCK_MODE` tests need per-module container state | Medium | Low | Module-scoped fixtures with `dependency_overrides` solve this. Pattern proven in Phase 2. |

## Timeline

| Week | Phase | Tests Migrated | Cumulative |
|---|---|---|---|
| 1, Day 1 | 0: Infrastructure | 0 | 0 |
| 1, Day 1-2 | 1: health_check | 30 | 30 |
| 1, Day 2-3 | 2: mock_paas_failure | 23 (×5 variants) | 53 |
| 1, Day 4 | 3: bot_run_concurrency | 30 | 83 |
| 1, Day 4-5 | 4: bot_run_lifecycle | 51 | 134 |
| 1, Day 5 | 5: paas_operations | 49 | 183 |
| 2, Day 1-2 | 6a: baseline read-only | ~300 | ~483 |
| 2, Day 3-4 | 6b: baseline CRUD | ~250 | ~733 |
| 2, Day 5 | 6c: baseline admin/config | ~200 | ~933 |
| 3, Day 1-2 | 6d: baseline PaaS | ~150 | ~1,083 |
| 3, Day 3-5 | 6e: baseline hooks | ~120 | ~1,203 |
| 4, Day 1-2 | 6f: baseline streaming | ~100 | ~1,303 |
| 4, Day 3 | 7: Smoke + cleanup | — | ~1,300 |

---

## Success Metrics

- [ ] All 1,250+ tests pass via `pytest tests/testclient/`
- [ ] ~50 smoke tests pass via `just test-e2e-smoke` (process-based)
- [ ] Zero production code changes
- [ ] CI runtime reduced from 15-20 min to 5-8 min
- [ ] No `nohup python main.py` in test pipeline
- [ ] No env var injection for mock behavior control
- [ ] Full coverage traceability for all migrated tests