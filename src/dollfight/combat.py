"""Geometry-driven two-player combat. Recognizing an attack never implies a hit."""

from dataclasses import dataclass, field

import numpy as np

from dollfight.kinematics import body_basis

OUTCOMES = {
    "hit": "命中",
    "block": "格挡",
    "parry": "精准拨挡",
    "guard_break": "破防",
    "evaded": "移动 / 闪避成功",
    "miss": "挥空",
    "out_of_range": "距离外",
    "tracking_lost": "失跟踪·取消",
    "recovery": "前后摇 / 硬直·未提交",
}


def attack_spec(action):
    side = 0 if action.startswith("left") else 1
    if action.endswith(("straight", "hook", "uppercut", "backfist")):
        spin = "spin" in action
        return {
            "joint": (7, 10)[side],
            "radius": 0.09,
            "damage": 16 if spin else 8,
            "duration": 0.85 if spin else 0.32,
            "reach": 0.95 if spin else 0.83,
            "startup": 0.0,
            "recovery": 0.45 if spin else 0.18,
        }
    if action.endswith(("kick", "knee")):
        spin = "spin" in action
        return {
            "joint": (12, 16)[side] if action.endswith("knee") else (13, 17)[side],
            "radius": 0.12,
            "damage": 18 if spin else 12,
            "duration": 0.85 if spin else 0.4,
            "reach": 1.2,
            "startup": 0.0,
            "recovery": 0.6 if spin else 0.35,
        }
    return None


def point_segment_distance(point, a, b):
    ab = b - a
    alpha = np.clip((point - a) @ ab / max(ab @ ab, 1e-12), 0, 1)
    closest = a + alpha * ab
    return float(np.linalg.norm(point - closest)), closest


def hurt_capsules(points, valid):
    result = []
    if valid[4]:
        result.append(("头部", points[4], points[4], 0.14))
    if valid[0] and valid[2]:
        result.append(("躯干", points[0], points[2], 0.19))
    for a, b in ((11, 12), (15, 16)):
        if valid[a] and valid[b]:
            result.append(("腿部", points[a], points[b], 0.09))
    return result


@dataclass
class Strike:
    id: str
    player: int
    action: str
    start: float
    spec: dict
    target_start: np.ndarray
    minimum_root_distance: float = 99.0
    stationary_contact: bool = False
    ended: bool = False
    closest_gap: float = 99.0
    last_tip: np.ndarray = field(default_factory=lambda: np.zeros(3))


class CombatResolver:
    def __init__(self):
        self.health = [100, 100]
        self.guard_energy = [100.0, 100.0]
        self.recovery_until = [0.0, 0.0]
        self.busy_until = [0.0, 0.0]
        self.action_windows = [None, None]
        self.guard_broken_until = [0.0, 0.0]
        self.last_hit_time = [-10.0, -10.0]
        self.last_parry_time = [-10.0, -10.0]
        self.parry_used = [-1, -1]
        self.chains = [0, 0]
        self.previous = None
        self.previous_time = None
        self.previous_valid = None
        self.strikes = []
        self.events = []

    def finish(self, strike, outcome, time_s, position, *, zone="", guard_side=None, defense=None):
        p, other = strike.player, 1 - strike.player
        damage = 0
        counter = False
        punish = ""
        if outcome == "block":
            cost = 23 if "spin" in strike.action else 15
            if self.guard_energy[other] < cost:
                outcome = "guard_break"
                self.guard_broken_until[other] = time_s + 0.8
            self.guard_energy[other] = max(0, self.guard_energy[other] - cost)
            self.recovery_until[p] = max(self.recovery_until[p], time_s + 0.12)
        if outcome == "parry":
            self.parry_used[other] = defense["parry_id"]
            self.last_parry_time[other] = time_s
            self.recovery_until[p] = time_s + 0.4
        if outcome in ("hit", "guard_break"):
            damage = strike.spec["damage"]
            window = self.action_windows[other]
            if window and time_s < window[0]:
                punish = "截击前摇"
            elif window and window[1] <= time_s < window[2]:
                punish = "后摇惩罚"
            if punish:
                damage += 2
            self.health[other] = max(0, self.health[other] - damage)
            self.chains[p] = self.chains[p] + 1 if time_s - self.last_hit_time[p] < 1.1 else 1
            self.last_hit_time[p] = time_s
            self.chains[other] = 0
            self.recovery_until[other] = max(self.recovery_until[other], time_s + 0.16)
            counter = time_s - self.last_parry_time[p] < 1.3
        else:
            self.chains[p] = 0
        label = OUTCOMES[outcome]
        if zone and damage:
            label += " · " + zone
        if counter:
            label = "拨挡反击 · " + label
        elif punish:
            label = punish + " · " + label
        event = {
            "id": f"combat-{len(self.events) + 1}",
            "time_s": round(time_s, 4),
            "attacker": p,
            "defender": other,
            "action": strike.action,
            "outcome": outcome,
            "label": label,
            "damage": damage,
            "zone": zone,
            "combo_count": self.chains[p] if damage else 0,
            "counter": counter,
            "punish": punish,
            "position": np.asarray(position).round(5).tolist(),
            "guard_side": guard_side,
            "strike_id": strike.id,
            "closest_gap_m": round(max(0, strike.closest_gap), 4),
        }
        self.events.append(event)
        strike.ended = True

    def process(self, points, states, attacks, valid, time_s):
        points = np.asarray(points, dtype=float)
        valid = np.asarray(valid, dtype=bool)
        dt = 1 / 30 if self.previous_time is None else time_s - self.previous_time
        if dt <= 0:
            raise ValueError("Combat timestamps must increase")
        previous = points if self.previous is None or dt > 0.2 else self.previous
        begin = len(self.events)
        for p in range(2):
            if time_s - self.last_hit_time[p] > 1.1:
                self.chains[p] = 0
            mode = states[p].get("defense", {}).get("mode", "open")
            self.guard_energy[p] = min(
                100, self.guard_energy[p] + dt * (3 if mode != "open" else 9)
            )
            for event in attacks[p]:
                spec = attack_spec(event["action"])
                if spec is None:
                    continue
                timing = event.get("timing")
                if timing is not None:
                    if not all(
                        np.isfinite(timing[k]) and 0 <= timing[k] <= 3
                        for k in ("startup", "active", "recovery")
                    ):
                        raise ValueError("攻击时序必须是 0–3 秒的有限数值")
                    spec.update(
                        startup=timing["startup"],
                        duration=timing["active"],
                        recovery=timing["recovery"],
                        command=True,
                    )
                strike = Strike(
                    f"p{p + 1}/{event['id']}",
                    p,
                    event["action"],
                    time_s,
                    spec,
                    points[1 - p].copy(),
                )
                if self.health[p] == 0 or time_s < max(self.recovery_until[p], self.busy_until[p]):
                    self.finish(strike, "recovery", time_s, points[p, spec["joint"]])
                else:
                    self.strikes.append(strike)
                    active_at = time_s + spec["startup"]
                    active_end = active_at + spec["duration"]
                    self.busy_until[p] = active_end + spec["recovery"]
                    self.action_windows[p] = (active_at, active_end, self.busy_until[p])
        active_display = []
        for strike in self.strikes:
            if strike.ended:
                continue
            p, other, joint = strike.player, 1 - strike.player, strike.spec["joint"]
            if self.health[p] == 0 or time_s < self.recovery_until[p]:
                self.finish(strike, "recovery", time_s, points[p, joint])
                continue
            if not (valid[p, joint] and valid[p, 0] and valid[other, 0]):
                self.finish(strike, "tracking_lost", time_s, points[p, joint])
                continue
            tip0, tip1 = previous[p, joint], points[p, joint]
            if self.previous_valid is not None and not self.previous_valid[p, joint]:
                tip0 = tip1
            strike.last_tip = tip1
            gap = float(np.linalg.norm((points[p, 0] - points[other, 0])[[0, 2]]))
            strike.minimum_root_distance = min(strike.minimum_root_distance, gap)
            if time_s < strike.start + strike.spec["startup"]:
                continue
            relative_travel = np.linalg.norm(tip1 - tip0) + np.max(
                np.linalg.norm(points[other] - previous[other], axis=1)
            )
            steps = int(np.clip(np.ceil(relative_travel / 0.025), 2, 40))
            defense = states[other].get("defense", {"mode": "open"})
            facing = body_basis(points[other])[:, 2] @ (points[p, 0] - points[other, 0]) > 0
            guard_allowed = (
                defense["mode"] != "open"
                and facing
                and time_s >= self.guard_broken_until[other]
                and time_s >= self.busy_until[other]
            )
            # Samples interpolate both players, avoiding endpoint-only tunnelling.
            # Never extend a hit window by a whole extra frame at low frame rates.
            previous_time = time_s if self.previous_time is None else self.previous_time
            active_start = strike.start + strike.spec["startup"]
            active_end = active_start + strike.spec["duration"]
            start_alpha = (
                np.clip((active_start - previous_time) / dt, 0, 1)
                if strike.spec.get("command")
                else 0
            )
            end_alpha = np.clip((active_end - previous_time) / dt, 0, 1)
            sample_alphas = np.linspace(start_alpha, end_alpha, steps + 1)
            if (
                previous_time >= active_end
                or start_alpha > end_alpha
                or (dt > 0.2 and time_s > active_end)
            ):
                sample_alphas = []
            for alpha in sample_alphas:
                tip = tip0 + alpha * (tip1 - tip0)
                target = previous[other] + alpha * (points[other] - previous[other])
                for _, a, b, radius in hurt_capsules(strike.target_start, valid[other]):
                    if point_segment_distance(tip, a, b)[0] <= radius + strike.spec["radius"]:
                        strike.stationary_contact = True
                if guard_allowed:
                    for side, elbow, wrist in (("left", 6, 7), ("right", 9, 10)):
                        if side not in defense.get("guard_sides", ["left", "right"]):
                            continue
                        if not (valid[other, elbow] and valid[other, wrist]):
                            continue
                        distance, contact = point_segment_distance(
                            tip, target[elbow], target[wrist]
                        )
                        if distance <= 0.10 + strike.spec["radius"]:
                            strike.closest_gap = min(
                                strike.closest_gap, distance - 0.10 - strike.spec["radius"]
                            )
                            parry = (
                                defense.get("parry_side") == side
                                and time_s <= defense.get("parry_until", -1)
                                and defense.get("parry_id", -1) != self.parry_used[other]
                            )
                            self.finish(
                                strike,
                                "parry" if parry else "block",
                                time_s,
                                contact,
                                guard_side=side,
                                defense=defense,
                            )
                            break
                if strike.ended:
                    break
                for zone, a, b, radius in hurt_capsules(target, valid[other]):
                    distance, contact = point_segment_distance(tip, a, b)
                    strike.closest_gap = min(
                        strike.closest_gap, distance - radius - strike.spec["radius"]
                    )
                    if distance <= radius + strike.spec["radius"]:
                        self.finish(strike, "hit", time_s, contact, zone=zone)
                        break
                if strike.ended:
                    break
            if not strike.ended and time_s >= active_end:
                outcome = (
                    "evaded"
                    if strike.stationary_contact
                    else "out_of_range"
                    if strike.minimum_root_distance > strike.spec["reach"]
                    else "miss"
                )
                self.finish(strike, outcome, time_s, tip1)
            if not strike.ended:
                active_display.append(
                    {
                        "player": p,
                        "action": strike.action,
                        "start": tip0.round(5).tolist(),
                        "end": tip1.round(5).tolist(),
                        "radius": strike.spec["radius"],
                    }
                )
        self.strikes = [strike for strike in self.strikes if not strike.ended]
        self.previous, self.previous_time = points.copy(), time_s
        self.previous_valid = valid.copy()
        return {
            "health": self.health.copy(),
            "guard_energy": [round(v, 1) for v in self.guard_energy],
            "chains": self.chains.copy(),
            "active_attacks": active_display,
            "event_ids": [e["id"] for e in self.events[begin:]],
            "recovery": [time_s < v for v in self.recovery_until],
            "action_phase": [
                "hitstun"
                if time_s < self.recovery_until[p]
                else "startup"
                if w and time_s < w[0]
                else "active"
                if w and time_s < w[1]
                else "recovery"
                if w and time_s < w[2]
                else "ready"
                for p, w in enumerate(self.action_windows)
            ],
        }, self.events[begin:]
