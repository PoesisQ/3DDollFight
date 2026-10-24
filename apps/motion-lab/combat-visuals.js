import * as THREE from "three";

const colors = ["#76e3ca", "#ed8a78"];
const up = new THREE.Vector3(0, 1, 0);
function capsule(color, radius) {
    const group = new THREE.Group();
    const material = new THREE.MeshBasicMaterial({
        color,
        wireframe: true,
        transparent: true,
        opacity: 0.45,
        depthTest: false,
    });
    const body = new THREE.Mesh(
        new THREE.CylinderGeometry(radius, radius, 1, 10, 1, true),
        material,
    );
    const ends = [0, 1].map(
        () => new THREE.Mesh(new THREE.SphereGeometry(radius, 10, 6), material),
    );
    group.add(body, ...ends);
    return {
        group,
        set(a, b, visible = true) {
            group.visible = visible;
            const av = new THREE.Vector3().fromArray(a),
                bv = new THREE.Vector3().fromArray(b);
            ends[0].position.copy(av);
            ends[1].position.copy(bv);
            body.position.copy(av).lerp(bv, 0.5);
            const direction = bv.sub(av),
                length = direction.length();
            body.visible = length > 1e-5;
            if (body.visible) {
                body.quaternion.setFromUnitVectors(up, direction.normalize());
                body.scale.y = length;
            }
        },
    };
}

export class CombatVisuals {
    constructor(scene) {
        this.group = new THREE.Group();
        this.debug = new THREE.Group();
        this.group.add(this.debug);
        scene.add(this.group);
        this.rings = colors.map((color) => {
            const mesh = new THREE.Mesh(
                new THREE.RingGeometry(0.25, 0.27, 48),
                new THREE.MeshBasicMaterial({
                    color,
                    side: THREE.DoubleSide,
                    transparent: true,
                    opacity: 0.65,
                }),
            );
            mesh.rotation.x = -Math.PI / 2;
            this.group.add(mesh);
            return mesh;
        });
        this.capsules = colors.map((color) =>
            [0.14, 0.19, 0.09, 0.09, 0.1, 0.1].map((r, i) => {
                const value = capsule(i < 4 ? color : "#80b9ff", r);
                this.debug.add(value.group);
                return value;
            }),
        );
        this.attacks = Array.from({ length: 4 }, () => {
            const value = capsule("#ffe29b", 0.03);
            this.debug.add(value.group);
            return value;
        });
        this.contact = new THREE.Mesh(
            new THREE.SphereGeometry(0.1, 16, 10),
            new THREE.MeshBasicMaterial({
                color: "#ffcf82",
                wireframe: true,
                transparent: true,
                opacity: 0.9,
                depthTest: false,
            }),
        );
        this.group.add(this.contact);
    }
    update(run, options, frame, second, alpha) {
        const { duel, nextDuel, time, index, hitboxes } = options;
        this.debug.visible = hitboxes;
        for (let p = 0; p < 2; p++) {
            const position = new THREE.Vector3()
                .fromArray(duel.positions[p])
                .lerp(
                    new THREE.Vector3().fromArray(nextDuel.positions[p]),
                    alpha,
                );
            this.rings[p].position.set(position.x, -0.026, position.z);
            const world = duel.world[p],
                quality = (p === 0 ? frame : second).quality;
            const pairs = [
                [4, 4],
                [0, 2],
                [11, 12],
                [15, 16],
                [6, 7],
                [9, 10],
            ];
            pairs.forEach(([a, b], i) =>
                this.capsules[p][i].set(
                    world[a],
                    world[b],
                    quality[a] === "observed" &&
                        quality[b] === "observed" &&
                        (i < 4 ||
                            (duel.defense[p].guard_sides || []).includes(
                                i === 4 ? "left" : "right",
                            )),
                ),
            );
        }
        const trails = run.duel.frames
            .slice(Math.max(0, index - 3), index + 1)
            .flatMap((f) => f.active_attacks)
            .slice(-4);
        this.attacks.forEach((a, i) =>
            trails[i]
                ? a.set(trails[i].start, trails[i].end)
                : (a.group.visible = false),
        );
        const event = run.duel.events
            .filter(
                (e) =>
                    e.time_s <= time + 0.0001 &&
                    time - e.time_s < 0.32 &&
                    ["hit", "block", "parry", "guard_break"].includes(
                        e.outcome,
                    ),
            )
            .at(-1);
        this.contact.visible = !!event;
        if (event) {
            const age = Math.max(0, time - event.time_s) / 0.32;
            this.contact.position.fromArray(event.position);
            this.contact.scale.setScalar(1 + age * 2);
            this.contact.material.opacity = 0.9 * (1 - age);
            this.contact.material.color.set(
                event.outcome === "block"
                    ? "#80b9ff"
                    : event.outcome === "parry"
                      ? "#ffdf80"
                      : "#ff8d70",
            );
        }
    }
}
