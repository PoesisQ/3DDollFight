// Dense-vertex contact QA on the same live cage and post-skin projection math.
// This measures vertices against capsules, not complete mesh/mesh collision.
import fs from "node:fs";
import { createHash } from "node:crypto";
import { ClothSolver } from "../apps/motion-lab/cloth.js";
import { projectGarmentPoint } from "../apps/motion-lab/garment-guide.js";
const framesPath = process.argv[2] || "outputs/sparring-latest.json";
const reportPath =
    process.argv[3] || "data/avatars/experiments/garment-v08-20261024.json";
const run = JSON.parse(fs.readFileSync(framesPath, "utf8"));
const mul = (a, b) => [
    a[3] * b[0] + b[3] * a[0] + a[1] * b[2] - a[2] * b[1],
    a[3] * b[1] + b[3] * a[1] + a[2] * b[0] - a[0] * b[2],
    a[3] * b[2] + b[3] * a[2] + a[0] * b[1] - a[1] * b[0],
    a[3] * b[3] - a[0] * b[0] - a[1] * b[1] - a[2] * b[2],
];
const rotate = (q, v) => {
    const t = [
        2 * (q[1] * v[2] - q[2] * v[1]),
        2 * (q[2] * v[0] - q[0] * v[2]),
        2 * (q[0] * v[1] - q[1] * v[0]),
    ];
    return [
        v[0] + q[3] * t[0] + q[1] * t[2] - q[2] * t[1],
        v[1] + q[3] * t[1] + q[2] * t[0] - q[0] * t[2],
        v[2] + q[3] * t[2] + q[0] * t[1] - q[1] * t[0],
    ];
};
const lerp = (a, b, t) => a.map((v, k) => v + (b[k] - v) * t);
function slerp(a, b, t) {
    let dot = a.reduce((s, v, k) => s + v * b[k], 0);
    if (dot < 0) {
        b = b.map((v) => -v);
        dot = -dot;
    }
    const theta = Math.acos(Math.min(1, dot));
    const p =
            theta < 1e-6 ? 1 - t : Math.sin((1 - t) * theta) / Math.sin(theta),
        q = theta < 1e-6 ? t : Math.sin(t * theta) / Math.sin(theta);
    return a.map((v, k) => p * v + q * b[k]);
}
function readGLB(path) {
    const b = fs.readFileSync(path),
        length = b.readUInt32LE(12);
    const doc = JSON.parse(b.subarray(20, 20 + length).toString()),
        binary = b.subarray(28 + length);
    const size = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT4: 16 },
        types = { 5126: Float32Array, 5123: Uint16Array, 5125: Uint32Array };
    return {
        doc,
        accessor(index) {
            const a = doc.accessors[index],
                v = doc.bufferViews[a.bufferView];
            const start = (v.byteOffset || 0) + (a.byteOffset || 0);
            const T = types[a.componentType];
            return new T(
                Uint8Array.from(
                    binary.subarray(
                        start,
                        start + a.count * size[a.type] * T.BYTES_PER_ELEMENT,
                    ),
                ).buffer,
            );
        },
    };
}
function penetration(v, caps) {
    let max = 0;
    for (const { a, b, radius } of caps) {
        const d = b.map((x, k) => x - a[k]);
        const t = Math.max(
            0,
            Math.min(
                1,
                d.reduce((s, x, k) => s + x * (v[k] - a[k]), 0) /
                    Math.max(
                        1e-12,
                        d.reduce((s, x) => s + x * x, 0),
                    ),
            ),
        );
        max = Math.max(
            max,
            radius - Math.hypot(...v.map((x, k) => x - a[k] - d[k] * t)),
        );
    }
    return max;
}
const quantile = (values, q) => {
    const a = values.sort((x, y) => x - y);
    return a[Math.min(a.length - 1, Math.round((a.length - 1) * q))] || 0;
};
const reports = [];
for (const [player, character] of ["nozomi", "mizore"].entries()) {
    const model = readGLB(`data/avatars/local/${character}-hybrid.vrm`),
        doc = model.doc;
    const cage = doc.nodes.find((n) => n.extras?.dollfightCage).extras
        .dollfightCage;
    const cloth = new ClothSolver(cage.rest.flat(), cage.segments, cage.rows, {
        shapeCorrective: true,
    });
    const part = doc.meshes.find((m) => m.name === "Tripo_LocalSurface")
        .primitives[0];
    const v = model.accessor(part.attributes.POSITION),
        j = model.accessor(part.attributes.JOINTS_0),
        w = model.accessor(part.attributes.WEIGHTS_0),
        indices = model.accessor(part.indices);
    const bones = doc.skins[0].joints;
    const cj = bones.map((n) => cage.nodes.indexOf(n));
    const frames = player === 0 ? run.frames : run.duel.opponent_frames,
        rest = run.target_rest;
    const groupQ = [
        0,
        Math.sin(((player === 0 ? 1 : -1) * Math.PI) / 4),
        0,
        Math.cos(Math.PI / 4),
    ];
    const targets = [];
    for (let begin = 0; begin < 900; ) {
        let end = begin + 1;
        const intent = frames[begin].performance.intent;
        while (end < 900 && frames[end].performance.intent === intent) end++;
        if (["front_kick", "roundhouse"].includes(intent)) {
            let peak = begin;
            for (let i = begin; i < end; i++)
                if (
                    Math.max(frames[i].avatar[13][1], frames[i].avatar[17][1]) >
                    Math.max(
                        frames[peak].avatar[13][1],
                        frames[peak].avatar[17][1],
                    )
                )
                    peak = i;
            for (const offset of [-4, 0, 4])
                targets.push(
                    Math.max(begin, Math.min(end - 1, peak + offset)) * 2,
                );
        }
        begin = end;
    }
    let maximumProxyPenetration = 0,
        maximumStretch = 1;
    const checks = [];
    for (let step = 0; step < 1800; step++) {
        const index = Math.floor(step / 2),
            alpha = (step % 2) * 0.5,
            a = frames[index],
            b = frames[index + 1];
        const arena = lerp(
            run.duel.frames[index].positions[player],
            run.duel.frames[index + 1].positions[player],
            alpha,
        );
        const local = [],
            global = [],
            world = [];
        for (let k = 0; k < 19; k++) {
            const q = slerp(a.rotations[k], b.rotations[k], alpha),
                parent = run.parents[k];
            global[k] = parent < 0 ? q : mul(global[parent], q);
            local[k] =
                parent < 0
                    ? [0, a.root[1] + alpha * (b.root[1] - a.root[1]), 0]
                    : rotate(
                          global[parent],
                          rest[k].map((v, d) => v - rest[parent][d]),
                      ).map((v, d) => v + local[parent][d]);
            world[k] = rotate(groupQ, local[k]).map((v, d) => v + arena[d]);
        }
        const hipQ = mul(groupQ, global[0]);
        const anchors = cage.rest.flatMap((p) =>
            rotate(
                hipQ,
                p.map((v, k) => v - rest[0][k]),
            ).map((v, k) => v + world[0][k]),
        );
        const caps = [
            [11, 12],
            [15, 16],
            [12, 13],
            [16, 17],
        ].map(([a, b], i) => ({
            a: world[a],
            b: world[b],
            radius: cage.capsuleRadii[i],
        }));
        if (!step) cloth.reset(anchors);
        cloth.step(1 / 60, anchors, caps);
        if (step % 10 === 0) {
            maximumProxyPenetration = Math.max(
                maximumProxyPenetration,
                cloth.collisionReport(caps).maxPenetration,
            );
            maximumStretch = Math.max(maximumStretch, cloth.stretch().max);
        }
        if (!targets.includes(step)) continue;
        const before = [],
            after = [],
            displacements = [];
        let worstSource = null;
        let preMax = 0,
            postMax = 0,
            over5mmBefore = 0,
            over5mmAfter = 0;
        for (let vi = 0; vi < v.length / 3; vi++) {
            const point = [0, 0, 0],
                source = Array.from(v.slice(vi * 3, vi * 3 + 3));
            for (let k = 0; k < 4; k++) {
                const ci = cj[j[vi * 4 + k]],
                    weight = w[vi * 4 + k];
                if (!weight) continue;
                if (ci < 0) throw Error("Garment contains a non-cage weight");
                const delta = rotate(
                    hipQ,
                    source.map((x, d) => x - cage.rest[ci][d]),
                );
                for (let d = 0; d < 3; d++)
                    point[d] +=
                        weight * (cloth.position[ci * 3 + d] + delta[d]);
            }
            const projected = projectGarmentPoint(point, caps);
            const pre = penetration(point, caps),
                post = penetration(projected, caps);
            if (post > postMax) worstSource = source;
            preMax = Math.max(preMax, pre);
            postMax = Math.max(postMax, post);
            over5mmBefore += pre > 0.005;
            over5mmAfter += post > 0.005;
            before.push(point);
            after.push(projected);
            displacements.push(
                Math.hypot(...point.map((x, d) => x - projected[d])),
            );
        }
        const ratios = [];
        for (let i = 0; i < indices.length; i += 3)
            for (let k = 0; k < 3; k++) {
                const ia = indices[i + k],
                    ib = indices[i + ((k + 1) % 3)];
                const prior = Math.hypot(
                    ...before[ia].map((x, d) => x - before[ib][d]),
                );
                if (prior > 0.0005)
                    ratios.push(
                        Math.hypot(
                            ...after[ia].map((x, d) => x - after[ib][d]),
                        ) / prior,
                    );
            }
        checks.push({
            time_s: step / 60,
            vertices: v.length / 3,
            before_max_penetration_m: preMax,
            after_max_penetration_m: postMax,
            before_vertices_over5mm: over5mmBefore,
            after_vertices_over5mm: over5mmAfter,
            worst_rest_position: worstSource,
            displacement_p95_m: quantile(displacements, 0.95),
            displacement_max_m: quantile(displacements, 1),
            projection_edge_ratio_p99: quantile(ratios, 0.99),
            projection_edge_ratio_max: quantile(ratios, 1),
        });
        console.log(character, JSON.stringify(checks.at(-1)));
    }
    reports.push({
        character,
        proxy_vertices: cage.rest.length,
        proxy_max_penetration_m: maximumProxyPenetration,
        proxy_max_constraint_length_ratio: maximumStretch,
        checks,
    });
}
const report = {
    replay_frames_path: framesPath,
    replay_frames_sha256: createHash("sha256")
        .update(fs.readFileSync(framesPath))
        .digest("hex"),
    avatar_sha256: Object.fromEntries(
        ["nozomi", "mizore"].map((name) => [
            name,
            createHash("sha256")
                .update(
                    fs.readFileSync(`data/avatars/local/${name}-hybrid.vrm`),
                )
                .digest("hex"),
        ]),
    ),
    contact_limits:
        "The waistband remains pelvis-pinned. Deep high-kick waist intersections remain; no full body or self collision certification.",
    corrective:
        "Pose-dependent guide and constraint lengths; bounded 25 mm smooth GPU SDF correction. Length ratios are relative to the original bind cage, not physical textile strain.",
    method: "60 Hz causal cage, actual VRM weights, CPU reference of the dense GPU projection",
    scope: "First round, six high-kick samples per model. Vertex/capsule contact only; does not certify triangle/body or self collision. Projection edge ratios show corrective distortion.",
    reports,
};
fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
