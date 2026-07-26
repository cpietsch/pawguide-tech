from __future__ import annotations

from pathlib import Path

PROJECT = Path(__file__).parents[1]


def test_x5_entrypoints_are_packaged_and_executable() -> None:
    expected = {
        "bootstrap-rdk-x5.sh",
        "check-x5-readiness.sh",
        "diagnose-dimos-x5.sh",
        "install-dimos-x5.sh",
        "install-x5-bridge.sh",
        "rdk-x5-platform.sh",
        "run-dimos-x5.sh",
        "direct-go2-mcp.py",
        "wait-for-dimos-mcp.sh",
        "install-x5-simulation.sh",
    }

    provision_names = {path.name for path in (PROJECT / "provision").iterdir()}
    assert expected <= provision_names
    for name in expected:
        assert (PROJECT / "provision" / name).stat().st_mode & 0o111


def test_service_uses_profile_installed_runner() -> None:
    dimos_service = (PROJECT / "provision/pawguide-dimos.service").read_text()
    x5_installer = (PROJECT / "provision/install-dimos-x5.sh").read_text()

    assert "ExecStart=/opt/pawguide/bin/run-dimos.sh" in dimos_service
    assert "/opt/pawguide/bin/run-dimos.sh" in x5_installer
    assert "x5" in x5_installer
    assert "direct-go2-mcp.py" in x5_installer

    gateway_service = (
        PROJECT / "provision/pawguide-gateway.service"
    ).read_text()
    assert "After=network-online.target tailscaled.service pawguide-dimos.service" in (
        gateway_service
    )
    assert "ExecStartPre=/opt/pawguide/bin/wait-for-dimos-mcp.sh" in (
        gateway_service
    )
    assert "--physical-minimal" in (
        PROJECT / "provision/enable-real-motion.sh"
    ).read_text()
    assert "--physical-minimal" in (
        PROJECT / "provision/check-x5-readiness.sh"
    ).read_text()


def test_bundle_builder_is_x5_only() -> None:
    bundle_builder = (PROJECT / "provision/build-edge-bundle.sh").read_text()

    assert 'hardware_target="${1:-x5}"' in bundle_builder
    assert 'hardware_target}" != "x5"' in bundle_builder
    assert 'bundle_name="pawguide-x5-mvp"' in bundle_builder


def test_manual_operator_is_part_of_the_edge_wheel() -> None:
    pyproject = (PROJECT / "pyproject.toml").read_text()
    readiness = (PROJECT / "provision/check-x5-readiness.sh").read_text()

    assert 'pawguide-operator = "pawguide.operator:main"' in pyproject
    assert "pawguide-operator" in readiness


def test_x5_real_motion_requires_installed_physical_readiness_gate() -> None:
    installer = (PROJECT / "provision/install-dimos-x5.sh").read_text()
    enable = (PROJECT / "provision/enable-real-motion.sh").read_text()
    readiness = (PROJECT / "provision/check-x5-readiness.sh").read_text()
    patch = (PROJECT / "vendor/dimos-pawguide.patch").read_text()

    for script in (
        "check-x5-readiness.sh",
        "configure-go2-ap.sh",
        "install-robot-credential.sh",
        "rdk-x5-platform.sh",
        "enable-real-motion.sh",
        "disable-real-motion.sh",
    ):
        assert script in installer
    assert "/opt/pawguide/bin/check-x5-readiness.sh --require-physical" in enable
    assert '"${require_physical}" -eq 1' in readiness
    assert '"pyyaml>=6.0.2"' in patch


def test_x5_robot_address_is_deployment_config_not_a_hardcoded_runtime() -> None:
    runner = (PROJECT / "provision/run-dimos-x5.sh").read_text()
    direct_bridge = (PROJECT / "provision/direct-go2-mcp.py").read_text()
    service = (PROJECT / "provision/pawguide-dimos.service").read_text()
    enable = (PROJECT / "provision/enable-real-motion.sh").read_text()
    configure = (PROJECT / "provision/configure-go2-ap.sh").read_text()

    assert "direct-go2-mcp.py" in runner
    assert 'os.environ.get("PAWGUIDE_ROBOT_IP", "192.168.12.1")' in direct_bridge
    assert 'ThreadingHTTPServer(("127.0.0.1", 9990)' in direct_bridge
    assert "EnvironmentFile=-/etc/pawguide/pawguide.env" in service
    assert "AF_NETLINK" in service
    assert 'ping -c 1 -W 2 "${robot_ip}"' in enable
    assert "PAWGUIDE_ROBOT_BSSID" in configure
    assert "https://download.pytorch.org/whl/cpu" in (
        PROJECT / "provision/install-dimos-x5.sh"
    ).read_text()


def test_physical_and_simulation_mcp_endpoints_are_isolated_on_x5() -> None:
    direct_bridge = (PROJECT / "provision/direct-go2-mcp.py").read_text()
    sim_env = (PROJECT / "provision/x5/pawguide-sim-concept.env").read_text()
    relay = (
        PROJECT / "provision/x5/pawguide-sim-mcp-relay.service"
    ).read_text()
    sim_gateway = (
        PROJECT / "provision/x5/pawguide-sim-gateway.service"
    ).read_text()
    sim_installer = (
        PROJECT / "provision/install-x5-simulation.sh"
    ).read_text()

    assert 'ThreadingHTTPServer(("127.0.0.1", 9990)' in direct_bridge
    assert "http://127.0.0.1:9992/mcp" in sim_env
    assert "TCP-LISTEN:9992" in relay
    assert "TCP:100.102.208.90:9991" in relay
    assert "EnvironmentFile=/etc/pawguide/pawguide-sim.env" in sim_gateway
    assert "ExecStart=/opt/pawguide/.venv/bin/pawguide-gateway" in sim_gateway
    assert "pawguide-sim-mcp-relay.service" in sim_installer
    assert "pawguide-sim-gateway.service" in sim_installer
