"""Offline intake checks for embedded GLB/VRM assets; not a full glTF validator.

Never executes model content, downloads external resources, or repairs weights.
Successful structure checks do not establish visual quality or usage rights.
"""

import hashlib
import json
import struct
from pathlib import Path

import numpy as np

HUMAN_BONES = (
    "hips",
    "spine",
    "chest",
    "neck",
    "head",
    "leftUpperArm",
    "leftLowerArm",
    "leftHand",
    "rightUpperArm",
    "rightLowerArm",
    "rightHand",
    "leftUpperLeg",
    "leftLowerLeg",
    "leftFoot",
    "leftToes",
    "rightUpperLeg",
    "rightLowerLeg",
    "rightFoot",
    "rightToes",
)
PARENTS = (-1, 0, 1, 2, 3, 2, 5, 6, 2, 8, 9, 0, 11, 12, 13, 0, 15, 16, 17)
DTYPES = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
WIDTHS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def index(value, size, label):
    if type(value) is not int or not 0 <= value < size:
        raise ValueError(f"{label}: invalid index {value!r}")
    return value


class EmbeddedGLB:
    def __init__(self, payload):
        if not 20 <= len(payload) <= 40 * 1024 * 1024:
            raise ValueError("Motion Lab accepts embedded GLB/VRM files from 20 bytes to 40 MiB")
        magic, version, length = struct.unpack_from("<III", payload)
        if (magic, version, length) != (0x46546C67, 2, len(payload)):
            raise ValueError("Invalid GLB 2 header or declared file length")
        chunks, offset = [], 12
        while offset < length:
            if offset + 8 > length:
                raise ValueError("Truncated GLB chunk header")
            count, kind = struct.unpack_from("<II", payload, offset)
            offset += 8
            if count % 4 or offset + count > length:
                raise ValueError("Truncated or unaligned GLB chunk")
            chunks.append((kind, payload[offset : offset + count]))
            offset += count
        if not chunks or chunks[0][0] != 0x4E4F534A:
            raise ValueError("The first GLB chunk must contain JSON")
        if sum(k == 0x4E4F534A for k, _ in chunks) != 1:
            raise ValueError("Duplicate JSON chunk")
        self.doc = json.loads(chunks[0][1])
        if not isinstance(self.doc, dict) or not isinstance(self.doc.get("asset"), dict):
            raise ValueError("GLB JSON must be an object with an asset object")
        if self.doc["asset"].get("version") != "2.0":
            raise ValueError("Expected glTF asset.version 2.0")
        if {"KHR_draco_mesh_compression", "EXT_meshopt_compression"}.intersection(
            self.doc.get("extensionsUsed", [])
        ):
            raise ValueError("Compressed geometry requires offline decoding before this preflight")
        binary = [b for k, b in chunks if k == 0x004E4942]
        if len(binary) > 1:
            raise ValueError("Only one embedded binary buffer is supported")
        self.binary = binary[0] if binary else b""
        buffers = self.doc.get("buffers", [])
        if len(buffers) != 1 or "uri" in buffers[0]:
            raise ValueError(
                "Preflight requires one embedded buffer; no external or data URI buffers"
            )
        size = buffers[0].get("byteLength", -1)
        if type(size) is not int or size < 0 or not 0 <= len(self.binary) - size <= 3:
            raise ValueError("Binary buffer length does not match its declaration")
        self.binary = self.binary[:size]
        for item in self.doc.get("images", []):
            if item.get("uri") and not item["uri"].startswith("data:"):
                raise ValueError("External image URI: package images into GLB before import")

    def accessor(self, accessor_id):
        accessors = self.doc.get("accessors", [])
        a = accessors[index(accessor_id, len(accessors), "accessor")]
        if "sparse" in a:
            raise ValueError("Sparse accessors require offline expansion; not silently skipped")
        if a.get("componentType") not in DTYPES or a.get("type") not in WIDTHS:
            raise ValueError("Unsupported accessor component type or shape")
        if a["type"] == "MAT4" and a["componentType"] != 5126:
            raise ValueError("This preflight supports float32 matrices only")
        count = a.get("count")
        if type(count) is not int or not 0 < count <= 2_000_000:
            raise ValueError("Invalid or excessive accessor count")
        dtype, width = np.dtype(DTYPES[a["componentType"]]), WIDTHS[a["type"]]
        views = self.doc.get("bufferViews", [])
        view = views[index(a.get("bufferView"), len(views), "bufferView")]
        if view.get("buffer") != 0:
            raise ValueError("Accessor must reference the embedded buffer")
        start, length, relative = (
            view.get("byteOffset", 0),
            view.get("byteLength"),
            a.get("byteOffset", 0),
        )
        stride = view.get("byteStride", dtype.itemsize * width)
        if not all(type(v) is int and v >= 0 for v in (start, length, relative, stride)):
            raise ValueError("Invalid buffer view offset/length/stride")
        if stride < dtype.itemsize * width or stride % dtype.itemsize:
            raise ValueError("Invalid accessor stride")
        if relative % dtype.itemsize or (start + relative) % dtype.itemsize:
            raise ValueError("Misaligned accessor offset")
        if (
            start + length > len(self.binary)
            or relative + (count - 1) * stride + width * dtype.itemsize > length
        ):
            raise ValueError("Accessor extends outside its buffer view")
        data = np.ndarray(
            (count, width), dtype, self.binary, start + relative, strides=(stride, dtype.itemsize)
        ).copy()
        if a.get("normalized"):
            if a["componentType"] not in (5120, 5121, 5122, 5123):
                raise ValueError("Only 8/16-bit integer attributes may use normalized=true")
            data = data.astype(float) / np.iinfo(dtype).max
            if dtype.kind == "i":
                data = np.maximum(data, -1)
        if not np.isfinite(data).all():
            raise ValueError("Non-finite accessor data")
        return data


def node_parents(nodes):
    parents = [-1] * len(nodes)
    for parent, node in enumerate(nodes):
        if "matrix" in node and any(key in node for key in ("translation", "rotation", "scale")):
            raise ValueError("A node cannot have both matrix and TRS transforms")
        for key, length in (("matrix", 16), ("translation", 3), ("rotation", 4), ("scale", 3)):
            if key not in node:
                continue
            values = np.asarray(node[key], dtype=float)
            if values.shape != (length,) or not np.isfinite(values).all():
                raise ValueError(f"Invalid node {key}")
            if key == "rotation" and abs(np.linalg.norm(values) - 1) > 0.001:
                raise ValueError("Node rotation quaternion is not normalized")
        for child in node.get("children", []):
            index(child, len(nodes), "node child")
            if parents[child] != -1:
                raise ValueError("A node has multiple parents")
            parents[child] = parent
    for start in range(len(nodes)):
        seen, current = set(), start
        while current != -1:
            if current in seen:
                raise ValueError("Cyclic node hierarchy")
            seen.add(current)
            current = parents[current]
    return parents


def human_mapping(doc):
    extensions = doc.get("extensions", {})
    if "VRMC_vrm" in extensions:
        bones = extensions["VRMC_vrm"].get("humanoid", {}).get("humanBones", {})
        return "VRM 1", {name: b.get("node") for name, b in bones.items()}
    if "VRM" in extensions:
        bones = extensions["VRM"].get("humanoid", {}).get("humanBones", [])
        names = [b["bone"] for b in bones]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate VRM 0 humanoid bone semantics")
        return "VRM 0", {b["bone"]: b.get("node") for b in bones}
    return "GLB (no VRM humanoid extension)", {}


def joint_world_positions(nodes, parents):
    """Read bind hierarchy transforms, including rotation/scale and matrix nodes."""
    worlds = {}

    def world(i):
        if i not in worlds:
            node = nodes[i]
            if "matrix" in node:
                local = np.asarray(node["matrix"]).reshape(4, 4).T
            else:
                x, y, z, w = node.get("rotation", [0, 0, 0, 1])
                local = np.eye(4)
                local[:3, :3] = [
                    [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                    [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                    [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
                ]
                local[:3, :3] *= node.get("scale", [1, 1, 1])
                local[:3, 3] = node.get("translation", [0, 0, 0])
            worlds[i] = (world(parents[i]) if parents[i] >= 0 else np.eye(4)) @ local
        return worlds[i]

    return np.array([world(i)[:3, 3] for i in range(len(nodes))])


def audit_bytes(payload):
    report = {
        "version": "avatar-preflight-2",
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "errors": [],
        "warnings": [],
        "motion_lab_structural_candidate": False,
        "visual_quality_verified": False,
    }
    try:
        model = EmbeddedGLB(payload)
        doc, nodes = model.doc, model.doc.get("nodes", [])
        parents = node_parents(nodes)
        kind, mapping = human_mapping(doc)
        report.update(
            format=kind,
            node_count=len(nodes),
            skin_count=len(doc.get("skins", [])),
            material_count=len(doc.get("materials", [])),
            animation_count=len(doc.get("animations", [])),
        )
        for bone, node in mapping.items():
            index(node, len(nodes), f"humanoid {bone}")
        if len(set(mapping.values())) != len(mapping):
            raise ValueError("Multiple humanoid semantics map to one node")
        missing = [name for name in HUMAN_BONES if name not in mapping]
        report["missing_motion_lab_bones"] = missing
        report["humanoid_mapping"] = mapping
        report["joint_names"] = [
            n.get("name", f"node_{i}")
            for i, n in enumerate(nodes)
            if any(i in s.get("joints", []) for s in doc.get("skins", []))
        ]
        for i, parent in enumerate(PARENTS):
            child, ancestor = mapping.get(HUMAN_BONES[i]), mapping.get(HUMAN_BONES[parent])
            if parent < 0 or child is None or ancestor is None:
                continue
            cursor = parents[child]
            while cursor != -1 and cursor != ancestor:
                cursor = parents[cursor]
            if cursor != ancestor:
                raise ValueError(f"Humanoid hierarchy mismatch at {HUMAN_BONES[i]}")
        skin_spans = []
        positions_world = joint_world_positions(nodes, parents)
        collapsed_skin = False
        for skin in doc.get("skins", []):
            joints = skin.get("joints", [])
            if not joints or len(set(joints)) != len(joints):
                raise ValueError("Empty or repeated skin joints")
            for joint in joints:
                index(joint, len(nodes), "skin joint")
            span = float(np.linalg.norm(np.ptp(positions_world[joints], axis=0)))
            skin_spans.append(span)
            collapsed_skin |= len(joints) > 1 and span < 1e-8
            if "inverseBindMatrices" in skin:
                matrices = model.accessor(skin["inverseBindMatrices"])
                if matrices.shape[1] != 16 or len(matrices) < len(joints):
                    raise ValueError("Inverse bind matrices must cover all skin joints")
                if np.any(abs(np.linalg.det(matrices.reshape(-1, 4, 4))) < 1e-12):
                    raise ValueError("Singular inverse bind matrix")
        vertices, skinned, max_influences, max_weight_error = 0, 0, 0, 0.0
        uses_extra_weight_sets = False
        influence_mass = np.zeros(len(nodes))
        for node in nodes:
            if "mesh" not in node:
                continue
            meshes = doc.get("meshes", [])
            mesh = meshes[index(node["mesh"], len(meshes), "mesh")]
            for primitive in mesh["primitives"]:
                attrs = primitive["attributes"]
                positions = model.accessor(attrs["POSITION"])
                if positions.shape[1] != 3:
                    raise ValueError("POSITION must be VEC3")
                count = len(positions)
                vertices += count
                if "skin" not in node:
                    continue
                skins = doc.get("skins", [])
                skin = skins[index(node["skin"], len(skins), "skin")]
                weight_sets = []
                joint_keys = sorted(k for k in attrs if k.startswith("JOINTS_"))
                if "JOINTS_0" not in attrs or {
                    k.replace("JOINTS_", "WEIGHTS_") for k in joint_keys
                } != {k for k in attrs if k.startswith("WEIGHTS_")}:
                    raise ValueError("Skinned mesh must have matching JOINTS_n and WEIGHTS_n")
                for key in joint_keys:
                    joint_accessor = doc["accessors"][index(attrs[key], len(doc["accessors"]), key)]
                    weight_key = key.replace("JOINTS_", "WEIGHTS_")
                    weight_accessor = doc["accessors"][
                        index(attrs[weight_key], len(doc["accessors"]), weight_key)
                    ]
                    if joint_accessor["componentType"] not in (5121, 5123) or joint_accessor.get(
                        "normalized"
                    ):
                        raise ValueError("JOINTS must use non-normalized uint8/uint16")
                    component = weight_accessor["componentType"]
                    if component != 5126 and not (
                        component in (5121, 5123) and weight_accessor.get("normalized") is True
                    ):
                        raise ValueError("WEIGHTS must be float32 or normalized uint8/uint16")
                    joint_ids = model.accessor(attrs[key])
                    weights = model.accessor(attrs[weight_key])
                    if joint_ids.shape != (count, 4) or weights.shape != (count, 4):
                        raise ValueError("Joint/weight attribute count mismatch")
                    if joint_ids.dtype.kind != "u" or np.any(joint_ids >= len(skin["joints"])):
                        raise ValueError("JOINTS contains invalid skin-local indices")
                    if np.any(weights < 0):
                        raise ValueError("Negative skin weight")
                    uses_extra_weight_sets |= key != "JOINTS_0" and bool(np.any(weights > 0))
                    weight_sets.append(weights)
                    influence_mass += np.bincount(
                        np.asarray(skin["joints"])[joint_ids].ravel(),
                        weights=weights.ravel(),
                        minlength=len(nodes),
                    )
                weights = np.concatenate(weight_sets, axis=1)
                sums = weights.sum(axis=1)
                if np.any(sums < 1e-8):
                    raise ValueError("Mesh contains vertices with no skin influence")
                error = float(np.max(abs(sums - 1)))
                max_weight_error = max(max_weight_error, error)
                if error > 0.02:
                    raise ValueError(
                        "Skin weights are not normalized (sum differs from 1 by >0.02)"
                    )
                max_influences = max(max_influences, int((weights > 1e-6).sum(axis=1).max()))
                skinned += count
        report.update(
            mesh_vertices_instanced=vertices,
            skinned_vertices_instanced=skinned,
            max_vertex_influences=max_influences,
            max_weight_sum_error=max_weight_error,
            uses_extra_weight_sets=uses_extra_weight_sets,
            skin_joint_spans=skin_spans,
            collapsed_skin=bool(collapsed_skin),
            dominant_joint_weight_fraction=(
                float(influence_mass.max() / influence_mass.sum()) if skinned else None
            ),
        )
        if collapsed_skin:
            report["warnings"].append(
                "Collapsed bind hierarchy: all joints of a multi-joint skin occupy one point; "
                "bone names and normalized weights do not establish an actionable rig"
            )
        if skinned > 100 and report["dominant_joint_weight_fraction"] > 0.995:
            report["warnings"].append(
                "More than 99.5% of skin influence belongs to one joint; inspect for "
                "placeholder or rigid whole-body weights before retargeting"
            )
        if not skinned:
            report["warnings"].append(
                "Static geometry: a rig/skin must be created before retargeting"
            )
        if not mapping:
            report["warnings"].append(
                "Bone naming alone is not VRM: map semantics and export proper VRM metadata"
            )
        elif missing:
            report["warnings"].append(
                "Motion Lab requires 19 mapped bones, more than VRM's minimum"
            )
        if max_influences > 4 or uses_extra_weight_sets:
            report["warnings"].append(
                "Extra weight sets/influences: pack into JOINTS_0/WEIGHTS_0 and revalidate"
            )
        report["motion_lab_structural_candidate"] = bool(
            mapping
            and not missing
            and skinned
            and max_influences <= 4
            and not uses_extra_weight_sets
            and not collapsed_skin
        )
        report["warnings"].append(
            "Inspect T-pose, scale, shoulder/hip deformation and clothing with fixed motion clips; "
            "structure checks are not visual acceptance"
        )
    except (
        ValueError,
        KeyError,
        TypeError,
        IndexError,
        AttributeError,
        struct.error,
        UnicodeError,
    ) as exc:
        report["errors"].append(str(exc))
    return report


def audit_file(path):
    path = Path(path)
    if path.stat().st_size > 40 * 1024 * 1024:
        raise ValueError("File exceeds the current 40 MiB intake limit")
    return {"file": path.name, **audit_bytes(path.read_bytes())}
