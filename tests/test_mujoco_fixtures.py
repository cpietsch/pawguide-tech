import json
import math
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text())


def test_each_fixture_has_a_valid_waypoint_document() -> None:
    manifest = _load("config/mujoco-fixtures.json")
    assert manifest["default"] == "engineering_short"

    for fixture in manifest["fixtures"].values():
        document = _load(fixture["waypoint_file"])
        assert document["version"] == 1
        for pose in document["waypoints"].values():
            assert len(pose["position"]) == 3
            assert len(pose["orientation"]) == 4
            assert math.isclose(
                sum(value * value for value in pose["orientation"]), 1.0
            )


def test_concept_fixture_is_five_metres_with_named_gate() -> None:
    manifest = _load("config/mujoco-fixtures.json")
    concept = manifest["fixtures"]["concept_gate"]
    waypoints = _load(concept["waypoint_file"])["waypoints"]

    assert set(waypoints) == {"home", "demo_gate"}
    home = waypoints["home"]["position"]
    gate = waypoints["demo_gate"]["position"]
    assert math.dist(home[:2], gate[:2]) == 5.0
    assert home[:2] == [0.0, -2.5]
    assert gate[:2] == [3.6, 0.9698703145794942]
    assert concept["arena"] == [-0.4, 4.0, -2.9, 1.3698703145794942]
    live_extent = (-4.075, 4.275, -6.625, 1.525)
    arena = concept["arena"]
    assert live_extent[0] <= arena[0] <= arena[1] <= live_extent[1]
    assert live_extent[2] <= arena[2] <= arena[3] <= live_extent[3]
    for point in (home, gate):
        assert live_extent[0] <= point[0] <= live_extent[1]
        assert live_extent[2] <= point[1] <= live_extent[3]
    assert concept["protected_lane"] == [home[:2], gate[:2]]
    assert concept["obstacles"] == []


def test_blocked_concept_has_no_bypass_and_same_exact_waypoints() -> None:
    manifest = _load("config/mujoco-fixtures.json")
    clear = manifest["fixtures"]["concept_gate"]
    blocked = manifest["fixtures"]["concept_gate_blocked"]

    assert blocked["protected_lane"] == clear["protected_lane"]
    assert blocked["blocked_lane"] == clear["protected_lane"]
    assert blocked["bypass_route"] is None
    assert blocked["expected_outcome"] == "fail_closed_stop"
    assert (
        _load(blocked["waypoint_file"])["waypoints"]
        == _load(clear["waypoint_file"])["waypoints"]
    )
    obstacle = blocked["obstacles"][0]
    route = clear["protected_lane"]
    route_angle = math.atan2(
        route[1][1] - route[0][1], route[1][0] - route[0][0]
    )
    assert abs(math.cos(obstacle["yaw_rad"] - route_angle)) < 1e-12

    center = obstacle["center"]
    wall_axis = (math.cos(obstacle["yaw_rad"]), math.sin(obstacle["yaw_rad"]))
    arena = blocked["arena"]
    corner_projections = [
        abs((x - center[0]) * wall_axis[0] + (y - center[1]) * wall_axis[1])
        for x in (arena[0], arena[1])
        for y in (arena[2], arena[3])
    ]
    assert obstacle["half_extents"][0] >= max(corner_projections)
