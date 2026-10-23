import numpy as np
import pytest

from dollfight.combat import CombatResolver
from dollfight.kinematics import EDGES, PARENTS, Retargeter, rest_pose, rotation_y
from dollfight.pipeline import load_clip, make_run
from dollfight.recognition import ActionRecognizer


def matrix(q):
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def test_pelvis_and_shoulders_do_not_turn_as_a_rigid_block():
    source = rest_pose()
    source[[5, 6, 7, 8, 9, 10]] = (source[[5, 6, 7, 8, 9, 10]] - source[2]) @ rotation_y(
        0.7
    ).T + source[2]
    _, q, _ = Retargeter(rest_pose(), foot_lock=False).process(source, 1 / 30)
    global_rot = []
    for i, parent in enumerate(PARENTS):
        global_rot.append(matrix(q[i]) if parent < 0 else global_rot[parent] @ matrix(q[i]))
    np.testing.assert_allclose(global_rot[0], np.eye(3), atol=1e-6)
    np.testing.assert_allclose(global_rot[2], rotation_y(0.7), atol=1e-6)


def test_lower_guard_capture_exposes_defense_below_the_chest():
    clip = load_clip("cmu_low_block")
    recognizer = ActionRecognizer(clip["rest"])
    low = 0
    for i, p in enumerate(clip["points"]):
        _, state = recognizer.process(p, np.ones(19, dtype=bool), i / clip["fps"])
        low += state["defense"]["mode"] == "low"
    assert low > 30  # genuine lower guard previously always appeared open


def test_mocap_calibration_and_short_leg_avatar_keep_grounded_support():
    clip = load_clip("cmu_roundhouse")
    assert 0.05 < clip["rest"][13, 1] < 0.2
    solver = Retargeter(clip["rest"], "power", foot_lock=True)
    ground_errors = []
    rotations = []
    for source in clip["points"]:
        target, q, _ = solver.process(source, 1 / 30)
        for foot in (13, 17):
            if source[foot, 1] < clip["rest"][foot, 1] + 0.035:
                ground_errors.append(abs(target[foot, 1] - solver.rest[foot, 1]))
        for a, b in EDGES:
            assert np.linalg.norm(target[b] - target[a]) == pytest.approx(
                np.linalg.norm(solver.rest[b] - solver.rest[a]), abs=1e-6
            )
        assert np.isfinite(q).all()
        rotations.append(q)
    assert np.percentile(ground_errors, 95) < 0.065
    rotations = np.asarray(rotations)
    jumps = np.rad2deg(
        2 * np.arccos(np.clip(abs(np.sum(rotations[:-1] * rotations[1:], axis=-1)), 0, 1))
    )
    # This real capture exposed 160–179 degree single-frame roll flips at an
    # almost straight support leg. It must not return when IK is changed.
    assert jumps[:, [11, 13, 15, 17]].max() < 70


@pytest.mark.parametrize(
    "name,expected",
    [
        ("cmu_roundhouse", ["right_roundhouse_kick", "left_roundhouse_kick"] * 2),
        ("cmu_front_kick", ["right_kick", "left_kick", "right_kick"]),
    ],
)
def test_reference_kicks_are_not_premature_knees_or_balancing_arm_punches(name, expected):
    run = make_run({"source": name, "noise_mm": 0})
    actual = [
        e["action"]
        for e in run["events"]
        if e["action"] not in ("crouch", "dodge_left", "dodge_right")
    ]
    assert actual == expected
    assert all("basis" not in e for e in run["events"])
    assert all(e["basis"] == "authored_reference" for e in run["reference_actions"])


def pair():
    p = np.array([rest_pose(), rest_pose() + [0, 0, 0.6]])
    p[0, 7] = p[1, 2]  # deliberately touching before windup: must NOT hit
    return p


VALID = np.ones((2, 19), dtype=bool)
OPEN = [{"defense": {"mode": "open"}} for _ in range(2)]


def command(player=0, identifier="a"):
    result = [[], []]
    result[player] = [
        {
            "id": identifier,
            "action": "left_straight",
            "timing": {"startup": 0.3, "active": 0.15, "recovery": 0.4},
        }
    ]
    return result


def test_startup_and_recovery_change_damage_and_action_acceptance():
    resolver, p = CombatResolver(), pair()
    for i in range(9):
        state, _ = resolver.process(p, OPEN, command() if i == 0 else [[], []], VALID, i / 30)
        assert resolver.health == [100, 100]
        assert state["action_phase"][0] == "startup"
    resolver.process(p, OPEN, [[], []], VALID, 0.3)
    assert resolver.health == [100, 92]
    resolver.process(p, OPEN, command(identifier="too-soon"), VALID, 0.6)
    assert resolver.events[-1]["outcome"] == "recovery"
    resolver.process(p, OPEN, command(identifier="ready-again"), VALID, 0.9)
    assert resolver.strikes[-1].id.endswith("ready-again")


def test_recovery_is_punishable_and_startup_can_be_interrupted():
    resolver, p = CombatResolver(), pair()
    p[0, 7] = [-2, 1.3, 0]  # whiff
    p[1, 7] = p[0, 2]
    resolver.process(p, OPEN, command(), VALID, 0)
    for i in range(1, 18):
        resolver.process(p, OPEN, [[], []], VALID, i / 30)
    resolver.process(p, OPEN, [[], [{"id": "punish", "action": "left_straight"}]], VALID, 0.6)
    assert resolver.events[-1]["punish"] == "后摇惩罚"
    assert resolver.health[0] == 90
    resolver = CombatResolver()
    resolver.process(p, OPEN, command(), VALID, 0)
    resolver.process(p, OPEN, [[], [{"id": "interrupt", "action": "left_straight"}]], VALID, 0.1)
    resolver.process(p, OPEN, [[], []], VALID, 0.13)
    assert any(e["punish"] == "截击前摇" for e in resolver.events)
    assert not resolver.strikes
