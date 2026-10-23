import * as THREE from "./vendor/three.module.min.js";

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
