import numpy as np
from test_animation_export import rotate

from dollfight.animation_export import export_duel
from dollfight.kinematics import PARENTS, rest_pose, rotation_y


def test_duel_export_maps_shared_clock_and_does_not_add_local_travel_twice():
    rest = rest_pose()
    identities = [[0, 0, 0, 1]] * 19
    source = [
        {"t": t, "root": [100 + t, rest[0, 1], 200], "rotations": identities} for t in (0, 1, 2)
    ]
    duel = [
        {
            "t": t,
            "opponent_frame": index,
            "positions": [[-0.8, 0, 0.1], [0.6, 0, -0.2]],
            "round": 1,
            "health": [100, 100],
            "distance_m": 1.4,
        }
        for t, index in ((0, 2), (1, 0), (2, 0))
    ]
    clips, timeline = export_duel(
        {
            "name": "test",
            "fps": 1,
            "duration": 2,
            "target_rest": rest,
            "frames": source,
            "duel": {"frames": duel, "opponent_frames": source},
        }
    )
    for player, clip in enumerate(clips):
        assert [f["time"] for f in clip["frames"]] == [0, 1, 2]
        yaw = (np.pi / 2, -np.pi / 2)[player]
        for frame in clip["frames"]:
            root = np.array([frame["root"][k] for k in "xyz"])
            expected = np.array(duel[0]["positions"][player]) + [0, rest[0, 1], 0]
            np.testing.assert_allclose(root, expected)
            for i, parent in enumerate(PARENTS):
                if parent >= 0:
                    delta = rest[i] - rest[parent]
                    np.testing.assert_allclose(
                        rotate(frame["rotations"][parent], delta),
                        rotation_y(yaw) @ delta,
                        atol=1e-8,
                    )
    assert timeline["version"] == "dollfight-duel-1"
