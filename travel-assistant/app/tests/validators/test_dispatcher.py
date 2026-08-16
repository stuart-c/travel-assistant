"""Unit tests for service credentials dispatcher."""

from unittest.mock import MagicMock, patch

from app.validators import validate_service_credentials


def test_validate_service_credentials_dispatcher() -> None:
    """Test service credentials dispatcher for canonical services and unrecognised keys."""
    with patch("app.validators.dispatcher.BodsClient") as mock_bus_cls:
        mock_instance = MagicMock()
        mock_instance.validate_tuple.return_value = (True, "bus ok")
        mock_bus_cls.return_value = mock_instance

        valid, msg, extra = validate_service_credentials("bus", {"bus_api_key": "k"})
        assert valid
        assert msg == "bus ok"
        assert extra == {}

    with patch("app.validators.dispatcher.TrainS3Client") as mock_s3_cls:
        mock_instance = MagicMock()
        mock_instance.validate_tuple.return_value = (True, "s3 ok")
        mock_s3_cls.return_value = mock_instance

        valid, msg, extra = validate_service_credentials(
            "train_s3", {"train_s3_bucket": "b"}
        )
        assert valid
        assert msg == "s3 ok"
        assert extra == {}

    with patch("app.validators.dispatcher.TrainLiveClient") as mock_live_cls:
        mock_instance = MagicMock()
        mock_instance.validate_tuple.return_value = (True, "live ok")
        mock_live_cls.return_value = mock_instance

        valid, msg, extra = validate_service_credentials(
            "train_live", {"train_live_api_key": "k"}
        )
        assert valid
        assert msg == "live ok"
        assert extra == {}

    with patch("app.validators.dispatcher.OpenAIClient") as mock_openai_cls:
        mock_instance = MagicMock()
        mock_instance.validate_tuple.return_value = (
            True,
            "openai ok",
            ["gpt-4o-mini", "gpt-4o"],
        )
        mock_openai_cls.return_value = mock_instance

        valid, msg, extra = validate_service_credentials(
            "open_api", {"open_api_key": "k"}
        )
        assert valid
        assert msg == "openai ok"
        assert extra == {"models": ["gpt-4o-mini", "gpt-4o"]}

    with patch("app.validators.dispatcher.GoogleMapsClient") as mock_maps_cls:
        mock_instance = MagicMock()
        mock_instance.validate_tuple.return_value = (True, "maps ok")
        mock_maps_cls.return_value = mock_instance

        valid, msg, extra = validate_service_credentials(
            "google_maps", {"google_maps_api_key": "k", "google_maps_region": "uk"}
        )
        assert valid
        assert msg == "maps ok"
        assert extra == {}

    for unknown_key in [
        "unknown_service_xyz",
        "train-s3",
        "s3",
        "train-live",
        "ldbws",
        "open-api",
        "openai",
        "googlemaps",
        "google",
        "maps",
    ]:
        valid, msg, extra = validate_service_credentials(unknown_key, {})
        assert not valid
        assert "Unknown service" in msg
        assert extra == {}
