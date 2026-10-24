"""Small embedded assets exercise intake failures without network/downloaded fixtures."""

import json
import struct

import numpy as np
import pytest

from dollfight.avatar_audit import HUMAN_BONES, PARENTS, audit_bytes


def encode(doc, binary):
    description = json.dumps(doc).encode()
    description += b" " * (-len(description) % 4)
    binary += b"\0" * (-len(binary) % 4)
    body = struct.pack("<II", len(description), 0x4E4F534A) + description
    body += struct.pack("<II", len(binary), 0x004E4942) + binary
    return struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body


def fixture(*, normalized=False, weights=None, joints=None):
    # Mesh occupies node 0: node indices and skin-local indices differ deliberately.
    nodes = [{"name": "mesh", "mesh": 0, "skin": 0}]
    nodes += [{"name": name, "children": [], "translation": [0, 0.1, 0]} for name in HUMAN_BONES]
    for i, parent in enumerate(PARENTS):
        if parent >= 0:
            nodes[parent + 1]["children"].append(i + 1)
    doc = {
        "asset": {"version": "2.0"},
        "nodes": nodes,
        "skins": [{"joints": list(range(1, 20))}],
        "extensions": {
            "VRMC_vrm": {
                "humanoid": {
                    "humanBones": {name: {"node": i + 1} for i, name in enumerate(HUMAN_BONES)}
                }
            }
        },
        "bufferViews": [],
        "accessors": [],
    }
    binary = bytearray()

    def accessor(data, component, shape, **extra):
        binary.extend(b"\0" * (-len(binary) % 4))
        view = {"buffer": 0, "byteOffset": len(binary), "byteLength": data.nbytes}
        # Four padding bytes per vertex test interleaved/strided POSITION data.
        if shape == "VEC3":
            view["byteStride"] = 16
        doc["bufferViews"].append(view)
        binary.extend(data.tobytes())
        doc["accessors"].append(
            {
                "bufferView": len(doc["bufferViews"]) - 1,
                "componentType": component,
                "count": len(data),
                "type": shape,
                **extra,
            }
        )
        return len(doc["accessors"]) - 1

    positions = np.array([[0, 0, 0, 99], [1, 0, 0, 99], [0, 1, 0, 99]], dtype="<f4")
    joint_values = np.array(joints if joints is not None else [[18, 0, 0, 0]] * 3, dtype="u1")
    weight_values = np.array(
        weights if weights is not None else [[255 if normalized else 1, 0, 0, 0]] * 3,
        dtype="u1" if normalized else "<f4",
    )
    attrs = {
        "POSITION": accessor(positions, 5126, "VEC3"),
        "JOINTS_0": accessor(joint_values, 5121, "VEC4"),
        "WEIGHTS_0": accessor(
            weight_values, 5121 if normalized else 5126, "VEC4", normalized=normalized
        ),
    }
    doc["meshes"] = [{"primitives": [{"attributes": attrs}]}]
    doc["buffers"] = [{"byteLength": len(binary)}]
    return doc, binary


@pytest.mark.parametrize("normalized", [False, True])
def test_accepts_strided_vertices_and_normalized_integer_weights(normalized):
    doc, binary = fixture(normalized=normalized)
    report = audit_bytes(encode(doc, binary))
    assert report["errors"] == []
    assert report["motion_lab_structural_candidate"]
    assert report["skinned_vertices_instanced"] == 3
    assert report["max_weight_sum_error"] == 0
    assert not report["visual_quality_verified"]


def test_names_alone_and_incomplete_vrm_are_not_ready_for_our_renderer():
    doc, binary = fixture()
    del doc["extensions"]
    report = audit_bytes(encode(doc, binary))
    assert not report["motion_lab_structural_candidate"]
    assert report["errors"] == []
    doc, binary = fixture()
    del doc["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]["leftToes"]
    report = audit_bytes(encode(doc, binary))
    assert report["missing_motion_lab_bones"] == ["leftToes"]
    # Toes are optional in VRM; missing them is our viewer limitation, not invalid VRM.
    assert report["errors"] == []
    assert not report["motion_lab_structural_candidate"]


def test_collapsed_named_rig_is_not_accepted_even_with_normalized_weights():
    doc, binary = fixture()
    for node in doc["nodes"]:
        node.pop("translation", None)
    report = audit_bytes(encode(doc, binary))
    assert report["errors"] == []
    assert report["collapsed_skin"]
    assert report["skin_joint_spans"] == [0]
    assert not report["motion_lab_structural_candidate"]
    assert any("Collapsed bind" in warning for warning in report["warnings"])


@pytest.mark.parametrize(
    "weights,expected",
    [
        ([[0, 0, 0, 0]] * 3, "no skin influence"),
        ([[0.2, 0.2, 0, 0]] * 3, "not normalized"),
        ([[1, -0.1, 0.1, 0]] * 3, "Negative skin weight"),
        ([[float("nan"), 0, 0, 0]] * 3, "Non-finite"),
    ],
)
def test_rejects_bad_vertex_weights(weights, expected):
    doc, binary = fixture(weights=weights)
    report = audit_bytes(encode(doc, binary))
    assert any(expected in error for error in report["errors"])
    assert not report["motion_lab_structural_candidate"]


def test_joint_indices_are_skin_local_not_node_ids():
    # 19 is a valid node, but the skin's 19 joints are indexed 0 through 18.
    doc, binary = fixture(joints=[[19, 0, 0, 0]] * 3)
    assert "skin-local" in audit_bytes(encode(doc, binary))["errors"][0]


@pytest.mark.parametrize(
    "case,expected",
    [
        ("overrun", "outside"),
        ("cycle", "Cyclic"),
        ("duplicate", "one node"),
        ("wrong_parent", "hierarchy mismatch"),
        ("external_image", "External image"),
        ("sparse", "Sparse"),
        ("non_unit_quaternion", "not normalized"),
        ("missing_weights", "matching"),
        ("compressed", "offline decoding"),
    ],
)
def test_broken_assets_produce_diagnostic_errors(case, expected):
    doc, binary = fixture()
    bones = doc["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]
    if case == "overrun":
        doc["accessors"][0]["count"] = 100
    elif case == "cycle":
        doc["nodes"][19]["children"].append(1)
    elif case == "duplicate":
        bones["head"]["node"] = bones["neck"]["node"]
    elif case == "wrong_parent":
        doc["nodes"][3]["children"].remove(6)
        doc["nodes"][12]["children"].append(6)
    elif case == "external_image":
        doc["images"] = [{"uri": "https://example.com/texture.png"}]
    elif case == "sparse":
        doc["accessors"][0]["sparse"] = {}
    elif case == "non_unit_quaternion":
        doc["nodes"][1]["rotation"] = [0, 0, 0, 0]
    elif case == "missing_weights":
        del doc["meshes"][0]["primitives"][0]["attributes"]["WEIGHTS_0"]
    elif case == "compressed":
        doc["extensionsUsed"] = ["EXT_meshopt_compression"]
    report = audit_bytes(encode(doc, binary))
    assert any(expected in error for error in report["errors"])
    assert not report["motion_lab_structural_candidate"]


def test_extra_weight_set_is_not_silently_lost_in_current_renderer():
    doc, binary = fixture(weights=[[0.5, 0, 0, 0]] * 3)
    attrs = doc["meshes"][0]["primitives"][0]["attributes"]
    attrs.update(JOINTS_1=attrs["JOINTS_0"], WEIGHTS_1=attrs["WEIGHTS_0"])
    report = audit_bytes(encode(doc, binary))
    assert not report["errors"]
    assert report["max_vertex_influences"] == 2
    assert report["uses_extra_weight_sets"]
    assert not report["motion_lab_structural_candidate"]


def test_truncation_and_non_object_json_do_not_crash_audit():
    doc, binary = fixture()
    assert audit_bytes(encode(doc, binary)[:-1])["errors"]
    assert audit_bytes(encode([], b""))["errors"]
    doc["nodes"][1] = 12
    assert audit_bytes(encode(doc, binary))["errors"]
