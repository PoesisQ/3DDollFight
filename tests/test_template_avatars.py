"""Regression checks for the authored-base route (offline, with LFS assets)."""

import json
from pathlib import Path

import numpy as np
import pytest

from dollfight.avatar_audit import HUMAN_BONES, EmbeddedGLB, audit_bytes

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=["nozomi", "mizore"])
def models(request):
    source = ROOT / "data/raw/avatars/sample.vrm"
    destination = ROOT / f"data/avatars/atelier/{request.param}.vrm"
    if not source.is_file() or not destination.is_file() or destination.stat().st_size < 1024:
        pytest.skip("Fetch the licensed sample and git lfs pull for asset regression checks")
    return EmbeddedGLB(source.read_bytes()), EmbeddedGLB(destination.read_bytes())


def test_authored_body_weights_and_face_uvs_survive(models):
    base, model = models
    for mesh_id, primitive_id in [(0, 0), (1, 1), (1, 2), (1, 3)]:
        a = base.doc["meshes"][mesh_id]["primitives"][primitive_id]["attributes"]
        b = model.doc["meshes"][mesh_id]["primitives"][primitive_id]["attributes"]
        for attribute in ("POSITION", "TEXCOORD_0", "JOINTS_0", "WEIGHTS_0"):
            np.testing.assert_array_equal(base.accessor(a[attribute]), model.accessor(b[attribute]))
    # Retained body bones really have the same bind matrices, not just same names.
    np.testing.assert_allclose(
        base.accessor(base.doc["skins"][0]["inverseBindMatrices"]),
        model.accessor(model.doc["skins"][0]["inverseBindMatrices"]),
        atol=1e-5,
    )


def test_skirt_is_separate_and_has_no_thigh_weights(models):
    _, model = models
    node = next(n for n in model.doc["nodes"] if n.get("name") == "DollFight_PleatedSkirt")
    assert node["extras"]["dollfightCloth"]["segments"] == 64
    joints = model.doc["skins"][node["skin"]]["joints"]
    names = [model.doc["nodes"][i]["name"] for i in joints]
    assert names[0] == "J_Bip_C_Hips"
    assert all(name.startswith("DF_Skirt_") for name in names[1:])
    assert len(names) == 65
    primitive = model.doc["meshes"][node["mesh"]]["primitives"][0]
    weights = model.accessor(primitive["attributes"]["WEIGHTS_0"])
    np.testing.assert_allclose(weights.sum(1), 1, atol=1e-6)
    assert len(weights) == 896


def test_template_keeps_full_humanoid_and_all_embedded_textures(models):
    base, model = models
    original = base.doc["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]
    mapping = model.doc["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]
    assert mapping == original
    assert set(HUMAN_BONES).issubset(mapping)
    assert "leftIndexDistal" in mapping and "rightThumbDistal" in mapping
    for a, b in zip(base.doc["images"], model.doc["images"], strict=True):
        av, bv = base.doc["bufferViews"][a["bufferView"]], model.doc["bufferViews"][b["bufferView"]]
        assert (
            base.binary[av["byteOffset"] : av["byteOffset"] + av["byteLength"]]
            == (model.binary[bv["byteOffset"] : bv["byteOffset"] + bv["byteLength"]])
        )


def test_manifest_hash_and_intake(models):
    _, model = models
    manifest = json.loads((ROOT / "data/avatars/atelier/manifest.json").read_text(encoding="utf-8"))
    for entry in manifest:
        report = audit_bytes((ROOT / f"data/avatars/atelier/{entry['character']}.vrm").read_bytes())
        assert not report["errors"]
        assert report["sha256"] == entry["sha256"]
        assert entry["triangles"] < 45_000
        assert entry["likeness_approved"] is False
