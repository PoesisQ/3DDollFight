"""Round results are visible snapshots, not post-hoc labels on a replay."""

from copy import deepcopy

from dollfight.animation_export import export_duel
from dollfight.duel import build_duel
from dollfight.kinematics import rest_pose
from dollfight.match import match_result, round_result, round_schedule


def recording(winners, *, duration=30):
    """Tiny static streams with enough direct contacts to finish selected rounds."""
    streams = []
    times = [
        round(rnd * duration + t, 4)
        for rnd in range(len(winners))
        for t in [*(i * 0.75 for i in range(17)), duration - 0.1]
    ]
    for player in range(2):
        events, frames = [], []
        for index, time_s in enumerate(times):
            rnd = int(time_s // duration)
            points = rest_pose()
            points[7] = [0, 1.2, 1.2]
            event_ids = []
            if winners[rnd] == player and time_s % duration < 13:
                identifier = f"p{player}-{index}"
                events.append({"id": identifier, "action": "left_straight"})
                event_ids.append(identifier)
            frames.append(
                {
                    "t": time_s,
                    "avatar": points.tolist(),
                    "solved": points.tolist(),
                    "quality": ["observed"] * 19,
                    "event_ids": event_ids,
                    "recognition": {"defense": {"mode": "open"}},
                    "performance": {"round": rnd + 1, "round_time": time_s % duration},
                }
            )
        streams.append(
            {
                "name": "test",
                "source": "synthetic",
                "fps": 10,
                "duration": times[-1],
                "source_rest": rest_pose().tolist(),
                "frames": frames,
                "events": events,
            }
        )
    return build_duel(*streams, {"initial_gap": 1.2, "movement_enabled": False})


def test_timeout_draws_finish_on_each_rounds_last_visible_frame():
    duel = recording([-1, -1, -1])
    assert [r["winner"] for r in duel["rounds"]] == [-1, -1, -1]
    assert all(r["reason"] == "timeout" for r in duel["rounds"])
    assert all(r["health"] == [100, 100] for r in duel["rounds"])
    assert duel["frames"][0]["round_state"] == "active"
    assert duel["frames"][0]["round_remaining"] == 30
    for frame in duel["frames"]:
        if frame["round_time"] > 29:
            assert frame["round_state"] == "finished"
            assert frame["round_remaining"] == 0
    assert duel["frames"][-1]["match_state"] == "finished"
    assert duel["match"]["winner"] == -1


def test_ko_locks_health_and_events_until_next_round_and_resets_health():
    duel = recording([0, -1])
    first = duel["rounds"][0]
    assert first["winner"] == 0
    assert first["reason"] == "ko"
    assert first["health"] == [100, 0]
    ended = next(f for f in duel["frames"] if f["round_state"] == "finished")
    later = [f for f in duel["frames"] if ended["t"] < f["t"] < 30]
    assert later
    assert all(f["health"] == ended["health"] for f in later)
    assert all(f["guard_energy"] == ended["guard_energy"] for f in later)
    assert all(f["active_attacks"] == [] and f["event_ids"] == [] for f in later)
    assert all(e["time_s"] <= ended["t"] for e in duel["events"] if e["round"] == 1)
    second_start = next(f for f in duel["frames"] if f["round"] == 2)
    assert second_start["health"] == [100, 100]
    assert second_start["guard_energy"] == [100, 100]
    assert second_start["action_phase"] == ["ready", "ready"]


def test_match_uses_round_wins_and_does_not_leak_future_results():
    duel = recording([0, 0, 1])
    assert [r["winner"] for r in duel["rounds"]] == [0, 0, 1]
    assert duel["match"]["wins"] == [2, 1]
    assert duel["match"]["winner"] == 0
    final = duel["frames"][-1]
    assert final["match_winner"] == 0
    assert final["wins"] == [2, 1]
    # Continue the whole authored rehearsal even after P1 wins two rounds.
    third_start = next(f for f in duel["frames"] if f["round"] == 3)
    assert third_start["match_state"] == "active"
    assert third_start["match_winner"] == -1
    assert third_start["wins"] == [2, 0]
    assert duel["frames"][0]["wins"] == [0, 0]
    assert duel["frames"][0]["round_winner"] == -1


def test_equal_round_wins_is_a_draw_without_total_health_tiebreak():
    duel = recording([0, 1, -1])
    assert duel["match"]["wins"] == [1, 1]
    assert duel["match"]["winner"] == -1
    assert duel["frames"][-1]["match_label"] == "比赛平局 · 1 : 1"


def quiet_recording(times, duration, *, final_attack=False, authored=False):
    stream = {
        "name": "test",
        "source": "synthetic",
        "fps": 10,
        "duration": duration,
        "source_rest": rest_pose().tolist(),
        "events": [],
        "frames": [
            {
                "t": t,
                "avatar": rest_pose().tolist(),
                "solved": rest_pose().tolist(),
                "quality": ["observed"] * 19,
                "event_ids": [],
                "recognition": {"defense": {"mode": "open"}},
            }
            for t in times
        ],
    }
    if authored:
        for frame in stream["frames"]:
            frame["performance"] = {"round": 1, "round_time": frame["t"]}
    second = deepcopy(stream)
    if final_attack:
        stream["events"] = [{"id": "late", "action": "left_straight"}]
        stream["frames"][-1]["event_ids"] = ["late"]
        stream["frames"][-1]["avatar"][7] = [0, 1.2, 1.2]
    return build_duel(stream, second, {"initial_gap": 1.2, "movement_enabled": False})


def test_double_ko_is_a_draw_and_does_not_award_a_win():
    result = round_result(1, [0, 0], 3)
    assert result["winner"] == -1
    assert result["reason"] == "double_ko"
    match = match_result([result], 1)
    assert match["state"] == "finished"
    assert match["winner"] == -1
    assert match["wins"] == [0, 0]


def test_timeout_awards_the_player_with_more_remaining_health():
    assert round_result(1, [80, 20], 30) is None
    result = round_result(1, [80, 20], 30, timeout=True)
    assert result["winner"] == 0
    assert result["health"] == [80, 20]
    assert result["reason"] == "timeout"
    assert round_result(1, [10, 90], 30, timeout=True)["winner"] == 1


def test_short_unannotated_clip_uses_its_duration_as_a_single_round():
    duel = quiet_recording([0, 0.5, 1], 1)
    assert len(duel["rounds"]) == 1
    assert duel["frames"][0]["round_remaining"] == 1
    assert duel["frames"][1]["round_remaining"] == 0.5
    assert duel["rounds"][0]["time_s"] == 1
    assert duel["frames"][-1]["match_state"] == "finished"


def test_long_unannotated_clip_splits_at_thirty_seconds_not_at_next_sample():
    duel = quiet_recording([0, 29.9, 30.1, 49.9], 50)
    assert [r["round"] for r in duel["rounds"]] == [1, 2]
    assert [r["time_s"] for r in duel["rounds"]] == [30, 50]
    assert duel["frames"][1]["round_state"] == "finished"
    assert duel["frames"][2]["round"] == 2
    assert duel["frames"][2]["round_remaining"] == 19.9
    assert duel["frames"][-1]["match_state"] == "finished"


def test_new_attack_at_exact_deadline_cannot_change_the_timeout_result():
    duel = quiet_recording([0, 30], 30, final_attack=True)
    assert duel["rounds"][0]["health"] == [100, 100]
    assert duel["rounds"][0]["winner"] == -1
    assert duel["events"] == []
    assert duel["frames"][-1]["round_reason"] == "timeout"


def test_short_annotated_clip_also_uses_its_actual_duration():
    duel = quiet_recording([0, 0.5, 1], 1, authored=True)
    assert duel["frames"][0]["round_remaining"] == 1
    assert duel["rounds"][0]["time_s"] == 1


def test_an_authored_round_cannot_continue_past_its_thirty_second_deadline():
    duel = quiet_recording([0, 31, 32], 32, authored=True)
    assert duel["frames"][1]["round_state"] == "finished"
    assert duel["rounds"][0]["time_s"] == 30


def test_full_rehearsals_last_pose_represents_the_nominal_ninetieth_second():
    frames = [
        {
            "t": index / 30,
            "performance": {"round": index // 900 + 1, "round_time": index % 900 / 30},
        }
        for index in range(2700)
    ]
    schedule, numbers = round_schedule(frames, frames[-1]["t"], fps=30)
    assert [r["end"] for r in schedule] == [30, 60, 90]
    assert numbers[-1] == 3


def knockout_recording(times, attacks, *, guarded=False):
    """Actual geometric contacts spanning authored rounds and the regulation clock."""
    streams = []
    for player in range(2):
        frames, events = [], []
        for index, time_s in enumerate(times):
            points = rest_pose()
            points[7] = [0, 1.2, 1.2]
            if guarded and player == 1:
                points[6] = points[7] = [0, 1.2, 0]
            event_ids = []
            if time_s in attacks[player]:
                identifier = f"p{player}-{index}"
                events.append({"id": identifier, "action": "left_straight"})
                event_ids.append(identifier)
            frames.append(
                {
                    "t": time_s,
                    "avatar": points.tolist(),
                    "solved": points.tolist(),
                    "root": rest_pose()[0].tolist(),
                    "rotations": [[0, 0, 0, 1]] * 19,
                    "quality": ["observed"] * 19,
                    "event_ids": event_ids,
                    "recognition": {
                        "defense": {"mode": "guard" if guarded and player == 1 else "open"}
                    },
                    "performance": {"round": int(time_s // 30) + 1},
                }
            )
        streams.append(
            {
                "name": "test",
                "source": "synthetic",
                "fps": 10,
                "duration": times[-1],
                "source_rest": rest_pose().tolist(),
                "target_rest": rest_pose().tolist(),
                "frames": frames,
                "events": events,
            }
        )
    config = {"match_mode": "knockout", "initial_gap": 1.2, "movement_enabled": False}
    return {**streams[0], "duel": build_duel(*streams, config)}


def test_knockout_keeps_health_and_guard_across_authored_choreography_boundaries():
    times = [0, 29.5, 29.9, 30, 30.1]
    for guarded in (False, True):
        duel = knockout_recording(times, [[29.5], []], guarded=guarded)["duel"]
        before, after = duel["frames"][2:4]
        assert before["health"] == after["health"]
        if guarded:
            assert before["guard_energy"][1] < 100
            assert after["guard_energy"][1] == round(before["guard_energy"][1] + 0.3, 1)
            assert duel["events"][0]["outcome"] == "block"
        else:
            assert after["health"][1] < 100
        assert all(f["round"] == 1 and f["round_state"] == "active" for f in duel["frames"])
        assert duel["rounds"] == []
        assert duel["match"]["state"] == "active"


def test_knockout_regulation_expiry_never_awards_health_advantage_and_late_attacks_can_win():
    late = [136 + index * 0.75 for index in range(16)]
    times = [0, 29.5, 30, 60, 90, 134.9, 135, *late, 151]
    duel = knockout_recording(times, [[29.5, *late], []])["duel"]
    deadline = next(f for f in duel["frames"] if f["t"] == 135)
    assert deadline["health"][0] > deadline["health"][1] > 0
    assert deadline["round_remaining"] == 0 and deadline["overtime"]
    assert deadline["round_state"] == deadline["match_state"] == "active"
    assert deadline["match_winner"] == -1 and deadline["wins"] == [0, 0]
    assert "加时" in deadline["match_label"]
    verdict = duel["rounds"][0]
    assert verdict["reason"] == "ko" and verdict["winner"] == 0
    assert duel["finish_time"] > 135
    assert duel["frames"][-1]["health"] == [100, 0]
    assert duel["match"]["state"] == "finished"


def test_knockout_stream_exhaustion_remains_active_without_inventing_a_winner():
    for end in (90, 140):
        duel = knockout_recording([0, 1, 30, 60, end], [[1], []])["duel"]
        assert duel["rounds"] == []
        assert duel["match"]["state"] == "active" and duel["match"]["winner"] == -1
        assert duel["finish_time"] == -1
        assert duel["frames"][-1]["overtime"] == (end >= 135)


def test_knockout_double_ko_is_same_frame_and_freezes_all_later_combat():
    strikes = [index * 0.75 for index in range(17)]
    duel = knockout_recording([*strikes, 29.9, 30, 60, 140], [strikes, strikes])["duel"]
    ended = next(f for f in duel["frames"] if f["match_state"] == "finished")
    assert ended["health"] == [0, 0]
    assert ended["round_reason"] == "double_ko"
    assert ended["match_winner"] == -1 and ended["wins"] == [0, 0]
    assert len(ended["event_ids"]) == 2
    for frame in duel["frames"]:
        if frame["t"] > ended["t"]:
            assert frame["health"] == ended["health"]
            assert frame["guard_energy"] == ended["guard_energy"]
            assert frame["event_ids"] == frame["active_attacks"] == []
            assert frame["round_remaining"] == ended["round_remaining"] > 0
            assert not frame["overtime"]
    assert all(event["time_s"] <= ended["t"] for event in duel["events"])


def test_knockout_export_metadata_uses_actual_finish_and_globally_unique_contacts():
    strikes = [index * 0.75 for index in range(17)]
    run = knockout_recording([*strikes, 30, 60], [strikes, []])
    _, timeline = export_duel(run)
    first_finished = next(f for f in timeline["frames"] if f["matchState"] == "finished")
    assert timeline["matchMode"] == "knockout" and timeline["roundCount"] == 1
    assert timeline["regulationDuration"] == 135
    assert timeline["finishTime"] == first_finished["time"] == run["duel"]["finish_time"]
    assert all(f["round"] == 1 and not f["overtime"] for f in timeline["frames"])
    identifiers = [c["id"] for c in timeline["contacts"]]
    assert len(set(identifiers)) == len(identifiers)
    assert all(identifier.startswith("r1-combat-") for identifier in identifiers)
    assert not any(identifier.startswith("r1-r1-") for identifier in identifiers)
    assert max(c["time"] for c in timeline["contacts"]) <= timeline["finishTime"]
    _, unfinished = export_duel(knockout_recording([0, 135, 140], [[], []]))
    assert unfinished["finishTime"] == -1
    assert unfinished["frames"][-1]["overtime"]
