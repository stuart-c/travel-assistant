"""CLI runner for the Travel Assistant MCP service (python3 -m app.mcp)."""

import argparse
import logging
import os
import uvicorn

from app.db import init_db
from app.mcp.server import create_mcp_app

logger = logging.getLogger("app.mcp")


def main() -> None:
    """Entrypoint for running the MCP server standalone or in the add-on container."""
    parser = argparse.ArgumentParser(
        description="Travel Assistant Model Context Protocol (MCP) Server"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT", 8098)),
        help="Port to bind the MCP SSE server (default: 8098)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.environ.get("MCP_HOST", "0.0.0.0"),
        help="Host interface to bind (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=os.environ.get("MCP_API_TOKEN", ""),
        help="Optional Bearer token for client authentication",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=os.environ.get("LOG_LEVEL", "info").lower(),
        help="Logging verbosity level",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Ensure database tables and migrations are initialised
    init_db()

    logger.info(
        "Starting Travel Assistant MCP service on %s:%d (Auth: %s)...",
        args.host,
        args.port,
        "Enabled" if args.token else "Disabled (Open)",
    )

    app = create_mcp_app(api_token=args.token)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
