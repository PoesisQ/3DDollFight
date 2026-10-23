// Fixed-step position based cloth. Authored topology is independent of leg skin
// weights. Structural/shear/bend distances and body capsules are solved together.
// No self collision, aerodynamic model or claim of production garment simulation.
export class ClothSolver {
    constructor(rest, segments, rows) {
        if (
            !Number.isInteger(segments) ||
            !Number.isInteger(rows) ||
            segments < 3 ||
            segments > 256 ||
            rows < 2 ||
            rows > 128 ||
            rest.length !== segments * rows * 3 ||
            !Array.from(rest).every(Number.isFinite)
        )
            throw new Error("Invalid cloth grid topology");
        this.rest = Float64Array.from(rest);
        this.position = Float64Array.from(rest);
        this.previous = Float64Array.from(rest);
        this.segments = segments;
        this.rows = rows;
        this.constraints = [];
        const edge = (a, b, stiffness) => {
            let length = 0;
            for (let k = 0; k < 3; k++)
                length += (rest[a * 3 + k] - rest[b * 3 + k]) ** 2;
            this.constraints.push([a, b, Math.sqrt(length), stiffness]);
        };
        for (let r = 0; r < rows; r++)
            for (let c = 0; c < segments; c++) {
                const i = r * segments + c;
                edge(i, r * segments + ((c + 1) % segments), 0.95);
                if (r + 1 < rows) {
                    edge(i, i + segments, 0.95);
                    edge(i, (r + 1) * segments + ((c + 1) % segments), 0.55);
                    edge(
                        i,
                        (r + 1) * segments + ((c + segments - 1) % segments),
                        0.55,
                    );
                }
                if (r + 2 < rows) edge(i, i + segments * 2, 0.24);
                edge(i, r * segments + ((c + 4) % segments), 0.13);
            }
    }
    reset(transformedRest) {
        this.position.set(transformedRest);
        this.previous.set(transformedRest);
        this.lastAnchors = Float64Array.from(transformedRest);
        this.lastCapsules = null;
    }
    step(dt, anchors, capsules, iterations = 5) {
        if (!(dt > 0 && dt <= 1 / 30 + 1e-8))
            throw new Error("Cloth needs fixed substeps <= 1/30 s");
        const fromAnchors = this.lastAnchors || anchors;
        const fromCapsules =
            this.lastCapsules?.length === capsules.length
                ? this.lastCapsules
                : capsules;
        const substeps = Math.max(1, Math.ceil(dt * 240 - 1e-8));
        let previousCapsules = fromCapsules;
        for (let sub = 1; sub <= substeps; sub++) {
            const alpha = sub / substeps;
            const interpolated = Float64Array.from(
                anchors,
                (v, i) => fromAnchors[i] + alpha * (v - fromAnchors[i]),
            );
            const contacts = capsules.map((capsule, i) => ({
                a: capsule.a.map(
                    (v, k) =>
                        fromCapsules[i].a[k] +
                        alpha * (v - fromCapsules[i].a[k]),
                ),
                b: capsule.b.map(
                    (v, k) =>
                        fromCapsules[i].b[k] +
                        alpha * (v - fromCapsules[i].b[k]),
                ),
                radius: capsule.radius,
            }));
            this.integrate(
                dt / substeps,
                interpolated,
                contacts,
                previousCapsules,
                iterations,
            );
            previousCapsules = contacts;
        }
        // Kinematic pins and body capsules can be mutually incompatible (a high
        // knee crosses the waistband). Give cloth inextensibility priority over
        // collision in that case, and report the remaining penetration explicitly.
        // Do not permit a visually torn surface to satisfy a contact constraint.
        for (let iteration = 0; iteration < 32; iteration++) {
            let largest = 1;
            for (const [a, b, rest] of this.constraints) {
                const ia = a * 3,
                    ib = b * 3,
                    p = this.position;
                const x = p[ib] - p[ia],
                    y = p[ib + 1] - p[ia + 1],
                    z = p[ib + 2] - p[ia + 2];
                const distance = Math.hypot(x, y, z);
                largest = Math.max(largest, distance / rest);
                if (distance <= rest * 1.12) continue;
                const wa = a < this.segments ? 0 : 1,
                    wb = b < this.segments ? 0 : 1;
                if (!wa && !wb) continue;
                const correction = (1 - (rest * 1.12) / distance) / (wa + wb);
                for (const [k, delta] of [x, y, z].entries()) {
                    p[ia + k] += wa * delta * correction;
                    p[ib + k] -= wb * delta * correction;
                }
            }
            if (largest < 1.15) break;
        }
        for (let i = this.segments * 3; i < this.position.length; i++) {
            const velocity = Math.max(
                (-2.7 * dt) / substeps,
                Math.min(
                    (2.7 * dt) / substeps,
                    this.position[i] - this.previous[i],
                ),
            );
            this.previous[i] = this.position[i] - velocity;
        }
        this.lastAnchors = Float64Array.from(anchors);
        this.lastCapsules = capsules.map((c) => ({
            a: [...c.a],
            b: [...c.b],
            radius: c.radius,
        }));
        return this.position;
    }
    integrate(dt, anchors, capsules, previousCapsules, iterations) {
        const p = this.position,
            old = this.previous,
            n = this.segments * 3;
        const before = Float64Array.from(p);
        const damping = Math.pow(0.94, dt * 60);
        for (let i = n; i < p.length; i++) {
            const current = p[i];
            p[i] += (p[i] - old[i]) * damping;
            if (i % 3 === 1) p[i] -= 9.81 * dt * dt;
            old[i] = current;
        }
        const pin = () => {
            for (let i = 0; i < n; i++) p[i] = anchors[i];
        };
        pin();
        for (let iteration = 0; iteration < iterations; iteration++) {
            for (const [a, b, rest, stiffness] of this.constraints) {
                const ia = a * 3,
                    ib = b * 3;
                const x = p[ib] - p[ia],
                    y = p[ib + 1] - p[ia + 1],
                    z = p[ib + 2] - p[ia + 2];
                const length = Math.hypot(x, y, z);
                if (length < 1e-9) continue;
                const wa = a < this.segments ? 0 : 1,
                    wb = b < this.segments ? 0 : 1;
                if (wa + wb === 0) continue;
                const correction =
                    ((1 - rest / length) * stiffness) / (wa + wb);
                p[ia] += wa * x * correction;
                p[ib] -= wb * x * correction;
                p[ia + 1] += wa * y * correction;
                p[ib + 1] -= wb * y * correction;
                p[ia + 2] += wa * z * correction;
                p[ib + 2] -= wb * z * correction;
            }
            for (let i = n; i < p.length; i += 3) {
                for (
                    let capsuleIndex = 0;
                    capsuleIndex < capsules.length;
                    capsuleIndex++
                ) {
                    const { a, b, radius } = capsules[capsuleIndex];
                    const dx = b[0] - a[0],
                        dy = b[1] - a[1],
                        dz = b[2] - a[2];
                    const length2 = dx * dx + dy * dy + dz * dz;
                    const t =
                        length2 > 1e-12
                            ? Math.max(
                                  0,
                                  Math.min(
                                      1,
                                      ((p[i] - a[0]) * dx +
                                          (p[i + 1] - a[1]) * dy +
                                          (p[i + 2] - a[2]) * dz) /
                                          length2,
                                  ),
                              )
                            : 0;
                    const cx = a[0] + t * dx,
                        cy = a[1] + t * dy,
                        cz = a[2] + t * dz;
                    let x = p[i] - cx,
                        y = p[i + 1] - cy,
                        z = p[i + 2] - cz;
                    let distance = Math.hypot(x, y, z);
                    if (distance >= radius) continue;
                    // Preserve the contact side across a moving capsule. A nearest
                    // point projection alone can send neighboring cloth vertices to
                    // opposite sides of a fast kicking thigh and tear open an edge.
                    const prior = previousCapsules[capsuleIndex];
                    const axis = prior.b.map((v, k) => v - prior.a[k]);
                    const norm2 = axis.reduce((sum, v) => sum + v * v, 0);
                    const previousT =
                        norm2 > 1e-12
                            ? Math.max(
                                  0,
                                  Math.min(
                                      1,
                                      axis.reduce(
                                          (sum, v, k) =>
                                              sum +
                                              (before[i + k] - prior.a[k]) * v,
                                          0,
                                      ) / norm2,
                                  ),
                              )
                            : 0;
                    const normal = axis.map(
                        (v, k) => before[i + k] - prior.a[k] - previousT * v,
                    );
                    const previousDistance = Math.hypot(...normal);
                    if (
                        previousDistance > 1e-9 &&
                        x * normal[0] + y * normal[1] + z * normal[2] < 0
                    ) {
                        [x, y, z] = normal;
                        distance = previousDistance;
                    }
                    if (distance < 1e-10) {
                        x = 0;
                        y = 0;
                        z = 1;
                        distance = 1;
                    }
                    p[i] = cx + (x * radius) / distance;
                    p[i + 1] = cy + (y * radius) / distance;
                    p[i + 2] = cz + (z * radius) / distance;
                }
                p[i + 1] = Math.max(0.018, p[i + 1]);
            }
            pin();
        }
        // Contact friction: do not carry positional penetration correction into
        // an arbitrarily large velocity on the following step.
        for (let i = n; i < p.length; i++) {
            const delta = Math.max(
                -2.7 * dt,
                Math.min(2.7 * dt, p[i] - old[i]),
            );
            old[i] = p[i] - delta;
        }
        return p;
    }
    stretch() {
        let max = 1,
            total = 0,
            worst = null;
        for (const [a, b, rest] of this.constraints) {
            let d = 0;
            for (let k = 0; k < 3; k++)
                d += (this.position[a * 3 + k] - this.position[b * 3 + k]) ** 2;
            const ratio = Math.sqrt(d) / rest;
            if (ratio > max) {
                max = ratio;
                worst = {
                    a,
                    b,
                    rest,
                    length: Math.sqrt(d),
                    positionA: Array.from(
                        this.position.slice(a * 3, a * 3 + 3),
                    ),
                    positionB: Array.from(
                        this.position.slice(b * 3, b * 3 + 3),
                    ),
                };
            }
            total += Math.abs(ratio - 1);
        }
        return { max, mean: total / this.constraints.length, worst };
    }
    collisionReport(capsules) {
        let maxPenetration = 0,
            penetrated = 0;
        for (let i = this.segments * 3; i < this.position.length; i += 3) {
            let penetration = 0;
            for (const { a, b, radius } of capsules) {
                const axis = b.map((v, k) => v - a[k]);
                const norm2 = axis.reduce((s, v) => s + v * v, 0);
                const t =
                    norm2 > 1e-12
                        ? Math.max(
                              0,
                              Math.min(
                                  1,
                                  axis.reduce(
                                      (s, v, k) =>
                                          s + (this.position[i + k] - a[k]) * v,
                                      0,
                                  ) / norm2,
                              ),
                          )
                        : 0;
                const distance = Math.hypot(
                    ...axis.map((v, k) => this.position[i + k] - a[k] - v * t),
                );
                penetration = Math.max(penetration, radius - distance);
            }
            maxPenetration = Math.max(maxPenetration, penetration);
            if (penetration > 0.005) penetrated++;
        }
        return {
            maxPenetration,
            fractionOver5mm: penetrated / (this.segments * (this.rows - 1)),
        };
    }
}
