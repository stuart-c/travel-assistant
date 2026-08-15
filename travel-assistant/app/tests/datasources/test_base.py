"""Unit tests for BaseDataSource and get_datasource factory."""

import pytest
from flask import Flask

from app.datasources import (
    BodsClient,
    DataSourceConfigError,
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


def test_get_datasource_unknown_service() -> None:
    """Test get_datasource raises DataSourceConfigError for unrecognized service key."""
    with pytest.raises(DataSourceConfigError) as exc_info:
        get_datasource("unknown_provider")
    assert "Unknown datasource service 'unknown_provider'" in str(exc_info.value)
