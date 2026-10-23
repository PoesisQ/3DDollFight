"""Evaluate two pose streams in one arena; reproducible even when scrubbing backwards."""

from collections import Counter

import numpy as np

from dollfight.combat import CombatResolver
from dollfight.duel_fixture import CHAPTERS
from dollfight.kinematics import rotation_y
from dollfight.locomotion import MovementMapper, separate_players
from dollfight.motion_reference import REVIEW_CHAPTERS


def world_joints(frame, position, side):
    points = np.asarray(frame["avatar"]).copy()
    points -= [points[0, 0], 0, points[0, 2]]
    return points @ rotation_y(side * np.pi / 2).T + position


def build_duel(primary, secondary, config):
    paired = secondary is not None
    second = secondary if paired else primary
    mappers = [
        MovementMapper(
            run["source_rest"][0],
            side=side,
            gain=config.get("movement_gain", 1.5),
            initial_gap=config.get("initial_gap", 2.2),
            enabled=config.get("movement_enabled", True),
        )
        for run, side in ((primary, 1), (second, -1))
    ]
    event_maps = [{event["id"]: event for event in run["events"]} for run in (primary, second)]
    references = [run.get("reference_actions", []) for run in (primary, second)]
    combat = CombatResolver()
    frames = []
    for i, frame in enumerate(primary["frames"]):
        delay = 0 if paired else round(4.5 * primary["fps"])
        other_index = min(max(0, i - delay), len(second["frames"]) - 1)
        sources = [frame, second["frames"][other_index]]
        valid = [np.array([q == "observed" for q in f["quality"]]) for f in sources]
        mapped = [
            mapper.process(np.asarray(f["solved"]), reliable, frame["t"])
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
                attacks[p] = [e for e in references[p] if previous_t < e["time_s"] <= source_t]
        states = [f["recognition"] for f in sources]
        result, _ = combat.process(world, states, attacks, valid, frame["t"])
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
                "defense": [
                    state.get("defense", {"mode": "open", "label": "未设防"}) for state in states
                ],
                **result,
            }
        )
    return {
        "frames": frames,
        "events": combat.events,
        "opponent_frames": second["frames"] if paired else None,
        "opponent_events": second["events"],
        "chapters": CHAPTERS
        if paired
        else [
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
        "summary": dict(Counter(event["outcome"] for event in combat.events)),
        "movement_gain": float(config.get("movement_gain", 1.5)),
        "initial_gap": float(config.get("initial_gap", 2.2)),
        "description": "独立双人合成输入"
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
