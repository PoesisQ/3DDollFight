"""Structural regression gates, not a claim of visually approved skinning."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

from dollfight.avatar_audit import EmbeddedGLB

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("character", ["nozomi", "mizore"])
def test_local_rig_keeps_source_detail_and_moves_limbs_separately(character):
    path = ROOT / f"data/avatars/local/{character}.vrm"
    if not path.exists() or path.read_bytes()[:4] != b"glTF":
        pytest.skip("optional LFS model not fetched")
    model = EmbeddedGLB(path.read_bytes())
    source = EmbeddedGLB((ROOT / f"data/avatars/tripo/{character}-h25-source.glb").read_bytes())
    p, original = (m.doc["meshes"][0]["primitives"][0] for m in (model, source))
    v = model.accessor(p["attributes"]["POSITION"])
    j = model.accessor(p["attributes"]["JOINTS_0"]).astype(int)
    w = model.accessor(p["attributes"]["WEIGHTS_0"])
    assert (
        sum(
            model.doc["accessors"][part["indices"]]["count"]
            for mesh in model.doc["meshes"]
            for part in mesh["primitives"]
        )
        == source.doc["accessors"][original["indices"]]["count"]
    )
    np.testing.assert_allclose(w.sum(1), 1, atol=1e-6)
    assert np.isfinite(w).all() and (w >= 0).all()
    skin = model.doc["skins"][0]
    ibm = model.accessor(skin["inverseBindMatrices"]).reshape(-1, 4, 4).transpose(0, 2, 1)
    rest = -ibm[:, :3, 3]
    human = model.doc["extensions"]["VRMC_vrm"]["humanoid"]["humanBones"]
    assert len(human) == 54 and np.ptp(rest[:, 1]) > 1.2
    assert len(np.unique(j[w > 0.1])) > 30  # Reject the free-export all-root placeholder.
    # Rotate the whole left arm around its shoulder; other parts must remain still.
    descendants = set()

    def visit(node):
        descendants.add(node)
        for child in model.doc["nodes"][node].get("children", []):
            visit(child)

    shoulder = human["leftUpperArm"]["node"]
    visit(shoulder)
    moved = np.array([node in descendants for node in skin["joints"]])
    influence = (w * moved[j]).sum(1)
    left_hand = (v[:, 0] > 0.55) & (v[:, 1] > 1.2)
    right_hand = (v[:, 0] < -0.55) & (v[:, 1] > 1.2)
    head = v[:, 1] > 1.5
    assert np.mean(influence[left_hand]) > 0.98
    assert np.mean(influence[right_hand]) < 0.01
    assert np.mean(influence[head]) < 0.01
    # A dark shoulder/sleeve must never be classified as a swinging hair lock.
    names = [model.doc["nodes"][node]["name"] for node in skin["joints"]]
    head_or_hair = np.array([n == "head" or n.startswith("DF_Hair_") for n in names])
    arms = (abs(v[:, 0]) > 0.19) & (v[:, 1] > 1.16)
    assert np.max((w * head_or_hair[j]).sum(1)[arms]) < 0.01
    # Cage deformation is GPU-weighted, not a 200k-vertex CPU cloth solver.
    cage = next(
        n["extras"]["dollfightCage"]
        for n in model.doc["nodes"]
        if "dollfightCage" in n.get("extras", {})
    )
    assert len(cage["rest"]) == cage["segments"] * cage["rows"] == 216
    is_cage = np.array([n.startswith("DF_Cage_") for n in names])
    foot = v[:, 1] < 0.4
    assert (w * is_cage[j])[foot].sum() == 0
    assert (w * is_cage[j]).sum() == 0  # Body and fabric never share a deforming seam.
    cloth_part = model.doc["meshes"][1]["primitives"][0]
    cj = model.accessor(cloth_part["attributes"]["JOINTS_0"]).astype(int)
    cw = model.accessor(cloth_part["attributes"]["WEIGHTS_0"])
    np.testing.assert_allclose((cw * is_cage[cj]).sum(1), 1, atol=1e-6)


def test_barycentric_transfer_blends_authored_weights_and_preserves_normalization(monkeypatch):
    pytest.importorskip("scipy")
    pytest.importorskip("trimesh")
    monkeypatch.setattr(sys, "path", [str(ROOT), *sys.path])
    from tools.rig_local_avatars import top4, transfer

    # Sixteen identical triangles meet the nearest-candidate contract.
    vertices = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float)
    faces = np.repeat([[0, 1, 2]], 16, axis=0)
    weights = np.eye(4)[[0, 1, 2]]
    transferred, distances = transfer(np.array([[0.25, 0.25, 0.02]]), vertices, faces, weights)
    np.testing.assert_allclose(transferred, [[0.5, 0.25, 0.25, 0]], atol=1e-6)
    np.testing.assert_allclose(distances, [0.02])
    _, packed = top4(transferred)
    np.testing.assert_allclose(packed.sum(1), 1)


def test_local_manifest_does_not_claim_skintokens_or_likeness_approval():
    manifest = json.loads((ROOT / "data/avatars/local/manifest.json").read_text(encoding="utf-8"))
    assert len(manifest) == 4
    assert all(
        "NOT SkinTokens" in item["method"] and not item["likeness_approved"] for item in manifest
    )


@pytest.mark.parametrize("character", ["nozomi", "mizore"])
def test_hybrid_replaces_the_whole_head_without_leaving_source_eyes(character):
    path = ROOT / f"data/avatars/local/{character}-hybrid.vrm"
    if not path.exists() or path.read_bytes()[:4] != b"glTF":
        pytest.skip("optional LFS model not fetched")
    model = EmbeddedGLB(path.read_bytes())
    names = {mesh["name"] for mesh in model.doc["meshes"]}
    assert {"AuthoredHair", "AuthoredHairCap", "AuthoredFace_1", "AuthoredFace_3"} <= names
    for mesh in model.doc["meshes"]:
        if mesh["name"].startswith("Tripo_"):
            for part in mesh["primitives"]:
                positions = model.accessor(part["attributes"]["POSITION"])
                assert positions[:, 1].max() < 1.38
