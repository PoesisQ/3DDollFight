import json

import numpy as np
import pytest

from dollfight.kinematics import (
    EDGES,
    PARENTS,
    PROFILES,
    Retargeter,
    bone_lengths,
    quaternion,
    rest_pose,
    swing_rotation,
    two_bone_ik,
)
from dollfight.motions import ATTACKS, pose_at
from dollfight.pipeline import export_poseframes, import_frames, make_run
from dollfight.recognition import ActionRecognizer
from dollfight.solver import SkeletonSolver


def quat_matrix(q):
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )


def test_ik_handles_unreachable_and_fully_folded_targets():
    for target in ([5, 0, 0], [0, 0, 0], [0, 0.4, 0.2]):
        middle, end = two_bone_ik([0, 0, 0], target, 0.3, 0.25, [0, 1, 0])
        assert np.isfinite(middle).all()
        np.testing.assert_allclose(np.linalg.norm(middle), 0.3, atol=1e-6)
        np.testing.assert_allclose(np.linalg.norm(end - middle), 0.25, atol=1e-6)


def test_opposite_bone_direction_is_a_proper_rotation():
    rotation = swing_rotation([1, 0, 0], [-1, 0, 0])
    np.testing.assert_allclose(rotation @ [1, 0, 0], [-1, 0, 0], atol=1e-8)
    np.testing.assert_allclose(quat_matrix(quaternion(rotation)), rotation, atol=1e-8)
    assert np.linalg.det(rotation) == pytest.approx(1)


@pytest.mark.parametrize("profile", PROFILES)
def test_emitted_local_rotations_reconstruct_target_fk_and_keep_lengths(profile):
    target = Retargeter(rest_pose(), profile)
    for t in np.linspace(0, 21, 80):
        source, _ = pose_at(t)
        points, quaternions, _ = target.process(source, 1 / 30)
        fk = np.zeros((19, 3))
        rotations = np.zeros((19, 3, 3))
        fk[0] = points[0]
        for i, parent in enumerate(PARENTS):
            local = quat_matrix(quaternions[i])
            rotations[i] = local if parent < 0 else rotations[parent] @ local
            if parent >= 0:
                fk[i] = fk[parent] + rotations[parent] @ (target.rest[i] - target.rest[parent])
        np.testing.assert_allclose(fk, points, atol=1e-6)
        np.testing.assert_allclose(bone_lengths(points), bone_lengths(target.rest), atol=1e-6)


def test_stationary_noise_reduction_and_bone_consistency():
    rng = np.random.default_rng(17)
    rest = pose_at(0)[0]
    solver = SkeletonSolver(rest_pose())
    raw_errors, filtered_errors = [], []
    for i in range(180):
        noisy = rest + rng.normal(0, 0.02, rest.shape)
        output, _, _ = solver.process(noisy, np.ones(19), i / 30)
        if i > 20:
            raw_errors.append(np.linalg.norm(noisy - rest, axis=1).mean())
            filtered_errors.append(np.linalg.norm(output - rest, axis=1).mean())
        np.testing.assert_allclose(bone_lengths(output), bone_lengths(rest_pose()), atol=1e-6)
    assert np.mean(filtered_errors) < 0.7 * np.mean(raw_errors)


def test_missing_limb_does_not_issue_an_attack_and_recovers_only_after_neutral():
    solver = SkeletonSolver(rest_pose())
    recognizer = ActionRecognizer(rest_pose())
    events = []
    saw_missing = False
    for i in range(120):
        t = i / 30
        points = pose_at(t)[0]
        confidence = np.ones(19)
        if 1.3 < t < 2.5:
            points[6:8] = np.nan
            confidence[6:8] = 0
        output, states, valid = solver.process(points, confidence, t)
        assert np.isfinite(output).all()
        saw_missing |= states[7] == "missing"
        found, _ = recognizer.process(output, valid, t)
        events.extend(found)
    assert saw_missing
    assert not any(e["action"].startswith("left") for e in events)


@pytest.mark.parametrize("mode", ["showcase", "turn"])
def test_action_events_are_detected_once_with_heading_changes(mode):
    run = make_run({"source": mode, "noise_mm": 0})
    assert [e["action"] for e in run["events"]] == ATTACKS


def test_noisy_idle_does_not_trigger_and_processing_rejects_duplicate_time():
    run = make_run({"source": "idle", "noise_mm": 30})
    assert run["events"] == []
    solver = SkeletonSolver(rest_pose())
    solver.process(rest_pose(), np.ones(19), 1.0)
    with pytest.raises(ValueError):
        solver.process(rest_pose(), np.ones(19), 1.0)


def test_poseframe_export_import_and_cross_stream_rejection():
    run = make_run({"source": "punch", "noise_mm": 0})
    messages = export_poseframes(run)
    clip = import_frames(messages)
    np.testing.assert_allclose(clip["points"][0], run["frames"][0]["raw"], atol=1e-6)
    assert clip["fps"] == pytest.approx(30, rel=0.001)
    messages[3]["clock_domain"] = "another-host"
    with pytest.raises(ValueError, match="同一时钟"):
        import_frames(messages)


def test_synthetic_fixture_bone_lengths_are_constant():
    expected = bone_lengths(rest_pose())
    for t in np.linspace(0, 21, 100):
        points, _ = pose_at(t)
        np.testing.assert_allclose(bone_lengths(points), expected, atol=1e-6)


@pytest.mark.parametrize("scale", [0.7, 1.3])
def test_recognition_uses_calibrated_body_size(scale):
    recognizer = ActionRecognizer(rest_pose() * scale)
    actions = []
    for t in np.arange(0, 22, 1 / 30):
        points, _ = pose_at(t)
        found, _ = recognizer.process(points * scale, np.ones(19, dtype=bool), t)
        actions.extend(e["action"] for e in found)
    assert actions == ATTACKS


def test_cmu_is_finite_metric_data_with_no_fabricated_accuracy():
    run = make_run({"source": "cmu_boxing", "noise_mm": 0})
    assert run["source"] == "cmu_optical_mocap"
    assert len(run["frames"]) == 720
    assert "accuracy" not in run["metrics"]
    points = np.array([f["avatar"] for f in run["frames"]])
    assert np.isfinite(points).all()
    assert 0.8 < points[:, 4, 1].mean() < 2
    target_lengths = bone_lengths(run["target_rest"])
    for parent, child in EDGES:
        lengths = np.linalg.norm(points[:, child] - points[:, parent], axis=1)
        assert np.max(abs(lengths - target_lengths[child - 1])) < 3e-5


def test_import_handles_inferred_joints_and_an_entire_missing_frame():
    messages = export_poseframes(
        {"frames": [{"t": i / 30, "raw": pose_at(i / 30)[0].tolist()} for i in range(60)]}
    )
    messages[2]["joints"]["left_wrist"].update(tracking_state="inferred", confidence=0.6)
    for joint in messages[35]["joints"].values():
        joint.update(position_m=None, tracking_state="missing", confidence=0)
    run = make_run({"source": "upload", "frames": messages, "noise_mm": 0})
    assert run["frames"][2]["quality"][7] == "observed"
    assert not run["frames"][35]["event_ids"]
    assert run["frames"][35]["error_mm"] is None
    json.dumps(run, allow_nan=False)
