"""Convert CMU 14_01 ASF/AMC into canonical19, with source hashes and units.

ASF bone endpoints are transformed by parent @ C @ M @ C^-1.
The output is downsampled at 30 Hz, keeps metric scale, and aligns the initial
heading to +Z. The file is optical motion capture, never Gemini measurements.
"""

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


def main():
    raw = ROOT / "data" / "raw" / "cmu"
    bones, hierarchy = read_asf(raw / "14.asf")
    frames = read_amc(raw / "14_01.amc")
    # First 24 seconds; 120 Hz source to 30 Hz display, no interpolation.
    points = np.array([forward(bones, hierarchy, f) for f in frames[:2880:4]])
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
    output = {
        "name": "cmu_boxing",
        "source": "cmu_optical_mocap",
        "fps": 30,
        "description": "CMU 14_01 真实光学拳击动捕；不是深度相机输入，无逐拳类别真值。",
        "source_fps": 120,
        "source_units_to_m": 2.54 / 100 / 0.45,
        "source_url": "https://mocap.cs.cmu.edu/search.php?subjectnumber=14",
        "source_hashes": {
            name: hashlib.sha256((raw / name).read_bytes()).hexdigest()
            for name in ("14.asf", "14_01.amc")
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
    (destination / "cmu_boxing.json").write_text(
        json.dumps(output, separators=(",", ":")), encoding="utf-8"
    )
    print(f"Converted {len(points)} frames ({len(points) / 30:.1f}s), metric canonical19")


if __name__ == "__main__":
    main()
