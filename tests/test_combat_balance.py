"""Rules and geometry regressions, independent of the authored choreography."""

import numpy as np
import pytest

from dollfight.combat import CombatResolver, attack_spec

VALID = np.ones((2, 19), dtype=bool)
OPEN = [{"defense": {"mode": "open"}} for _ in range(2)]


def arena():
    points = np.zeros((2, 19, 3))
    for p, x in enumerate((-1.0, 1.0)):
        points[p] = [x, 0, 0]
        points[p, 0] = [x, 1, 0]
        points[p, 2] = [x, 1.5, 0]
        points[p, 4] = [x, 1.9, 0]
        points[p, [11, 15]] = [x, 0.9, 0]
        points[p, [12, 16]] = [x, 0.5, 0]
        points[p, [13, 17]] = [x, 0.1, 0]
    return points


def command(p=0, action="left_straight", identifier="a", timing=None):
    attacks = [[], []]
    event = {"id": identifier, "action": action}
    if timing is not None:
        event["timing"] = timing
    attacks[p] = [event]
    return attacks


@pytest.mark.parametrize(
    "action,bounds,base",
    [
        ("straight", (6, 10), 8),
        ("hook", (8, 12), 10),
        ("uppercut", (9, 13), 11),
        ("backfist", (8, 12), 10),
        ("spin_backfist", (12, 17), 14),
        ("knee", (10, 15), 12),
        ("kick", (11, 16), 13),
        ("side_kick", (13, 19), 16),
        ("roundhouse_kick", (14, 20), 17),
        ("spin_kick", (17, 24), 20),
    ],
)
def test_move_bounds_and_left_right_symmetry(action, bounds, base):
    left, right = attack_spec("left_" + action), attack_spec("right_" + action)
    assert (left["damage_min"], left["damage_max"]) == bounds
    assert left["damage"] == base == right["damage"]
    assert left["recovery"] == right["recovery"]


def test_body_zone_changes_damage_without_randomness():
    dealt = []
    for y in (0.3, 1.3, 1.9):
        resolver, points = CombatResolver(), arena()
        points[0, 7] = [1, y, 0]
        resolver.process(points, OPEN, command(), VALID, 0)
        dealt.append(resolver.events[0]["damage"])
    assert dealt == [6, 8, 10]


def test_foot_tip_capsule_can_hit_when_ankle_stays_outside():
    resolver, points = CombatResolver(), arena()
    points[0, 13], points[0, 14] = [0.4, 1.3, 0], [0.95, 1.3, 0]
    resolver.process(points, OPEN, command(action="left_side_kick"), VALID, 0)
    assert resolver.health == [100, 84]


def test_same_time_contacts_trade_and_allow_double_ko():
    resolver, points = CombatResolver(), arena()
    points[0, 7], points[1, 7] = [1, 1.3, 0], [-1, 1.3, 0]
    resolver.health = [8, 8]
    resolver.process(points, OPEN, [command()[0], command(1)[1]], VALID, 0)
    assert resolver.health == [0, 0]
    assert [e["outcome"] for e in resolver.events] == ["hit", "hit"]


@pytest.mark.parametrize("first", (0, 1))
def test_earlier_contact_interrupts_later_contact_for_either_player(first):
    resolver, points = CombatResolver(), arena()
    points[0, 7], points[1, 7] = [-0.5, 1.3, 0], [0.5, 1.3, 0]
    resolver.process(points, OPEN, [command()[0], command(1)[1]], VALID, 0)
    points[first, 7] = points[1 - first, 2] - [0, 0.2, 0]
    points[1 - first, 7] = points[first, 2] - [0, 0.2, 0]
    # The first player's fist travels faster, contacting earlier in this frame.
    points[first, 7, 0] += 0.8 if first == 0 else -0.8
    resolver.process(points, OPEN, [[], []], VALID, 0.1)
    hits = [e for e in resolver.events if e["damage"]]
    assert len(hits) == 1 and hits[0]["attacker"] == first


def test_duplicate_event_id_never_creates_a_second_strike():
    resolver, points = CombatResolver(), arena()
    points[0, 7] = [1, 1.3, 0]
    resolver.process(points, OPEN, command(), VALID, 0)
    resolver.process(points, OPEN, command(), VALID, 1)
    assert resolver.health == [100, 92]
    assert len(resolver.events) == 1


def test_target_tracking_recovery_does_not_sweep_a_phantom_body():
    resolver, points = CombatResolver(), arena()
    points[0, 7] = [0, 1.3, 0]
    missing = VALID.copy()
    missing[1, [0, 2, 4, 11, 12, 13, 15, 16, 17]] = False
    points[1, :, 0] = -1
    resolver.process(points, OPEN, [[], []], missing, 0)
    points[1, :, 0] = 1
    resolver.process(points, OPEN, command(), VALID, 0.1)
    assert resolver.health == [100, 100]


def test_command_startup_and_expiry_never_damage_outside_active_interval():
    resolver, points = CombatResolver(), arena()
    timing = {"startup": 0.1, "active": 0.1, "recovery": 0.2}
    points[0, 7] = [1, 1.3, 0]
    resolver.process(points, OPEN, command(timing=timing), VALID, 0)
    assert resolver.health == [100, 100]
    points[0, 7] = [-1, 1.3, 0]
    resolver.process(points, OPEN, [[], []], VALID, 0.05)
    resolver.process(points, OPEN, [[], []], VALID, 0.2)
    points[0, 7] = [1, 1.3, 0]
    resolver.process(points, OPEN, [[], []], VALID, 0.25)
    assert resolver.health == [100, 100]


def test_guard_break_locks_attacks_for_full_break_duration():
    from test_duel import attack, pair, shield

    resolver, points = CombatResolver(), pair()
    points[0, 7] = [0.15, 1.4, 0]
    points[1, 6], points[1, 7] = [0.14, 1.3, 0], [0.14, 1.7, 0]
    resolver.guard_energy[1] = 0
    resolver.process(points, shield(), attack(), VALID, 0)
    resolver.process(points, OPEN, attack(1, identifier="late"), VALID, 0.3)
    assert resolver.events[-1]["outcome"] == "recovery"
    assert resolver.recovery_until[1] >= 0.8


@pytest.mark.parametrize(
    "kind",
    [
        "straight",
        "hook",
        "uppercut",
        "spin_backfist",
        "knee",
        "kick",
        "side_kick",
        "roundhouse_kick",
        "spin_kick",
    ],
)
@pytest.mark.parametrize("zone,y", [("腿部", 0.3), ("躯干", 1.3), ("头部", 1.9)])
@pytest.mark.parametrize("punish", [False, True])
def test_every_move_zone_and_punish_stays_within_damage_bounds(kind, zone, y, punish):
    resolver, points = CombatResolver(), arena()
    spec = attack_spec("left_" + kind)
    points[0, [spec["joint"], spec["end_joint"]]] = [1, y, 0]
    if punish:
        resolver.action_windows[1] = (1.0, 2.0, 3.0)
    resolver.process(points, OPEN, command(action="left_" + kind), VALID, 0)
    event = resolver.events[0]
    assert event["zone"] == zone
    assert spec["damage_min"] <= event["damage"] <= spec["damage_max"]
    assert bool(event["punish"]) == punish


@pytest.mark.parametrize("side,joint", [("left", 7), ("right", 10)])
@pytest.mark.parametrize("mirrored", [False, True])
def test_mutual_contacts_have_equal_damage_and_chain_state(side, joint, mirrored):
    resolver, points = CombatResolver(), arena()
    points[0, joint], points[1, joint] = [1, 1.3, 0], [-1, 1.3, 0]
    if mirrored:
        points = points[::-1].copy()
    strikes = [command(action=side + "_straight")[0], command(1, side + "_straight")[1]]
    state, events = resolver.process(points, OPEN, strikes, VALID, 0)
    assert state["health"] == [92, 92]
    assert [event["damage"] for event in events] == [8, 8]
    assert state["chains"][0] == state["chains"][1]


def test_missing_toe_uses_ankle_only_instead_of_invalid_foot_geometry():
    resolver, points = CombatResolver(), arena()
    points[0, 13], points[0, 14] = [0.4, 1.3, 0], [1, 1.3, 0]
    valid = VALID.copy()
    valid[0, 14] = False
    resolver.process(points, OPEN, command(action="left_kick"), valid, 0)
    assert resolver.health == [100, 100]


def test_fast_crossing_uses_both_moving_players_and_only_one_hit():
    resolver, points = CombatResolver(), arena()
    points[0, 7] = [-1, 1.3, 0]
    resolver.process(points, OPEN, command(), VALID, 0)
    points[0, 7] = [2, 1.3, 0]
    points[1, :, 0] = -0.5
    resolver.process(points, OPEN, [[], []], VALID, 0.1)
    assert resolver.health == [100, 92]
    assert len([e for e in resolver.events if e["damage"]]) == 1


def test_interrupted_strike_stays_cancelled_after_stun_ends_inside_same_frame():
    resolver, points = CombatResolver(), arena()
    points[0, 7], points[1, 7] = [0.71, 1.3, 0], [1, 1.3, 0]
    resolver.process(points, OPEN, [command()[0], command(1)[1]], VALID, 0)
    points[0, 7], points[1, 7] = [1, 1.3, 0], [-0.73, 1.3, 0]
    resolver.process(points, OPEN, [[], []], VALID, 0.2)
    assert resolver.health == [100, 92]
    assert [event["outcome"] for event in resolver.events] == ["hit", "recovery"]


@pytest.mark.parametrize("delay", [0.3, 30.0])
def test_gap_without_reliable_sweep_history_never_backdates_new_contact(delay):
    resolver, points = CombatResolver(), arena()
    resolver.process(points, OPEN, [[], []], VALID, 0)
    points[0, 7] = [1, 1.3, 0]
    resolver.process(points, OPEN, command(), VALID, delay)
    assert resolver.events[-1]["time_s"] == delay


def test_newly_observed_target_can_only_be_hit_at_current_sample_time():
    resolver, points = CombatResolver(), arena()
    points[0, 7] = [1, 1.3, 0]
    valid = VALID.copy()
    valid[1, [0, 2]] = False
    resolver.process(points, OPEN, [[], []], valid, 0)
    resolver.process(points, OPEN, command(), VALID, 0.1)
    assert resolver.events[-1]["time_s"] == 0.1
