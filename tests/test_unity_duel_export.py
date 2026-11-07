import numpy as np
from test_animation_export import rotate

from dollfight.animation_export import export_duel
from dollfight.kinematics import PARENTS, rest_pose, rotation_y


def test_duel_export_maps_shared_clock_and_does_not_add_local_travel_twice():
    rest = rest_pose()
    identities = [[0, 0, 0, 1]] * 19
    source = [
        {"t": t, "root": [100 + t, rest[0, 1], 200], "rotations": identities} for t in (0, 1, 2)
    ]
    duel = [
        {
            "t": t,
            "opponent_frame": index,
            "positions": [[-0.8, 0, 0.1], [0.6, 0, -0.2]],
            "round": 1,
            "health": [100, 100],
            "distance_m": 1.4,
        }
        for t, index in ((0, 2), (1, 0), (2, 0))
    ]
    clips, timeline = export_duel(
        {
            "name": "test",
            "fps": 1,
            "duration": 2,
            "target_rest": rest,
            "frames": source,
            "duel": {"frames": duel, "opponent_frames": source},
        }
    )
    for player, clip in enumerate(clips):
        assert [f["time"] for f in clip["frames"]] == [0, 1, 2]
        yaw = (np.pi / 2, -np.pi / 2)[player]
        for frame in clip["frames"]:
            root = np.array([frame["root"][k] for k in "xyz"])
            expected = np.array(duel[0]["positions"][player]) + [0, rest[0, 1], 0]
            np.testing.assert_allclose(root, expected)
            for i, parent in enumerate(PARENTS):
                if parent >= 0:
                    delta = rest[i] - rest[parent]
                    np.testing.assert_allclose(
                        rotate(frame["rotations"][parent], delta),
                        rotation_y(yaw) @ delta,
                        atol=1e-8,
                    )
    assert timeline["version"] == "dollfight-duel-1"


def test_duel_export_preserves_authoritative_results_and_contact_geometry():
    rest = rest_pose()
    world = np.stack((rest + [-0.7, 0, 0], rest + [0.7, 0, 0]))
    source = [{"t": 0, "root": rest[0].tolist(), "rotations": [[0, 0, 0, 1]] * 19}]
    arena = {
        "t": 0,
        "opponent_frame": 0,
        "positions": [[-0.7, 0, 0], [0.7, 0, 0]],
        "round": 3,
        "health": [80, 0],
        "guard_energy": [75, 25],
        "distance_m": 1.4,
        "world": world.tolist(),
        "round_state": "finished",
        "round_winner": 0,
        "round_reason": "ko",
        "round_remaining": 4.5,
        "wins": [2, 1],
        "match_state": "finished",
        "match_winner": 0,
        "round_label": "P1 回合胜利 · KO",
        "match_label": "P1 比赛胜利",
        "active_attacks": [{"player": 0, "start": [0, 1, 0], "end": [0.2, 1, 0], "radius": 0.09}],
    }
    event = {"time_s": 0, "attacker": 0, "round": 3, "label": "命中 · 躯干", "damage": 13}
    _, timeline = export_duel(
        {
            "name": "test",
            "fps": 30,
            "duration": 1,
            "target_rest": rest,
            "frames": source,
            "duel": {"frames": [arena], "opponent_frames": source, "events": [event]},
        }
    )
    frame = timeline["frames"][0]
    assert frame["roundState"] == "finished"
    assert frame["roundWinner"] == 0 and frame["roundReason"] == "ko"
    assert frame["roundRemaining"] == 4.5
    assert frame["wins"] == [2, 1]
    assert frame["matchState"] == "finished" and frame["matchWinner"] == 0
    assert frame["roundLabel"] == arena["round_label"]
    assert frame["matchLabel"] == arena["match_label"]
    assert frame["guardEnergy"] == [75, 25]
    assert frame["lastContact"] == "P1 · 命中 · 躯干 · −13 HP"
    # Legacy snapshots may include a partial event; do not invent combat data.
    assert timeline["contacts"] == []
    head = next(c for c in frame["hurtCapsules"] if c["player"] == 0 and c["zone"] == "头部")
    assert head["a"] == dict(zip("xyz", world[0, 4], strict=True))
    assert head["radius"] == 0.14
    assert frame["attackCapsules"][0]["radius"] == 0.09


def test_duel_export_contacts_are_structured_sorted_and_round_unique():
    rest = rest_pose()
    source = [
        {"t": 0, "root": rest[0].tolist(), "rotations": [[0, 0, 0, 1]] * 19} for _ in range(2)
    ]
    arena = [
        {
            "t": 0,
            "opponent_frame": 0,
            "positions": [[-0.7, 0, 0], [0.7, 0, 0]],
            "round": round_number,
            "health": [100, 100],
            "distance_m": 1.4,
        }
        for round_number in (1, 2)
    ]

    def event(event_id, round_number, attacker, outcome, time_s, position):
        return {
            "id": event_id,
            "time_s": time_s,
            "round": round_number,
            "attacker": attacker,
            "defender": 1 - attacker,
            "action": "punch",
            "outcome": outcome,
            "label": f"{outcome} · 躯干",
            "damage": 8,
            "combo_count": 2,
            "counter": attacker == 1,
            "position": position,
        }

    events = [
        event("combat-2", 1, 1, "parry", 0.5, [1, 2, 3]),
        event("combat-1", 1, 0, "hit", 0.5, [-1, 0.5, 2]),
        event("combat-1", 2, 0, "block", 0.5, [4, 5, 6]),
        event("combat-3", 2, 0, "miss", 0.75, [0, 0, 0]),
    ]
    _, timeline = export_duel(
        {
            "name": "test",
            "fps": 30,
            "duration": 1,
            "target_rest": rest,
            "frames": source,
            "duel": {"frames": arena, "opponent_frames": source, "events": events},
        }
    )

    contacts = timeline["contacts"]
    assert [contact["id"] for contact in contacts] == [
        "r1-combat-2",
        "r1-combat-1",
        "r2-combat-1",
    ]
    assert len({contact["id"] for contact in contacts}) == 3
    assert [contact["attacker"] for contact in contacts] == [1, 0, 0]
    assert [contact["defender"] for contact in contacts] == [0, 1, 1]
    assert contacts[0] == {
        "id": "r1-combat-2",
        "time": 0.5,
        "round": 1,
        "attacker": 1,
        "defender": 0,
        "action": "punch",
        "outcome": "parry",
        "label": "parry · 躯干",
        "damage": 8.0,
        "comboCount": 2,
        "counter": True,
        "position": {"x": 1.0, "y": 2.0, "z": 3.0},
    }
