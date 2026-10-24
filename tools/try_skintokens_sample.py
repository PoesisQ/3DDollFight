"""One anonymous hosted experiment using ONLY our hash-pinned public VRM sample.

Run explicitly with uv run --locked --group assets python tools/try_skintokens_sample.py.
This uploads a public model to VAST-AI's HF Space; the Motion Lab never does this.
"""

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full-rig", action="store_true", help="Predict skeleton as well as skin")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    manifest = json.loads((ROOT / "data/avatars/sample.json").read_text(encoding="utf-8"))
    content = (ROOT / "data/raw/avatars/sample.vrm").read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != manifest["sha256"]:
        raise ValueError("Only the unmodified public sample from sample.json may be uploaded")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = ROOT / "outputs/avatar-experiments" / stamp
    folder.mkdir(parents=True, exist_ok=False)
    # VRM is a GLB container. Keep all bytes/metadata; change the suffix solely
    # for the hosted mesh importer's accepted file types, NOT to convert a rig.
    source = folder / "public-sample.glb"
    source.write_bytes(content)
    os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
    os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
    from gradio_client import Client, handle_file

    parameters = dict(
        top_k=5,
        top_p=0.95,
        temperature=1.0,
        repetition_penalty=2.0,
        num_beams=10,
        use_skeleton=not args.full_rig,
        use_transfer=True,
        use_postprocess=False,
        model_ckpt="experiments/articulation_xl_quantization_256_token_4/grpo_1400.ckpt",
        hf_path="None",
    )
    record = {
        "started_utc": stamp,
        "provider": "VAST-AI/SkinTokens",
        "client": "gradio-client==2.7.2",
        "endpoint": "https://vast-ai-skintokens.hf.space/",
        "api_name": "/run_gradio",
        "input_source": manifest["url"],
        "input_sha256": digest,
        "parameters": parameters,
        "status": "submitted",
        "generated_appearance": False,
        "note": "Hosted revision/seed are not fixed by this API. This is a binding experiment.",
    }

    def save():
        (folder / "experiment.json").write_text(json.dumps(record, indent=2), encoding="utf-8")

    save()
    print(f"Public sample binding experiment: {folder.relative_to(ROOT)}", flush=True)
    job = None
    try:
        client = Client(
            record["endpoint"],
            token=None,
            max_workers=1,
            verbose=False,
            download_files=folder / "result",
            analytics_enabled=False,
            httpx_kwargs={"timeout": 60},
        )
        job = client.submit(files=[handle_file(str(source))], **parameters, api_name="/run_gradio")
        result = job.result(timeout=args.timeout)
        record["message"] = str(result[0])
        values = result[1] if isinstance(result[1], list) else [result[1]]
        outputs = []
        for value in values:
            if value is None:
                continue
            path = Path(value).resolve()
            if not path.is_relative_to(folder.resolve()) or not path.is_file():
                raise ValueError("Result must be a downloaded file in the experiment directory")
            payload = path.read_bytes()
            outputs.append(
                {
                    "file": path.relative_to(ROOT).as_posix(),
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        if not outputs:
            raise ValueError("Hosted service returned no output file: " + record["message"])
        record.update(status="downloaded_unvalidated", outputs=outputs)
    except TimeoutError:
        if job is not None:
            job.cancel()
        record.update(status="timeout", error="Timed out; cancellation requested")
    except Exception as exc:
        record.update(status="failed", error=f"{type(exc).__name__}: {exc}")
    save()
    print(json.dumps(record, ensure_ascii=True, indent=2), flush=True)
    return 0 if record["status"] == "downloaded_unvalidated" else 1


if __name__ == "__main__":
    raise SystemExit(main())
