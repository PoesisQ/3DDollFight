"""CPU-only local rig: authored barycentric weight transfer + independent garment cage.

Preserves Tripo topology/UVs; this is NOT SkinTokens inference. Requires the
optional assets group. A hybrid variant replaces the generated head with the
licensed authored head/hair and gives exposed skin a consistent cel material.
Both variants remain studies, not likeness-approved final characters.
"""

import copy
import hashlib
import io
import json
import struct
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image
from scipy import sparse
from scipy.spatial import cKDTree

from dollfight.avatar_audit import EmbeddedGLB, audit_bytes, node_parents
from tools.build_template_avatars import SOURCE_SHA, normals, world_matrices

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data/avatars/local"
SOURCE_HASHES = {
    "nozomi": "399f4ff3336b693051951663de14033fb0e3d5945faf03bbd2be907eead20dcd",
    "mizore": "84aa58a79aae85f09b13c1b55b1f7b4ee8eda5a3344510ee5207efe4f7e2afe4",
}


class Writer:
    def __init__(self):
        self.doc = {
            "asset": {"version": "2.0", "generator": "DollFight local surface transfer 0.1"},
            "scene": 0,
            "scenes": [{"nodes": []}],
            "nodes": [],
            "meshes": [],
            "skins": [],
            "materials": [],
            "textures": [],
            "images": [],
            "samplers": [],
            "buffers": [{"byteLength": 0}],
            "bufferViews": [],
            "accessors": [],
            "extensionsUsed": ["VRMC_vrm", "KHR_materials_unlit"],
        }
        self.binary = bytearray()

    def view(self, raw):
        self.binary.extend(b"\0" * (-len(self.binary) % 4))
        i = len(self.doc["bufferViews"])
        self.doc["bufferViews"].append(
            {"buffer": 0, "byteOffset": len(self.binary), "byteLength": len(raw)}
        )
        self.binary.extend(raw)
        return i

    def accessor(self, array, shape="VEC3", component=5126):
        array = np.asarray(array, dtype={5126: "<f4", 5123: "<u2", 5125: "<u4"}[component])
        spec = {
            "bufferView": self.view(array.tobytes()),
            "componentType": component,
            "count": len(array),
            "type": shape,
        }
        if shape == "VEC3":
            spec.update(min=array.min(0).tolist(), max=array.max(0).tolist())
        self.doc["accessors"].append(spec)
        return len(self.doc["accessors"]) - 1

    def materials(self, model):
        """Import embedded textures with their original UV layout and image bytes."""
        offsets = {
            key: len(self.doc[key]) for key in ("images", "textures", "samplers", "materials")
        }
        for item in model.doc.get("images", []):
            v = model.doc["bufferViews"][item["bufferView"]]
            start = v.get("byteOffset", 0)
            self.doc["images"].append(
                {
                    "mimeType": item["mimeType"],
                    "bufferView": self.view(model.binary[start : start + v["byteLength"]]),
                }
            )
        self.doc["samplers"].extend(copy.deepcopy(model.doc.get("samplers", [])))
        for tex in model.doc.get("textures", []):
            tex = copy.deepcopy(tex)
            tex["source"] += offsets["images"]
            if "sampler" in tex:
                tex["sampler"] += offsets["samplers"]
            self.doc["textures"].append(tex)
        for original in model.doc["materials"]:
            mat = {
                "name": original.get("name", "surface"),
                "doubleSided": True,
                "pbrMetallicRoughness": copy.deepcopy(original.get("pbrMetallicRoughness", {})),
                "extensions": {"KHR_materials_unlit": {}},
            }
            pbr = mat["pbrMetallicRoughness"]
            pbr.pop("metallicRoughnessTexture", None)
            pbr.update(metallicFactor=0, roughnessFactor=1)
            if "baseColorTexture" in pbr:
                pbr["baseColorTexture"]["index"] += offsets["textures"]
            for key in ("alphaMode", "alphaCutoff"):
                if key in original:
                    mat[key] = original[key]
            self.doc["materials"].append(mat)
        return offsets["materials"]

    def mesh(self, name, v, f, uv, j, w, material, extra=None):
        # Compact per part, keep every selected source triangle and UV seam.
        unique, inverse = np.unique(f, return_inverse=True)
        p = {
            "attributes": {
                "POSITION": self.accessor(v[unique]),
                "NORMAL": self.accessor(normals(v, f)[unique]),
                "TEXCOORD_0": self.accessor(uv[unique], "VEC2"),
                "JOINTS_0": self.accessor(j[unique], "VEC4", 5123),
                "WEIGHTS_0": self.accessor(w[unique], "VEC4"),
            },
            "indices": self.accessor(inverse.reshape(-1, 1), "SCALAR", 5125),
            "material": material,
        }
        self.doc["meshes"].append({"name": name, "primitives": [p]})
        self.doc["nodes"].append(
            {
                "name": name,
                "mesh": len(self.doc["meshes"]) - 1,
                "skin": 0,
                **({"extras": extra} if extra else {}),
            }
        )
        self.doc["scenes"][0]["nodes"].append(len(self.doc["nodes"]) - 1)

    def finish(self, joint_nodes, positions):
        ibm = np.repeat(np.eye(4)[None], len(joint_nodes), axis=0)
        ibm[:, :3, 3] = -np.array(positions)
        self.doc["skins"] = [
            {
                "joints": joint_nodes,
                "inverseBindMatrices": self.accessor(
                    ibm.transpose(0, 2, 1).reshape(-1, 16), "MAT4"
                ),
            }
        ]
        self.doc["buffers"][0]["byteLength"] = len(self.binary)
        raw = json.dumps(self.doc, ensure_ascii=False, separators=(",", ":")).encode()
        raw += b" " * (-len(raw) % 4)
        self.binary.extend(b"\0" * (-len(self.binary) % 4))
        body = struct.pack("<II", len(raw), 0x4E4F534A) + raw
        body += struct.pack("<II", len(self.binary), 0x004E4942) + self.binary
        return struct.pack("<III", 0x46546C67, 2, len(body) + 12) + body


def fit(points):
    """Shared anatomical fit for this pair: metre-scale landmark alignment."""
    p = np.array(points, dtype=float).copy()
    y = p[:, 1].copy()
    p[:, 0] *= 0.96
    p[:, 1] = np.interp(
        y,
        [0, 0.1, 0.5154, 0.9081, 1.2742, 1.3863, 1.6154],
        [0, 0.1, 0.50, 0.94, 1.275, 1.405, 1.65],
    )
    p[:, 2] += np.interp(y, [0, 1, 1.3, 1.4, 1.65], [-0.028, 0.018, 0.015, 0.03, 0.03])
    return p


def reference_weights(model, primitive, skin, names, node_to_name):
    j = model.accessor(primitive["attributes"]["JOINTS_0"]).astype(int)
    w = model.accessor(primitive["attributes"]["WEIGHTS_0"])
    parents = node_parents(model.doc["nodes"])
    mapping = []
    for node in skin["joints"]:
        while node not in node_to_name and node >= 0:
            node = parents[node]
        mapping.append(names.index(node_to_name[node]) if node >= 0 else 0)
    result = np.zeros((len(j), len(names)), dtype=np.float32)
    for col in range(4):
        np.add.at(result, (np.arange(len(j)), np.array(mapping)[j[:, col]]), w[:, col])
    return result


def transfer(target, vertices, faces, weights):
    """Closest of 16 nearby authored triangles, barycentric weight interpolation."""
    triangles = vertices[faces]
    tree = cKDTree(triangles.mean(axis=1))
    output = np.zeros((len(target), weights.shape[1]), dtype=np.float32)
    distances = np.zeros(len(target))
    for start in range(0, len(target), 2048):
        p = target[start : start + 2048]
        _, candidates = tree.query(p, k=16, workers=-1)
        tri = triangles[candidates].reshape(-1, 3, 3)
        repeated = np.repeat(p, 16, axis=0)
        closest = trimesh.triangles.closest_point(tri, repeated).reshape(-1, 16, 3)
        d = np.linalg.norm(closest - p[:, None], axis=2)
        best = d.argmin(1)
        index = candidates[np.arange(len(p)), best]
        bary = trimesh.triangles.points_to_barycentric(
            triangles[index], closest[np.arange(len(p)), best]
        )
        bary = np.maximum(bary, 0)
        bary /= np.maximum(bary.sum(1, keepdims=True), 1e-12)
        output[start : start + len(p)] = np.einsum("ij,ijk->ik", bary, weights[faces[index]])
        distances[start : start + len(p)] = d[np.arange(len(p)), best]
    return output, distances


def smooth_weights(v, f, weights, fixed):
    # Weld UV duplicates for adjacency only, never alter exported UVs/topology.
    _, weld = np.unique(np.round(v, 5), axis=0, return_inverse=True)
    n = weld.max() + 1
    wf = weld[f]
    a = np.concatenate([wf[:, 0], wf[:, 1], wf[:, 2]])
    b = np.concatenate([wf[:, 1], wf[:, 2], wf[:, 0]])
    adj = sparse.coo_matrix((np.ones(len(a) * 2), (np.r_[a, b], np.r_[b, a])), shape=(n, n)).tocsr()
    adj.data[:] = 1
    adj = sparse.diags(1 / np.maximum(np.asarray(adj.sum(1)).ravel(), 1)) @ adj
    counts = np.bincount(weld)
    merged = np.zeros((n, weights.shape[1]), dtype=np.float32)
    np.add.at(merged, weld, weights)
    merged /= counts[:, None]
    anchor = merged.copy()
    locked = np.zeros(n, dtype=bool)
    locked[weld[fixed]] = True
    for _ in range(8):
        merged = 0.35 * anchor + 0.65 * (adj @ merged)
        merged[locked] = anchor[locked]
    return merged[weld]


def top4(weights):
    j = np.argsort(weights, axis=1)[:, -4:][:, ::-1]
    w = np.take_along_axis(weights, j, axis=1)
    w /= np.maximum(w.sum(1, keepdims=True), 1e-12)
    return j, w


def texture_colors(model, primitive, uv):
    mat = model.doc["materials"][primitive["material"]]
    index = mat["pbrMetallicRoughness"]["baseColorTexture"]["index"]
    image = model.doc["images"][model.doc["textures"][index]["source"]]
    view = model.doc["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset", 0)
    pixels = (
        np.array(
            Image.open(io.BytesIO(model.binary[start : start + view["byteLength"]])).convert("RGB")
        )
        / 255
    )
    xy = np.clip(uv, 0, 1) * [pixels.shape[1] - 1, pixels.shape[0] - 1]
    return pixels[xy[:, 1].astype(int), xy[:, 0].astype(int)]


def garment_region(v, colors, character):
    """Fit an outer skirt envelope, including dark folds and white hem trim.

    Color-only labels fragment shadowed fabric and confuse knees with the hem.
    Blue seeds estimate elliptical cross-sections; interior legs stay outside
    the garment even when their albedo is desaturated. Bounds are asset-specific.
    """
    bottom, top = (0.58 if character == "nozomi" else 0.525), 0.995
    blue = (colors[:, 2] > colors[:, 0] * 1.3) & (colors[:, 2] > colors[:, 1] * 1.1)
    levels = np.linspace(bottom + 0.045, top - 0.03, 12)
    profiles = []
    for y in levels:
        selected = blue & (abs(v[:, 1] - y) < 0.035)
        lo, hi = np.quantile(v[selected][:, [0, 2]], [0.02, 0.98], axis=0)
        profiles.append([*(0.5 * (lo + hi)), *(0.5 * (hi - lo))])
    fitted = np.array([np.interp(v[:, 1], levels, p) for p in np.array(profiles).T]).T
    radial = ((v[:, 0] - fitted[:, 0]) / fitted[:, 2]) ** 2
    radial += ((v[:, 2] - fitted[:, 1]) / fitted[:, 3]) ** 2
    return (v[:, 1] > bottom) & (v[:, 1] < top) & (radial > 0.78**2), bottom, top


def authored_hair_rig(writer, authored, names, positions, joint_nodes):
    """Keep the artist's strand membership and hierarchy in fitted rest space.

    Re-express rest frames as translation-only frames, just like our humanoid.
    Inverse binds are rebuilt by Writer.finish; no spatial fringe/ponytail guess.
    """
    nodes = authored.doc["nodes"]
    parents = node_parents(nodes)
    worlds = world_matrices(nodes)
    selected = {i for i, node in enumerate(nodes) if node.get("name", "").startswith("J_Sec_Hair")}
    mapping = {}
    pending = set(selected)
    while pending:
        ready = sorted(i for i in pending if parents[i] not in pending)
        if not ready:
            raise ValueError("Cyclic authored hair hierarchy")
        for old in ready:
            parent = mapping.get(parents[old], names.index("head"))
            pos = fit(worlds[old, :3, 3][None])[0]
            node = len(writer.doc["nodes"])
            joint = len(joint_nodes)
            mapping[old] = joint
            writer.doc["nodes"].append(
                {
                    "name": nodes[old]["name"],
                    "translation": (pos - np.array(positions[parent])).tolist(),
                }
            )
            writer.doc["nodes"][joint_nodes[parent]].setdefault("children", []).append(node)
            joint_nodes.append(node)
            positions.append(pos.tolist())
            pending.remove(old)
    springs = []
    for spring in authored.doc["extensions"]["VRMC_springBone"]["springs"]:
        chain = [j for j in spring["joints"] if j["node"] in mapping]
        if len(chain) < 2:
            continue
        # Front strands should retain their silhouette; back locks lag a turn.
        strand_number = int(nodes[chain[0]["node"]]["name"].split("_")[-1])
        is_front = strand_number <= 4
        springs.append(
            {
                "name": spring.get("name", "Authored hair strand"),
                "colliderGroups": [0],
                "joints": [
                    {
                        "node": joint_nodes[mapping[j["node"]]],
                        "hitRadius": min(j.get("hitRadius", 0.006), 0.009),
                        "stiffness": (4.5 if is_front else 2.0)
                        if k == 0
                        else (2.5 if is_front else 1.0),
                        "dragForce": 0.4,
                        "gravityPower": 0.025,
                    }
                    for k, j in enumerate(chain)
                ],
            }
        )
    return mapping, springs


def build(character, hybrid=False):
    source_path = ROOT / f"data/avatars/tripo/{character}-h25-source.glb"
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != SOURCE_HASHES[character]:
        raise ValueError("Source differs from the pinned Tripo export")
    if (
        hashlib.sha256((ROOT / "data/raw/avatars/sample.vrm").read_bytes()).hexdigest()
        != SOURCE_SHA
    ):
        raise ValueError("Reference differs from the licensed pinned pixiv model")
    source = EmbeddedGLB(source_path.read_bytes())
    reference = EmbeddedGLB((ROOT / "data/raw/avatars/sample.vrm").read_bytes())
    authored = None
    if hybrid:
        authored_path = ROOT / f"data/avatars/atelier/{character}.vrm"
        entries = json.loads(
            (ROOT / "data/avatars/atelier/manifest.json").read_text(encoding="utf-8")
        )
        expected = next(item["sha256"] for item in entries if item["character"] == character)
        if hashlib.sha256(authored_path.read_bytes()).hexdigest() != expected:
            raise ValueError("Authored hair differs from its pinned atelier manifest")
        authored = EmbeddedGLB(authored_path.read_bytes())
    writer = Writer()
    human = reference.doc["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]
    names = list(human)
    node_to_name = {entry["node"]: name for name, entry in human.items()}
    parents = node_parents(reference.doc["nodes"])
    world = world_matrices(reference.doc["nodes"])
    positions = fit(np.array([world[human[n]["node"], :3, 3] for n in names])).tolist()
    joint_nodes = list(range(len(names)))
    for i, name in enumerate(names):
        p = parents[human[name]["node"]]
        while p >= 0 and p not in node_to_name:
            p = parents[p]
        parent = names.index(node_to_name[p]) if p >= 0 else -1
        writer.doc["nodes"].append(
            {
                "name": name,
                "translation": (
                    np.array(positions[i]) - (np.array(positions[parent]) if parent >= 0 else 0)
                ).tolist(),
            }
        )
        if parent < 0:
            writer.doc["scenes"][0]["nodes"].append(i)
    for name, entry in human.items():
        p = parents[entry["node"]]
        while p >= 0 and p not in node_to_name:
            p = parents[p]
        if p >= 0:
            writer.doc["nodes"][names.index(node_to_name[p])].setdefault("children", []).append(
                names.index(name)
            )
    meta = copy.deepcopy(reference.doc["extensions"]["VRMC_vrm"]["meta"])
    meta.pop("thumbnailImage", None)
    meta.update(
        name=f"{character} · Tripo 本地绑定" + (" / 手颈与发束重建" if hybrid else " / 原网格"),
        version="0.2.0" if hybrid else "0.1.0",
        authors=["Tripo AI (source)", "pixiv Inc. (weight/face reference)", "DollFight"],
        copyrightInformation=(
            "Tripo free-plan non-commercial source. "
            "Authored reference (c) 2022 pixiv Inc. "
            "Character rights remain with original owners."
        ),
    )
    writer.doc["extensions"] = {
        "VRMC_vrm": {
            "specVersion": "1.0",
            "meta": meta,
            "humanoid": {"humanBones": {n: {"node": i} for i, n in enumerate(names)}},
        }
    }
    material = writer.materials(source)
    prim = source.doc["meshes"][0]["primitives"][0]
    v = source.accessor(prim["attributes"]["POSITION"]).astype(float) * 1.65
    uv = source.accessor(prim["attributes"]["TEXCOORD_0"])
    f = source.accessor(prim["indices"]).reshape(-1, 3).astype(int)
    colors = texture_colors(source, prim, uv)
    ref_prim = reference.doc["meshes"][0]["primitives"][0]
    rv = fit(reference.accessor(ref_prim["attributes"]["POSITION"]))
    rf = reference.accessor(ref_prim["indices"]).reshape(-1, 3).astype(int)
    rw = reference_weights(reference, ref_prim, reference.doc["skins"][0], names, node_to_name)
    weights, distance = transfer(v, rv, rf, rw)
    hair = (v[:, 1] > 1.32) & (
        (colors.max(1) < 0.46) | (v[:, 1] > 1.59) | ((v[:, 2] < -0.04) & (v[:, 1] > 1.38))
    )
    hair |= (v[:, 1] > 1.13) & (v[:, 2] < -0.06) & (colors.max(1) < 0.36)
    # Dark sleeves/arm shadows are not hair, even at the same height.
    hair &= abs(v[:, 0]) < 0.16
    head = v[:, 1] > 1.365
    weights[head | hair] = 0
    weights[head | hair, names.index("head")] = 1
    # Geometry alone confuses exposed knees with the hem. Separate blue fabric
    # and white trim from warm skin using the original embedded UV albedo.
    skin_color = (colors[:, 0] > colors[:, 2] * 1.3) & (colors[:, 0] > colors[:, 1] * 1.08)
    skirt, hem, waist = garment_region(v, colors, character)
    weights = smooth_weights(v, f, weights, head | hair | skirt)
    j, w = top4(weights)
    # A coarse cage controls the high-detail skirt through GPU bone translations.
    segments, rows = 24, 9
    angles = np.mod(np.arctan2(v[:, 0], v[:, 2] - 0.015), 2 * np.pi)
    cage = []
    for row in range(rows):
        y = waist - row / (rows - 1) * (waist - hem)
        for col in range(segments):
            angle = col * 2 * np.pi / segments
            mask = (
                skirt
                & (abs(v[:, 1] - y) < 0.04)
                & (abs(np.angle(np.exp(1j * (angles - angle)))) < 0.23)
            )
            radial = np.hypot(v[:, 0], v[:, 2] - 0.015)
            r = float(np.median(radial[mask])) if mask.any() else 0.16
            pos = [r * np.sin(angle), y, 0.015 + r * np.cos(angle)]
            cage.append(pos)
            node = len(writer.doc["nodes"])
            writer.doc["nodes"].append(
                {
                    "name": f"DF_Cage_{row}_{col}",
                    "translation": (np.array(pos) - positions[names.index("hips")]).tolist(),
                }
            )
            writer.doc["nodes"][names.index("hips")].setdefault("children", []).append(node)
            joint_nodes.append(node)
            positions.append(pos)
    t = np.clip((waist - v[:, 1]) / (waist - hem) * (rows - 1), 0, rows - 1.00001)
    a = angles / (2 * np.pi) * segments
    row, col = t.astype(int), a.astype(int)
    u, z = t % 1, a % 1
    cj = np.array(
        [
            row * segments + col,
            row * segments + (col + 1) % segments,
            (row + 1) * segments + col,
            (row + 1) * segments + (col + 1) % segments,
        ]
    ).T + len(names)
    cw = np.array([(1 - u) * (1 - z), (1 - u) * z, u * (1 - z), u * z]).T
    # Assign semantic parts per TRIANGLE and duplicate the boundary vertices.
    # A single fused source vertex cannot simultaneously belong to a thigh and
    # a free skirt hem. Per-vertex thresholding makes long mixed-weight ribbons.
    cloth_faces = skirt[f].sum(1) >= 2
    # Head-following locks with separate spring chains: no arm/shoulder weights.
    # Geometry remains unchanged; the hair rig is a low-dimensional approximation.
    springs = []
    authored_hair = (
        fit(authored.accessor(authored.doc["meshes"][2]["primitives"][0]["attributes"]["POSITION"]))
        if authored
        else None
    )
    hair_positions = authored_hair if authored is not None else v[hair]
    hair_chain_ids = {}
    for side in () if hybrid else (-1, 1):
        chain, chain_ids = [], []
        previous = names.index("head")
        for level, y in enumerate((1.49, 1.38, 1.27, 1.16)):
            mask = (hair_positions[:, 0] * side > 0) & (abs(hair_positions[:, 1] - y) < 0.07)
            pos = (
                np.median(hair_positions[mask], axis=0)
                if mask.any()
                else np.array([side * 0.07, y, -0.12])
            )
            pos[1] = y
            node = len(writer.doc["nodes"])
            writer.doc["nodes"].append(
                {
                    "name": f"DF_Hair_{side}_{level}",
                    "translation": (pos - np.array(positions[previous])).tolist(),
                }
            )
            writer.doc["nodes"][previous].setdefault("children", []).append(node)
            joint_nodes.append(node)
            positions.append(pos.tolist())
            chain.append(node)
            chain_ids.append(len(joint_nodes) - 1)
            previous = node
        hair_chain_ids[side] = chain_ids
        springs.append(
            {
                "name": "Local hair lock",
                "colliderGroups": [0],
                "joints": [
                    {
                        "node": n,
                        "hitRadius": 0.012,
                        "stiffness": 1.5,
                        "dragForce": 0.65,
                        "gravityPower": 0.08,
                    }
                    for n in chain
                ],
            }
        )
        amount = np.clip((1.49 - v[:, 1]) / 0.11, 0, 2.9999)
        index, t = amount.astype(int), amount % 1
        selected = hair & (v[:, 0] * side >= 0) & (v[:, 1] < 1.47)
        j[selected] = np.c_[
            np.array(chain_ids)[index],
            np.array(chain_ids)[index + 1],
            np.zeros((len(v), 2), dtype=int),
        ][selected]
        w[selected] = np.c_[1 - t, t, np.zeros((len(v), 2))][selected]
    authored_hair_map = {}
    if hybrid:
        authored_hair_map, springs = authored_hair_rig(
            writer, authored, names, positions, joint_nodes
        )
    colliders = []
    for a, b, radius in (
        ("chest", "neck", 0.075),
        ("leftUpperArm", "leftLowerArm", 0.045),
        ("rightUpperArm", "rightLowerArm", 0.045),
    ):
        i, k = names.index(a), names.index(b)
        colliders.append(
            {
                "node": i,
                "shape": {
                    "capsule": {
                        "offset": [0, 0, 0],
                        "tail": (np.array(positions[k]) - positions[i]).tolist(),
                        "radius": radius,
                    }
                },
            }
        )
    writer.doc["extensionsUsed"].append("VRMC_springBone")
    writer.doc["extensions"]["VRMC_springBone"] = {
        "specVersion": "1.0",
        "colliders": colliders,
        "colliderGroups": [{"colliders": list(range(len(colliders)))}],
        "springs": springs,
    }
    # Replace the complete malformed head/locks as one authored assembly.
    # Partial pixel-labelled face removal leaves source eyes/fringe fragments.
    replace_head = head | hair
    # Keep triangles together at semantic boundaries to avoid split UV cracks.
    remove = replace_head[f].sum(1) >= 2 if hybrid else np.zeros(len(f), dtype=bool)
    if hybrid:
        # Replace the malformed fingers with the complete authored forearm/hand,
        # joining underneath the sleeve rather than across an exposed wrist.
        replace_arm = (abs(v[:, 0]) > 0.325) & (v[:, 1] > 1.10)
        # Retain an overlapping collar; the authored neck continues into the head.
        replace_neck = (abs(v[:, 0]) < 0.075) & (v[:, 1] > 1.295) & skin_color
        remove |= (replace_arm | replace_neck)[f].sum(1) >= 2
    body_faces = f[~remove & ~cloth_faces]
    if hybrid:
        exposed_limbs = ((abs(v[:, 0]) > 0.32) & (v[:, 1] > 1.16) & (v[:, 1] < 1.365)) | (
            (v[:, 1] > 0.51) & (v[:, 1] < 0.90)
        )
        # Baked skirt shadows are dark/grey, so skin hue alone leaves patchwork
        # on thighs. Outer fabric has already been separated geometrically.
        skin_region = (
            ((skin_color & (colors[:, 0] > 0.3)) | exposed_limbs) & ~hair & (v[:, 1] < 1.365)
        )
        skin_faces = skin_region[body_faces].sum(1) >= 2
        writer.doc["materials"].append(
            {
                "name": "Consistent cel skin",
                "doubleSided": True,
                "pbrMetallicRoughness": {
                    "baseColorFactor": [0.98, 0.84, 0.74, 1],
                    "metallicFactor": 0,
                    "roughnessFactor": 1,
                },
                "extensions": {"KHR_materials_unlit": {}},
            }
        )
        writer.mesh(
            "Tripo_ExposedSkin",
            v,
            body_faces[skin_faces],
            uv,
            j,
            w,
            len(writer.doc["materials"]) - 1,
        )
        writer.mesh("Tripo_Body", v, body_faces[~skin_faces], uv, j, w, material)
    else:
        writer.mesh("Tripo_Body", v, body_faces, uv, j, w, material)
    writer.mesh(
        "Tripo_LocalSurface",
        v,
        f[cloth_faces],
        uv,
        cj,
        cw,
        material,
        {
            "dollfightCage": {
                "version": 1,
                "segments": segments,
                "rows": rows,
                "rest": cage,
                "nodes": joint_nodes[len(names) : len(names) + len(cage)],
                "capsuleRadii": [0.080, 0.080, 0.045, 0.045]
                if hybrid
                else [0.052, 0.052, 0.037, 0.037],
            },
            "dollfightBinding": (
                "authored barycentric surface transfer, welded adjacency smoothing; "
                "head rigid; skirt independent"
            ),
        },
    )
    if hybrid:
        base_material = writer.materials(reference)
        # This is the actual skin mesh with articulated fingers, ears and neck.
        # Its original bind weights meet the face seam in the same rest frame.
        body_v = fit(reference.accessor(ref_prim["attributes"]["POSITION"]))
        include = (abs(body_v[:, 0]) > 0.295) | (
            (abs(body_v[:, 0]) < 0.115) & (body_v[:, 1] > 1.285)
        )
        bj, bw = top4(rw)
        writer.mesh(
            "AuthoredHandsNeck",
            body_v,
            rf[include[rf].all(1)],
            reference.accessor(ref_prim["attributes"]["TEXCOORD_0"]),
            bj,
            bw,
            base_material + ref_prim["material"],
        )
        # Face components share the original complete UVs; no projected image.
        for k, p in enumerate(reference.doc["meshes"][1]["primitives"]):
            pv = fit(reference.accessor(p["attributes"]["POSITION"]))
            pf = reference.accessor(p["indices"]).reshape(-1, 3).astype(int)
            pw = np.zeros((len(pv), len(names)))
            pw[:, names.index("head")] = 1
            pj, pw = top4(pw)
            writer.mesh(
                f"AuthoredFace_{k}",
                pv,
                pf,
                reference.accessor(p["attributes"]["TEXCOORD_0"]),
                pj,
                pw,
                base_material + p["material"],
            )
        for label, p in (
            ("AuthoredHair", authored.doc["meshes"][2]["primitives"][0]),
            ("AuthoredHairCap", authored.doc["meshes"][0]["primitives"][4]),
        ):
            pv = fit(authored.accessor(p["attributes"]["POSITION"]))
            pf = authored.accessor(p["indices"]).reshape(-1, 3).astype(int)
            pj = np.full((len(pv), 4), names.index("head"), dtype=int)
            pw = np.zeros((len(pv), 4))
            pw[:, 0] = 1
            if label == "AuthoredHair":
                old_j = authored.accessor(p["attributes"]["JOINTS_0"]).astype(int)
                old_nodes = authored.doc["skins"][2]["joints"]
                remap = np.array([authored_hair_map.get(n, names.index("head")) for n in old_nodes])
                pj = remap[old_j]
                pw = authored.accessor(p["attributes"]["WEIGHTS_0"])
            original_material = authored.doc["materials"][p["material"]]
            color = original_material["pbrMetallicRoughness"]["baseColorFactor"]
            writer.doc["materials"].append(
                {
                    "name": label,
                    "doubleSided": True,
                    "pbrMetallicRoughness": {
                        "baseColorFactor": color,
                        "metallicFactor": 0,
                        "roughnessFactor": 1,
                    },
                    "extensions": {"KHR_materials_unlit": {}},
                }
            )
            writer.mesh(
                label,
                pv,
                pf,
                authored.accessor(p["attributes"]["TEXCOORD_0"]),
                pj,
                pw,
                len(writer.doc["materials"]) - 1,
            )
    payload = writer.finish(joint_nodes, positions)
    tag = character + ("-hybrid" if hybrid else "")
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / f"{tag}.vrm").write_bytes(payload)
    report = audit_bytes(payload)
    (DEST / f"{tag}-audit.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if report["errors"]:
        raise ValueError(report["errors"])
    return {
        "name": tag,
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "source_triangles": len(f),
        "retained_source_triangles": len(body_faces) + int(cloth_faces.sum()),
        "human_bones": len(names),
        "cage_bones": len(cage),
        "transfer_distance_m_p50_p95": np.quantile(distance[~skirt & ~head], [0.5, 0.95]).tolist(),
        "method": (
            "CPU surface transfer + adjacency smoothing + separate GPU garment cage; NOT SkinTokens"
        ),
        "hybrid_face": hybrid,
        "hybrid_head": hybrid,
        "authored_hands_neck": hybrid,
        "hair_binding": "authored strand topology" if hybrid else "two spatial chains",
        "hair_bones": len(authored_hair_map) if hybrid else 8,
        "authored_hair_sha256": hashlib.sha256(authored_path.read_bytes()).hexdigest()
        if hybrid
        else None,
        "likeness_approved": False,
    }


def main():
    entries = []
    for character in ("nozomi", "mizore"):
        for hybrid in (False, True):
            entry = build(character, hybrid)
            entries.append(entry)
            print(json.dumps(entry, ensure_ascii=False), flush=True)
    (DEST / "manifest.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
