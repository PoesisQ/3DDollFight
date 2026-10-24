"""Geometric regression for the authored rehearsal; not a naturalness score."""

import numpy as np
import pytest

from dollfight.kinematics import EDGES, segment_basis
from dollfight.sparring import EXCHANGES, inertialize_track, rehearsal_pair
from dollfight.transitions import exp_rotation, inverse, log_rotation, multiply


@pytest.fixture(scope="module")
def pair():
    return rehearsal_pair()


def test_three_rounds_have_independent_streams_and_return_without_root_drift(pair):
    assert not np.allclose(pair[0]["points"], pair[1]["points"])
    for clip in pair:
        p = clip["points"]
        assert p.shape == (2700, 19, 3)
        assert np.isfinite(p).all()
        assert np.ptp(p[:, 0, 0]) < 0.35
        assert 0.5 < np.ptp(p[:, 0, 2]) < 0.8
        for start in (0, 900, 1800):
            np.testing.assert_allclose(p[start, 0, [0, 2]], [0, 0], atol=1e-5)
        assert max(np.linalg.norm(np.diff(p[:, 0], axis=0), axis=1)) < 0.06


def test_rehearsal_changes_reach_and_contacts_without_stretching_limbs(pair):
    for clip in pair:
        p, rest = clip["points"], clip["rest"]
        for a, b in EDGES:
            np.testing.assert_allclose(
                np.linalg.norm(p[:, a] - p[:, b], axis=1),
                np.linalg.norm(rest[a] - rest[b]),
                atol=1e-7,
            )
        assert p[:, [13, 17], 1].min() > -0.02
        # Actual high kicks are present, not only labels in the timeline.
        assert p[:, [13, 17], 1].max() > 1.15


def test_every_transition_is_continuous_in_world_space(pair):
    boundaries = np.rint(np.cumsum([e[0] for e in EXCHANGES])[:-1] * 30).astype(int)
    for clip in pair:
        for rnd in range(3):
            for boundary in boundaries:
                i = boundary + rnd * 900
                displacement = np.linalg.norm(clip["points"][i] - clip["points"][i - 1], axis=1)
                assert displacement.max() < 0.13, (rnd, i, displacement.max())


def test_replay_annotations_include_both_punches_and_kicks_without_becoming_ground_truth(pair):
    for clip in pair:
        actions = clip["reference_actions"]
        assert len(actions) >= 14
        assert any(a["basis"] == "offline_extension_annotation" for a in actions)
        assert any("roundhouse" in a["action"] for a in actions)
        for a in actions:
            assert 0 <= a["time_s"] < a["active_at"] < a["active_end"] < a["recovery_end"] < 90


def test_reported_step_and_kick_preparation_do_not_fold_or_cross_legs(pair):
    # User-reported 1.5 s: shortening the trailing step used to reverse its
    # knee pole. Inspect geometry, not the contact labels produced by the IK.
    for clip in pair:
        pose = clip["points"][45]
        forward = segment_basis(pose[11] - pose[15], pose[1] - pose[0])[:, 2]
        for h, k, a in ((11, 12, 13), (15, 16, 17)):
            axis = pose[a] - pose[h]
            pole = pose[k] - pose[h] - axis * ((pose[k] - pose[h]) @ axis) / (axis @ axis)
            assert pole @ forward > 0.015
    # User-reported 8.3 s: an anchor from the preceding step pulled the new
    # kick stance's feet almost on top of each other (11 mm lateral spacing).
    pose = pair[1]["points"][249]
    left = segment_basis(pose[11] - pose[15], pose[1] - pose[0])[:, 0]
    assert (pose[13] - pose[17]) @ left > 0.20


def test_join_predicts_outgoing_velocity_instead_of_adding_incoming_velocity():
    angles = np.r_[np.arange(10) * 0.02, 1 + np.arange(20) * 0.05]
    q = exp_rotation(np.stack((angles, angles * 0, angles * 0), axis=1))[:, None]
    roots = np.zeros((30, 3))
    roots[:, 1] = angles
    roots, joined = inertialize_track(roots, q, [10])
    delta = log_rotation(multiply(joined[10], inverse(joined[9])))
    np.testing.assert_allclose(delta, [[0.02, 0, 0]], atol=1e-9)
    assert roots[10, 1] - roots[9, 1] == pytest.approx(0.02)
    np.testing.assert_allclose(joined[22:], q[22:], atol=1e-9)
