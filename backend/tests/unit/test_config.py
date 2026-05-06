"""Unit tests for application config."""

import pytest

from app.config import Settings


@pytest.mark.unit
def test_settings_defaults() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.app_env == "development"
    assert s.api_prefix == "/v1"
    assert s.jwt_algorithm == "HS256"


@pytest.mark.unit
def test_cors_origin_list_parsing() -> None:
    s = Settings(  # type: ignore[call-arg]
        _env_file=None,
        cors_origins="http://a.com, http://b.com,  http://c.com  ",
    )
    assert s.cors_origin_list == [
        "http://a.com",
        "http://b.com",
        "http://c.com",
    ]


@pytest.mark.unit
def test_cors_empty_origins() -> None:
    s = Settings(_env_file=None, cors_origins="")  # type: ignore[call-arg]
    assert s.cors_origin_list == []


@pytest.mark.unit
def test_is_production_flag() -> None:
    dev = Settings(_env_file=None, app_env="development")  # type: ignore[call-arg]
    prod = Settings(_env_file=None, app_env="production")  # type: ignore[call-arg]
    assert dev.is_production is False
    assert prod.is_production is True
