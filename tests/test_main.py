# tests/test_main.py
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.security import AUTH_BYPASS

# Mark all tests in this file as async
pytestmark = pytest.mark.asyncio


async def test_health_check():
    """
    Tests the public health check endpoint.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_unauthorized_access():
    """
    Tests that protected endpoints require authentication — unless AUTH_BYPASS
    is enabled (the local dev default), in which case every request is treated
    as the dev user and access is allowed instead.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/test")
    assert response.status_code == (200 if AUTH_BYPASS else 401)


# Additional tests would include:
# - Database integration tests
# - Authorization engine tests
# - API endpoint tests with mocked authentication
# - Model validation tests
