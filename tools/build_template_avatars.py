"""Build animation-first school-uniform studies on the licensed pixiv VRM sample.

Preserves the authored body, face, UVs, fingers and twist weights. Accessories
are separate geometry; the skirt has its own panel bones (no thigh weighting).
This is a character appearance study, not a likeness-approved finished model.
No image generation, texture projection, paid services or downloads occur here.
"""

import copy
import hashlib
import json
import struct
from pathlib import Path

import numpy as np

from dollfight.avatar_audit import EmbeddedGLB, audit_bytes, node_parents

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data/avatars/atelier"
SOURCE = ROOT / "data/raw/avatars/sample.vrm"
SOURCE_SHA = "12c2b97e95e700783a6a550dc0eee2d7880aeedccef9ae67bc4c5a2f0f2631a2"


def local_matrix(node):
    if "matrix" in node:
        return np.array(node["matrix"]).reshape(4, 4).T
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    matrix = np.eye(4)
    matrix[:3, :3] = [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]
    matrix[:3, :3] *= node.get("scale", [1, 1, 1])
    matrix[:3, 3] = node.get("translation", [0, 0, 0])
    return matrix


def world_matrices(nodes):
    parents = node_parents(nodes)
    result = {}

    def visit(i):
        if i not in result:
            result[i] = (visit(parents[i]) if parents[i] >= 0 else np.eye(4)) @ local_matrix(
                nodes[i]
            )
        return result[i]

    return np.array([visit(i) for i in range(len(nodes))])


def normals(vertices, faces):
    tri = vertices[faces]
    directions = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    result = np.zeros_like(vertices, dtype=float)
    for corner in range(3):
        np.add.at(result, faces[:, corner], directions)
    return result / np.maximum(np.linalg.norm(result, axis=1, keepdims=True), 1e-12)


class Builder:
    def __init__(self, model):
        self.source = model
        self.doc = copy.deepcopy(model.doc)
        self.binary = bytearray(model.binary)

    def accessor(self, data, component=5126, shape="VEC3"):
        dtype = {5126: "<f4", 5125: "<u4", 5123: "<u2"}[component]
        data = np.asarray(data, dtype=dtype)
        self.binary.extend(b"\0" * (-len(self.binary) % 4))
        self.doc["bufferViews"].append(
            {"buffer": 0, "byteOffset": len(self.binary), "byteLength": data.nbytes}
        )
        self.binary.extend(data.tobytes())
        spec = {
            "bufferView": len(self.doc["bufferViews"]) - 1,
            "componentType": component,
            "type": shape,
            "count": len(data),
        }
        if shape == "VEC3":
            spec.update(min=data.min(0).tolist(), max=data.max(0).tolist())
        self.doc["accessors"].append(spec)
        return len(self.doc["accessors"]) - 1

    def material(self, name, color, double=False):
        self.doc["materials"].append(
            {
                "name": name,
                "doubleSided": double,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [*color, 1],
                    "metallicFactor": 0,
                    "roughnessFactor": 0.9,
                },
                "extensions": {
                    "KHR_materials_unlit": {},
                    "VRMC_materials_mtoon": {
                        "specVersion": "1.0",
                        "shadeColorFactor": (np.array(color) * 0.66).tolist(),
                        "shadingToonyFactor": 0.8,
                        "giEqualizationFactor": 0.75,
                        "outlineWidthMode": "worldCoordinates",
                        "outlineWidthFactor": 0.00045,
                        "outlineColorFactor": [0.025, 0.035, 0.05],
                    },
                },
            }
        )
        return len(self.doc["materials"]) - 1

    def geometry(self, name, vertices, faces, material, bone, extras=None):
        vertices = np.array(vertices, dtype=float)
        faces = np.array(faces, dtype=int)
        joints = np.zeros((len(vertices), 4), dtype="<u2")
        weights = np.zeros((len(vertices), 4))
        weights[:, 0] = 1
        attrs = {
            "POSITION": self.accessor(vertices),
            "NORMAL": self.accessor(normals(vertices, faces)),
            "JOINTS_0": self.accessor(joints, 5123, "VEC4"),
            "WEIGHTS_0": self.accessor(weights, shape="VEC4"),
        }
        self.doc["meshes"].append(
            {
                "name": name,
                "primitives": [
                    {
                        "attributes": attrs,
                        "indices": self.accessor(faces.reshape(-1, 1), 5125, "SCALAR"),
                        "material": material,
                    }
                ],
            }
        )
        self.doc["skins"].append({"joints": [bone]})
        self.doc["nodes"].append(
            {
                "name": name,
                "mesh": len(self.doc["meshes"]) - 1,
                "skin": len(self.doc["skins"]) - 1,
                **({"extras": extras} if extras else {}),
            }
        )
        self.doc["scenes"][0]["nodes"].append(len(self.doc["nodes"]) - 1)
        return self.doc["meshes"][-1], self.doc["skins"][-1]

    def finish(self):
        # Preserve authored bind offsets, including constraint/twist bones.
        # Only edited hair bones get the corresponding change of rest frame.
        world = world_matrices(self.doc["nodes"])
        original_world = world_matrices(self.source.doc["nodes"])
        for i, skin in enumerate(self.doc["skins"]):
            if i < len(self.source.doc["skins"]):
                source = self.source.doc["skins"][i]
                matrices = self.source.accessor(source["inverseBindMatrices"]).copy()
                for k, j in enumerate(skin["joints"]):
                    if self.doc["nodes"][j].get("name", "").startswith("J_Sec_Hair"):
                        bind = matrices[k].reshape(4, 4).T
                        matrices[k] = (
                            np.linalg.inv(world[j]) @ original_world[j] @ bind
                        ).T.reshape(16)
            else:
                matrices = np.array([np.linalg.inv(world[j]).T.reshape(16) for j in skin["joints"]])
            skin["inverseBindMatrices"] = self.accessor(matrices, shape="MAT4")
        self.doc["buffers"][0]["byteLength"] = len(self.binary)
        description = json.dumps(self.doc, ensure_ascii=False, separators=(",", ":")).encode()
        description += b" " * (-len(description) % 4)
        self.binary.extend(b"\0" * (-len(self.binary) % 4))
        body = struct.pack("<II", len(description), 0x4E4F534A) + description
        body += struct.pack("<II", len(self.binary), 0x004E4942) + self.binary
        return struct.pack("<III", 0x46546C67, 2, len(body) + 12) + body


def hair_warp(points, character, part="back"):
    result = np.array(points, dtype=float).copy()
    y = result[:, 1].copy()
    if character == "mizore":
        # Shoulder-length bob; retain the original scalp, fringe and face UVs.
        result[:, 1] = np.where(y < 1.44, 1.44 + (y - 1.44) * 0.40, y)
    elif part == "side":
        result[:, 1] = np.where(y < 1.44, 1.44 + (y - 1.44) * 0.30, y)
    elif part == "back":
        # Gather the long locks behind the neck into a ponytail silhouette.
        amount = np.clip((1.53 - y) / 0.09, 0, 1)
        amount = amount * amount * (3 - 2 * amount)
        result[:, 0] *= 1 - 0.70 * amount
        result[:, 2] = result[:, 2] * (1 - amount) - 0.175 * amount
        result[:, 1] = np.where(y < 1.44, 1.49 + (y - 1.44) * 0.78, y + 0.05 * amount)
        # Keep a small volume rather than collapsing all locks to one plane.
        result[:, 2] += points[:, 2] * 0.23 * amount
    return result


def edit_hair(builder, character):
    model, doc = builder.source, builder.doc
    primitive = doc["meshes"][2]["primitives"][0]
    vertices = model.accessor(primitive["attributes"]["POSITION"])
    faces = model.accessor(primitive["indices"]).reshape(-1, 3)
    if character == "mizore":
        warped = hair_warp(vertices, character)
    else:
        # Use the author's hair-chain membership, not spatial thresholds that
        # also pull the fringe backward and expose the forehead.
        skin = model.doc["skins"][2]
        joint = model.accessor(primitive["attributes"]["JOINTS_0"])
        weight = model.accessor(primitive["attributes"]["WEIGHTS_0"])
        memberships = {"back": np.zeros(len(vertices)), "side": np.zeros(len(vertices))}
        for k, node_id in enumerate(skin["joints"]):
            name = doc["nodes"][node_id].get("name", "")
            if not name.startswith("J_Sec_Hair"):
                continue
            number = int(name.removesuffix("_end").split("_")[-1])
            part = "back" if 5 <= number <= 10 else "side" if number >= 11 else None
            if part:
                memberships[part] += np.sum(np.where(joint == k, weight, 0), axis=1)
        warped = vertices.astype(float).copy()
        for part, amount in memberships.items():
            warped += (hair_warp(vertices, character, part) - vertices) * amount[:, None]
    primitive["attributes"]["POSITION"] = builder.accessor(warped)
    primitive["attributes"]["NORMAL"] = builder.accessor(normals(warped, faces))
    before = world_matrices(doc["nodes"])
    desired = before.copy()
    for i, node in enumerate(doc["nodes"]):
        if node.get("name", "").startswith("J_Sec_Hair"):
            number = int(node["name"].removesuffix("_end").split("_")[-1])
            part = "back" if 5 <= number <= 10 else "side" if number >= 11 else "fringe"
            desired[i, :3, 3] = hair_warp(before[i, :3, 3][None], character, part)[0]
    parents = node_parents(doc["nodes"])
    for i, node in enumerate(doc["nodes"]):
        if node.get("name", "").startswith("J_Sec_Hair"):
            node["translation"] = (
                np.linalg.inv(desired[parents[i]]) @ np.append(desired[i, :3, 3], 1)
            )[:3].tolist()
    tint = [0.025, 0.035, 0.062, 1] if character == "mizore" else [0.055, 0.035, 0.030, 1]
    for i in (4, 12):
        material = doc["materials"][i]
        material["emissiveFactor"] = [0, 0, 0]
        material.pop("emissiveTexture", None)
        material["pbrMetallicRoughness"]["baseColorFactor"] = tint
        material["pbrMetallicRoughness"].pop("baseColorTexture", None)
        toon = material["extensions"]["VRMC_materials_mtoon"]
        toon.pop("shadeMultiplyTexture", None)
        toon["shadeColorFactor"] = (np.array(tint[:3]) * 0.45).tolist()
        toon["parametricRimColorFactor"] = (np.array(tint[:3]) * 0.35).tolist()
        toon["shadingToonyFactor"] = 0.65


def outfit(builder, character):
    model, doc = builder.source, builder.doc
    mapping = doc["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]
    chest, hips = mapping["upperChest"]["node"], mapping["hips"]["node"]
    blue = builder.material("Sailor blue", [0.19, 0.38, 0.60], True)
    white = builder.material("Ivory trim", [0.89, 0.93, 0.96], True)
    teal = builder.material("Turquoise scarf", [0.025, 0.33, 0.32], True)
    sock = builder.material(
        "Knee socks", [0.025, 0.028, 0.036] if character == "nozomi" else [0.88, 0.92, 0.96]
    )
    # Keep the authored shirt and its shoulder/twist weights, shorten its tunic hem.
    top = doc["meshes"][0]["primitives"][3]
    v = model.accessor(top["attributes"]["POSITION"]).astype(float)
    t = np.clip((1.08 - v[:, 1]) / 0.25, 0, 1)
    v[:, 1] += 0.142 * t
    v[:, 0] *= 1 - 0.18 * t
    sleeve = np.clip((abs(v[:, 0]) - 0.14) / 0.08, 0, 1)
    v[:, 1] += (1.305 - v[:, 1]) * sleeve * 0.35
    v[:, 2] *= 1 - 0.22 * sleeve
    f = model.accessor(top["indices"]).reshape(-1, 3)
    top["attributes"]["POSITION"] = builder.accessor(v)
    top["attributes"]["NORMAL"] = builder.accessor(normals(v, f))
    # Clip an offset copy of the authored surface at exact sock heights. Merely
    # recoloring whole triangles produced a visibly jagged upper edge.
    body = doc["meshes"][0]["primitives"][0]
    add_socks(builder, body, sock)
    # The collar wraps over the shoulders to a real square back flap.
    collar_v = [
        [-0.045, 1.329, 0.020],
        [-0.15, 1.306, 0.010],
        [-0.085, 1.20, 0.137],
        [-0.018, 1.215, 0.143],
        [0.045, 1.329, 0.020],
        [0.15, 1.306, 0.010],
        [0.085, 1.20, 0.137],
        [0.018, 1.215, 0.143],
        [-0.045, 1.329, -0.065],
        [-0.15, 1.306, -0.075],
        [-0.15, 1.205, -0.106],
        [0.045, 1.329, -0.065],
        [0.15, 1.306, -0.075],
        [0.15, 1.205, -0.106],
    ]
    collar_f = [
        [0, 1, 2],
        [0, 2, 3],
        [4, 6, 5],
        [4, 7, 6],
        [0, 8, 9],
        [0, 9, 1],
        [4, 5, 12],
        [4, 12, 11],
        [8, 11, 12],
        [8, 12, 9],
        [9, 12, 13],
        [9, 13, 10],
    ]
    builder.geometry("Sailor collar", collar_v, collar_f, blue, chest)
    for side in (-1, 1):
        pts = [
            [side * 0.14, 1.298, 0.035],
            [side * 0.132, 1.296, 0.041],
            [side * 0.075, 1.207, 0.144],
            [side * 0.084, 1.206, 0.143],
        ]
        builder.geometry("Collar piping", pts, [[0, 1, 2], [0, 2, 3]], white, chest)
    builder.geometry(
        "Scarf",
        [
            [-0.025, 1.225, 0.148],
            [0.025, 1.225, 0.148],
            [0.014, 1.185, 0.15],
            [0.035, 1.11, 0.146],
            [0, 1.08, 0.149],
            [-0.027, 1.12, 0.146],
            [-0.012, 1.185, 0.15],
        ],
        [[0, 1, 2], [0, 2, 6], [6, 2, 3], [6, 3, 4], [6, 4, 5]],
        teal,
        chest,
    )
    add_skirt(builder, hips, blue, white)


def add_socks(builder, primitive, material):
    model, doc = builder.source, builder.doc
    attrs = primitive["attributes"]
    v, normal = model.accessor(attrs["POSITION"]), model.accessor(attrs["NORMAL"])
    indices, weights = model.accessor(attrs["JOINTS_0"]), model.accessor(attrs["WEIGHTS_0"])
    dense = np.zeros((len(v), len(doc["skins"][0]["joints"])))
    for i in range(4):
        dense[np.arange(len(v)), indices[:, i]] += weights[:, i]
    records = np.concatenate((v, normal, dense), axis=1)
    output = []
    for face in model.accessor(primitive["indices"]).reshape(-1, 3):
        if v[face, 1].min() > 0.43 or v[face, 1].max() < 0.08:
            continue
        polygon = list(records[face])
        for height, sign in ((0.08, 1), (0.43, -1)):
            clipped = []
            for a, b in zip(polygon, polygon[1:] + polygon[:1], strict=True):
                inside_a, inside_b = sign * (a[1] - height) >= 0, sign * (b[1] - height) >= 0
                if inside_a:
                    clipped.append(a)
                if inside_a != inside_b:
                    t = (height - a[1]) / (b[1] - a[1])
                    clipped.append(a + (b - a) * t)
            polygon = clipped
        for j in range(1, len(polygon) - 1):
            output.extend([polygon[0], polygon[j], polygon[j + 1]])
    data = np.array(output)
    norm = data[:, 3:6]
    norm /= np.maximum(np.linalg.norm(norm, axis=1, keepdims=True), 1e-12)
    pos = data[:, :3] + norm * 0.0018
    weight = data[:, 6:]
    joint = np.argsort(weight, axis=1)[:, -4:]
    weight = np.take_along_axis(weight, joint, axis=1)
    weight /= weight.sum(axis=1, keepdims=True)
    doc["meshes"].append(
        {
            "name": "Fitted knee socks",
            "primitives": [
                {
                    "attributes": {
                        "POSITION": builder.accessor(pos),
                        "NORMAL": builder.accessor(norm),
                        "JOINTS_0": builder.accessor(joint, 5123, "VEC4"),
                        "WEIGHTS_0": builder.accessor(weight, shape="VEC4"),
                    },
                    "indices": builder.accessor(np.arange(len(pos)).reshape(-1, 1), 5125, "SCALAR"),
                    "material": material,
                }
            ],
        }
    )
    doc["nodes"].append({"name": "Fitted knee socks", "mesh": len(doc["meshes"]) - 1, "skin": 0})
    doc["scenes"][0]["nodes"].append(len(doc["nodes"]) - 1)


def add_skirt(builder, hips, blue, white):
    doc = builder.doc
    # 16 box pleats, 64 vertices around each ring. The lower bands are geometry,
    # so they remain coherent from every view rather than stretching a front photo.
    segments = 64
    heights = np.array(
        [0.985, 0.96, 0.92, 0.87, 0.82, 0.77, 0.72, 0.67, 0.62, 0.598, 0.585, 0.558, 0.545, 0.52]
    )
    vertices = []
    for y in heights:
        t = (0.985 - y) / 0.465
        for i in range(segments):
            theta = 2 * np.pi * i / segments
            pleat = (0.008 + 0.008 * t) * (1 if i % 4 in (0, 1) else -1)
            vertices.append(
                [
                    (0.174 + 0.090 * t + pleat) * np.sin(theta),
                    y,
                    (0.137 + 0.078 * t + pleat) * np.cos(theta),
                ]
            )
    faces, stripe_faces = [], []
    for row in range(len(heights) - 1):
        for col in range(segments):
            a, b = row * segments + col, row * segments + (col + 1) % segments
            dest = stripe_faces if row in (9, 11) else faces
            dest.extend([[a, b, a + segments], [b, b + segments, a + segments]])
    mesh, skin = builder.geometry(
        "DollFight_PleatedSkirt",
        vertices,
        faces,
        blue,
        hips,
        {
            "dollfightCloth": {
                "version": 1,
                "segments": segments,
                "rows": len(heights),
                "pinnedRows": 1,
            }
        },
    )
    stripe = copy.deepcopy(mesh["primitives"][0])
    stripe["indices"] = builder.accessor(np.array(stripe_faces).reshape(-1, 1), 5125, "SCALAR")
    stripe["material"] = white
    mesh["primitives"].append(stripe)
    # Portable VRM fallback: panel chains and capsule collisions. Motion Lab uses
    # a separate fixed-step cloth solver, NOT a claim that spring bones are cloth.
    world = world_matrices(doc["nodes"])
    inverse_hips = np.linalg.inv(world[hips])
    panel_nodes = []
    spring = doc["extensions"]["VRMC_springBone"]
    for panel in range(16):
        theta = 2 * np.pi * panel / 16
        chain, previous = [], None
        for row, t in enumerate((0, 0.333333, 0.666667, 1)):
            pos = np.array(
                [
                    (0.174 + 0.090 * t) * np.sin(theta),
                    0.985 - 0.465 * t,
                    (0.137 + 0.078 * t) * np.cos(theta),
                ]
            )
            local = (inverse_hips @ np.append(pos, 1))[:3] if previous is None else pos - previous
            node = len(doc["nodes"])
            doc["nodes"].append(
                {"name": f"DF_Skirt_{panel:02d}_{row}", "translation": local.tolist()}
            )
            if previous is None:
                # Undo the parent's bind orientation: new chain axes are world-aligned.
                doc["nodes"][-1]["matrix"] = (
                    (
                        inverse_hips
                        @ np.array(
                            [[1, 0, 0, pos[0]], [0, 1, 0, pos[1]], [0, 0, 1, pos[2]], [0, 0, 0, 1]]
                        )
                    )
                    .T.reshape(16)
                    .tolist()
                )
                del doc["nodes"][-1]["translation"]
                doc["nodes"][hips].setdefault("children", []).append(node)
            else:
                doc["nodes"][chain[-1]].setdefault("children", []).append(node)
            chain.append(node)
            previous = pos
        panel_nodes.extend(chain)
        spring["springs"].append(
            {
                "name": "DollFight skirt panel",
                "colliderGroups": [10, 11],
                "joints": [
                    {
                        "node": n,
                        "hitRadius": 0.025,
                        "stiffness": 0.6,
                        "dragForce": 0.5,
                        "gravityPower": 0.2,
                    }
                    for n in chain
                ],
            }
        )
    skin["joints"] = [hips, *panel_nodes]
    joints, weights = np.zeros((len(vertices), 4), dtype="<u2"), np.zeros((len(vertices), 4))
    for row, y in enumerate(heights):
        along = np.clip((0.985 - y) / 0.465 * 3, 0, 2.9999)
        k, u = int(along), along % 1
        for col in range(segments):
            i = row * segments + col
            if row == 0:
                weights[i, 0] = 1
                continue
            panel, v = col // 4, (col % 4) / 4
            joints[i] = [
                1 + panel * 4 + k,
                1 + panel * 4 + k + 1,
                1 + ((panel + 1) % 16) * 4 + k,
                1 + ((panel + 1) % 16) * 4 + k + 1,
            ]
            weights[i] = [(1 - u) * (1 - v), u * (1 - v), (1 - u) * v, u * v]
    attrs = mesh["primitives"][0]["attributes"]
    attrs["JOINTS_0"] = builder.accessor(joints, 5123, "VEC4")
    attrs["WEIGHTS_0"] = builder.accessor(weights, shape="VEC4")
    mesh["primitives"][1]["attributes"] = copy.deepcopy(attrs)


def build(character):
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError("Unexpected base model; fetch the pinned licensed sample first")
    builder = Builder(EmbeddedGLB(raw))
    edit_hair(builder, character)
    outfit(builder, character)
    doc = builder.doc
    meta = doc["extensions"]["VRMC_vrm"]["meta"]
    meta.update(
        name=("希美方向" if character == "nozomi" else "霙方向") + " · 校服底模 / 外观草稿",
        version="0.2.0",
        authors=["pixiv Inc. (base model)", "DollFight (modifications)"],
        references=[
            "https://github.com/vrm-c/vrm-specification/tree/master/samples/VRM1_Constraint_Twist_Sample",
            "https://liz-bluebird.com/",
        ],
        copyrightInformation=(
            "Base (c) 2022 pixiv Inc.; character inspiration rights belong to their owners."
        ),
    )
    meta.pop("thumbnailImage", None)  # Original portrait would misrepresent the derivative.
    doc["asset"]["generator"] = "DollFight licensed-template study 0.2"
    payload = builder.finish()
    report = audit_bytes(payload)
    if report["errors"]:
        raise ValueError(report["errors"])
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / f"{character}.vrm").write_bytes(payload)
    (DEST / f"{character}-audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    triangles = sum(
        doc["accessors"][p["indices"]]["count"] // 3 for m in doc["meshes"] for p in m["primitives"]
    )
    return {
        "character": character,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "triangles": triangles,
        "human_bones": len(doc["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]),
        "base_sha256": SOURCE_SHA,
        "likeness_approved": False,
        "body_binding": "unchanged authored pixiv weights including fingers and twist bones",
        "cloth": "separate 896-vertex skirt; 16 panel bone chains; browser PBD override",
        "textures": "base UV textures preserved; no front-image projection",
    }


def main():
    entries = [build(c) for c in ("nozomi", "mizore")]
    (DEST / "manifest.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(entries, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
