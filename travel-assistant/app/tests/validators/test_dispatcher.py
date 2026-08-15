"""Unit tests for service credentials dispatcher."""

from unittest.mock import patch

from app.validators import validate_service_credentials


def test_validate_service_credentials_dispatcher() -> None:
    """Test service credentials dispatcher for all services and unknown service."""
    with patch("app.validators.dispatcher.validate_bus_api_key") as mock_bus:
        mock_bus.return_value = (True, "bus ok")
        valid, msg, extra = validate_service_credentials("bus", {"bus_api_key": "k"})
        assert valid
        assert msg == "bus ok"
        assert extra == {}

    with patch("app.validators.dispatcher.validate_train_s3_bucket") as mock_s3:
        mock_s3.return_value = (True, "s3 ok")
        valid, msg, extra = validate_service_credentials(
            "train_s3", {"train_s3_bucket": "b"}
        )
        assert valid
        assert msg == "s3 ok"
        assert extra == {}

        valid, msg, extra = validate_service_credentials(
            "train-s3", {"train_s3_bucket": "b"}
        )
        assert valid
        assert msg == "s3 ok"
        assert extra == {}

    with patch("app.validators.dispatcher.validate_train_live_token") as mock_live:
        mock_live.return_value = (True, "live ok")
        valid, msg, extra = validate_service_credentials(
            "train_live", {"train_live_api_key": "k"}
        )
        assert valid
        assert msg == "live ok"
        assert extra == {}

        valid, msg, extra = validate_service_credentials(
            "ldbws", {"train_live_api_key": "k"}
        )
        assert valid
        assert msg == "live ok"
        assert extra == {}

    with patch("app.validators.dispatcher.validate_open_api_key") as mock_openai:
        mock_openai.return_value = (True, "openai ok", ["gpt-4o-mini", "gpt-4o"])
        valid, msg, extra = validate_service_credentials(
            "open_api", {"open_api_key": "k"}
        )
        assert valid
        assert msg == "openai ok"
        assert extra == {"models": ["gpt-4o-mini", "gpt-4o"]}

        valid, msg, extra = validate_service_credentials(
            "openai", {"open_api_key": "k"}
        )
        assert valid
        assert msg == "openai ok"
        assert extra == {"models": ["gpt-4o-mini", "gpt-4o"]}

    with patch("app.validators.dispatcher.validate_google_maps_api_key") as mock_maps:
        mock_maps.return_value = (True, "maps ok")
        valid, msg, extra = validate_service_credentials(
            "google_maps", {"google_maps_api_key": "k", "google_maps_region": "uk"}
        )
        assert valid
        assert msg == "maps ok"
        assert extra == {}

        valid, msg, extra = validate_service_credentials(
            "maps", {"google_maps_api_key": "k"}
        )
        assert valid
        assert msg == "maps ok"
        assert extra == {}

    valid, msg, extra = validate_service_credentials("unknown_service_xyz", {})
    assert not valid
    assert "Unknown service" in msg
    assert extra == {}
