"""Application logging configuration and access log filters.

Provides custom log filters and Gunicorn logger classes to divert static asset
(JavaScript and CSS) HTTP access logs to DEBUG level.
"""

import logging
import os
import re
import traceback
from typing import Any, Optional
from flask import Flask

try:
    from gunicorn.glogging import Logger as BaseGunicornLogger
except ImportError:  # pragma: no cover
    BaseGunicornLogger = object  # type: ignore

STATIC_ACCESS_PATTERN = re.compile(
    r"\b(?:GET|HEAD|OPTIONS|POST|PUT|DELETE|PATCH)\s+[^\"\s\?]+\.(?:js|css)(?:\?[^\s\"]*)?\s+HTTP",
    re.IGNORECASE,
)


class StaticAccessLogFilter(logging.Filter):
    """Filter that diverts JavaScript (.js) and CSS (.css) access logs to DEBUG level."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Inspect the log record and downgrade static asset access logs to DEBUG."""
        try:
            message = record.getMessage()
        except Exception:
            return True

        if STATIC_ACCESS_PATTERN.search(message):
            record.levelno = logging.DEBUG
            record.levelname = "DEBUG"
        return True


class GunicornLogger(BaseGunicornLogger):
    """Custom Gunicorn logger that routes JS and CSS access logs to DEBUG level."""

    def setup(self, cfg: Any) -> None:
        """Configure log levels, handlers, and filters for Gunicorn loggers."""
        super().setup(cfg)
        static_filter = StaticAccessLogFilter()

        if self.loglevel <= logging.DEBUG:
            self.access_log.setLevel(logging.DEBUG)

        self.access_log.addFilter(static_filter)
        for handler in self.access_log.handlers:
            if self.loglevel <= logging.DEBUG:
                handler.setLevel(logging.DEBUG)
            handler.addFilter(static_filter)

    def access(self, resp: Any, req: Any, environ: dict, request_time: Any) -> None:
        """Log an HTTP request, diverting static JS and CSS asset requests to DEBUG."""
        if not self.access_log_enabled:
            return

        try:
            safe_atoms = self.atoms_wrapper_class(
                self.atoms(resp, req, environ, request_time)
            )
            raw_path = (
                environ.get("PATH_INFO", "")
                or (getattr(req, "path", None) or "")
                or environ.get("RAW_URI", "")
            )
            path_clean = raw_path.split("?")[0].split("#")[0].lower().strip()
            if path_clean.endswith((".js", ".css")):
                self.access_log.debug(self.cfg.access_log_format, safe_atoms)
            else:
                self.access_log.info(self.cfg.access_log_format, safe_atoms)
        except Exception:
            self.error(traceback.format_exc())


def configure_logging(app: Optional[Flask] = None) -> None:
    """Configure system logging level, format, and static access log filtering."""
    log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper().strip()
    log_level_map = {
        "TRACE": logging.DEBUG,
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "NOTICE": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "FATAL": logging.CRITICAL,
        "CRITICAL": logging.CRITICAL,
    }
    level = log_level_map.get(log_level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        force=True,
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    static_filter = StaticAccessLogFilter()
    root_logger.addFilter(static_filter)
    for handler in root_logger.handlers:
        handler.addFilter(static_filter)
        if level <= logging.DEBUG:
            handler.setLevel(level)

    # Configure Werkzeug development access logger
    werkzeug_logger = logging.getLogger("werkzeug")
    werkzeug_logger.setLevel(level)
    werkzeug_logger.addFilter(static_filter)
    for handler in werkzeug_logger.handlers:
        handler.addFilter(static_filter)
        if level <= logging.DEBUG:
            handler.setLevel(level)

    # Configure Gunicorn access logger if present
    gunicorn_access_logger = logging.getLogger("gunicorn.access")
    if level <= logging.DEBUG:
        gunicorn_access_logger.setLevel(logging.DEBUG)
    gunicorn_access_logger.addFilter(static_filter)
    for handler in gunicorn_access_logger.handlers:
        handler.addFilter(static_filter)
        if level <= logging.DEBUG:
            handler.setLevel(level)
