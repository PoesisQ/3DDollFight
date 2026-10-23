import json

import numpy as np
import pytest

from dollfight.kinematics import EDGES
from dollfight.pipeline import make_run
from dollfight.transitions import DT, compose_flow, inertial_offset


@pytest.fixture(scope="module")
def pair():
    return compose_flow(False), compose_flow(True)


def test_decay_matches_position_and_velocity_at_both_ends():
    offset, velocity = np.array([0.8, -0.3, 1.2]), np.array([-0.2, 0.7, -1.0])
    duration, step = 0.6, 1e-6

    def fn(t):
        return inertial_offset(offset, velocity, t, duration)

    np.testing.assert_allclose(fn(0), offset)
    np.testing.assert_allclose((fn(step) - fn(0)) / step, velocity, atol=2e-5)
    np.testing.assert_allclose(fn(duration), 0, atol=1e-12)
    np.testing.assert_allclose((fn(duration) - fn(duration - step)) / step, 0, atol=2e-5)


def test_join_alignment_is_same_in_both_comparisons(pair):
    hard, smooth = pair
    assert hard["points"].shape == smooth["points"].shape
    assert hard["transitions"] == smooth["transitions"]
    assert len(smooth["transitions"]) == 5
    assert all(t["anchored_feet"] for t in smooth["transitions"])


def test_each_join_removes_teleport_without_changing_bone_lengths(pair):
    hard, smooth = pair
    points = smooth["points"]
    assert np.isfinite(points).all()
    for a, b in EDGES:
        lengths = np.linalg.norm(points[:, a] - points[:, b], axis=1)
        np.testing.assert_allclose(
            lengths, np.linalg.norm(smooth["rest"][a] - smooth["rest"][b]), atol=1e-8
        )
    for join in smooth["transitions"]:
        i = join["frame"]
        before = np.linalg.norm(hard["points"][i] - hard["points"][i - 1], axis=1).max()
        after = np.linalg.norm(points[i] - points[i - 1], axis=1).max()
        assert after < 0.1  # previous maximum was 0.665 m in one 30 Hz frame
        assert after < before * 0.3
        old_velocity = (points[i - 1, 0] - points[i - 2, 0]) / DT
        new_velocity = (points[i, 0] - points[i - 1, 0]) / DT
        np.testing.assert_allclose(new_velocity, old_velocity, atol=1e-8)
        # Actual FK endpoints must stay attached to the old support, not only a flag.
        for ankle in join["anchored_feet"]:
            assert np.linalg.norm(points[i, ankle] - points[i - 1, ankle]) < 0.015


def test_inertia_ends_before_annotated_attacks_and_returns_to_capture(pair):
    hard, smooth = pair
    for join in smooth["transitions"]:
        end = join["time_s"] + join["duration"]
        assert not any(join["time_s"] <= a["time_s"] < end for a in smooth["reference_actions"])
        i = join["frame"] + round(join["duration"] / DT)
        np.testing.assert_allclose(
            smooth["points"][i : i + 5], hard["points"][i : i + 5], atol=1e-8
        )


def test_contact_flags_and_diagnostics_can_cross_the_json_api():
    run = make_run({"source": "bind_pose", "noise_mm": 0}, include_duel=True)
    decoded = json.loads(json.dumps(run, allow_nan=False))
    assert decoded["source"] == "asset_bind_check"
    assert not decoded["events"]
