"""Convert CMU 14_01 ASF/AMC into canonical19, with source hashes and units.

ASF bone endpoints are transformed by parent @ C @ M @ C^-1.
The output is downsampled at 30 Hz, keeps metric scale, and aligns the initial
heading to +Z. The file is optical motion capture, never Gemini measurements.
"""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from dollfight.kinematics import EDGES, body_basis, rest_pose, rotation_y, unit

ROOT = Path(__file__).resolve().parents[1]


def euler_xyz(degrees):
    x, y, z = np.deg2rad(degrees)
    rx = np.array([[1, 0, 0], [0, np.cos(x), -np.sin(x)], [0, np.sin(x), np.cos(x)]])
    ry = rotation_y(y)
    rz = np.array([[np.cos(z), -np.sin(z), 0], [np.sin(z), np.cos(z), 0], [0, 0, 1]])
    return rz @ ry @ rx


def read_asf(path):
    bones, hierarchy, section, bone = {}, {}, "", None
    for line in path.read_text().splitlines():
        tokens = line.split()
        if not tokens or tokens[0].startswith("#"):
            continue
        if tokens[0].startswith(":"):
            section = tokens[0]
        elif section == ":bonedata":
            if tokens[0] == "begin":
                bone = {"dof": []}
            elif tokens[0] == "end":
                bones[bone["name"]] = bone
            elif tokens[0] == "name":
                bone["name"] = tokens[1]
            elif tokens[0] in ("direction", "axis"):
                bone[tokens[0]] = np.array(list(map(float, tokens[1:4])))
            elif tokens[0] == "length":
                bone["length"] = float(tokens[1])
            elif tokens[0] == "dof":
                bone["dof"] = tokens[1:]
        elif section == ":hierarchy" and tokens[0] not in ("begin", "end"):
            hierarchy[tokens[0]] = tokens[1:]
    return bones, hierarchy


def read_amc(path):
    frames, current = [], None
    for line in path.read_text().splitlines():
        tokens = line.split()
        if not tokens or tokens[0].startswith(("#", ":")):
            continue
        if tokens[0].isdigit():
            if current is not None:
                frames.append(current)
            current = {}
        else:
            current[tokens[0]] = list(map(float, tokens[1:]))
    if current:
        frames.append(current)
    return frames


def forward(bones, hierarchy, frame):
    root = frame["root"]
    positions = {"root": np.array(root[:3])}
    rotations = {"root": euler_xyz(root[3:])}

    def visit(parent):
        for name in hierarchy.get(parent, []):
            bone = bones[name]
            axis = euler_xyz(bone["axis"])
            angles = np.zeros(3)
            for dof, angle in zip(bone["dof"], frame.get(name, []), strict=True):
                angles[{"rx": 0, "ry": 1, "rz": 2}[dof]] = angle
            rotations[name] = rotations[parent] @ axis @ euler_xyz(angles) @ axis.T
            positions[name] = positions[parent] + rotations[name] @ (
                bone["direction"] * bone["length"]
            )
            visit(name)

    visit("root")
    names = [
        "root",
        "lowerback",
        "thorax",
        "upperneck",
        "head",
        "lclavicle",
        "lhumerus",
        "lradius",
        "rclavicle",
        "rhumerus",
        "rradius",
        "lhipjoint",
        "lfemur",
        "ltibia",
        "ltoes",
        "rhipjoint",
        "rfemur",
        "rtibia",
        "rtoes",
    ]
    return np.array([positions[name] for name in names]) * (2.54 / 100 / 0.45)


def convert(subject="14", trial="14_01", name="cmu_boxing", seconds=24, description=None):
    raw = ROOT / "data" / "raw" / "cmu"
    bones, hierarchy = read_asf(raw / f"{subject}.asf")
    frames = read_amc(raw / f"{trial}.amc")
    # First 24 seconds; 120 Hz source to 30 Hz display, no interpolation.
    points = np.array([forward(bones, hierarchy, f) for f in frames[: int(seconds * 120) : 4]])
    initial = points[0, 0].copy()
    initial[1] = 0
    points -= initial
    basis = body_basis(points[0])
    yaw = np.arctan2(basis[0, 2], basis[2, 2])
    points = points @ rotation_y(-yaw).T
    floor = np.percentile(points[:, [14, 18], 1], 2)
    points[:, :, 1] -= floor - 0.04
    reference = rest_pose()
    reference[0] = [0, float(np.median(points[:30, 0, 1])), 0]
    base = rest_pose()
    for parent, child in EDGES:
        length = np.median(np.linalg.norm(points[:, child] - points[:, parent], axis=1))
        reference[child] = reference[parent] + unit(base[child] - base[parent]) * length
    # A capture may begin in a low fighting stance, not an upright calibration
    # pose. The neutral T-pose must put its ankles on the observed floor; using
    # the first crouched pelvis as neutral produced negative ankle heights.
    ankle_height = float(np.percentile(points[:, [13, 17], 1], 5))
    reference[:, 1] += ankle_height - np.mean(reference[[13, 17], 1])
    output = {
        "name": name,
        "source": "cmu_optical_mocap",
        "fps": 30,
        "description": description
        or "CMU 14_01 真实光学拳击动捕；不是深度相机输入，无逐拳类别真值。",
        "source_fps": 120,
        "source_units_to_m": 2.54 / 100 / 0.45,
        "source_url": f"https://mocap.cs.cmu.edu/search.php?subjectnumber={subject}",
        "source_hashes": {
            name: hashlib.sha256((raw / name).read_bytes()).hexdigest()
            for name in (f"{subject}.asf", f"{trial}.amc")
        },
        "transform": {
            "initial_xz": initial.tolist(),
            "heading_yaw": float(yaw),
            "floor_y": float(floor),
        },
        "rest": reference.round(6).tolist(),
        "points": points.round(5).tolist(),
    }
    destination = ROOT / "data" / "samples"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / f"{name}.json").write_text(
        json.dumps(output, separators=(",", ":")), encoding="utf-8"
    )
    print(f"{name}: {len(points)} frames ({len(points) / 30:.1f}s), metric canonical19")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--martial", action="store_true")
    parser.add_argument("--locomotion", action="store_true")
    args = parser.parse_args()
    if args.locomotion:
        for subject, trial, name, seconds, label in (
            ("08", "08_04", "cmu_walk", 12, "慢步前进"),
            ("76", "76_01", "cmu_retreat_punch", 20, "后退然后出拳 · 一次连续采集"),
            ("76", "76_09", "cmu_backwalk", 16, "后退行走 · 非倒放"),
            ("69", "69_42", "cmu_strafe", 28, "侧向走动与转向"),
        ):
            convert(
                subject, trial, name, seconds, f"CMU {trial} 真人光学动捕 · {label}；保留根位移。"
            )
    elif args.martial:
        for trial, name, label in (
            ("04", "cmu_front_kick", "前踢 / 提膝、伸腿、回收"),
            ("05", "cmu_low_block", "下段格挡 / 全身协同"),
            ("07", "cmu_roundhouse", "回旋踢 / 转髋、支撑脚枢转"),
            ("10", "cmu_knife_guard", "手刀防御 / 步法与躯干"),
        ):
            convert(
                "135",
                f"135_{trial}",
                name,
                60,
                f"CMU 135_{trial} 真人光学动捕 · {label}；原始连续动作，无人工旋转肢体。",
            )
    else:
        convert()


if __name__ == "__main__":
    main()
