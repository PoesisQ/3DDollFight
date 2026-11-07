"""Geometry-driven two-player combat. Recognizing an attack never implies a hit."""

from dataclasses import dataclass, field
from itertools import groupby

import numpy as np

from dollfight.combat_rules import attack_spec, hit_damage
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


def point_segment_distance(point, a, b):
    ab = b - a
    alpha = np.clip((point - a) @ ab / max(ab @ ab, 1e-12), 0, 1)
    closest = a + alpha * ab
    return float(np.linalg.norm(point - closest)), closest


def segment_segment_distance(a, b, c, d):
    """Distance between closed segments, also handling spheres/parallel axes."""
    if np.array_equal(a, b):
        return point_segment_distance(a, c, d)
    u, v, w = b - a, d - c, a - c
    uu, uv, vv, uw, vw = u @ u, u @ v, v @ v, u @ w, v @ w
    denominator = uu * vv - uv * uv
    if denominator > 1e-12:
        s, t = (uv * vw - vv * uw) / denominator, (uu * vw - uv * uw) / denominator
        if 0 <= s <= 1 and 0 <= t <= 1:
            return float(np.linalg.norm(a + s * u - c - t * v)), c + t * v
    candidates = [point_segment_distance(p, c, d) for p in (a, b)]
    candidates.extend((point_segment_distance(p, a, b)[0], p) for p in (c, d))
    return min(candidates, key=lambda item: item[0])


def hurt_capsules(points, valid):
    result = []
    if valid[4]:
        result.append(("头部", points[4], points[4], 0.14))
    if valid[0] and valid[2]:
        result.append(("躯干", points[0], points[2], 0.19))
    for a, b in ((11, 12), (12, 13), (15, 16), (16, 17)):
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
    target_valid: np.ndarray = field(default_factory=lambda: np.ones(19, dtype=bool))
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
        self.seen_attacks = set()

    def finish(self, strike, outcome, time_s, position, *, zone="", guard_side=None, defense=None):
        p, other = strike.player, 1 - strike.player
        damage = 0
        counter = False
        punish = ""
        if outcome == "block":
            cost = strike.spec["guard_cost"]
            if self.guard_energy[other] < cost:
                outcome = "guard_break"
                self.guard_broken_until[other] = time_s + 0.8
                self.recovery_until[other] = max(self.recovery_until[other], time_s + 0.8)
            self.guard_energy[other] = max(0, self.guard_energy[other] - cost)
            self.recovery_until[p] = max(self.recovery_until[p], time_s + 0.12)
        if outcome == "parry":
            self.parry_used[other] = defense["parry_id"]
            self.last_parry_time[other] = time_s
            self.recovery_until[p] = max(self.recovery_until[p], time_s + 0.4)
        if outcome in ("hit", "guard_break"):
            window = self.action_windows[other]
            if window and time_s < window[0]:
                punish = "截击前摇"
            elif window and window[1] <= time_s < window[2]:
                punish = "后摇惩罚"
            damage = hit_damage(strike.spec, zone, bool(punish))
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
            "damage_range": [strike.spec["damage_min"], strike.spec["damage_max"]],
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

    def _contact(self, strike, previous, points, valid, states, time_s, dt, steps):
        p, other = strike.player, 1 - strike.player
        joint, end_joint = strike.spec["joint"], strike.spec["end_joint"]
        # Missing toes degrade the foot capsule to an ankle sphere.
        end_joint = end_joint if valid[p, end_joint] else joint
        has_history = self.previous_time is not None and dt <= 0.2
        previous_time = self.previous_time if has_history else time_s
        span = time_s - previous_time
        active_start = strike.start + strike.spec["startup"]
        active_end = active_start + strike.spec["duration"]
        if previous_time >= active_end or (dt > 0.2 and time_s > active_end):
            return None
        start_alpha = (
            float(np.clip((active_start - previous_time) / dt, 0, 1))
            if strike.spec.get("command")
            else 0.0
        )
        if has_history and not (
            self.previous_valid[p, joint] and self.previous_valid[p, end_joint]
        ):
            start_alpha = 1.0
        end_alpha = float(np.clip((active_end - previous_time) / dt, 0, 1))
        if time_s < active_start or start_alpha > end_alpha:
            return None
        # Every strike shares the same sampling clock, so identical-time
        # contacts do not gain an ordering advantage from different speeds.
        alphas = np.unique(np.r_[start_alpha, np.arange(steps + 1) / steps, end_alpha])
        alphas = alphas[(alphas >= start_alpha) & (alphas <= end_alpha)]
        defense = states[other].get("defense", {"mode": "open"})
        for alpha in alphas:
            contact_time = previous_time + float(alpha) * span
            target = previous[other] + alpha * (points[other] - previous[other])
            target_valid = valid[other]
            if has_history and alpha < 1:
                target_valid = target_valid & self.previous_valid[other]
            weapon_a = previous[p, joint] + alpha * (points[p, joint] - previous[p, joint])
            weapon_b = previous[p, end_joint] + alpha * (
                points[p, end_joint] - previous[p, end_joint]
            )
            for _, a, b, radius in hurt_capsules(strike.target_start, strike.target_valid):
                if segment_segment_distance(weapon_a, weapon_b, a, b)[0] <= (
                    radius + strike.spec["radius"]
                ):
                    strike.stationary_contact = True
            facing = body_basis(target)[:, 2] @ (points[p, 0] - target[0]) > 0
            guard_allowed = (
                defense["mode"] != "open"
                and facing
                and contact_time >= self.guard_broken_until[other]
                and contact_time >= self.busy_until[other]
                and contact_time >= self.recovery_until[other]
            )
            if guard_allowed:
                for side, elbow, wrist in (("left", 6, 7), ("right", 9, 10)):
                    if side not in defense.get("guard_sides", ["left", "right"]):
                        continue
                    if not (target_valid[elbow] and target_valid[wrist]):
                        continue
                    distance, contact = segment_segment_distance(
                        weapon_a, weapon_b, target[elbow], target[wrist]
                    )
                    if distance <= 0.10 + strike.spec["radius"]:
                        strike.closest_gap = min(
                            strike.closest_gap, distance - 0.10 - strike.spec["radius"]
                        )
                        return {
                            "strike": strike,
                            "time": contact_time,
                            "position": contact,
                            "outcome": "block",
                            "guard_side": side,
                            "defense": defense,
                        }
            for zone, a, b, radius in hurt_capsules(target, target_valid):
                distance, contact = segment_segment_distance(weapon_a, weapon_b, a, b)
                strike.closest_gap = min(
                    strike.closest_gap, distance - radius - strike.spec["radius"]
                )
                if distance <= radius + strike.spec["radius"]:
                    return {
                        "strike": strike,
                        "time": contact_time,
                        "position": contact,
                        "outcome": "hit",
                        "zone": zone,
                    }
        return None

    def process(self, points, states, attacks, valid, time_s):
        points = np.asarray(points, dtype=float)
        valid = np.asarray(valid, dtype=bool) & np.isfinite(points).all(axis=2)
        points = np.nan_to_num(points)
        dt = 1 / 30 if self.previous_time is None else time_s - self.previous_time
        if not np.isfinite(time_s) or dt <= 0:
            raise ValueError("Combat timestamps must increase and be finite")
        previous = points.copy() if self.previous is None or dt > 0.2 else self.previous.copy()
        if self.previous_valid is not None:
            # Never sweep through an unobserved endpoint from the previous frame.
            previous[~self.previous_valid] = points[~self.previous_valid]
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
                identifier = f"p{p + 1}/{event['id']}"
                if spec is None or identifier in self.seen_attacks:
                    continue
                self.seen_attacks.add(identifier)
                timing = event.get("timing")
                if timing is not None:
                    if (
                        not all(
                            np.isfinite(timing[k]) and 0 <= timing[k] <= 3
                            for k in ("startup", "active", "recovery")
                        )
                        or timing["active"] == 0
                    ):
                        raise ValueError("攻击时序必须是 0–3 秒的有限数值，有效时段必须大于零")
                    spec.update(
                        startup=timing["startup"],
                        duration=timing["active"],
                        recovery=timing["recovery"],
                        command=True,
                    )
                strike = Strike(
                    identifier,
                    p,
                    event["action"],
                    time_s,
                    spec,
                    points[1 - p].copy(),
                    valid[1 - p].copy(),
                )
                if min(self.health) == 0 or time_s < max(
                    self.recovery_until[p], self.busy_until[p]
                ):
                    self.finish(strike, "recovery", time_s, points[p, spec["joint"]])
                else:
                    self.strikes.append(strike)
                    active_at = time_s + spec["startup"]
                    active_end = active_at + spec["duration"]
                    self.busy_until[p] = active_end + spec["recovery"]
                    self.action_windows[p] = (active_at, active_end, self.busy_until[p])
        travel = np.linalg.norm(points - previous, axis=2)
        # 2.5 cm relative motion per sample; both players can move in opposition.
        steps = max(2, int(np.ceil(2 * np.max(travel[valid], initial=0) / 0.025)))
        contacts = []
        for strike in self.strikes:
            if strike.ended:
                continue
            p, other, joint = strike.player, 1 - strike.player, strike.spec["joint"]
            if not (valid[p, joint] and valid[p, 0] and valid[other, 0]):
                self.finish(strike, "tracking_lost", time_s, points[p, joint])
                continue
            strike.last_tip = points[p, joint]
            gap = float(np.linalg.norm((points[p, 0] - points[other, 0])[[0, 2]]))
            strike.minimum_root_distance = min(strike.minimum_root_distance, gap)
            contact = self._contact(strike, previous, points, valid, states, time_s, dt, steps)
            if contact is not None:
                contacts.append(contact)
        for _, same_time in groupby(
            sorted(contacts, key=lambda c: c["time"]), key=lambda c: round(c["time"], 10)
        ):
            group = list(same_time)
            # Snapshot eligibility before changing health/stun to permit true trades.
            eligible = [
                contact
                for contact in group
                if min(self.health) > 0
                and not contact["strike"].ended
                and contact["time"] >= self.recovery_until[contact["strike"].player]
            ]
            chains_before = self.chains.copy()
            last_hits_before = self.last_hit_time.copy()
            interrupted = set()
            for contact in eligible:
                strike, contact_time = contact["strike"], contact["time"]
                outcome, defense = contact["outcome"], contact.get("defense")
                if outcome == "block":
                    other = 1 - strike.player
                    parry = (
                        defense.get("parry_side") == contact["guard_side"]
                        and contact_time <= defense.get("parry_until", -1)
                        and defense.get("parry_id", -1) != self.parry_used[other]
                    )
                    outcome = "parry" if parry else outcome
                self.finish(
                    strike,
                    outcome,
                    contact_time,
                    contact["position"],
                    zone=contact.get("zone", ""),
                    guard_side=contact.get("guard_side"),
                    defense=defense,
                )
                event = self.events[-1]
                if event["damage"]:
                    p = strike.player
                    event["combo_count"] = (
                        chains_before[p] + 1 if contact_time - last_hits_before[p] < 1.1 else 1
                    )
                    self.chains[p] = event["combo_count"]
                    interrupted.add(1 - p)
                elif outcome == "parry":
                    interrupted.add(strike.player)
            # A trade interrupts both chains. An earlier hit cancels the old
            # attack permanently, even if stun ends before this frame does.
            for p in interrupted:
                self.chains[p] = 0
                for strike in self.strikes:
                    if strike.player == p and not strike.ended:
                        self.finish(
                            strike, "recovery", group[0]["time"], points[p, strike.spec["joint"]]
                        )
        active_display = []
        for strike in self.strikes:
            if strike.ended:
                continue
            p, joint = strike.player, strike.spec["joint"]
            if min(self.health) == 0 or time_s < self.recovery_until[p]:
                self.finish(strike, "recovery", time_s, points[p, joint])
                continue
            active_start = strike.start + strike.spec["startup"]
            active_end = active_start + strike.spec["duration"]
            if time_s >= active_end:
                outcome = (
                    "evaded"
                    if strike.stationary_contact
                    else "out_of_range"
                    if strike.minimum_root_distance > strike.spec["reach"]
                    else "miss"
                )
                self.finish(strike, outcome, time_s, points[p, joint])
            elif time_s >= active_start:
                end_joint = strike.spec["end_joint"]
                end_joint = end_joint if valid[p, end_joint] else joint
                active_display.append(
                    {
                        "player": p,
                        "action": strike.action,
                        "start": previous[p, joint].round(5).tolist(),
                        "end": points[p, joint].round(5).tolist(),
                        "weapon_start": points[p, joint].round(5).tolist(),
                        "weapon_end": points[p, end_joint].round(5).tolist(),
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
