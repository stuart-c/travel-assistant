"""BODS (Bus Open Data Service) datasource package.

Provides client API interactions and TransXChange timetable XML parsing.
"""

from __future__ import annotations

import requests

from app.datasources.bods.client import (
    DEFAULT_BODS_BASE_URL,
    BodsClient,
)
from app.datasources.bods.operating_profile import (
    _clean_tag,
    _parse_operating_profile,
    parse_operating_profile,
)
from app.datasources.bods.sequence_aligner import (
    _align_subsequence,
    _align_times_to_master,
    _merge_stop_sequences,
    align_subsequence,
    align_times_to_master,
    can_merge_corridor,
    merge_stop_sequences,
)
from app.datasources.bods.transxchange_parser import (
    parse_transxchange_dataset,
    parse_transxchange_xml,
)

__all__ = [
    "DEFAULT_BODS_BASE_URL",
    "BodsClient",
    "parse_operating_profile",
    "_parse_operating_profile",
    "_clean_tag",
    "merge_stop_sequences",
    "_merge_stop_sequences",
    "align_times_to_master",
    "_align_times_to_master",
    "align_subsequence",
    "_align_subsequence",
    "can_merge_corridor",
    "parse_transxchange_xml",
    "parse_transxchange_dataset",
    "requests",
]
