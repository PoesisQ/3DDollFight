"""Causal confidence gating, One Euro smoothing and fixed-length projection."""

import numpy as np

from dollfight.kinematics import EDGES, PARENTS, two_bone_ik, unit


class SkeletonSolver:
    def __init__(self, rest, *, cutoff=1.7, beta=4.0, smoothing=True, constraints=True):
        self.rest = np.asarray(rest, dtype=float)
        self.lengths = np.array(
            [0] + [np.linalg.norm(rest[i] - rest[p]) for i, p in enumerate(PARENTS) if p >= 0]
        )
        self.cutoff, self.beta = cutoff, beta
        self.smoothing, self.constraints = smoothing, constraints
        self.previous_time = None
        self.filtered = self.rest.copy()
        self.last_observed = self.rest.copy()
        self.last_seen = np.full(19, -np.inf)
        self.derivative = np.zeros_like(self.rest)

    def process(self, observed, confidence, time_s):
        if self.previous_time is not None and time_s <= self.previous_time:
            raise ValueError("Frame timestamps must increase")
        dt = 1 / 30 if self.previous_time is None else time_s - self.previous_time
        gap = dt > 0.3
        dt = min(dt, 0.1)
        valid = np.isfinite(observed).all(axis=1) & (confidence >= 0.35)
        if self.previous_time is not None and not gap:
            displacement = np.linalg.norm(observed - self.last_observed, axis=1)
            age = time_s - self.last_seen
            valid &= (displacement < 0.15 + 8 * np.minimum(age, 0.3)) | (age > 0.3)
        states = []
        for i in range(19):
            if valid[i]:
                fresh = self.previous_time is None or gap or time_s - self.last_seen[i] > 0.25
                if fresh or not self.smoothing:
                    self.filtered[i] = observed[i]
                    self.derivative[i] = 0
                else:
                    velocity = (observed[i] - self.last_observed[i]) / dt
                    derivative_alpha = 1 / (1 + 1 / (2 * np.pi * dt))
                    self.derivative[i] += derivative_alpha * (velocity - self.derivative[i])
                    cutoff = self.cutoff + self.beta * np.linalg.norm(self.derivative[i])
                    alpha = 1 / (1 + 1 / (2 * np.pi * cutoff * dt))
                    self.filtered[i] += alpha * (observed[i] - self.filtered[i])
                self.last_observed[i] = observed[i]
                self.last_seen[i] = time_s
                states.append("observed")
            elif time_s - self.last_seen[i] < 0.15:
                # Bounded short prediction is visual only, not attack evidence.
                speed = np.linalg.norm(self.derivative[i])
                self.filtered[i] += self.derivative[i] * min(1, 2 / max(speed, 1e-8)) * dt * 0.3
                states.append("predicted")
            else:
                parent = PARENTS[i]
                if parent >= 0:
                    self.filtered[i] = self.filtered[parent] + self.rest[i] - self.rest[parent]
                states.append("missing")
        solved = self.filtered.copy()
        if self.constraints:
            for parent, child in EDGES:
                direction = unit(
                    solved[child] - solved[parent], unit(self.rest[child] - self.rest[parent])
                )
                solved[child] = solved[parent] + direction * self.lengths[child]
            # Preserve bend direction while preventing hyperextension; analytic IK.
            for a, b, c in ((5, 6, 7), (8, 9, 10), (11, 12, 13), (15, 16, 17)):
                ab, bc = self.lengths[b], self.lengths[c]
                reach = np.linalg.norm(solved[c] - solved[a])
                maximum = np.sqrt(ab * ab + bc * bc - 2 * ab * bc * np.cos(np.deg2rad(177)))
                minimum = np.sqrt(ab * ab + bc * bc - 2 * ab * bc * np.cos(np.deg2rad(18)))
                if reach > maximum or reach < minimum:
                    target = solved[a] + unit(solved[c] - solved[a]) * np.clip(
                        reach, minimum, maximum
                    )
                    solved[b], solved[c] = two_bone_ik(solved[a], target, ab, bc, solved[b])
                    for parent, child in EDGES:
                        if parent == c:
                            solved[child] = (
                                solved[parent]
                                + unit(solved[child] - solved[parent]) * self.lengths[child]
                            )
        self.previous_time = time_s
        return solved, states, valid
