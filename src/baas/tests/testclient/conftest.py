"""TestClient conftest — in-process ASGI transport for E2E migration.

Uses ``httpx.AsyncClient(transport=ASGITransport(app=app))`` so existing
``async def test_*`` functions work without any test-body changes.
The ``bootstrap_init`` session fixture (loaded by the root ``conftest.py``)
pre-wires the full ``ApplicationContainer`` with ``it-sqlite`` overlay and
replaces the FastAPI lifespan with a noop.

``dependency_overrides`` are supported via ``iter_api_routes()`` to extract
the actual ``Provide[...].call`` objects. See the unit tests under
``tests/unit/adapters/web/`` for the canonical pattern.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

if TYPE_CHECKING:
    from secbaas.community.bootstrap import ApplicationContainer

# ── Transport fixture ─────────────────────────────────────────────────────

DEFAULT_TIMEOUT = 120.0
ASYNC_POLL_TIMEOUT = 0.5
TEST_TENANT = "team_claw"
"""Tenant used by TestClient tests. Matches the seed data inserted
by the stub SQLite ORM plugin (see ``_seed.py``)."""
TEST_ENV = "local"

# Template UUIDs — seeded by _seed.py with SOFAPY_CONFIG_OVERLAY=it-sqlite
TEMPLATE_ARCA = "TEMPLATE-4d0e2849d7004111836333de782b95d8"
TEMPLATE_LOCAL = "TEMPLATE-f996ecc77d224ef7bd80757d8d2bcd0d"
TEMPLATE_POOLAB = "TEMPLATE-54942a40aa794eaaae2be166f94890ed"
TEMPLATE_TECLAW = "TEMPLATE-3106e731ffb04e0285e27c387e153737"
TEMPLATE_K8S = "TEMPLATE-8e4a2a3b4c5d4e6f7a8b9c0d1e2f3a4b"
TEMPLATE_DOCKER = "TEMPLATE-9f5b3c4d5e6f7a8b9c0d1e2f3a4b5c6d"
TEMPLATE_SIGMA = "TEMPLATE-a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
DEFAULT_TEMPLATE_UUID = TEMPLATE_ARCA


@pytest.fixture(scope="session")
def _testclient_app():
    """Import the pre-wired app after ``bootstrap_init`` has run.

    ``bootstrap_init`` (session-scoped, loaded by root ``conftest.py``)
    mutates the module-level ``app`` object before this fixture is called.
    """
    from secbaas.community.adapters.web.app import app

    return app


@pytest_asyncio.fixture(scope="function")
async def http_client(
    bootstrap_init: ApplicationContainer,  # noqa: ARG001 — triggers fixture
    _testclient_app,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP client backed by in-process ASGI transport.

    Replaces the E2E conftest's ``httpx.AsyncClient(base_url=localhost:8888)``
    with an ASGI-backed client. Test function bodies remain identical.
    """
    transport = ASGITransport(app=_testclient_app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        timeout=DEFAULT_TIMEOUT,
        follow_redirects=True,
    ) as client:
        yield client


# ── Reused E2E helpers (identical API surface) ─────────────────────────────

@pytest.fixture(scope="session")
def test_tenant() -> str:
    return TEST_TENANT


@pytest.fixture(scope="session")
def test_template_uuid() -> str:
    return DEFAULT_TEMPLATE_UUID


@pytest.fixture
def unique_id() -> str:
    return uuid4().hex[:16]


@pytest.fixture
def unique_request_id(unique_id: str) -> str:
    return uuid4().hex


@pytest.fixture
def unique_bot_name(unique_id: str) -> str:
    return f"tc-test-{unique_id}"


@pytest.fixture
def created_bot_uuids() -> list[str]:
    return []


@pytest.fixture
def created_publish_ids() -> list[int]:
    return []


# ── Import the full APITestHelper from the E2E conftest ───────────────────
# We reuse the same class to avoid duplicating 100+ URL builders.

from tests.e2e.conftest import (  # noqa: E402
    APITestHelper,
    activate_test_bot,
    call_device_callback,
    cleanup_bot,
    create_paas_device,
    create_test_bot,
    destroy_paas_device,
    find_existing_bot,
    set_mock_paas_failure,
)

from tests.e2e.hook_helpers import (  # noqa: E402
    activate_bot,
    approve_and_complete,
    approve_publish,
    assert_result_message_has_hook_data,
    create_and_activate_bot,
    create_hook_bot,
    get_devices_from_progress,
    get_publish_status,
    get_running_batch_devices,
    send_callbacks_for_hook_devices,
    wait_for_publish_status,
)


@pytest.fixture
def api(http_client: httpx.AsyncClient, test_tenant: str) -> APITestHelper:
    return APITestHelper(http_client, test_tenant)


@pytest.fixture
def mock_paas_env() -> dict[str, str]:
    return {}


# ── Bot lifecycle fixtures ─────────────────────────────────────────────────

@pytest_asyncio.fixture
async def created_bot(
    api: APITestHelper,
    unique_bot_name: str,
    created_bot_uuids: list[str],
) -> dict[str, Any]:
    """Create and activate a test bot, with cleanup on teardown."""
    bot = await create_test_bot(api, unique_bot_name, template_uuid=DEFAULT_TEMPLATE_UUID)
    created_bot_uuids.append(bot["bot_uuid"])
    await activate_test_bot(api, bot)
    yield bot
    await cleanup_bot(api, bot["bot_uuid"])


@pytest_asyncio.fixture
async def created_paas_device(
    api: APITestHelper,
    unique_id: str,
) -> dict[str, Any]:
    """Create a PaaS device via facade and return device info, with teardown cleanup."""
    device = await create_paas_device(api, unique_id)
    yield device
    # Cleanup: destroy the device
    try:
        await destroy_paas_device(api, device["paas_device_id"])
    except Exception:
        pass  # Best-effort cleanup


# ── dependency_overrides helper ────────────────────────────────────────────

def override_dependency(app, dep_name: str, factory):
    """Override a ``Depends(Provide[Container.x])`` dependency by name.

    Extracts the actual ``Provide[...].call`` object from the app's route
    tree and registers it in ``app.dependency_overrides``.

    Returns the ``dep.call`` key so the caller can restore/remove it later.

    Usage::

        dep_key = override_dependency(app, "service", lambda: mock_service)
        yield mock_service
        del app.dependency_overrides[dep_key]
    """
    from tests.unit.adapters.web.conftest import iter_api_routes

    for route in iter_api_routes(app):
        for dep in route.dependant.dependencies:
            if dep.name == dep_name:
                app.dependency_overrides[dep.call] = factory
                return dep.call
    raise RuntimeError(
        f"Dependency '{dep_name}' not found in app routes. "
        f"Available names: check route tree."
    )


# ── Logging configuration ────────────────────────────────────────────────


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    handler = config.pluginmanager.get_plugin("logging-plugin")
    if handler is None:
        return
    cli_handler = getattr(handler, "handler", None)
    if cli_handler is None:
        return
    fmt = "%(asctime)s %(levelname)s %(name)s:%(message)s"
    cli_handler.setFormatter(logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S"))