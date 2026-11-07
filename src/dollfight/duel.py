"""Evaluate two pose streams in one arena; reproducible even when scrubbing backwards."""

from collections import Counter

import numpy as np

from dollfight.combat import CombatResolver
from dollfight.duel_fixture import CHAPTERS
from dollfight.kinematics import rotation_y
from dollfight.locomotion import MovementMapper, separate_players
from dollfight.match import (
    KNOCKOUT_REGULATION_SECONDS,
    knockout_match_result,
    match_result,
    round_result,
    round_schedule,
)
from dollfight.motion_reference import REVIEW_CHAPTERS
from dollfight.sparring import SHOWCASE_PRESENTATION_RATE, SHOWCASE_REGULATION_SECONDS


def world_joints(frame, position, side):
    points = np.asarray(frame["avatar"]).copy()
    points -= [points[0, 0], 0, points[0, 2]]
    return points @ rotation_y(side * np.pi / 2).T + position


def build_duel(primary, secondary, config):
    match_mode = config.get("match_mode", "rounds")
    if match_mode not in ("rounds", "knockout"):
        raise ValueError("Unknown match mode")
    knockout = match_mode == "knockout"
    showcase = config.get("rehearsal_profile") == "showcase"
    regulation_seconds = SHOWCASE_REGULATION_SECONDS if showcase else KNOCKOUT_REGULATION_SECONDS
    paired = secondary is not None
    second = secondary if paired else primary
    mappers = [
        MovementMapper(
            run["frames"][0]["root"] if run["source"].startswith("cmu_") else run["source_rest"][0],
            side=side,
            gain=config.get("movement_gain", 1.5),
            initial_gap=config.get("initial_gap", 2.2),
            enabled=config.get("movement_enabled", True),
            mode="mocap" if run["source"].startswith("cmu_") else "station",
        )
        for run, side in ((primary, 1), (second, -1))
    ]
    event_maps = [{event["id"]: event for event in run["events"]} for run in (primary, second)]
    references = [run.get("reference_actions", []) for run in (primary, second)]
    combat = CombatResolver()
    completed_events = []
    rounds = []
    schedule, round_numbers = round_schedule(
        primary["frames"], primary["duration"], fps=primary["fps"]
    )
    if knockout:
        schedule = [
            {
                "round": 1,
                "start": primary["frames"][0]["t"],
                "end": primary["frames"][0]["t"] + regulation_seconds,
                "last_index": len(primary["frames"]) - 1,
            }
        ]
        round_numbers = [1] * len(primary["frames"])
    round_index = 0
    current_round = schedule[0]["round"]
    verdict = None
    frozen_result = None
    frames = []
    for i, frame in enumerate(primary["frames"]):
        round_number = round_numbers[i]
        if round_number != current_round:
            completed_events.extend(combat.events)
            combat = CombatResolver()
            current_round = round_number
            round_index += 1
            verdict = None
            frozen_result = None
        delay = 0 if paired else round(4.5 * primary["fps"])
        other_index = min(max(0, i - delay), len(second["frames"]) - 1)
        sources = [frame, second["frames"][other_index]]
        valid = [np.array([q == "observed" for q in f["quality"]]) for f in sources]
        mapped = [
            mapper.process(
                np.asarray(f["avatar"] if mapper.mode == "mocap" else f["solved"]),
                reliable,
                frame["t"],
            )
            for mapper, f, reliable in zip(mappers, sources, valid, strict=True)
        ]
        positions, limited = separate_players([value[0] for value in mapped])
        world = np.array(
            [
                world_joints(f, position, side)
                for f, position, side in zip(sources, positions, (1, -1), strict=True)
            ]
        )
        attacks = [
            [event_maps[p][event_id] for event_id in sources[p]["event_ids"]]
            if p == 0 or i >= delay
            else []
            for p in range(2)
        ]
        # Reference playback uses independently authored hit windows. Recognition
        # events remain unchanged and visible, and are used for all other inputs.
        for p, source_frame in enumerate(sources):
            if references[p] and (p == 0 or i >= delay):
                source_t = source_frame["t"]
                previous_t = (
                    -1
                    if (i == 0 or (p == 1 and i == delay))
                    else (
                        primary["frames"][i - 1]["t"]
                        if p == 0
                        else second["frames"][max(0, other_index - 1)]["t"]
                    )
                )
                # Reference kick windows must not suppress every recognized punch
                # elsewhere in a composed recording.
                annotated = {e["action"] for e in references[p]}
                attacks[p] = [e for e in attacks[p] if e["action"] not in annotated] + [
                    e for e in references[p] if previous_t < e["time_s"] <= source_t
                ]
            intent = source_frame.get("performance", {}).get("intent")
            if intent in ("guard", "advance", "retreat", "side", "low_block"):
                attacks[p] = []  # Authored rehearsal intent, never a classifier label.
            elif intent:
                attacks[p] = [e for e in attacks[p] if "basis" in e]
        states = [f["recognition"] for f in sources]
        clock = schedule[round_index]
        if verdict is None:
            at_deadline = not knockout and frame["t"] >= clock["end"]
            if at_deadline and frozen_result is not None:
                result = {**frozen_result}
            else:
                result, _ = combat.process(
                    world, states, [[], []] if at_deadline else attacks, valid, frame["t"]
                )
            at_end = i == clock["last_index"]
            verdict = round_result(current_round, combat.health, frame["t"])
            if verdict is None and not knockout:
                verdict = round_result(
                    current_round, combat.health, clock["end"], timeout=at_end or at_deadline
                )
            if verdict is not None:
                rounds.append(verdict)
                result["active_attacks"] = []
                result["recovery"] = [False, False]
                result["action_phase"] = ["round_over", "round_over"]
            frozen_result = {**result, "event_ids": []}
        else:
            # Keep the authored animation moving, but never regenerate guard,
            # accept commands or apply damage after this round's verdict.
            result = {**frozen_result}
        for event in combat.events:
            if "round" not in event:
                event["round"] = current_round
                event["id"] = f"r{current_round}-{event['id']}"
        result["event_ids"] = [f"r{current_round}-{event_id}" for event_id in result["event_ids"]]
        match_time = verdict["time_s"] if knockout and verdict is not None else frame["t"]
        overtime = knockout and match_time >= clock["end"]
        match = (
            knockout_match_result(verdict, overtime=overtime)
            if knockout
            else match_result(rounds, len(schedule))
        )
        frames.append(
            {
                "t": frame["t"],
                "opponent_frame": other_index,
                "positions": positions.round(5).tolist(),
                "world": world.round(5).tolist(),
                "movement": [value[1] for value in mapped],
                "separation_limited": limited,
                "distance_m": round(
                    float(np.linalg.norm((positions[0] - positions[1])[[0, 2]])), 3
                ),
                "round": current_round,
                "overtime": overtime,
                "round_time": round(frame["t"] - clock["start"], 4),
                "round_state": "finished" if verdict is not None else "active",
                "round_winner": verdict["winner"] if verdict is not None else -1,
                "round_reason": verdict["reason"] if verdict is not None else "",
                "round_remaining": round(max(0, clock["end"] - match_time), 4)
                if knockout or verdict is None
                else 0,
                "round_label": match["label"]
                if knockout
                else verdict["label"]
                if verdict is not None
                else "",
                "wins": match["wins"],
                "match_state": match["state"],
                "match_winner": match["winner"],
                "match_label": match["label"],
                "intent": [f.get("performance", {}).get("label", "") for f in sources],
                "defense": [
                    state.get("defense", {"mode": "open", "label": "未设防"}) for state in states
                ],
                **result,
            }
        )
    completed_events.extend(combat.events)
    rehearsal = primary["name"] == "cmu_sparring"
    return {
        "frames": frames,
        "events": completed_events,
        "rounds": rounds,
        "match": match,
        "match_mode": match_mode,
        "regulation_duration": regulation_seconds if knockout else 30.0,
        "presentation_profile": "showcase" if showcase else "legacy",
        "presentation_rate": SHOWCASE_PRESENTATION_RATE if showcase else 0.75,
        "finish_time": next((f["t"] for f in frames if f["match_state"] == "finished"), -1),
        "opponent_frames": second["frames"] if paired else None,
        "opponent_events": second["events"],
        "chapters": CHAPTERS
        if primary["name"] == "duel"
        else primary.get("chapters")
        or [
            {
                "time_s": max(0, e["time_s"] - 0.1),
                "label": f"{i + 1}. {e['label']}",
                "detail": (
                    f"真人动作参考 · 前摇 {e['timing']['startup']:.2f} s / "
                    f"有效 {e['timing']['active']:.2f} s / "
                    f"后摇 {e['timing']['recovery']:.2f} s"
                ),
            }
            for i, e in enumerate(references[0])
        ]
        or REVIEW_CHAPTERS.get(primary["name"], []),
        "paired": paired,
        "summary": dict(Counter(event["outcome"] for event in completed_events)),
        "movement_gain": float(config.get("movement_gain", 1.5)),
        "initial_gap": float(config.get("initial_gap", 2.2)),
        "description": "一分钟展示 · 单局 KO 决胜 · 真人动捕编排"
        if showcase
        else "三分钟单局 · KO 决胜；时间到加时 · 真人动捕排练"
        if knockout
        else "90 秒 / 三回合双人排练 · 真人动捕经轨迹与步幅编辑 · 非实机采集"
        if rehearsal
        else "独立双人合成输入"
        if paired
        else (
            "真人动作回放 · P2 延后 4.5 s · 攻击窗口为参考标注"
            if references[0]
            else "P2 为同段输入延后 4.5 s；非真实双人"
        ),
        "limitations": [
            "无相机接入；移动由米制骨盆位移模拟相机输出。",
            "当前是有序的 2.5D 对战区域；限制站位范围并防止穿过对手。",
            "碰撞使用球/胶囊近似；姿态输入未叠加受击动画。",
        ],
    }
