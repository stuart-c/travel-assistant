import asyncio
import json
from typing import Generator
from unittest.mock import patch
import pytest
from flask import Flask
from flask.testing import FlaskClient
from starlette.applications import Starlette
from starlette.responses import Response
from starlette.routing import Route
from starlette.testclient import TestClient
from app.mcp.auth import BearerAuthMiddleware
from app.mcp.registry import (
    sync_mcp_tools_with_db,
)
from app.mcp.server import (
    TravelAssistantMCPServer,
    create_mcp_app,
    invalidate_permission_cache,
)
from app.mcp.tools_database import (
    db_execute,
    db_get_table_info,
    db_query,
)
from app.mcp.tools_dispatcher import (
    dispatcher_evaluate,
    dispatcher_get_status,
    dispatcher_reset_session,
    dispatcher_test_notification,
)
from app.mcp.tools_journey import (
    journey_create,
    journey_delete,
    journey_get,
    journey_list,
    journey_update,
)
from app.mcp.tools_stops import stops_get_live_departures, stops_search
from app.mcp.tools_sync import sync_get_status, sync_trigger
from app.mcp.tools_timetable import (
    timetable_create,
    timetable_delete,
    timetable_get,
    timetable_list,
    timetable_update,
)
from app.mcp.tools_walking import (
    transfer_list,
    walking_create,
    walking_delete,
    walking_list,
)
from app.models.journey import Journey
from app.models.mcp import MCPTool
from app.models.transfer import PlatformTransfer
from app.models.transit import Stop


@pytest.fixture(autouse=True)
def reset_cache_after_test() -> Generator[None, None, None]:
    """Ensure permission cache is invalidated before and after every test."""
    invalidate_permission_cache()
    yield
    invalidate_permission_cache()


def test_mcp_tool_model_lifecycle(app: Flask) -> None:
    """Test MCPTool Peewee model creation, querying, and permission lookup."""
    with app.app_context():
        tool = MCPTool.create(
            tool_name="test_tool",
            domain="test",
            description="Test Tool Description",
            is_mutating=False,
            enabled=False,
        )
        assert tool.id is not None
        assert MCPTool.is_tool_enabled("test_tool") is False
        assert MCPTool.is_tool_enabled("non_existent") is False

        # Enable tool and test query helpers
        tool.enabled = True
        tool.save()

        assert MCPTool.is_tool_enabled("test_tool") is True

        all_tools = MCPTool.get_all_tools()
        assert any(t.tool_name == "test_tool" for t in all_tools)

        enabled_tools = MCPTool.get_enabled_tools()
        assert any(t.tool_name == "test_tool" for t in enabled_tools)


def test_startup_discovery_defaults_to_disabled(app: Flask) -> None:
    """Verify that newly discovered tools in the registry default to disabled."""
    with app.app_context():
        # Clear mcp_tools table
        MCPTool.delete().execute()
        assert MCPTool.select().count() == 0

        # Run startup sync
        stats = sync_mcp_tools_with_db()
        assert stats["added"] > 0

        # All newly added tools must be disabled (enabled=False)
        all_tools = MCPTool.select()
        assert all_tools.count() > 0
        for tool in all_tools:
            assert (
                tool.enabled is False
            ), f"Tool {tool.tool_name} was not disabled by default."

        # Modify one tool to enabled, re-run sync, and verify override is preserved
        sample = all_tools.first()
        sample.enabled = True
        sample.save()

        stats2 = sync_mcp_tools_with_db()
        assert stats2["added"] == 0
        reloaded = MCPTool.get_by_id(sample.id)
        assert reloaded.enabled is True


def test_config_mcp_views(client: FlaskClient, app: Flask) -> None:
    """Test /config/mcp page rendering, data fetching, and changeset saving."""
    with app.app_context():
        sync_mcp_tools_with_db()

        # 1. GET /config/mcp page
        resp = client.get("/config/mcp")
        assert resp.status_code == 200
        assert b"Model Context Protocol" in resp.data
        assert b"Registered Tools" in resp.data

        # 2. GET /config/mcp/data
        data_resp = client.get("/config/mcp/data")
        assert data_resp.status_code == 200
        payload = data_resp.get_json()
        assert "data" in payload
        items = payload["data"]
        assert len(items) > 0

        # Pick a read-only and mutating tool
        read_tool = next(t for t in items if not t["is_mutating"])
        mutating_tool = next(t for t in items if t["is_mutating"])

        # 3. POST /config/mcp/data to enable tools
        save_resp = client.post(
            "/config/mcp/data",
            json={
                "added": [],
                "updated": [
                    {"id": read_tool["id"], "enabled": True},
                    {"id": mutating_tool["id"], "enabled": True},
                ],
                "deleted": [],
            },
        )
        assert save_resp.status_code == 200
        result = save_resp.get_json()
        assert result["success"] is True
        assert result["stats"]["updated"] == 2

        # Verify persisted values
        t1 = MCPTool.get_by_id(read_tool["id"])
        assert t1.enabled is True
        t2 = MCPTool.get_by_id(mutating_tool["id"])
        assert t2.enabled is True

        # 4. POST /config/mcp/data to disable a tool
        disable_resp = client.post(
            "/config/mcp/data",
            json={
                "added": [],
                "updated": [
                    {"id": read_tool["id"], "enabled": False},
                ],
                "deleted": [],
            },
        )
        assert disable_resp.status_code == 200
        t1_reload = MCPTool.get_by_id(read_tool["id"])
        assert t1_reload.enabled is False


def test_mcp_server_dynamic_tool_omission_and_permission_enforcement(
    app: Flask,
) -> None:
    """Verify that disabled tools are omitted from list_tools and calls are rejected."""
    with app.app_context():
        sync_mcp_tools_with_db()

        # Set all tools to disabled initially
        MCPTool.update(enabled=False).execute()
        invalidate_permission_cache()

        server = TravelAssistantMCPServer("Test Server")

        async def _run_checks() -> None:
            # 1. With all tools disabled, list_tools must be empty
            active_tools = await server.list_tools()
            assert len(active_tools) == 0

            # 2. Calling any disabled tool returns an error
            call_res = await server.call_tool("stops_search", {"query": "King's Cross"})
            assert call_res.is_error is True
            assert "disabled" in call_res.content[0].text

            # 3. Enable read-only tool 'stops_search'
            stop_tool = MCPTool.get(MCPTool.tool_name == "stops_search")
            stop_tool.enabled = True
            stop_tool.save()
            invalidate_permission_cache()

            # Now list_tools contains stops_search
            tools_after = await server.list_tools()
            tool_names = [t.name for t in tools_after]
            assert "stops_search" in tool_names

            # 4. Mutating tool 'sync_trigger' configured as disabled
            sync_call_res = await server.call_tool("sync_trigger", {"dataset": "stops"})
            assert sync_call_res.is_error is True
            assert "disabled" in sync_call_res.content[0].text

            # 5. Enable mutating tool 'sync_trigger'
            sync_tool = MCPTool.get(MCPTool.tool_name == "sync_trigger")
            sync_tool.enabled = True
            sync_tool.save()
            invalidate_permission_cache()

            tools_with_sync = await server.list_tools()
            assert "sync_trigger" in [t.name for t in tools_with_sync]

            with patch("app.mcp.tools_sync.request_sync") as mock_sync:
                allowed_call = await server.call_tool(
                    "sync_trigger", {"dataset": "stops"}
                )
                assert allowed_call.is_error is False
                mock_sync.assert_called_once_with("stops")

        asyncio.run(_run_checks())


def test_bearer_auth_middleware() -> None:
    """Test Bearer token authentication middleware for Starlette."""

    async def sample_endpoint(request):
        return Response("ok")

    app = Starlette(routes=[Route("/test", sample_endpoint)])
    app.add_middleware(BearerAuthMiddleware, api_token="super-secret-token")
    client = TestClient(app)

    # 1. Unauthenticated request without header -> 401
    r1 = client.get("/test")
    assert r1.status_code == 401
    assert "Unauthorized" in r1.text

    # 2. Request with invalid token -> 401
    r2 = client.get("/test", headers={"Authorization": "Bearer wrong-token"})
    assert r2.status_code == 401

    # 3. Request with valid token -> 200
    r3 = client.get("/test", headers={"Authorization": "Bearer super-secret-token"})
    assert r3.status_code == 200

    # 4. App created without token allows unauthenticated requests
    open_app = Starlette(routes=[Route("/test", sample_endpoint)])
    open_app.add_middleware(BearerAuthMiddleware, api_token="")
    open_client = TestClient(open_app)
    r4 = open_client.get("/test")
    assert r4.status_code == 200


def test_journey_tools_crud(app: Flask) -> None:
    """Test journey MCP tool functions with London public transport endpoints."""
    with app.app_context():
        # 1. Create journey
        res = journey_create(
            name="London Commute",
            from_type="rail",
            from_id="KGX",
            from_name="London King's Cross",
            to_type="rail",
            to_id="EUS",
            to_name="London Euston",
            time_settings=[
                {
                    "mode": "depart",
                    "time": "08:30",
                    "days": ["mon", "tue", "wed", "thu", "fri"],
                }
            ],
        )
        assert res["success"] is True
        j_id = res["journey"]["id"]

        # 2. List journeys
        j_list = journey_list()
        assert len(j_list) >= 1
        assert any(j["id"] == j_id for j in j_list)

        # 3. Get journey
        j_data = journey_get(j_id)
        assert j_data["name"] == "London Commute"
        assert j_data["from_name"] == "London King's Cross"

        # 4. Update journey
        u_res = journey_update(j_id, name="Updated London Commute")
        assert u_res["success"] is True
        assert u_res["journey"]["name"] == "Updated London Commute"

        # 5. Delete journey
        d_res = journey_delete(j_id)
        assert d_res["success"] is True
        assert d_res["deleted_id"] == j_id

        # Verify deletion
        not_found = journey_get(j_id)
        assert "error" in not_found


def test_timetable_tools_crud(app: Flask) -> None:
    """Test timetable MCP tool functions."""
    with app.app_context():
        # 1. Create timetable
        res = timetable_create(
            name="Route 73 Bus Schedule",
            transport_type="bus",
            start_date="2026-09-01",
            end_date="2026-12-31",
            content={
                "stops": [
                    {"id": "490000077E", "name": "Euston Station", "type": "bus"},
                    {"id": "490000077W", "name": "King's Cross Station", "type": "bus"},
                ],
                "trips": [
                    {
                        "id": "trip_1",
                        "headsign": "Route 73 to King's Cross",
                        "times": [
                            {"arr": "08:00", "dep": "08:00"},
                            {"arr": "08:15", "dep": "08:15"},
                        ],
                    }
                ],
            },
        )
        assert res["success"] is True
        tt_id = res["timetable"]["id"]

        # 2. List timetables
        tt_list = timetable_list(transport_type="bus")
        assert len(tt_list) >= 1
        assert any(t["id"] == tt_id for t in tt_list)

        # 3. Get timetable
        tt_data = timetable_get(tt_id)
        assert tt_data["name"] == "Route 73 Bus Schedule"

        # 4. Update timetable
        u_res = timetable_update(tt_id, name="Updated Route 73 Bus Schedule")
        assert u_res["success"] is True
        assert u_res["timetable"]["name"] == "Updated Route 73 Bus Schedule"

        # 5. Delete timetable
        d_res = timetable_delete(tt_id)
        assert d_res["success"] is True
        assert d_res["deleted_id"] == tt_id


def test_walking_and_transfer_tools(app: Flask) -> None:
    """Test walking and transfer MCP tools."""
    with app.app_context():
        # 1. Create walking link
        w_res = walking_create(
            start_type="rail",
            start_id="KGX",
            start_name="London King's Cross",
            finish_type="rail",
            finish_id="STP",
            finish_name="London St Pancras",
            time_needed_minutes=3,
            bidirectional=True,
        )
        assert w_res["success"] is True
        w_id = w_res["walking"]["id"]

        # 2. List walking links
        w_list = walking_list(query="King's Cross")
        assert len(w_list) >= 1

        # 3. Delete walking link
        del_res = walking_delete(w_id)
        assert del_res["success"] is True

        # 4. Create platform transfer and query via transfer_list
        PlatformTransfer.create(
            location_type="rail",
            location_id="KGX",
            location_name="London King's Cross",
            from_platform="1",
            to_platform="8",
            transfer_time_minutes=4,
            bidirectional=True,
            step_free=True,
            notes="Transfer via footbridge",
        )
        t_list = transfer_list(location_id="KGX")
        assert len(t_list) >= 1
        assert t_list[0]["from_platform"] == "1"


def test_stops_and_departures_tools(app: Flask) -> None:
    """Test transit stop search and live departure tools."""
    with app.app_context():
        # Seed test stops
        Stop.create(
            atco_code="9100KINGSX",
            naptan_code="KGX",
            stop_type="rail",
            name="London King's Cross",
            latitude=51.5308,
            longitude=-0.1238,
        )

        results = stops_search(query="King's Cross", stop_type="rail")
        assert len(results) >= 1
        assert results[0]["atco_code"] == "9100KINGSX"

        with patch(
            "app.datasources.train_live.TrainLiveClient.get_departure_board"
        ) as mock_board:
            mock_board.return_value = {"services": []}
            dep_res = stops_get_live_departures(station_crs="KGX", num_rows=5)
            assert dep_res["crs"] == "KGX"
            assert "board" in dep_res


def test_dispatcher_tools(app: Flask) -> None:
    """Test dispatcher live control tools."""
    with app.app_context():
        j = Journey.create(
            name="King's Cross to Euston Test",
            from_type="rail",
            from_id="KGX",
            from_name="London King's Cross",
            to_type="rail",
            to_id="EUS",
            to_name="London Euston",
            time_settings=[{"mode": "depart", "time": "12:00", "days": ["mon"]}],
        )

        # 1. dispatcher_get_status
        status = dispatcher_get_status()
        assert "monitor_running" in status
        assert "active_journeys_count" in status

        # 2. dispatcher_evaluate
        eval_res = dispatcher_evaluate(j.id)
        assert eval_res["journey_id"] == j.id

        # 3. dispatcher_test_notification
        with patch(
            "app.datasources.homeassistant.HomeAssistantClient.send_mobile_notification"
        ) as mock_send:
            mock_send.return_value = True
            notif_res = dispatcher_test_notification(j.id)
            assert notif_res["success"] is True
            assert "[TEST]" in notif_res["title"]

        # 4. dispatcher_reset_session
        reset_res = dispatcher_reset_session()
        assert "error" in reset_res or reset_res.get("success") is True


def test_sync_tools(app: Flask) -> None:
    """Test sync trigger and sync get status MCP tools."""
    with app.app_context():
        sync_stats = sync_get_status()
        assert isinstance(sync_stats, list)

        # Trigger invalid dataset
        inv_res = sync_trigger("non_existent_dataset")
        assert "error" in inv_res

        # Trigger valid dataset
        with patch("app.mcp.tools_sync.request_sync") as mock_req:
            val_res = sync_trigger("stops")
            assert val_res["success"] is True
            mock_req.assert_called_once_with("stops")


def test_database_tools(app: Flask) -> None:
    """Test db_get_table_info and db_query tools with permission constraints."""
    with app.app_context():
        # 1. db_get_table_info (all tables)
        info_all = db_get_table_info()
        assert info_all["success"] is True
        assert info_all["table_count"] > 0
        names = [t["name"] for t in info_all["tables"]]
        assert "journeys" in names
        assert "mcp_tools" in names

        # 2. db_get_table_info (single table)
        info_single = db_get_table_info("journeys")
        assert info_single["success"] is True
        assert info_single["table"]["name"] == "journeys"
        col_names = [c["name"] for c in info_single["table"]["columns"]]
        assert "id" in col_names
        assert "name" in col_names

        # Invalid table names
        assert db_get_table_info("invalid;name")["success"] is False
        assert db_get_table_info("non_existent_table_xyz")["success"] is False

        # 3. db_query (read-only)
        # Empty and multi-statements rejected
        assert db_query("")["success"] is False
        assert db_query("SELECT 1; SELECT 2;")["success"] is False

        # SELECT succeeds
        sel_res = db_query("SELECT name FROM journeys LIMIT 5")
        assert sel_res["success"] is True
        assert sel_res["type"] == "SELECT"
        assert isinstance(sel_res["rows"], list)

        # Mutating operations rejected under db_query
        ins_rej = db_query(
            "INSERT INTO journeys (name) VALUES ('Hacked')",
        )
        assert ins_rej["success"] is False
        assert "read-only" in ins_rej["error"]

        upd_rej = db_query(
            "UPDATE journeys SET name = 'Hacked'",
        )
        assert upd_rej["success"] is False
        assert "read-only" in upd_rej["error"]

        del_rej = db_query("DELETE FROM journeys")
        assert del_rej["success"] is False
        assert "read-only" in del_rej["error"]

        # Prohibited DDL rejected
        assert db_query("DROP TABLE journeys")["success"] is False

        # 4. db_execute (mutating statements)
        # Empty and multi-statements rejected
        assert db_execute("")["success"] is False
        assert (
            db_execute(
                "INSERT INTO journeys (name) VALUES ('A'); INSERT INTO journeys (name) VALUES ('B');"
            )["success"]
            is False
        )

        # SELECT rejected under db_execute
        sel_execute_rej = db_execute("SELECT name FROM journeys")
        assert sel_execute_rej["success"] is False
        assert "strictly permits INSERT, UPDATE, and DELETE" in sel_execute_rej["error"]

        # INSERT succeeds
        ins_res = db_execute(
            "INSERT INTO journeys (name, from_type, from_id, from_name, to_type, to_id, to_name, time_settings, created_at, updated_at) "
            "VALUES (?, 'rail', 'KGX', 'London King''s Cross', 'rail', 'EUS', 'London Euston', '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            params=["Test Commute DB Tool"],
        )
        assert ins_res["success"] is True
        assert ins_res["rows_affected"] == 1
        new_id = ins_res["last_insert_id"]
        assert new_id is not None

        # Verify inserted row via db_query
        check_res = db_query(
            "SELECT name FROM journeys WHERE id = ?",
            params=[new_id],
        )
        assert check_res["success"] is True
        assert check_res["rows"][0]["name"] == "Test Commute DB Tool"

        # UPDATE succeeds under db_execute
        upd_res = db_execute(
            "UPDATE journeys SET name = ? WHERE id = ?",
            params=["Updated Commute DB Tool", new_id],
        )
        assert upd_res["success"] is True
        assert upd_res["rows_affected"] == 1

        # DELETE succeeds under db_execute
        del_res = db_execute(
            "DELETE FROM journeys WHERE id = ?",
            params=[new_id],
        )
        assert del_res["success"] is True
        assert del_res["rows_affected"] == 1

        # Prohibited DDL (DROP TABLE) rejected under db_execute
        drop_rej = db_execute("DROP TABLE journeys")
        assert drop_rej["success"] is False
        assert "DROP" in drop_rej["error"]


def test_database_tools_server_enforcement(app: Flask) -> None:
    """Test server-level permission dispatching for database tools."""
    with app.app_context():
        sync_mcp_tools_with_db()
        server = TravelAssistantMCPServer("DB Test Server")

        async def _run() -> None:
            # 1. When db_query is disabled -> rejected
            MCPTool.update(enabled=False).where(
                MCPTool.tool_name == "db_query"
            ).execute()
            invalidate_permission_cache()

            call_disabled = await server.call_tool(
                "db_query", {"query": "SELECT count(*) FROM journeys"}
            )
            assert call_disabled.is_error is True
            assert "disabled" in call_disabled.content[0].text

            # 2. When db_query is enabled -> succeeds for SELECT
            MCPTool.update(enabled=True).where(
                MCPTool.tool_name == "db_query"
            ).execute()
            invalidate_permission_cache()

            call_read_sel = await server.call_tool(
                "db_query", {"query": "SELECT count(*) as count FROM journeys"}
            )
            assert call_read_sel.is_error is False
            assert "count" in call_read_sel.content[0].text

            # 3. When db_execute is disabled -> rejected
            MCPTool.update(enabled=False).where(
                MCPTool.tool_name == "db_execute"
            ).execute()
            invalidate_permission_cache()

            call_exec_disabled = await server.call_tool(
                "db_execute",
                {"query": "DELETE FROM journeys WHERE id = 99999"},
            )
            assert call_exec_disabled.is_error is True
            assert "disabled" in call_exec_disabled.content[0].text

            # 4. When db_execute is enabled -> succeeds
            MCPTool.update(enabled=True).where(
                MCPTool.tool_name == "db_execute"
            ).execute()
            invalidate_permission_cache()

            call_rw_ins = await server.call_tool(
                "db_execute",
                {
                    "query": (
                        "INSERT INTO journeys (name, from_type, from_id, from_name, to_type, to_id, to_name, time_settings, created_at, updated_at) "
                        "VALUES ('RW Test', 'rail', 'KGX', 'London King''s Cross', 'rail', 'EUS', 'London Euston', '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    )
                },
            )
            assert call_rw_ins.is_error is False
            assert "rows_affected" in call_rw_ins.content[0].text

        asyncio.run(_run())


def test_dispatcher_evaluate_is_read_only() -> None:
    """Verify dispatcher_evaluate tool metadata is configured as non-mutating."""
    from app.mcp.registry import REGISTERED_TOOLS

    assert "dispatcher_evaluate" in REGISTERED_TOOLS
    assert REGISTERED_TOOLS["dispatcher_evaluate"].is_mutating is False


def test_create_mcp_app_allows_lan_host_headers(app: Flask) -> None:
    """Verify create_mcp_app permits arbitrary LAN host headers by default without 421."""
    with app.app_context():
        mcp_app = create_mcp_app(host="0.0.0.0")
        with TestClient(mcp_app) as client:
            # POST /sse with LAN IP host header (e.g. 192.168.3.2:8098)
            response = client.post(
                "/sse",
                headers={"host": "192.168.3.2:8098"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test-client", "version": "1.0.0"},
                    },
                },
            )
            assert response.status_code == 200
            assert "Travel Assistant" in response.text
            for line in response.text.splitlines():
                if line.startswith("data: "):
                    payload = json.loads(line[6:])
                    assert payload["result"]["serverInfo"]["name"] == "Travel Assistant"

            # Verify alias routes /mcp and / also route successfully
            mcp_resp = client.post(
                "/mcp",
                headers={"host": "192.168.3.2:8098"},
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test-client", "version": "1.0.0"},
                    },
                },
            )
            assert mcp_resp.status_code == 200
            assert "Travel Assistant" in mcp_resp.text


def test_create_mcp_app_with_allowed_hosts_enforces_protection(app: Flask) -> None:
    """Verify create_mcp_app with allowed_hosts rejects invalid host headers with 421."""
    with app.app_context():
        mcp_app = create_mcp_app(
            host="0.0.0.0",
            allowed_hosts=["allowed.local:*", "localhost:*"],
        )
        with TestClient(mcp_app) as client:
            # Valid allowed host
            valid_resp = client.post(
                "/sse",
                headers={"host": "allowed.local:8098"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test-client", "version": "1.0.0"},
                    },
                },
            )
            assert valid_resp.status_code == 200

            # Invalid host should be rejected by transport security with 421
            invalid_resp = client.post(
                "/sse",
                headers={"host": "attacker.com:8098"},
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test-client", "version": "1.0.0"},
                    },
                },
            )
            assert invalid_resp.status_code == 421
            assert "Invalid Host header" in invalid_resp.text


def test_create_mcp_app_with_api_token(app: Flask) -> None:
    """Verify create_mcp_app enforces Bearer token authentication when configured."""
    with app.app_context():
        mcp_app = create_mcp_app(api_token="super-secret")
        with TestClient(mcp_app) as client:
            # Missing token -> 401
            unauth_resp = client.post(
                "/sse",
                headers={"host": "192.168.3.2:8098"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test-client", "version": "1.0.0"},
                    },
                },
            )
            assert unauth_resp.status_code == 401

            # Valid token -> 200 (passes auth)
            auth_resp = client.post(
                "/sse",
                headers={
                    "host": "192.168.3.2:8098",
                    "authorization": "Bearer super-secret",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "test-client", "version": "1.0.0"},
                    },
                },
            )
            assert auth_resp.status_code == 200


def test_cli_main_entrypoint(monkeypatch: pytest.MonkeyPatch, app: Flask) -> None:
    """Test python3 -m app.mcp entrypoint invocation with mocked uvicorn."""
    from app.mcp.__main__ import main

    monkeypatch.setattr(
        "sys.argv",
        [
            "app.mcp",
            "--port",
            "8098",
            "--host",
            "127.0.0.1",
            "--token",
            "test-token",
            "--allowed-hosts",
            "127.0.0.1:*,localhost:*",
        ],
    )

    with patch("uvicorn.run") as mock_uvicorn, patch(
        "app.mcp.__main__.create_mcp_app"
    ) as mock_create_app:
        main()
        mock_create_app.assert_called_once_with(
            api_token="test-token",
            host="127.0.0.1",
            allowed_hosts=["127.0.0.1:*", "localhost:*"],
        )
        mock_uvicorn.assert_called_once()
        _, kwargs = mock_uvicorn.call_args
        assert kwargs["port"] == 8098
        assert kwargs["host"] == "127.0.0.1"
