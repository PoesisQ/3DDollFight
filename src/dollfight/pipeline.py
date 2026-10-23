"""Replay runs through the same causal solver, recognizer and retargeter per frame."""

import json
from pathlib import Path
from time import perf_counter

import numpy as np

from dollfight.contracts import JOINTS, validate_message
from dollfight.kinematics import EDGES, PARENTS, PROFILES, Retargeter, bone_lengths, rest_pose, unit
from dollfight.motions import synthetic_clip
from dollfight.recognition import ActionRecognizer
from dollfight.solver import SkeletonSolver

ROOT = Path(__file__).resolve().parents[2]
CATALOG = [
    {"id": "duel", "label": "战术对练 · 进退 / 防守 / 旋转 / 连招", "kind": "双人合成"},
    {"id": "showcase", "label": "招式巡检 · 13 种动作", "kind": "合成验证"},
    {"id": "cmu_boxing", "label": "CMU 14_01 · 真人拳击动捕", "kind": "公开动捕"},
    {"id": "punch", "label": "左右直拳 · 重复与回收", "kind": "合成验证"},
    {"id": "occlusion", "label": "手臂遮挡 · 丢失与恢复", "kind": "合成验证"},
    {"id": "turn", "label": "转向出招 · 身体局部坐标", "kind": "合成验证"},
    {"id": "idle", "label": "静止与摆动 · 误触发检查", "kind": "负样本"},
]


def calibrated_rest(points):
    # Only the initial standing window is used; future action frames do not
    # influence calibration when this replay algorithm is used online.
    points = points[:30]
    template = rest_pose()
    result = template.copy()
    pelvis = points[np.isfinite(points[:, 0]).all(axis=1), 0]
    if len(pelvis) < min(5, len(points)):
        raise ValueError("起始站立窗口缺少可靠 pelvis，无法标定")
    result[0] = np.median(pelvis, axis=0)
    if not 0.2 < result[0, 1] < 2.5:
        raise ValueError("骨盆离地高度不合理；请检查相机高度、坐标和米制单位")
    for parent, child in EDGES:
        lengths = np.linalg.norm(points[:, child] - points[:, parent], axis=1)
        lengths = lengths[np.isfinite(lengths) & (lengths > 0.01)]
        if not len(lengths):
            raise ValueError(f"没有足够的 {JOINTS[child]} 有效观测，无法标定骨长")
        result[child] = result[parent] + unit(template[child] - template[parent]) * np.median(
            lengths
        )
    return result


def import_frames(messages, camera_height=1.4, camera_distance=2.5):
    if not 2 <= len(messages) <= 1800:
        raise ValueError("请导入 2–1800 帧 PoseFrame JSONL（单人、同一连续流）")
    points, confidence, times = [], [], []
    previous_sequence = -1
    stream = None
    for message in messages:
        validate_message(message)
        if message["message_type"] != "pose_frame":
            raise ValueError("回放输入必须为 PoseFrame")
        identity = tuple(
            message[k]
            for k in ("session_id", "stream_id", "player_id", "clock_domain", "calibration_id")
        )
        if stream is not None and identity != stream:
            raise ValueError("一次导入只接受同一时钟/标定/玩家的数据流")
        stream = identity
        if message["sequence"] <= previous_sequence:
            raise ValueError("帧序号必须递增")
        previous_sequence = message["sequence"]
        point = np.array([message["joints"][name]["position_m"] or [np.nan] * 3 for name in JOINTS])
        point = point * [1, -1, -1] + [0, camera_height, camera_distance]
        points.append(point)
        confidence.append(
            [
                message["joints"][name]["confidence"]
                if message["joints"][name]["tracking_state"] in ("observed", "inferred")
                else 0.0
                for name in JOINTS
            ]
        )
        times.append(int(message["captured_at_ns"]))
    times = np.array([value - times[0] for value in times], dtype=float) / 1e9
    if np.any(np.diff(times) <= 0):
        raise ValueError("时间戳必须严格递增")
    points = np.array(points)
    points[np.asarray(confidence) < 0.35] = np.nan
    return {
        "name": "uploaded",
        "source": "uploaded_poseframe",
        "points": points,
        "confidence": np.array(confidence),
        "times": times,
        "fps": float(1 / np.median(np.diff(times))),
        "rest": calibrated_rest(points),
        "description": "用户 PoseFrame：水平相机适配，可设置高度、距离；无三维真值。",
    }


def load_clip(name):
    if name == "cmu_boxing":
        clip = json.loads((ROOT / "data/samples/cmu_boxing.json").read_text(encoding="utf-8"))
        clip["points"] = np.asarray(clip["points"])
        clip["rest"] = np.asarray(clip["rest"])
        return clip
    if name not in {item["id"] for item in CATALOG}:
        raise ValueError("Unknown source")
    return synthetic_clip(name)


def make_run(config, *, include_duel=False, player=0):
    name = config.get("source", "duel")
    clip = (
        import_frames(
            config["frames"],
            float(config.get("camera_height", 1.4)),
            float(config.get("camera_distance", 2.5)),
        )
        if name == "upload"
        else load_clip(name)
        if name != "duel"
        else None
    )
    if name == "duel":
        from dollfight.duel_fixture import duel_clip

        clip = duel_clip(player)
    sigma = np.clip(float(config.get("noise_mm", 5)), 0, 80) / 1000
    dropout = np.clip(float(config.get("dropout", 0)), 0, 0.5)
    cutoff = float(np.clip(config.get("cutoff", 1.7), 0.2, 12))
    profile = config.get("profile", "standard")
    if profile not in PROFILES:
        raise ValueError("Unknown avatar profile")
    seed = int(config.get("seed", 42)) + player
    rng = np.random.default_rng(seed)
    truth = clip["points"]
    observations = truth + rng.normal(0, sigma, truth.shape)
    confidence = clip.get("confidence", np.ones(truth.shape[:2])).copy()
    confidence[rng.random(confidence.shape) < dropout] = 0
    times = clip.get("times", np.arange(len(truth)) / clip["fps"])
    if name == "occlusion":
        confidence[(times > 1.5) & (times < 2.1), 6:8] = 0
        confidence[(times > 8.8) & (times < 9.1), 16:18] = 0
    observations[confidence < 0.35] = np.nan
    solver = SkeletonSolver(
        clip["rest"],
        cutoff=cutoff,
        smoothing=bool(config.get("smoothing", True)),
        constraints=bool(config.get("constraints", True)),
    )
    recognizer = ActionRecognizer(clip["rest"])
    retarget = Retargeter(clip["rest"], profile, foot_lock=bool(config.get("foot_lock", True)))
    frames, events, costs, errors_raw, errors_solved, bones_raw, bones_solved = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )
    lengths = bone_lengths(clip["rest"])
    errors_all, errors_missing = [], []
    previous_t = None
    for index, (point, quality, time_s) in enumerate(
        zip(observations, confidence, times, strict=True)
    ):
        start = perf_counter()
        solved, states, valid = solver.process(point, quality, float(time_s))
        recognized, state = recognizer.process(solved, valid, float(time_s))
        avatar, quaternions, contacts = retarget.process(
            solved, 1 / clip["fps"] if previous_t is None else time_s - previous_t
        )
        previous_t = time_s
        costs.append((perf_counter() - start) * 1000)
        events.extend({**event, "frame": index} for event in recognized)
        raw_error = np.linalg.norm(point - truth[index], axis=1)
        solved_error = np.linalg.norm(solved - truth[index], axis=1)
        comparable = np.isfinite(raw_error) & np.isfinite(solved_error)
        errors_raw.extend(raw_error[comparable])
        errors_solved.extend(solved_error[comparable])
        errors_all.extend(solved_error[np.isfinite(solved_error)])
        errors_missing.extend(solved_error[~comparable & np.isfinite(solved_error)])
        raw_bones = abs(bone_lengths(point) - lengths)
        fixed_bones = abs(bone_lengths(solved) - lengths)
        bones_raw.extend(raw_bones[np.isfinite(raw_bones)])
        bones_solved.extend(fixed_bones)
        frames.append(
            {
                "t": round(float(time_s), 5),
                "raw": [
                    [round(float(v), 5) for v in row] if np.isfinite(row).all() else None
                    for row in point
                ],
                "solved": solved.round(5).tolist(),
                "avatar": avatar.round(5).tolist(),
                "rotations": quaternions.round(7).tolist(),
                "root": avatar[0].round(5).tolist(),
                "quality": states,
                "contacts": contacts,
                "recognition": state,
                "event_ids": [event["id"] for event in recognized],
                "error_mm": round(float(np.nanmean(solved_error) * 1000), 2)
                if np.isfinite(solved_error).any()
                else None,
            }
        )

    def mean(values):
        return float(np.mean(values)) * 1000 if len(values) else 0.0

    metrics = {
        "raw_error_mm": round(mean(errors_raw), 2),
        "solved_error_mm": round(mean(errors_solved), 2),
        "solved_all_error_mm": round(mean(errors_all), 2),
        "solved_missing_error_mm": round(mean(errors_missing), 2) if errors_missing else None,
        "raw_bone_error_mm": round(mean(bones_raw), 3),
        "solved_bone_error_mm": round(mean(bones_solved), 3),
        "processing_p50_ms": round(float(np.percentile(costs, 50)), 3),
        "processing_p95_ms": round(float(np.percentile(costs, 95)), 3),
        "observed_percent": round(float(np.isfinite(observations).all(axis=2).mean() * 100), 1),
        "event_count": len(events),
        "reference": "clean_input" if name != "upload" else "input_consistency_only",
        "comparison": "raw_error_mm/solved_error_mm use the same observed joints",
    }
    run = {
        "version": "0.3.0",
        "source": clip["source"],
        "name": name,
        "description": clip["description"],
        "fps": clip["fps"],
        "duration": float(times[-1]),
        "joints": JOINTS,
        "parents": PARENTS.tolist(),
        "source_rest": clip["rest"].tolist(),
        "target_rest": retarget.rest.tolist(),
        "frames": frames,
        "events": events,
        "metrics": metrics,
        "config": {key: value for key, value in config.items() if key != "frames"},
        "limitations": [
            "算法耗时仅单人骨架、识别与重定向，不含碰撞、相机、网络和渲染。",
            "误差相对未加噪输入；不代表真实 RGB-D 人体关节准确率。",
            "位置输入无法恢复真实前臂扭转和手指；使用父骨架朝向先验。",
        ],
    }
    if include_duel:
        from dollfight.duel import build_duel

        secondary = make_run(config, player=1) if name == "duel" else None
        run["duel"] = build_duel(run, secondary, config)
    return run


def export_poseframes(run):
    messages = []
    for sequence, frame in enumerate(run["frames"]):
        joints = {}
        for name, point in zip(JOINTS, frame["raw"], strict=True):
            position = None if point is None else [point[0], 1.4 - point[1], 2.5 - point[2]]
            joints[name] = {
                "position_m": position,
                "confidence": 0 if position is None else 1,
                "tracking_state": "missing" if position is None else "observed",
            }
        messages.append(
            {
                "schema_version": "0.1.0",
                "message_type": "pose_frame",
                "session_id": "lab-export",
                "stream_id": "replay-0",
                "player_id": "p1",
                "sequence": sequence,
                "captured_at_ns": str(round((frame["t"] + 1) * 1e9)),
                "clock_domain": "replay-clock",
                "calibration_id": "level-camera-h1.4-d2.5",
                "coordinate_frame": "camera_optical_rh",
                "skeleton_id": "canonical19",
                "joints": joints,
            }
        )
    return messages
