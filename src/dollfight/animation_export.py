"""Portable replay artifact for Unity Humanoid. Not a camera transport protocol."""

import numpy as np

from dollfight.combat import hurt_capsules
from dollfight.kinematics import PARENTS, quaternion, rotation_y


def multiply(a, b):
    av, bv = np.asarray(a[:3]), np.asarray(b[:3])
    return np.r_[a[3] * bv + b[3] * av + np.cross(av, bv), a[3] * b[3] - av @ bv]


def vector(v):
    return dict(zip(("x", "y", "z"), map(float, v), strict=True))


def export_animation(run):
    frames = []
    for frame in run["frames"]:
        global_rotations = []
        for i, parent in enumerate(PARENTS):
            q = np.array(frame["rotations"][i])
            if parent >= 0:
                q = multiply(global_rotations[parent], q)
            q /= np.linalg.norm(q)
            global_rotations.append(q)
        frames.append(
            {
                "time": frame["t"],
                "root": vector(frame["root"]),
                "handClose": float(
                    frame.get("performance", {}).get(
                        "hand_close", frame.get("action_timing", {}).get("hand_close", 0.15)
                    )
                ),
                "rotations": [
                    dict(zip(("x", "y", "z", "w"), map(float, q), strict=True))
                    for q in global_rotations
                ],
            }
        )
    return {
        "version": "dollfight-humanoid-1",
        "coordinates": "stage_rh_y_up_meters",
        "rotationSpace": "global_delta_from_canonical_t_pose",
        "source": run["name"],
        "fps": run["fps"],
        "rest": [vector(p) for p in run["target_rest"]],
        "frames": frames,
    }


def export_duel(run):
    """Same arena roots/headings as Motion Lab, applied exactly once.

    Both output streams use the shared rehearsal clock, including repeated or
    remapped opponent indices. Canonical root X/Z is already represented by
    duel.positions, so adding it again would cause the old runaway translation.
    """
    duel = run["duel"]
    contact_outcomes = {"hit", "block", "parry", "guard_break"}
    contact_events = []
    for event in duel.get("events", []):
        # Older saved replays may contain recognition-only events without the
        # resolved combat payload. Keep those out of the authoritative stream.
        required = (
            "id",
            "time_s",
            "round",
            "attacker",
            "defender",
            "action",
            "outcome",
            "label",
            "damage",
            "combo_count",
            "counter",
            "position",
        )
        if not all(key in event for key in required) or event["outcome"] not in contact_outcomes:
            continue
        round_number = int(event["round"])
        prefix = f"r{round_number}-"
        contact_events.append(
            {
                "id": event["id"]
                if str(event["id"]).startswith(prefix)
                else prefix + str(event["id"]),
                "time": float(event["time_s"]),
                "round": round_number,
                "attacker": int(event["attacker"]),
                "defender": int(event["defender"]),
                "action": str(event["action"]),
                "outcome": str(event["outcome"]),
                "label": str(event["label"]),
                "damage": float(event["damage"]),
                "comboCount": int(event["combo_count"]),
                "counter": bool(event["counter"]),
                "position": vector(event["position"]),
            }
        )
    contact_events.sort(key=lambda event: event["time"])
    players = []
    for player, yaw in enumerate((np.pi / 2, -np.pi / 2)):
        source = run["frames"] if player == 0 else duel.get("opponent_frames") or run["frames"]
        frames = []
        heading = quaternion(rotation_y(yaw))
        for i, arena in enumerate(duel["frames"]):
            frame = source[i if player == 0 else arena["opponent_frame"]]
            rotations = np.array(frame["rotations"], dtype=float)
            rotations[0] = multiply(heading, rotations[0])
            root = np.array(arena["positions"][player], dtype=float)
            root[1] += frame["root"][1]
            frames.append({**frame, "t": arena["t"], "root": root, "rotations": rotations})
        players.append(export_animation({**run, "frames": frames}))
    snapshots = []
    for f in duel["frames"]:
        capsules = []
        if "world" in f:
            world = np.asarray(f["world"])
            for player in range(2):
                source = (
                    run["frames"] if player == 0 else duel.get("opponent_frames") or run["frames"]
                )
                index = len(snapshots) if player == 0 else f["opponent_frame"]
                valid = np.array(
                    [q == "observed" for q in source[index].get("quality", ["observed"] * 19)]
                )
                for zone, a, b, radius in hurt_capsules(world[player], valid):
                    capsules.append(
                        {
                            "player": player,
                            "zone": zone,
                            "a": vector(a),
                            "b": vector(b),
                            "radius": radius,
                        }
                    )
        contacts = [
            e
            for e in duel.get("events", [])
            if (
                e["time_s"] <= f["t"] + 0.0001
                and e.get("round", f["round"]) == f["round"]
                and e.get("outcome", "hit") in ("hit", "block", "parry", "guard_break")
            )
        ]
        contact = contacts[-1] if contacts else None
        snapshots.append(
            {
                "time": f["t"],
                "round": f["round"],
                "overtime": bool(f.get("overtime", False)),
                "health": f["health"],
                "distance": f["distance_m"],
                "intent": f.get("intent", [""])[0],
                "guardEnergy": f.get("guard_energy", [100, 100]),
                "roundState": f.get("round_state", "active"),
                "roundWinner": f.get("round_winner", -1),
                "roundReason": f.get("round_reason", ""),
                "roundRemaining": f.get("round_remaining", max(0, 30 - (f.get("round_time") or 0))),
                "wins": f.get("wins", [0, 0]),
                "matchState": f.get("match_state", "active"),
                "matchWinner": f.get("match_winner", -1),
                "roundLabel": f.get("round_label", ""),
                "matchLabel": f.get("match_label", ""),
                "lastContact": (
                    f"P{contact['attacker'] + 1} · {contact['label']}"
                    + (f" · −{contact['damage']} HP" if contact["damage"] else "")
                )
                if contact
                else "",
                "lastContactTime": contact["time_s"] if contact else -1,
                "hurtCapsules": capsules,
                "attackCapsules": [
                    {
                        "player": a["player"],
                        "zone": "攻击",
                        "a": vector(a.get("weapon_start", a["end"])),
                        "b": vector(a.get("weapon_end", a["end"])),
                        "radius": a["radius"],
                    }
                    for a in f.get("active_attacks", [])
                ],
            }
        )
    timeline = {
        "version": "dollfight-duel-1",
        "duration": run["duration"],
        "fps": run["fps"],
        "source": "CMU motion capture rehearsal; not live camera input",
        "roundCount": max(f["round"] for f in duel["frames"]),
        "matchMode": duel.get("match_mode", "rounds"),
        "presentationProfile": duel.get("presentation_profile", "legacy"),
        "presentationRate": float(duel.get("presentation_rate", 0.75)),
        "regulationDuration": float(duel.get("regulation_duration", 30)),
        "finishTime": float(
            next((f["t"] for f in duel["frames"] if f.get("match_state") == "finished"), -1)
        ),
        "contacts": contact_events,
        "frames": snapshots,
    }
    return players, timeline
