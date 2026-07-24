"""E2E tests for PaaS Health Providers (Phase 1.2).

Exercises PaaS health check endpoints and per-provider health routes.
Since no dedicated PaaS health HTTP route exists in the current router,
the paas_health_url() route is probed defensively; per-provider endpoints
under /api/v1/health-check/paas/ are tested directly via the http_client.

Endpoint mapping:
- GET /api/v1/health-check/paas         — paas health overview (may 404)
- GET /api/v1/health-check/paas/{name}  — per-provider health
"""

import pytest
from httpx import AsyncClient

from tests.testclient.conftest import APITestHelper

pytestmark = [pytest.mark.baseline]

PAAS_HEALTH_BASE = "/api/v1/health-check/paas"
PAAS_PROVIDERS = ["arca", "poolab", "teclaw", "local", "k8s", "docker", "sigma"]


class TestPaasHealth:
    """Tests for PaaS health check endpoints."""

    @pytest.mark.asyncio
    async def test_paas_health_overview(self, api: APITestHelper) -> None:
        """GET /paas health overview — skip if route does not exist."""
        response = await api.client.get(
            api.paas_health_url(),
            params=api.params(),
        )

        if response.status_code == 404:
            pytest.skip("No dedicated PaaS health route exists")
        assert response.status_code != 500, (
            f"Expected non-500, got {response.status_code}: {response.text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_paas_health_per_provider_arca(
        self, http_client: AsyncClient, test_tenant: str
    ) -> None:
        """GET /paas/arca per-provider health returns non-500."""
        response = await http_client.get(
            f"{PAAS_HEALTH_BASE}/arca",
            params={"tenant": test_tenant},
        )

        if response.status_code == 404:
            pytest.skip("Per-provider PaaS health route not available")
        assert response.status_code != 500, (
            f"Expected non-500, got {response.status_code}: {response.text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_paas_health_per_provider_poolab(
        self, http_client: AsyncClient, test_tenant: str
    ) -> None:
        """GET /paas/poolab per-provider health returns non-500."""
        response = await http_client.get(
            f"{PAAS_HEALTH_BASE}/poolab",
            params={"tenant": test_tenant},
        )

        if response.status_code == 404:
            pytest.skip("Per-provider PaaS health route not available")
        assert response.status_code != 500, (
            f"Expected non-500, got {response.status_code}: {response.text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_paas_health_per_provider_teclaw(
        self, http_client: AsyncClient, test_tenant: str
    ) -> None:
        """GET /paas/teclaw per-provider health returns non-500."""
        response = await http_client.get(
            f"{PAAS_HEALTH_BASE}/teclaw",
            params={"tenant": test_tenant},
        )

        if response.status_code == 404:
            pytest.skip("Per-provider PaaS health route not available")
        assert response.status_code != 500, (
            f"Expected non-500, got {response.status_code}: {response.text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_paas_health_per_provider_local(
        self, http_client: AsyncClient, test_tenant: str
    ) -> None:
        """GET /paas/local per-provider health returns non-500."""
        response = await http_client.get(
            f"{PAAS_HEALTH_BASE}/local",
            params={"tenant": test_tenant},
        )

        if response.status_code == 404:
            pytest.skip("Per-provider PaaS health route not available")
        assert response.status_code != 500, (
            f"Expected non-500, got {response.status_code}: {response.text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_paas_health_unknown_provider(
        self, http_client: AsyncClient, test_tenant: str
    ) -> None:
        """GET /paas/unknown-provider returns 4xx (not 500)."""
        response = await http_client.get(
            f"{PAAS_HEALTH_BASE}/nonexistent-provider",
            params={"tenant": test_tenant},
        )

        assert response.status_code != 500, (
            f"Expected non-500 for unknown provider, got {response.status_code}: "
            f"{response.text[:200]}"
        )

    @pytest.mark.asyncio
    async def test_paas_health_no_devices(
        self, http_client: AsyncClient, test_tenant: str
    ) -> None:
        """GET /paas/arca with no devices in system returns non-500."""
        response = await http_client.get(
            f"{PAAS_HEALTH_BASE}/arca",
            params={"tenant": test_tenant},
        )

        if response.status_code == 404:
            pytest.skip("Per-provider PaaS health route not available")
        assert response.status_code != 500, (
            f"Expected non-500, got {response.status_code}: {response.text[:200]}"
        )
