import numpy as np

from dollfight.foot_contact import FootHeadingLock
from dollfight.kinematics import rest_pose, rotation_y


def test_planted_shoe_resists_heading_noise_but_releases_for_a_pivot_and_takeoff():
    rest = rest_pose()
    ankle, toe = rest[13].copy(), rest[14].copy()
    solver = FootHeadingLock()
    for _ in range(6):
        solver.update(ankle, toe, ankle, toe, True, 1 / 30)
    jitter = ankle + rotation_y(0.01) @ (toe - ankle)
    correction = solver.update(ankle, jitter, ankle, toe, True, 1 / 30)
    np.testing.assert_allclose(correction @ (jitter - ankle), toe - ankle, atol=1e-8)
    pivot = ankle + rotation_y(0.20) @ (toe - ankle)
    np.testing.assert_allclose(solver.update(ankle, pivot, ankle, toe, True, 1 / 30), np.eye(3))
    for _ in range(6):
        solver.update(ankle, toe, ankle, toe, True, 1 / 30)
    # A raised heel/toe must preserve the captured orientation, even if the
    # upstream position detector still labels it as contact for one frame.
    np.testing.assert_allclose(
        solver.update(ankle + [0, 0.12, 0], toe + [0, 0.12, 0], ankle, toe, True, 1 / 30),
        np.eye(3),
    )


def test_guard_is_not_a_repeated_deep_duck():
    from dollfight.sparring import excerpt

    points, _, _ = excerpt("guard")
    trunk = points[:, 1] - points[:, 0]
    lean = np.rad2deg(np.arctan2(np.linalg.norm(trunk[:, [0, 2]], axis=1), trunk[:, 1]))
    assert lean.max() < 16
