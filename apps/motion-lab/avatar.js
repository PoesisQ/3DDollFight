import * as THREE from "three";

const V = (p) => new THREE.Vector3(...p);

// Vertices are authored in bind space, with actual joint indices / weights.
export function createAvatar(rest, parents, tint = "#76e3ca") {
    const group = new THREE.Group();
    const bones = rest.map((point, i) => {
        const bone = new THREE.Bone();
        bone.name = `joint_${i}`;
        bone.position.copy(V(point));
        if (parents[i] >= 0) bone.position.sub(V(rest[parents[i]]));
        return bone;
    });
    bones.forEach((bone, i) => {
        if (parents[i] >= 0) bones[parents[i]].add(bone);
    });
    const positions = [],
        colors = [],
        indices = [],
        weights = [],
        triangles = [];
    const cloth = new THREE.Color(tint),
        dark = new THREE.Color("#293c47");
    const skin = new THREE.Color("#d7dfd8"),
        joints = new THREE.Color("#415d67");
    function vertex(point, color, a, b = a, weight = 0) {
        positions.push(...point.toArray());
        colors.push(color.r, color.g, color.b);
        indices.push(a, b, 0, 0);
        weights.push(1 - weight, weight, 0, 0);
    }
    function tube(a, b, radiusA, radiusB, color, depth = 1) {
        const start = V(rest[a]),
            end = V(rest[b]),
            axis = end.clone().sub(start).normalize();
        const ref =
            Math.abs(axis.z) < 0.9
                ? new THREE.Vector3(0, 0, 1)
                : new THREE.Vector3(1, 0, 0);
        const x = new THREE.Vector3().crossVectors(axis, ref).normalize();
        const y = new THREE.Vector3().crossVectors(axis, x).normalize();
        const base = positions.length / 3,
            segments = 12,
            rings = 9;
        for (let r = 0; r <= rings; r++) {
            const t = r / rings,
                center = start.clone().lerp(end, t);
            const radius =
                THREE.MathUtils.lerp(radiusA, radiusB, t) *
                (1 + 0.08 * Math.sin(t * Math.PI));
            for (let j = 0; j <= segments; j++) {
                const angle = (j * Math.PI * 2) / segments;
                const point = center
                    .clone()
                    .addScaledVector(x, Math.cos(angle) * radius)
                    .addScaledVector(y, Math.sin(angle) * radius * depth);
                const blend = 0.25 * THREE.MathUtils.smoothstep(t, 0.55, 1);
                vertex(point, color, a, b, blend);
            }
        }
        for (let r = 0; r < rings; r++)
            for (let j = 0; j < segments; j++) {
                const n = base + r * (segments + 1) + j;
                triangles.push(
                    n,
                    n + 1,
                    n + segments + 1,
                    n + 1,
                    n + segments + 2,
                    n + segments + 1,
                );
            }
    }
    function ellipsoid(
        center,
        radius,
        bone,
        color,
        latitudes = 12,
        longitudes = 16,
    ) {
        const base = positions.length / 3;
        for (let i = 0; i <= latitudes; i++)
            for (let j = 0; j <= longitudes; j++) {
                const theta = (i * Math.PI) / latitudes,
                    phi = (j * Math.PI * 2) / longitudes;
                vertex(
                    new THREE.Vector3(
                        center[0] + radius[0] * Math.sin(theta) * Math.cos(phi),
                        center[1] + radius[1] * Math.cos(theta),
                        center[2] + radius[2] * Math.sin(theta) * Math.sin(phi),
                    ),
                    color,
                    bone,
                );
            }
        for (let i = 0; i < latitudes; i++)
            for (let j = 0; j < longitudes; j++) {
                const n = base + i * (longitudes + 1) + j;
                triangles.push(
                    n,
                    n + longitudes + 1,
                    n + 1,
                    n + 1,
                    n + longitudes + 1,
                    n + longitudes + 2,
                );
            }
    }
    const width = (rest[5][0] - rest[8][0]) / 0.44;
    tube(0, 1, 0.16 * width, 0.18 * width, dark, 0.8);
    tube(1, 2, 0.18 * width, 0.23 * width, cloth, 0.68);
    tube(2, 3, 0.23 * width, 0.065, cloth, 0.68);
    tube(3, 4, 0.055, 0.06, joints);
    ellipsoid(rest[4], [0.125, 0.16, 0.12], 4, skin);
    for (const [s, e, w] of [
        [5, 6, 7],
        [8, 9, 10],
    ]) {
        ellipsoid(rest[s], [0.09, 0.085, 0.09], s, cloth);
        tube(s, e, 0.073, 0.058, cloth);
        ellipsoid(rest[e], [0.058, 0.058, 0.058], e, joints, 8, 12);
        tube(e, w, 0.057, 0.043, skin);
        ellipsoid(rest[w], [0.078, 0.09, 0.085], w, cloth);
    }
    for (const [h, k, a] of [
        [11, 12, 13],
        [15, 16, 17],
    ]) {
        ellipsoid(rest[h], [0.105 * width, 0.12, 0.11], h, dark);
        tube(h, k, 0.105 * width, 0.07, dark);
        ellipsoid(rest[k], [0.071, 0.071, 0.071], k, joints, 8, 12);
        tube(k, a, 0.075, 0.045, dark);
        ellipsoid(
            [rest[a][0], rest[a][1] - 0.035, rest[a][2] + 0.065],
            [0.075, 0.065, 0.145],
            a,
            cloth,
        );
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute(
        "position",
        new THREE.Float32BufferAttribute(positions, 3),
    );
    geometry.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    geometry.setAttribute(
        "skinIndex",
        new THREE.Uint16BufferAttribute(indices, 4),
    );
    geometry.setAttribute(
        "skinWeight",
        new THREE.Float32BufferAttribute(weights, 4),
    );
    geometry.setIndex(triangles);
    geometry.computeVertexNormals();
    const material = new THREE.MeshStandardMaterial({
        vertexColors: true,
        roughness: 0.7,
        metalness: 0.08,
        side: THREE.DoubleSide,
    });
    const mesh = new THREE.SkinnedMesh(geometry, material);
    mesh.add(bones[0]);
    group.add(mesh);
    group.updateMatrixWorld(true);
    const skeleton = new THREE.Skeleton(bones);
    mesh.bind(skeleton);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.frustumCulled = false;
    // Face details make frontal vs side views visible without an external asset.
    const visor = new THREE.Mesh(
        new THREE.BoxGeometry(0.19, 0.038, 0.025),
        new THREE.MeshStandardMaterial({ color: "#203239", roughness: 0.5 }),
    );
    visor.position.set(0, 0.02, 0.106);
    bones[4].add(visor);
    for (const x of [-0.045, 0.045]) {
        const eye = new THREE.Mesh(
            new THREE.BoxGeometry(0.028, 0.009, 0.007),
            new THREE.MeshBasicMaterial({ color: tint }),
        );
        eye.position.set(x, 0.02, 0.121);
        bones[4].add(eye);
    }
    const skeletonHelper = new THREE.SkeletonHelper(bones[0]);
    skeletonHelper.material.depthTest = false;
    skeletonHelper.material.transparent = true;
    skeletonHelper.material.opacity = 0.85;
    // SkeletonHelper already uses the root's world matrix. Attach it at scene level
    // to avoid applying the avatar group translation / rotation a second time.
    skeletonHelper.renderOrder = 10;
    skeletonHelper.visible = false;
    return {
        group,
        mesh,
        bones,
        skeletonHelper,
        apply(frame, next, alpha = 0) {
            const q = new THREE.Quaternion();
            bones.forEach((bone, i) => {
                bone.quaternion.fromArray(frame.rotations[i]);
                if (next)
                    bone.quaternion.slerp(
                        q.fromArray(next.rotations[i]),
                        alpha,
                    );
            });
            const height = next
                ? THREE.MathUtils.lerp(frame.root[1], next.root[1], alpha)
                : frame.root[1];
            bones[0].position.set(0, height, 0);
            group.updateMatrixWorld(true);
        },
        appearance(showBones, wireframe) {
            skeletonHelper.visible = showBones;
            material.wireframe = wireframe;
        },
        dispose() {
            group.traverse((o) => {
                o.geometry?.dispose();
                if (o.material) o.material.dispose();
            });
            skeletonHelper.removeFromParent();
            skeletonHelper.geometry.dispose();
            skeletonHelper.material.dispose();
            skeleton.dispose();
        },
    };
}

export function createStick(color, parents) {
    const group = new THREE.Group(),
        spheres = [];
    const dot = new THREE.SphereGeometry(0.024, 8, 6);
    for (let i = 0; i < parents.length; i++) {
        const sphere = new THREE.Mesh(
            dot,
            new THREE.MeshBasicMaterial({ color }),
        );
        group.add(sphere);
        spheres.push(sphere);
    }
    const geometry = new THREE.BufferGeometry();
    const positions = new Float32Array((parents.length - 1) * 6);
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    const lines = new THREE.LineSegments(
        geometry,
        new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.8 }),
    );
    lines.frustumCulled = false;
    group.add(lines);
    return {
        group,
        apply(points, quality = [], center = [0, 0, 0]) {
            let n = 0;
            points.forEach((p, i) => {
                spheres[i].visible = !!p;
                if (p) {
                    spheres[i].position.set(
                        p[0] - center[0],
                        p[1],
                        p[2] - center[2],
                    );
                    spheres[i].material.color.set(
                        quality[i] === "missing"
                            ? "#ee7e74"
                            : quality[i] === "predicted"
                              ? "#e1bb70"
                              : color,
                    );
                }
                if (parents[i] >= 0) {
                    const a = points[parents[i]];
                    const from =
                        p && a
                            ? [a[0] - center[0], a[1], a[2] - center[2]]
                            : [0, -5, 0];
                    const to =
                        p && a
                            ? [p[0] - center[0], p[1], p[2] - center[2]]
                            : [0, -5, 0];
                    positions.set(from, n);
                    positions.set(to, n + 3);
                    n += 6;
                }
            });
            geometry.attributes.position.needsUpdate = true;
        },
        dispose() {
            geometry.dispose();
            dot.dispose();
            lines.material.dispose();
            spheres.forEach((s) => s.material.dispose());
        },
    };
}
