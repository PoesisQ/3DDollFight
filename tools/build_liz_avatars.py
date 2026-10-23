"""Package generated Hunyuan meshes as experimental VRM assets.

Original reference PNGs are embedded unchanged. Front projection and procedural
back colors are a preview material, not multiview texture reconstruction.
Region-aware distance weights are an explicit baseline, not TokenRig output.
"""

import hashlib
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image

from dollfight.avatar_audit import HUMAN_BONES, PARENTS, EmbeddedGLB, audit_bytes

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data/avatars/liz"


def skeleton():
    return np.array(
        [
            [0, 0.94, 0],
            [0, 1.10, 0],
            [0, 1.30, 0],
            [0, 1.43, 0],
            [0, 1.56, 0],
            [0.17, 1.35, 0],
            [0.40, 1.33, 0],
            [0.60, 1.32, 0],
            [-0.17, 1.35, 0],
            [-0.40, 1.33, 0],
            [-0.60, 1.32, 0],
            [0.085, 0.94, 0],
            [0.09, 0.50, 0.015],
            [0.09, 0.09, 0],
            [0.09, 0.04, 0.11],
            [-0.085, 0.94, 0],
            [-0.09, 0.50, 0.015],
            [-0.09, 0.09, 0],
            [-0.09, 0.04, 0.11],
        ]
    )


def weight_mesh(vertices, faces, rest, pixel_colors):
    count = len(vertices)
    distances = np.empty((count, 19))
    ends = [1, 2, 3, 4, None, 6, 7, None, 9, 10, None, 12, 13, 14, None, 16, 17, 18, None]
    for bone, end in enumerate(ends):
        a = rest[bone]
        b = rest[end] if end is not None else a + ([0, 0.14, 0] if bone == 4 else [0, 0, 0.06])
        delta = b - a
        along = np.clip((vertices - a) @ delta / (delta @ delta), 0, 1)
        distances[:, bone] = np.sum((vertices - a - along[:, None] * delta) ** 2, axis=1)
    weights = np.zeros_like(distances)
    for i, (x, y, z) in enumerate(vertices):
        # Limit influences to anatomically adjacent regions; nearest bones alone
        # bleed across skirt/legs and attach hanging hair to the shoulders.
        hair = y > 1.18 and z < -0.055 and np.max(pixel_colors[i]) < 0.46
        if y > 1.48 or hair:
            allowed = [4]
        elif abs(x) > 0.23 and y > 1.14:
            allowed = [5, 6, 7] if x > 0 else [8, 9, 10]
        elif y < 0.60:
            # A shaft follows one bone. Blend only around the anatomical joint;
            # nearest-segment Gaussians gave the middle calf too much thigh/foot
            # influence, visibly bowing the shin during kicks.
            hip, knee, ankle, toe = (11, 12, 13, 14) if x > 0 else (15, 16, 17, 18)
            upper = float(np.clip((y - rest[knee, 1] + 0.045) / 0.09, 0, 1))
            upper = upper * upper * (3 - 2 * upper)
            foot = float(np.clip((rest[ankle, 1] + 0.035 - y) / 0.07, 0, 1))
            foot = foot * foot * (3 - 2 * foot)
            toe_weight = foot * float(np.clip((z - 0.06) / 0.07, 0, 1))
            weights[i, hip] = upper
            weights[i, knee] = (1 - upper) * (1 - foot)
            weights[i, ankle] = (1 - upper) * (foot - toe_weight)
            weights[i, toe] = (1 - upper) * toe_weight
            continue
        elif y < 1.04:
            # A deliberately simple skirt baseline. Cloth simulation and collision
            # are not solved here; high kicks must be visually inspected.
            leg_weight = 0.48 * float(np.clip((1.04 - y) / 0.5, 0, 1))
            left = float(np.clip(x / 0.18 + 0.5, 0, 1))
            weights[i, 0] = 1 - leg_weight
            weights[i, 11], weights[i, 15] = leg_weight * left, leg_weight * (1 - left)
            continue
        else:
            allowed = [0, 1, 2, 3] if y < 1.4 else [2, 3, 4]
        values = np.exp(-(distances[i, allowed] - distances[i, allowed].min()) / 0.012)
        weights[i, allowed] = values / values.sum()
    # Diffuse across actual mesh edges, not Euclidean proximity. This removes
    # abrupt regional boundaries without joining neighboring disconnected surfaces.
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    edges = np.unique(np.sort(edges, axis=1), axis=0)
    src = np.concatenate((edges[:, 0], edges[:, 1]))
    dst = np.concatenate((edges[:, 1], edges[:, 0]))
    degree = np.bincount(dst, minlength=count).clip(1)
    initial = weights.copy()
    for _ in range(24):
        neighbor = np.column_stack(
            [
                np.bincount(dst, weights=weights[src, bone], minlength=count) / degree
                for bone in range(19)
            ]
        )
        weights = 0.08 * initial + 0.92 * neighbor
    joints = np.argsort(-weights, axis=1)[:, :4]
    values = np.take_along_axis(weights, joints, axis=1)
    values /= values.sum(axis=1, keepdims=True)
    return joints.astype("u1"), values.astype("<f4")


def back_colors(vertices, character):
    colors = np.ones((len(vertices), 4), dtype="<f4")
    for i, (x, y, _) in enumerate(vertices):
        color = [0.94, 0.94, 0.94]
        if y > 1.44:
            color = [0.065, 0.066, 0.075] if character == "nozomi" else [0.06, 0.075, 0.115]
        elif y > 1.4 or (abs(x) > 0.29 and y > 1.14):
            color = [0.94, 0.76, 0.64]
        elif 0.62 < y < 1.04:
            color = [0.28, 0.57, 0.76]
        elif 0.10 < y < 0.45:
            color = [0.08, 0.08, 0.085] if character == "nozomi" else [0.9, 0.9, 0.91]
        elif 0.45 <= y < 0.55:
            color = [0.94, 0.76, 0.64]
        elif y < 0.04:
            color = [0.16, 0.32, 0.47]
        colors[i, :3] = color
    return colors


def project_uv(vertices, pixels, top, bottom):
    """Orthographic front projection; clamp only the exterior image background."""
    height, width = pixels.shape[:2]
    span = (bottom - top) / 1.72
    rows = np.clip(bottom - vertices[:, 1] * span, top, bottom)
    columns = vertices[:, 0] * span + width / 2
    # Keep a globally affine projection (row-wise silhouette fitting produces
    # ripples on a triangulated surface). Only clamp head/limb background samples
    # to their nearest foreground texel; the source PNG remains unchanged.
    for i in np.flatnonzero((vertices[:, 1] > 1.4) | (np.abs(vertices[:, 0]) > 0.3)):
        y = int(rows[i])
        x = int(np.clip(columns[i], 0, width - 1))
        if pixels[y, x].min() > 0.91:
            foreground = np.flatnonzero(pixels[y].min(axis=1) < 0.88)
            if len(foreground):
                columns[i] = foreground[np.argmin(abs(foreground - x))]
    return np.column_stack((columns / width, rows / height))


def build(character, source):
    model = EmbeddedGLB(source.read_bytes())
    primitive = model.doc["meshes"][0]["primitives"][0]
    vertices = model.accessor(primitive["attributes"]["POSITION"]).astype(float)
    faces = model.accessor(primitive["indices"]).reshape(-1, 3).astype("<u4")
    bounds = (vertices.min(0), vertices.max(0))
    vertices -= [(bounds[0][0] + bounds[1][0]) / 2, bounds[0][1], 0]
    vertices *= 1.72 / (bounds[1][1] - bounds[0][1])
    rest = skeleton()
    reference = DEST / f"{character}-reference.png"
    pixels = np.asarray(Image.open(reference).convert("RGB")) / 255
    # Full reference-image silhouette bounds; geometry was generated from this image.
    top, bottom = (122, 1412) if character == "nozomi" else (114, 1405)
    uv = project_uv(vertices, pixels, top, bottom)
    pixel = np.clip((uv * [1024, 1536]).astype(int), [0, 0], [1023, 1535])
    joints, weights = weight_mesh(vertices, faces, rest, pixels[pixel[:, 1], pixel[:, 0]])
    triangle = vertices[faces]
    face_normals = np.cross(triangle[:, 1] - triangle[:, 0], triangle[:, 2] - triangle[:, 0])
    normals = np.zeros_like(vertices)
    for corner in range(3):
        np.add.at(normals, faces[:, corner], face_normals)
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    doc = {
        "asset": {"version": "2.0", "generator": "DollFight experimental Hunyuan adapter"},
        "buffers": [],
        "bufferViews": [],
        "accessors": [],
        "nodes": [],
        "meshes": [],
        "extensionsUsed": ["VRMC_vrm", "KHR_materials_unlit"],
    }
    binary = bytearray()

    def blob(data):
        binary.extend(b"\0" * (-len(binary) % 4))
        doc["bufferViews"].append({"buffer": 0, "byteOffset": len(binary), "byteLength": len(data)})
        binary.extend(data)
        return len(doc["bufferViews"]) - 1

    def accessor(data, component, shape):
        data = np.asarray(data)
        spec = {
            "bufferView": blob(data.tobytes()),
            "componentType": component,
            "count": len(data),
            "type": shape,
        }
        if shape == "VEC3":
            spec.update(min=data.min(0).tolist(), max=data.max(0).tolist())
        doc["accessors"].append(spec)
        return len(doc["accessors"]) - 1

    attrs = {
        "POSITION": accessor(vertices.astype("<f4"), 5126, "VEC3"),
        "NORMAL": accessor(normals.astype("<f4"), 5126, "VEC3"),
        "TEXCOORD_0": accessor(uv.astype("<f4"), 5126, "VEC2"),
        "JOINTS_0": accessor(joints, 5121, "VEC4"),
        "WEIGHTS_0": accessor(weights, 5126, "VEC4"),
    }
    colors = accessor(back_colors(vertices, character), 5126, "VEC4")
    primitives = []
    # A concave facial surface can have a backward normal. Splitting by normal
    # incorrectly painted those triangles as the back of the head.
    front = triangle[:, :, 2].mean(axis=1) >= -0.035
    for side, mask in enumerate((front, ~front)):
        primitives.append(
            {
                "attributes": attrs if side == 0 else {**attrs, "COLOR_0": colors},
                "indices": accessor(faces[mask].reshape(-1, 1), 5125, "SCALAR"),
                "material": side,
            }
        )
    doc["meshes"] = [{"primitives": primitives}]
    doc["images"] = [{"bufferView": blob(reference.read_bytes()), "mimeType": "image/png"}]
    doc["textures"] = [{"source": 0}]
    doc["materials"] = [
        {
            "name": "front reference projection",
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": 0},
                "metallicFactor": 0,
                "roughnessFactor": 1,
            },
            "extensions": {"KHR_materials_unlit": {}},
        },
        {
            "name": "procedural back colors (not reconstructed)",
            "pbrMetallicRoughness": {"metallicFactor": 0, "roughnessFactor": 1},
            "extensions": {"KHR_materials_unlit": {}},
        },
    ]
    matrices = []
    for i, name in enumerate(HUMAN_BONES):
        parent = PARENTS[i]
        node = {
            "name": name,
            "translation": (rest[i] if parent < 0 else rest[i] - rest[parent]).tolist(),
        }
        children = [j for j, p in enumerate(PARENTS) if p == i]
        if children:
            node["children"] = children
        doc["nodes"].append(node)
        m = np.eye(4)
        m[:3, 3] = -rest[i]
        matrices.append(m.T.reshape(16))
    doc["nodes"].append({"name": character + " generated mesh", "mesh": 0, "skin": 0})
    doc["skins"] = [
        {
            "joints": list(range(19)),
            "skeleton": 0,
            "inverseBindMatrices": accessor(np.array(matrices, dtype="<f4"), 5126, "MAT4"),
        }
    ]
    doc["scenes"], doc["scene"] = [{"nodes": [0, 19]}], 0
    title = "伞木希美" if character == "nozomi" else "铠冢霙"
    doc["extensions"] = {
        "VRMC_vrm": {
            "specVersion": "1.0",
            "meta": {
                "name": title + " · Hunyuan / 规则蒙皮实验",
                "version": "0.1",
                "authors": [
                    "DollFight coursework processing; character design from Liz and the Blue Bird"
                ],
                "licenseUrl": "https://vrm.dev/licenses/1.0/",
                "avatarPermission": "onlyAuthor",
                "commercialUsage": "personalNonProfit",
                "allowRedistribution": False,
                "modification": "allowModification",
                "references": ["https://liz-bluebird.com/"],
                "otherLicenseUrl": "https://liz-bluebird.com/",
            },
            "humanoid": {"humanBones": {n: {"node": i} for i, n in enumerate(HUMAN_BONES)}},
        }
    }
    doc["buffers"] = [{"byteLength": len(binary)}]
    encoded = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 4)
    binary.extend(b"\0" * (-len(binary) % 4))
    body = struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
    body += struct.pack("<II", len(binary), 0x004E4942) + binary
    payload = struct.pack("<III", 0x46546C67, 2, len(body) + 12) + body
    report = audit_bytes(payload)
    if report["errors"]:
        raise ValueError(report["errors"])
    destination = DEST / f"{character}.vrm"
    destination.write_bytes(payload)
    (DEST / f"{character}-audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(character, len(vertices), "vertices", len(faces), "faces", len(payload), "bytes")
    return {
        "character": character,
        "source_mesh_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "reference_sha256": hashlib.sha256(reference.read_bytes()).hexdigest(),
        "vrm_sha256": hashlib.sha256(payload).hexdigest(),
        "vertices": len(vertices),
        "faces": len(faces),
        "binding": "region-distance baseline; not SkinTokens",
        "texture": "unchanged front reference projection + procedural back colors",
        "quality": "experimental; clothing penetration and back/side likeness need inspection",
    }


def main():
    entries = []
    for character in ("nozomi", "mizore"):
        source = DEST / f"{character}-shape.glb"
        entries.append(build(character, source))
    (DEST / "generated.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
