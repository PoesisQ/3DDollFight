"""New captured motions must differ in geometry, not just in their labels."""

import json

import numpy as np

from dollfight.kinematics import body_basis
from dollfight.pipeline import ROOT, load_clip, make_run
from dollfight.sparring import excerpt, exchange_plan
from dollfight.transitions import matrix


def test_side_thrust_and_front_kick_have_different_body_relative_extension():
    for kind, sideways in (("side_kick", True), ("front_kick", False)):
        p, _, refs = excerpt(kind)
        action = refs[0]
        peak = round((action["active_at"] + action["active_end"]) * 15)
        pose = p[peak]
        foot = (pose[17] - pose[15]) @ body_basis(pose)
        assert abs(foot[0]) > abs(foot[2]) if sideways else abs(foot[2]) > 2 * abs(foot[0])
        assert pose[17, 1] > 1.1


def test_spin_capture_keeps_jump_and_full_body_turn_at_correct_source_rate():
    raw = json.loads((ROOT / "data/samples/cmu_spin_kick.json").read_text())
    assert raw["source_fps"] == 60 and raw["fps"] == 30
    assert len(raw["points"]) == 115  # 230 source frames, not 58 at double speed
    p, q, _ = excerpt("spin_kick")
    heading = np.unwrap([np.arctan2(matrix(r[0])[0, 2], matrix(r[0])[2, 2]) for r in q])
    assert np.ptp(heading) > np.pi * 1.6
    assert np.ptp(p[:, 0, 1]) > 0.35
    assert np.any(np.min(p[:, [13, 17], 1], axis=1) > 0.6)


def test_three_rounds_use_distinct_captured_exchanges():
    plans = [exchange_plan(i) for i in range(3)]
    assert len({tuple((e[1], e[2]) for e in plan) for plan in plans}) == 3
    moves = {kind for plan in plans for e in plan for kind in e[1:3]}
    assert {
        "front_kick",
        "roundhouse",
        "side_kick",
        "spin_kick",
        "lunge_punch",
        "empi",
        "knife_guard",
    } <= moves
    assert all(sum(e[0] for e in plan) == 30 for plan in plans)


def test_early_side_kicks_are_recognized_from_geometry_without_reference_labels():
    run = make_run({"source": "cmu_side_kick", "noise_mm": 0})
    kicks = [e for e in run["events"] if e["time_s"] < 11 and "kick" in e["action"]]
    assert [e["action"] for e in kicks] == ["right_side_kick"] * 3 + ["left_side_kick"]
    assert all("basis" not in e for e in kicks)
    # The later difficult repeats are intentionally not claimed as validated.
    assert load_clip("cmu_side_kick")["source"] == "cmu_optical_mocap"
