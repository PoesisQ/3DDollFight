"""Deterministic ordinary attacks; all distances are arena metres."""

# min, max, base, active seconds, recovery seconds, reach, guard cost
MOVES = {
    "straight": (6, 10, 8, 0.32, 0.18, 0.83, 15),
    "hook": (8, 12, 10, 0.32, 0.24, 0.78, 17),
    "uppercut": (9, 13, 11, 0.32, 0.28, 0.75, 18),
    "backfist": (8, 12, 10, 0.32, 0.24, 0.83, 17),
    "spin_backfist": (12, 17, 14, 0.85, 0.45, 0.95, 22),
    "knee": (10, 15, 12, 0.35, 0.30, 0.70, 19),
    "kick": (11, 16, 13, 0.40, 0.35, 1.20, 20),
    "side_kick": (13, 19, 16, 0.40, 0.45, 1.30, 23),
    "roundhouse_kick": (14, 20, 17, 0.45, 0.50, 1.30, 24),
    "spin_kick": (17, 24, 20, 0.85, 0.60, 1.35, 28),
}


def attack_spec(action):
    side, separator, kind = action.partition("_")
    if not separator or side not in ("left", "right") or kind not in MOVES:
        return None
    offset = 0 if side == "left" else 1
    low, high, base, duration, recovery, reach, guard_cost = MOVES[kind]
    kick = kind.endswith("kick")
    joint = (13, 17)[offset] if kick else (12, 16)[offset] if kind == "knee" else (7, 10)[offset]
    return {
        "joint": joint,
        "end_joint": (14, 18)[offset] if kick else joint,
        "radius": 0.12 if kick or kind == "knee" else 0.09,
        "damage_min": low,
        "damage_max": high,
        "damage": base,
        "duration": duration,
        "reach": reach,
        # Recognizer events arrive after recognizing motion, unlike commands.
        "startup": 0.0,
        "recovery": recovery,
        "guard_cost": guard_cost,
    }


def hit_damage(spec, zone, punish=False):
    adjustment = {"头部": 2, "腿部": -2}.get(zone, 0) + (2 if punish else 0)
    return min(spec["damage_max"], max(spec["damage_min"], spec["damage"] + adjustment))
