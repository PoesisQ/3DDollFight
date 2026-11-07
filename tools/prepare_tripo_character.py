"""Preserve supplied Tripo FBX/textures and pack Standard metallic/smoothness.

Run with a Python environment containing Pillow. Then run Unity's
DollFight.Editor.TripoCharacterImport.Prepare to build the Humanoid prefab.
"""

import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_NAME = "tripo_convert_b9e9ce29-c08e-4b8d-80aa-684acc71674c"
DESTINATION = ROOT / "unity/Assets/Art/TripoB9E9"
FILES = {
    ARCHIVE_NAME + ".fbx": "TripoB9E9.fbx",
    ARCHIVE_NAME + ".fbm/tripo_rgb_7aabbbc5-b18b-4be8-98f1-c175361ee5c0.jpg": "Albedo.jpg",
    ARCHIVE_NAME + ".fbm/tripo_normal_0bd4243b-6f8d-49ca-bfc8-d47f7fe00fd1.jpg": "Normal.jpg",
    ARCHIVE_NAME + ".fbm/anime_girl_3d_model_metallic.JPEG": "OriginalMetallic.jpg",
    ARCHIVE_NAME + ".fbm/anime_girl_3d_model_roughness.JPEG": "OriginalRoughness.jpg",
}


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def save_preserving_original(path, data):
    if path.exists() and path.read_bytes() != data:
        raise ValueError(f"Existing asset differs from supplied original: {path}")
    if not path.exists():
        path.write_bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=ROOT.parent / "素材" / (ARCHIVE_NAME + ".zip")
    )
    args = parser.parse_args()
    source = args.source.resolve()
    DESTINATION.mkdir(parents=True, exist_ok=True)
    originals = []
    with zipfile.ZipFile(source) as archive:
        if set(archive.namelist()) != set(FILES):
            raise ValueError("Archive contents changed; review the new source before importing")
        for entry, filename in FILES.items():
            data = archive.read(entry)
            save_preserving_original(DESTINATION / filename, data)
            info = {
                "archive_entry": entry,
                "asset": filename,
                "bytes": len(data),
                "sha256": sha256(data),
            }
            if filename != "TripoB9E9.fbx":
                with Image.open(io.BytesIO(data)) as image:
                    info["pixels"] = list(image.size)
            originals.append(info)
    with (
        Image.open(DESTINATION / "OriginalMetallic.jpg") as metal_image,
        Image.open(DESTINATION / "OriginalRoughness.jpg") as rough_image,
    ):
        metallic = metal_image.convert("RGB").getchannel("R")
        roughness = rough_image.convert("RGB").getchannel("R")
        if metallic.size != roughness.size:
            raise ValueError("Metallic and roughness resolution mismatch")
        smoothness = roughness.point(lambda value: 255 - value)
        zero = Image.new("L", metallic.size, 0)
        packed = Image.merge("RGBA", (metallic, zero, zero, smoothness))
        packed_path = DESTINATION / "MetallicSmoothness.png"
        # Write atomically so a live Unity AssetDatabase cannot import half a PNG.
        png = io.BytesIO()
        packed.save(png, format="PNG", compress_level=6)
        temporary = packed_path.with_suffix(".preparing")
        temporary.write_bytes(png.getvalue())
        temporary.replace(packed_path)
    provenance = {
        "source": "../素材/" + source.name,
        "source_archive": source.name,
        "source_sha256": sha256(source.read_bytes()),
        "source_kind": "User-supplied local Tripo conversion archive",
        "license": "Not supplied in the archive; no license or authorship inferred",
        "originals": originals,
        "derived": [
            {
                "asset": packed_path.name,
                "sha256": sha256(packed_path.read_bytes()),
                "pixels": list(packed.size),
                "conversion": (
                    "Lossless RGBA PNG: R=metallic red channel, G=B=0, "
                    "A=255-roughness red channel; no resizing"
                ),
            }
        ],
        "unity_prepare": "DollFight.Editor.TripoCharacterImport.Prepare",
        "prefab": "Assets/Resources/DollFight/Characters/TripoB9E9.prefab",
    }
    (DESTINATION / "provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"Preserved {len(originals)} original files; packed {packed.size} metallic/smoothness map"
    )


if __name__ == "__main__":
    main()
