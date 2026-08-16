"""Unit tests for BaseDataSource and get_datasource factory."""

import pytest
from flask import Flask

from app.datasources import (
    BodsClient,
    DataSourceConfigError,
    GoogleMapsClient,
    NaptanClient,
    OpenAIClient,
    TrainLiveClient,
    TrainS3Client,
    get_datasource,
)


def test_get_datasource_factory_known_services(app: Flask) -> None:
    """Test get_datasource instantiates correct client for each service key."""
    with app.app_context():
        bods = get_datasource("bus")
        assert isinstance(bods, BodsClient)

        s3 = get_datasource("train_s3")
        assert isinstance(s3, TrainS3Client)

        live = get_datasource("train_live")
        assert isinstance(live, TrainLiveClient)

        openai = get_datasource("open_api")
        assert isinstance(openai, OpenAIClient)

        naptan = get_datasource("naptan")
        assert isinstance(naptan, NaptanClient)

        maps_client = get_datasource("google_maps")
        assert isinstance(maps_client, GoogleMapsClient)


def test_get_datasource_unknown_service() -> None:
    """Test get_datasource raises DataSourceConfigError for unrecognised service key or alias."""
    for unknown_key in [
        "unknown_provider",
        "bods",
        "s3",
        "darwin",
        "openai",
        "ha",
        "googlemaps",
        "maps",
    ]:
        with pytest.raises(DataSourceConfigError) as exc_info:
            get_datasource(unknown_key)
        assert f"Unknown datasource service '{unknown_key}'" in str(exc_info.value)
