import numpy as np

from dollfight.animation_export import export_animation
from dollfight.kinematics import PARENTS, Retargeter, rest_pose
from dollfight.motions import pose_at


def rotate(q, v):
    qv = np.array([q[k] for k in ("x", "y", "z")])
    return v + 2 * np.cross(qv, np.cross(qv, v) + q["w"] * v)


def test_exported_global_rotations_reconstruct_fk_before_and_after_basis_reflection():
    retargeter = Retargeter(rest_pose(), "reach")
    frames = []
    for i, t in enumerate((1.7, 4.7, 12.7)):
        points, rotations, _ = retargeter.process(pose_at(t)[0], 1 / 30)
        frames.append({"t": i / 30, "root": points[0], "rotations": rotations, "avatar": points})
    run = {"name": "test", "fps": 30, "target_rest": retargeter.rest, "frames": frames}
    clip = export_animation(run)
    for source, frame in zip(frames, clip["frames"], strict=True):
        positions = np.zeros((19, 3))
        positions[0] = source["root"]
        for i, parent in enumerate(PARENTS):
            if parent < 0:
                continue
            delta = retargeter.rest[i] - retargeter.rest[parent]
            positions[i] = positions[parent] + rotate(frame["rotations"][parent], delta)
            q = frame["rotations"][parent]
            mirrored = {"x": -q["x"], "y": -q["y"], "z": q["z"], "w": q["w"]}
            np.testing.assert_allclose(
                rotate(mirrored, delta * [1, 1, -1]), rotate(q, delta) * [1, 1, -1], atol=1e-6
            )
        np.testing.assert_allclose(positions, source["avatar"], atol=1e-6)
