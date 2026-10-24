import * as THREE from "./vendor/three.module.min.js";

// Combat-readable view: retain the player's horizontal viewing direction,
// move the virtual camera back enough to include the opponent's entire pose.
// This is intentionally different from calibrated physical-eye projection.
export function configureOpponentCamera(camera, eye, points, aspect) {
    const box = new THREE.Box3().setFromPoints(
        points.map((p) => new THREE.Vector3(...p)),
    );
    box.expandByScalar(0.24); // hair, hands and clothing beyond joint centres
    const center = box.getCenter(new THREE.Vector3());
    const back = eye.clone().sub(center).setY(0).normalize();
    if (back.lengthSq() < 0.1) back.set(-1, 0, 0);
    const up = new THREE.Vector3(0, 1, 0);
    const right = new THREE.Vector3().crossVectors(up, back).normalize();
    camera.fov = 52;
    camera.aspect = aspect;
    camera.near = 0.04;
    camera.far = 40;
    const tanY = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * 0.86;
    const tanX = tanY * aspect;
    let distance = 1;
    for (const x of [box.min.x, box.max.x])
        for (const y of [box.min.y, box.max.y])
            for (const z of [box.min.z, box.max.z]) {
                const relative = new THREE.Vector3(x, y, z).sub(center);
                distance = Math.max(
                    distance,
                    Math.abs(relative.dot(right)) / tanX + relative.dot(back),
                    Math.abs(relative.y) / tanY + relative.dot(back),
                );
            }
    camera.position.copy(center).addScaledVector(back, distance);
    camera.up.copy(up);
    camera.lookAt(center);
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld(true);
}

// Physical screen corners in world coordinates: lower-left, lower-right, upper-left.
export function configureOffAxis(camera, eye, a, b, c, near = 0.04, far = 35) {
    const right = b.clone().sub(a).normalize(),
        up = c.clone().sub(a).normalize();
    const normal = new THREE.Vector3().crossVectors(right, up).normalize();
    const va = a.clone().sub(eye),
        vb = b.clone().sub(eye),
        vc = c.clone().sub(eye);
    const distance = -normal.dot(va);
    if (distance <= 0 || Math.abs(right.dot(up)) > 1e-5)
        throw new Error("眼位须位于矩形屏幕的观看侧");
    const left = (right.dot(va) * near) / distance,
        rightEdge = (right.dot(vb) * near) / distance;
    const bottom = (up.dot(va) * near) / distance,
        top = (up.dot(vc) * near) / distance;
    camera.position.copy(eye);
    camera.near = near;
    camera.far = far;
    camera.quaternion.setFromRotationMatrix(
        new THREE.Matrix4().makeBasis(right, up, normal),
    );
    camera.projectionMatrix.makePerspective(
        left,
        rightEdge,
        top,
        bottom,
        near,
        far,
    );
    camera.projectionMatrixInverse.copy(camera.projectionMatrix).invert();
    camera.updateMatrixWorld(true);
}
