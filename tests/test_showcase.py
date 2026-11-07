"""One-minute presentation uses real motion, eligibility, geometry and HP."""

import inspect
import json
from pathlib import Path

import numpy as np
import pytest

from dollfight.animation_export import export_duel
from dollfight.combat import CombatResolver, hurt_capsules, segment_segment_distance
from dollfight.combat_rules import attack_spec
from dollfight.kinematics import EDGES
from dollfight.pipeline import ROOT
from dollfight.server import replay_run
from dollfight.sparring import rehearsal_clip, rehearsal_pair, showcase_plan


def test_showcase_is_an_explicit_profile_and_keeps_legacy_default():
    parameters = inspect.signature(rehearsal_clip).parameters
    assert "profile" in parameters, "The short showcase must be separate from the legacy rehearsal."
    assert parameters["profile"].default == "legacy"
    clip = rehearsal_clip(0, profile="showcase")
    assert 55 <= len(clip["points"]) / clip["fps"] <= 70
    assert len({a["action"].partition("_")[2] for a in clip["reference_actions"]}) >= 5


def test_baseline_busy_rejection_reproduces_the_visible_purple_right_punch():
    fixture = json.loads(
        (Path(__file__).parent / "fixtures/showcase/baseline-busy-punch.json").read_text(
            encoding="utf-8"
        )
    )
    resolver = CombatResolver()
    previous = -1
    for frame in fixture["frames"]:
        commands = [c for c in fixture["commands"] if previous < c["time_s"] <= frame["t"]]
        resolver.process(
            frame["world"], frame["states"], [[], commands], np.ones((2, 19), bool), frame["t"]
        )
        previous = frame["t"]
    rejected = next(e for e in resolver.events if "extension-1" in e["strike_id"])
    assert rejected["outcome"] == "recovery" and rejected["time_s"] == 18.3
    frame = next(f for f in fixture["frames"] if abs(f["t"] - 18.56667) < 0.00001)
    world = np.array(frame["world"])
    spec = attack_spec("right_straight")
    gap = min(
        segment_segment_distance(world[1, 10], world[1, 10], a, b)[0] - radius - spec["radius"]
        for _, a, b, radius in hurt_capsules(world[0], np.ones(19, bool))
    )
    assert gap < -0.01, (
        "The raw recorded right punch really intersects the head after being rejected."
    )


def test_short_profile_preserves_bones_floor_and_transition_continuity():
    boundaries = np.rint(np.cumsum([e[0] for e in showcase_plan()])[:-1] * 30).astype(int)
    for clip in rehearsal_pair(profile="showcase"):
        points, rest = clip["points"], clip["rest"]
        assert np.isfinite(points).all()
        for parent, child in EDGES:
            np.testing.assert_allclose(
                np.linalg.norm(points[:, child] - points[:, parent], axis=1),
                np.linalg.norm(rest[child] - rest[parent]),
                atol=1e-7,
            )
        assert points[:, [13, 17], 1].min() > -0.02
        for boundary in boundaries:
            assert np.linalg.norm(points[boundary] - points[boundary - 1], axis=1).max() < 0.15
        # A real airborne capture is retained instead of turning a walk into a hop.
        flight = np.array([m["intent"] == "spin_kick" for m in clip["performance"]])
        assert np.max(np.min(points[flight][:, [13, 17], 1], axis=1)) > 0.45


@pytest.fixture(scope="module")
def showcase_run():
    # The shipped short dolls, not a taller generic skeleton that hides misses.
    import runpy

    read_model = runpy.run_path(str(ROOT / "tools/prepare_unity.py"))["read_model"]
    rest, _, _ = read_model(ROOT / "data/avatars/local/nozomi-hybrid.vrm")
    return replay_run(
        {
            "source": "cmu_sparring",
            "rehearsal_profile": "showcase",
            "target_rest": rest.tolist(),
            "noise_mm": 0,
            "dropout": 0,
            "initial_gap": 1.7,
            "movement_gain": 1.0,
            "match_mode": "knockout",
        },
        include_duel=True,
    )


def test_showcase_resolves_real_ko_for_both_players_with_five_move_styles(showcase_run):
    duel = showcase_run["duel"]
    assert duel["finish_time"] > 0, "The showcase must finish through real HP damage."
    assert len(duel["rounds"]) == 1 and 0 in duel["rounds"][0]["health"]
    hits = [e for e in duel["events"] if e["damage"]]
    assert {e["attacker"] for e in hits} == {0, 1}
    assert len({e["action"].partition("_")[2] for e in hits}) >= 5
    assert any(e["outcome"] == "block" for e in duel["events"])
    assert not [e for e in duel["events"] if e["outcome"] == "recovery"], (
        "Single captured turns must not keep playing rejected/canceled punches."
    )
    final = next(f for f in duel["frames"] if f["match_state"] == "finished")
    assert all(f["health"] == final["health"] for f in duel["frames"] if f["t"] >= final["t"])


def test_showcase_export_has_a_conservative_subminute_wall_budget(showcase_run):
    _, timeline = export_duel(showcase_run)
    assert timeline.get("presentationProfile") == "showcase"
    assert timeline.get("presentationRate") == 1.2
    assert timeline["regulationDuration"] == 66
    assert 45 <= timeline["finishTime"] / timeline["presentationRate"] <= 55
    # Upper bound every contact at the largest current 75 ms hitstop. Real
    # overlaps share stop time, so summing is deliberately conservative.
    wall_upper = (
        timeline["finishTime"] / timeline["presentationRate"]
        + 1.35
        + len(timeline["contacts"]) * 0.075
    )
    assert wall_upper < 60
