from __future__ import annotations

import asyncio

from httpx import ASGITransport, AsyncClient
import pytest

from pawguide.adapter import MockRobotAdapter
from pawguide.app import _tokens_from_env, create_app
from pawguide.supervisor import SafetySupervisor, SupervisorConfig


def make_app() -> tuple[object, SafetySupervisor]:
    supervisor = SafetySupervisor(
        MockRobotAdapter(),
        SupervisorConfig(allowed_waypoints=frozenset({"home"})),
    )
    app = create_app(
        supervisor=supervisor,
        operator_token="operator-token",
        dev_token="dev-token",
    )
    return app, supervisor


def test_health_is_public_but_state_requires_authentication() -> None:
    app, _supervisor = make_app()

    async def exercise_api() -> None:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                assert (await client.get("/health")).status_code == 200
                assert (await client.get("/health")).json() == {
                    "status": "ok",
                    "adapter": "mock",
                    "motion_capable": False,
                }
                assert (await client.get("/v1/state")).status_code == 401
                response = await client.get(
                    "/v1/state",
                    headers={"Authorization": "Bearer dev-token"},
                )
                assert response.status_code == 200
                assert response.json()["stop_latched"] is True

    asyncio.run(exercise_api())


def test_capabilities_are_explicit_about_mock_mode_and_roles() -> None:
    app, _supervisor = make_app()

    async def exercise_api() -> None:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
                headers={"Authorization": "Bearer dev-token"},
            ) as client:
                response = await client.get("/v1/capabilities")

                assert response.status_code == 200
                body = response.json()
                assert body["adapter"] == "mock"
                assert body["motion_capable"] is False
                assert body["heartbeat_period_ms"] == 500
                assert body["heartbeat_timeout_ms"] == 2000
                assert "reset_stop" in body["operator_actions"]
                assert "reset_stop" not in body["developer_actions"]

    asyncio.run(exercise_api())


def test_dev_client_cannot_heartbeat_or_release_stop() -> None:
    app, _supervisor = make_app()

    async def exercise_api() -> None:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
                headers={"Authorization": "Bearer dev-token"},
            ) as client:
                heartbeat = await client.post(
                    "/v1/heartbeat",
                    json={"source": "remote-dev"},
                )
                reset = await client.post(
                    "/v1/commands",
                    json={
                        "command_id": "23bc7fef-062e-4bb7-92f1-9f6a6bb51df1",
                        "action": "reset_stop",
                        "arguments": {},
                    },
                )
                stop = await client.post(
                    "/v1/commands",
                    json={
                        "command_id": "fc3268c9-abcb-468b-b76e-8e5778029a70",
                        "action": "stop",
                        "arguments": {},
                    },
                )

                assert heartbeat.status_code == 403
                assert reset.status_code == 403
                assert stop.status_code == 200
                assert stop.json()["accepted"] is True

    asyncio.run(exercise_api())


def test_operator_arms_locally_before_dev_starts_a_mission() -> None:
    app, _supervisor = make_app()

    async def exercise_api() -> None:
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://testserver",
            ) as client:
                heartbeat = await client.post(
                    "/v1/heartbeat",
                    headers={"Authorization": "Bearer operator-token"},
                    json={"source": "pixel"},
                )
                reset = await client.post(
                    "/v1/commands",
                    headers={"Authorization": "Bearer operator-token"},
                    json={
                        "command_id": "3de0d8bf-a7a9-45c8-aafe-d99a26e22d96",
                        "action": "reset_stop",
                        "arguments": {},
                    },
                )
                patrol = await client.post(
                    "/v1/commands",
                    headers={"Authorization": "Bearer dev-token"},
                    json={
                        "command_id": "b155b695-4985-48a3-856f-f2766bb33d26",
                        "action": "start_patrol",
                        "arguments": {},
                    },
                )

                assert heartbeat.status_code == 200
                assert reset.status_code == 200
                assert patrol.status_code == 200
                assert patrol.json()["accepted"] is True
                assert patrol.json()["state"] == "patrolling"

    asyncio.run(exercise_api())


def test_tokens_can_be_loaded_from_files(tmp_path, monkeypatch) -> None:
    operator_file = tmp_path / "operator.token"
    dev_file = tmp_path / "dev.token"
    operator_file.write_text("operator-from-file\n", encoding="utf-8")
    dev_file.write_text("dev-from-file\n", encoding="utf-8")
    monkeypatch.setenv("PAWGUIDE_OPERATOR_TOKEN_FILE", str(operator_file))
    monkeypatch.setenv("PAWGUIDE_DEV_TOKEN_FILE", str(dev_file))
    monkeypatch.delenv("PAWGUIDE_OPERATOR_TOKEN", raising=False)
    monkeypatch.delenv("PAWGUIDE_DEV_TOKEN", raising=False)

    assert _tokens_from_env() == ("operator-from-file", "dev-from-file")


def test_ambiguous_secret_configuration_is_rejected(tmp_path, monkeypatch) -> None:
    operator_file = tmp_path / "operator.token"
    operator_file.write_text("operator-from-file", encoding="utf-8")
    monkeypatch.setenv("PAWGUIDE_OPERATOR_TOKEN", "operator-direct")
    monkeypatch.setenv("PAWGUIDE_OPERATOR_TOKEN_FILE", str(operator_file))
    monkeypatch.setenv("PAWGUIDE_DEV_TOKEN", "dev-direct")

    with pytest.raises(RuntimeError, match="set only one"):
        _tokens_from_env()


def test_real_adapter_requires_an_explicit_motion_gate(monkeypatch) -> None:
    monkeypatch.setenv("PAWGUIDE_OPERATOR_TOKEN", "operator")
    monkeypatch.setenv("PAWGUIDE_DEV_TOKEN", "dev")
    monkeypatch.setenv("PAWGUIDE_ADAPTER", "dimos_mcp")
    monkeypatch.setenv("PAWGUIDE_ENABLE_REAL_MOTION", "NO")

    with pytest.raises(RuntimeError, match="PAWGUIDE_ENABLE_REAL_MOTION=YES"):
        create_app()
