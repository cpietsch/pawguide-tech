from __future__ import annotations

from pathlib import Path

PROJECT = Path(__file__).parents[1]


def test_x5_and_s100_entrypoints_are_packaged_and_executable() -> None:
    expected = {
        "bootstrap-rdk-x5.sh",
        "check-x5-readiness.sh",
        "diagnose-dimos-x5.sh",
        "install-dimos-x5.sh",
        "install-x5-bridge.sh",
        "rdk-x5-platform.sh",
        "run-dimos-x5.sh",
        "bootstrap-rdk-s100.sh",
        "check-s100-readiness.sh",
        "diagnose-dimos-s100.sh",
        "install-dimos-s100.sh",
        "install-s100-bridge.sh",
        "rdk-s100-platform.sh",
        "run-dimos-s100.sh",
    }

    provision_names = {path.name for path in (PROJECT / "provision").iterdir()}
    assert expected <= provision_names
    for name in expected:
        assert (PROJECT / "provision" / name).stat().st_mode & 0o111


def test_service_uses_profile_installed_runner() -> None:
    dimos_service = (PROJECT / "provision/pawguide-dimos.service").read_text()
    x5_installer = (PROJECT / "provision/install-dimos-x5.sh").read_text()
    s100_installer = (PROJECT / "provision/install-dimos-s100.sh").read_text()

    assert "ExecStart=/opt/pawguide/bin/run-dimos.sh" in dimos_service
    assert "/opt/pawguide/bin/run-dimos.sh" in x5_installer
    assert "/opt/pawguide/bin/run-dimos.sh" in s100_installer
    assert "x5" in x5_installer
    assert "s100" in s100_installer


def test_bundle_builder_defaults_to_x5_and_accepts_both_profiles() -> None:
    bundle_builder = (PROJECT / "provision/build-edge-bundle.sh").read_text()

    assert 'hardware_target="${1:-x5}"' in bundle_builder
    assert "x5 | s100" in bundle_builder
    assert 'bundle_name="pawguide-${hardware_target}-mvp"' in bundle_builder


def test_manual_operator_is_part_of_the_edge_wheel() -> None:
    pyproject = (PROJECT / "pyproject.toml").read_text()
    readiness = (PROJECT / "provision/check-x5-readiness.sh").read_text()

    assert 'pawguide-operator = "pawguide.operator:main"' in pyproject
    assert "pawguide-operator" in readiness
