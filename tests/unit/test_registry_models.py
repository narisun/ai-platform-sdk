"""Unit tests for platform_sdk.registry models + exceptions."""
import pytest

pytestmark = pytest.mark.unit


def test_registry_entry_round_trip():
    from platform_sdk.registry import RegistryEntry
    payload = {
        "name": "ai-mcp-data",
        "url": "http://data-mcp:8080",
        "expected_url": "http://data-mcp:8080",
        "type": "mcp",
        "state": "registered",
        "version": "0.5.0",
        "metadata": {"owner": "data-team"},
        "last_heartbeat_at": "2026-04-30T12:00:00Z",
        "registered_at": "2026-04-30T11:55:00Z",
        "last_changed_at": "2026-04-30T12:00:00Z",
    }
    entry = RegistryEntry.model_validate(payload)
    assert entry.name == "ai-mcp-data"
    assert entry.type == "mcp"
    assert entry.state == "registered"
    # Round-trip should produce equivalent JSON
    again = RegistryEntry.model_validate(entry.model_dump(mode="json"))
    assert again == entry


def test_registry_entry_rejects_invalid_type():
    from platform_sdk.registry import RegistryEntry
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        RegistryEntry.model_validate({
            "name": "x", "type": "INVALID", "state": "registered",
            "url": None, "expected_url": None, "version": None,
            "last_heartbeat_at": None, "registered_at": None,
            "last_changed_at": "2026-04-30T12:00:00Z",
        })


def test_registry_entry_healthy_property():
    from platform_sdk.registry import RegistryEntry
    e = RegistryEntry.model_validate({
        "name": "x", "url": "http://x", "expected_url": None,
        "type": "mcp", "state": "registered", "version": None,
        "metadata": {}, "last_heartbeat_at": "2026-04-30T12:00:00Z",
        "registered_at": "2026-04-30T11:00:00Z",
        "last_changed_at": "2026-04-30T12:00:00Z",
    })
    assert e.healthy is True
    e2 = e.model_copy(update={"state": "stale"})
    assert e2.healthy is False
    e3 = e.model_copy(update={"state": "expected_unregistered"})
    assert e3.healthy is False


def test_registration_request_minimal():
    from platform_sdk.registry import RegistrationRequest
    req = RegistrationRequest.model_validate({
        "name": "ai-agent-analytics",
        "url": "http://analytics-agent:8000",
        "type": "agent",
    })
    assert req.version is None
    assert req.metadata == {}


def test_exceptions_importable():
    from platform_sdk.registry import RegistryUnreachable, ServiceNotFound
    err = RegistryUnreachable("network blew up")
    assert "blew up" in str(err)
    err2 = ServiceNotFound("ai-mcp-data")
    assert "ai-mcp-data" in str(err2)
