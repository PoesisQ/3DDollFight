"""Explicit anonymous image-to-mesh experiment for our two generated character references."""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("character", choices=("nozomi", "mizore"))
    parser.add_argument(
        "--texture", action="store_true", help="Request the provider's full texture pipeline"
    )
    args = parser.parse_args()
    source = ROOT / f"data/avatars/liz/{args.character}-reference.png"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = ROOT / "outputs/avatar-experiments" / f"{stamp}-{args.character}"
    folder.mkdir(parents=True)
    record = {
        "provider": "tencent/Hunyuan3D-2",
        "character": args.character,
        "input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "started_utc": stamp,
        "status": "starting",
        "seed": 231023,
        "steps": 20,
        "octree_resolution": 256,
        "hosted_revision_verified": False,
        "rigged": False,
        "textured": False,
        "requested_texture": args.texture,
    }
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    from gradio_client import Client, handle_file

    job = None
    try:
        client = Client(
            record["provider"],
            token=None,
            verbose=False,
            analytics_enabled=False,
            download_files=folder,
            httpx_kwargs={"timeout": 40},
        )
        job = client.submit(
            caption=None,
            image=handle_file(str(source)),
            mv_image_front=None,
            mv_image_back=None,
            mv_image_left=None,
            mv_image_right=None,
            steps=20,
            guidance_scale=5.0,
            seed=231023,
            octree_resolution=256,
            check_box_rembg=True,
            num_chunks=8000,
            randomize_seed=False,
            api_name="/generation_all" if args.texture else "/shape_generation",
        )
        print(f"Submitted public character reference: {args.character}", flush=True)
        result = job.result(timeout=180)
        value = result[1 if args.texture else 0]
        if isinstance(value, dict):
            value = value.get("value", value.get("path"))
        if isinstance(value, dict):
            value = value.get("path")
        path = Path(value).resolve()
        if not path.is_relative_to(folder.resolve()) or not path.is_file():
            raise ValueError("Output is not a downloaded file in the experiment directory")
        record.update(
            status="downloaded_unvalidated",
            output=str(path.relative_to(ROOT)),
            output_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            stats=result[3 if args.texture else 2],
            textured=args.texture,
        )
    except TimeoutError:
        if job is not None:
            job.cancel()
        record.update(status="timeout", error="Timeout; cancellation requested")
    except Exception as exc:
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    (folder / "experiment.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record, indent=2), flush=True)
    return 0 if record["status"] == "downloaded_unvalidated" else 1


if __name__ == "__main__":
    raise SystemExit(main())
