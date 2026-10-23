import numpy as np
import pytest

from dollfight.combat import CombatResolver
from dollfight.duel import build_duel, world_joints
from dollfight.kinematics import rest_pose, rotation_y
from dollfight.locomotion import MovementMapper, separate_players
from dollfight.motions import ATTACKS, pose_at
from dollfight.pipeline import make_run
from dollfight.recognition import ActionRecognizer

VALID = np.ones((2, 19), dtype=bool)
OPEN = [{"defense": {"mode": "open"}} for _ in range(2)]


def pair(gap=0.65):
    frame = {"avatar": rest_pose().tolist()}
    return np.array(
        [world_joints(frame, [-gap / 2, 0, 0], 1), world_joints(frame, [gap / 2, 0, 0], -1)]
    )


def attack(player=0, action="left_straight", identifier="a"):
    attacks = [[], []]
    attacks[player] = [{"id": identifier, "action": action}]
    return attacks


def shield(time_limit=-1):
    return [
        OPEN[0],
        {
            "defense": {
                "mode": "high",
                "guard_sides": ["left"],
                "parry_side": "left",
                "parry_id": 1,
                "parry_until": time_limit,
            }
        },
    ]


def test_movement_maps_station_depth_not_body_heading_and_freezes_on_loss():
    origin = rest_pose()[0]
    mappers = [MovementMapper(origin, side=1), MovementMapper(origin, side=-1)]
    for i in range(30):
        points = (rest_pose() - origin) @ rotation_y(i / 29 * 2 * np.pi).T + origin
        points += [0.1, 0, 0.4]
        positions = [m.process(points, VALID[0], i / 30)[0] for m in mappers]
    assert positions[0][0] == pytest.approx(-1.1 + (0.4 - 0.025) * 1.5, abs=1e-3)
    assert positions[1][0] == pytest.approx(-positions[0][0])
    assert positions[0][2] < 0 < positions[1][2]
    invalid = VALID[0].copy()
    invalid[0] = False
    pos, info = mappers[0].process(rest_pose(), invalid, 1.0)
    np.testing.assert_allclose(pos, positions[0])
    assert "失跟踪" in info["state"]
    with pytest.raises(ValueError):
        mappers[0].process(rest_pose(), VALID[0], 1.0)


def test_movement_deadzone_speed_boundary_and_lane_order():
    mapper = MovementMapper(rest_pose()[0], side=1)
    pos, _ = mapper.process(rest_pose() + [0.01, 0, 0.01], VALID[0], 0)
    np.testing.assert_allclose(pos, [-1.1, 0, 0])
    last = pos
    for i in range(1, 90):
        pos, state = mapper.process(rest_pose() + [3, 0, 3], VALID[0], i / 30)
        assert np.linalg.norm(pos - last) <= 1.8 / 30 + 1e-8
        last = pos
    assert state["clamped"]
    assert state["mapped_forward_m"] <= (0.65 - 0.025) * 1.5 + 0.001
    ordered, limited = separate_players([[1, 0, 0.2], [-1, 0, -0.2]])
    assert limited and ordered[1, 0] - ordered[0, 0] == pytest.approx(0.55)
    np.testing.assert_allclose(ordered[:, 2], [0.2, -0.2])


def test_attack_event_at_distance_never_deals_damage():
    resolver, points = CombatResolver(), pair(3)
    for i in range(20):
        resolver.process(points, OPEN, attack() if i == 0 else [[], []], VALID, i / 30)
    assert resolver.health == [100, 100]
    assert [e["outcome"] for e in resolver.events] == ["out_of_range"]


def test_swept_contact_hits_between_frames_only_once():
    resolver, points = CombatResolver(), pair()
    points[0, 7] = [-0.4, 1.3, 0]
    resolver.process(points, OPEN, [[], []], VALID, 0)
    points[0, 7] = [0.8, 1.3, 0]
    resolver.process(points, OPEN, attack(), VALID, 1 / 30)
    for i in range(2, 20):
        resolver.process(points, OPEN, [[], []], VALID, i / 30)
    assert resolver.health == [100, 92]
    assert len(resolver.events) == 1


@pytest.mark.parametrize("parry_until,outcome", [(0.2, "parry"), (-1, "block")])
def test_forearm_contact_and_timed_parry(parry_until, outcome):
    resolver, points = CombatResolver(), pair()
    points[0, 7] = [0.15, 1.4, 0]
    points[1, 6], points[1, 7] = [0.14, 1.3, 0], [0.14, 1.7, 0]
    resolver.process(points, shield(parry_until), attack(), VALID, 0)
    assert resolver.events[0]["outcome"] == outcome
    assert resolver.health == [100, 100]
    if outcome == "parry":
        points[1, 10] = points[0, 2]
        resolver.process(points, OPEN, attack(1, "right_straight", "counter"), VALID, 0.2)
        assert resolver.events[-1]["counter"]
        assert resolver.health == [92, 100]


@pytest.mark.parametrize("failure", ["height", "facing", "missing"])
def test_guard_pose_alone_does_not_block_every_hit(failure):
    resolver, points = CombatResolver(), pair()
    if failure == "facing":
        points[1] = (points[1] - points[1, 0]) @ rotation_y(np.pi).T + points[1, 0]
    points[0, 7] = [0.15, 1.4, 0]
    points[1, 6], points[1, 7] = [0.14, 1.3, 0], [0.14, 1.7, 0]
    valid = VALID.copy()
    if failure == "height":
        points[1, [6, 7], 1] += 1
    if failure == "missing":
        valid[1, 6] = False
    resolver.process(points, shield(), attack(), valid, 0)
    assert resolver.events[0]["outcome"] == "hit"


def test_missing_attack_tip_cancels_and_expired_window_cannot_hit():
    resolver, points = CombatResolver(), pair()
    points[0, 7] = points[1, 2]
    valid = VALID.copy()
    valid[0, 7] = False
    resolver.process(points, OPEN, attack(), valid, 0)
    assert resolver.events[0]["outcome"] == "tracking_lost"
    assert resolver.health == [100, 100]
    resolver, points = CombatResolver(), pair(3)
    resolver.process(points, OPEN, attack(), VALID, 0)
    points[0, 7] = points[1, 2]
    resolver.process(points, OPEN, [[], []], VALID, 0.8)
    assert resolver.health == [100, 100]


def test_guard_break_and_hitstun_interrupt_active_attack():
    resolver, points = CombatResolver(), pair()
    points[0, 7] = [0.15, 1.4, 0]
    points[1, 6], points[1, 7] = [0.14, 1.3, 0], [0.14, 1.7, 0]
    resolver.guard_energy[1] = 2
    resolver.process(points, shield(), attack(), VALID, 0)
    assert resolver.events[0]["outcome"] == "guard_break"
    assert resolver.health == [100, 92]
    resolver.process(points, OPEN, attack(1), VALID, 0.03)
    assert resolver.events[-1]["outcome"] == "recovery"


@pytest.fixture(scope="module")
def duel_runs():
    config = {"source": "duel", "noise_mm": 5}
    return make_run(config), make_run(config, player=1), config


def test_independent_duel_exercises_distance_combo_defense_and_rotation(duel_runs):
    p1, p2, config = duel_runs
    duel = build_duel(p1, p2, config)
    events = duel["events"]
    assert events[0]["outcome"] == "out_of_range"
    assert any(e["combo_count"] == 3 for e in events)
    assert any(e["outcome"] == "block" for e in events)
    assert any(e["outcome"] == "parry" for e in events)
    assert any(e["counter"] for e in events)
    assert any(e["outcome"] == "hit" and "spin_backfist" in e["action"] for e in events)
    assert any(e["outcome"] == "hit" and "spin_kick" in e["action"] for e in events)
    assert all(e["damage"] == 0 for e in events if 7.6 < e["time_s"] < 11.5)
    assert all(f["positions"][1][0] - f["positions"][0][0] >= 0.5499 for f in duel["frames"])
    assert any(e.get("combo") for e in p1["events"])


def test_same_actions_without_approach_do_not_hit(duel_runs):
    p1, p2, config = duel_runs
    duel = build_duel(p1, p2, {**config, "movement_enabled": False})
    assert duel["frames"][-1]["health"] == [100, 100]
    assert len(duel["events"]) > 10
    assert all(e["outcome"] == "out_of_range" for e in duel["events"])


def test_world_root_is_translated_exactly_once():
    points = rest_pose() + [0.2, 0, 0.55]
    result = world_joints({"avatar": points.tolist()}, [-0.3, 0, 0.1], 1)
    np.testing.assert_allclose(result[0], [-0.3, points[0, 1], 0.1])
    expected = (points[7] - points[0]) @ rotation_y(np.pi / 2).T + result[0]
    np.testing.assert_allclose(result[7], expected)


@pytest.mark.parametrize(
    "kind", ["arms_down", "yaw_oscillation", "tracking_loss", "missing_elbow", "missing_knee"]
)
def test_turning_is_not_sufficient_evidence_for_a_spin_attack(kind):
    recognizer = ActionRecognizer(rest_pose())
    points = rest_pose()
    # An extended arm is only attack evidence if it is raised; oscillating the
    # trunk must not accumulate unsigned yaw into a full turn.
    points[7] = points[5] + ([0, -0.55, 0] if kind == "arms_down" else [0, 0, 0.55])
    points[10] = points[8] + [0, -0.55, 0]
    if kind == "missing_knee":
        points[7] = points[5] + [0, -0.55, 0]
        points[17] = points[15] + [0, 0, 0.75]
    actions = []
    for i in range(120):
        yaw = 0.6 * np.sin(i / 30 * 10) if kind == "yaw_oscillation" else i / 119 * 2 * np.pi
        rotated = (points - points[0]) @ rotation_y(yaw).T + points[0]
        valid = VALID[0].copy()
        if kind == "tracking_loss":
            valid[5] = False
        elif kind == "missing_elbow":
            valid[6] = False
        elif kind == "missing_knee":
            valid[16] = False
        events, _ = recognizer.process(rotated, valid, i / 30)
        actions.extend(e["action"] for e in events)
    assert not any("spin" in a for a in actions)


def test_fast_small_torso_twists_do_not_suppress_ordinary_attacks():
    recognizer = ActionRecognizer(rest_pose())
    actions = []
    for i in range(660):
        time_s = i / 30
        points, _ = pose_at(time_s)
        root = points[0].copy()
        points = (points - root) @ rotation_y(0.35 * np.sin(7 * time_s)).T + root
        found, _ = recognizer.process(points, VALID[0], time_s)
        actions.extend(e["action"] for e in found)
    assert actions == ATTACKS
