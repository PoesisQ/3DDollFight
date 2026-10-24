// Pose-space skirt lift. The spring/cloth solver adds secondary motion around
// this guide; it is an authored corrective, not a simulated textile material.
// All inputs are world-space, so turning and arena translation commute with it.
export function skirtGuide(rest, segments, rows, capsules) {
    const result = Float64Array.from(rest);
    const center = (row) => {
        const c = [0, 0, 0];
        for (let j = 0; j < segments; j++)
            for (let k = 0; k < 3; k++)
                c[k] += rest[(row * segments + j) * 3 + k] / segments;
        return c;
    };
    const waist = center(0),
        hem = center(rows - 1);
    const down = hem.map((v, k) => v - waist[k]);
    const length = Math.hypot(...down);
    for (let k = 0; k < 3; k++) down[k] /= length || 1;
    const dot = (a, b) => a.reduce((s, v, k) => s + v * b[k], 0);
    const cross = (a, b) => [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ];
    const legs = capsules.slice(0, 2).map(({ a, b }) => {
        const leg = b.map((v, k) => v - a[k]);
        const ll = Math.hypot(...leg) || 1;
        for (let k = 0; k < 3; k++) leg[k] /= ll;
        const along = dot(leg, down);
        const planar = leg.map((v, k) => v - down[k] * along);
        const pl = Math.hypot(...planar) || 1;
        for (let k = 0; k < 3; k++) planar[k] /= pl;
        return {
            planar,
            angle: Math.max(
                0,
                Math.min(
                    2.75,
                    (Math.acos(Math.max(-1, Math.min(1, along))) - 0.3) * 1.35,
                ),
            ),
        };
    });
    for (let col = 0; col < segments; col++) {
        const top = Array.from(rest.slice(col * 3, col * 3 + 3));
        const radial = top.map((v, k) => v - waist[k]);
        const along = dot(radial, down);
        for (let k = 0; k < 3; k++) radial[k] -= along * down[k];
        const radius = Math.hypot(...radial) || 1;
        for (let k = 0; k < 3; k++) radial[k] /= radius;
        let lift = 0,
            selected = null;
        for (const leg of legs) {
            const alignment = Math.max(
                0,
                Math.min(1, dot(radial, leg.planar) / 0.7),
            );
            const angle =
                leg.angle * alignment * alignment * (3 - 2 * alignment);
            if (angle > lift) {
                lift = angle;
                selected = leg;
            }
        }
        if (!selected || lift < 1e-5) continue;
        const axis = cross(down, selected.planar);
        const cosine = Math.cos(lift),
            sine = Math.sin(lift);
        for (let row = 1; row < rows; row++) {
            const i = (row * segments + col) * 3;
            const offset = [
                rest[i] - top[0],
                rest[i + 1] - top[1],
                rest[i + 2] - top[2],
            ];
            const crossed = cross(axis, offset),
                axial = dot(axis, offset);
            for (let k = 0; k < 3; k++)
                result[i + k] =
                    top[k] +
                    offset[k] * cosine +
                    crossed[k] * sine +
                    axis[k] * axial * (1 - cosine);
        }
    }
    return result;
}

// Small continuous SDF correction after skinning. Regularization at the bone
// axis avoids the radial discontinuity that creates ribbons. Total correction
// is bounded to 25 mm; deep contact remains a guide/cloth problem, not hidden
// by moving individual dense vertices arbitrarily far.
export function projectGarmentPoint(point, capsules, margin = 0.006) {
    const delta = [0, 0, 0];
    for (const { a, b, radius } of capsules) {
        const axis = b.map((v, k) => v - a[k]),
            length2 = axis.reduce((s, v) => s + v * v, 0);
        const t = Math.max(
            0,
            Math.min(
                1,
                axis.reduce((s, v, k) => s + v * (point[k] - a[k]), 0) /
                    Math.max(length2, 1e-10),
            ),
        );
        const radial = point.map((v, k) => v - a[k] - axis[k] * t),
            distance = Math.hypot(...radial);
        const depth = Math.max(0, radius + margin - distance);
        const amount = 0.025 * (1 - Math.exp(-depth / 0.025));
        for (let k = 0; k < 3; k++)
            delta[k] +=
                (radial[k] / Math.sqrt(distance * distance + 0.015 * 0.015)) *
                amount;
    }
    const scale = Math.max(1, Math.hypot(...delta) / 0.025);
    return point.map((v, k) => v + delta[k] / scale);
}
export const garmentProjectionGLSL = `
vec3 dfWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;
vec3 dfDelta=vec3(0.0);
for(int dfI=0;dfI<4;dfI++) {
    vec3 axis=dfLegB[dfI].xyz-dfLegA[dfI].xyz;
    float t=clamp(dot(dfWorld-dfLegA[dfI].xyz,axis)/max(dot(axis,axis),1e-10),0.0,1.0);
    vec3 radial=dfWorld-dfLegA[dfI].xyz-axis*t;
    float distance=length(radial),depth=max(0.0,dfLegA[dfI].w+.006-distance);
    float amount=.025*(1.0-exp(-depth/.025));
    dfDelta+=radial/sqrt(distance*distance+.015*.015)*amount;
}
dfWorld+=dfDelta/max(1.0,length(dfDelta)/.025);
transformed = (dfWorldToLocal * vec4(dfWorld, 1.0)).xyz;
`;
