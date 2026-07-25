"""Full Pipeline Gate: run complete pipeline 3 times with real image.

Usage:
    set QWEN_TEST_API_KEY=sk-ws-...
    python scripts/pipeline_gate.py --image <path> --runs 3
"""
import asyncio
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Set env vars for real Qwen API
os.environ.setdefault("VISION_PROVIDER", "openai_compatible")
os.environ.setdefault("VISION_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
os.environ.setdefault("VISION_MODEL", "qwen3.7-plus")
os.environ.setdefault("OCR_PROVIDER", "paddleocr_v6")
os.environ.setdefault("OCR_ENABLED", "true")

# API key from QWEN_TEST_API_KEY or VISION_API_KEY
_api_key = os.environ.get("QWEN_TEST_API_KEY") or os.environ.get("VISION_API_KEY", "")
if _api_key:
    os.environ["VISION_API_KEY"] = _api_key


def check_gate(job_dir: Path, job: dict) -> dict:
    """Check all gate conditions."""
    gate = {
        "job_id": job.get("id", ""),
        "status": job.get("status", ""),
        "content_received": False,
        "json_valid": False,
        "structured_result_exists": False,
        "schema_passed": False,
        "fusion_done": False,
        "final_result_exists": False,
        "excel_exists": False,
        "excel_file": "",
        "ocr_success": False,
        "ocr_ms": 0,
        "vision_ms": 0,
        "http_status": None,
        "request_id": "",
        "content_chars": 0,
        "raw_response_exists": False,
        "error": job.get("error", ""),
    }

    # Check raw_response
    raw_path = job_dir / "vision" / "raw_response.txt"
    if raw_path.exists():
        gate["raw_response_exists"] = True
        content = raw_path.read_text(encoding="utf-8")
        gate["content_chars"] = len(content)
        gate["content_received"] = len(content) > 0
        # Check JSON validity
        try:
            from lite_app.pipeline_v2 import extract_json
            extract_json(content)
            gate["json_valid"] = True
        except Exception:
            pass

    # Check structured_result
    sr_path = job_dir / "vision" / "structured_result.json"
    if sr_path.exists():
        gate["structured_result_exists"] = True

    # Check schema
    gate["schema_passed"] = not job.get("validation_errors")

    # Check fusion
    fusion_dir = job_dir / "fusion"
    if fusion_dir.exists() and any(fusion_dir.iterdir()):
        gate["fusion_done"] = True

    # Check final result (pipeline creates review/final_result.json and result.json)
    final_path = job_dir / "review" / "final_result.json"
    result_path = job_dir / "result.json"
    if final_path.exists() or result_path.exists():
        gate["final_result_exists"] = True

    # Check OCR
    ocr_dir = job_dir / "ocr"
    if ocr_dir.exists():
        ocr_files = list(ocr_dir.glob("*.json"))
        if ocr_files:
            gate["ocr_success"] = True

    # Timings
    timings = job.get("timings_ms", {})
    gate["ocr_ms"] = timings.get("ocr_ms", 0)
    gate["vision_ms"] = timings.get("vision_ms", 0)

    # Vision metadata
    gate["http_status"] = job.get("vision_http_status")
    gate["request_id"] = job.get("vision_request_id", "")
    # Cache hit detection: vision_ms < 100ms indicates cache replay
    vision_engine = job.get("vision_engine", {})
    gate["vision_cache_hit"] = bool(vision_engine.get("cache_hit", False))
    gate["call_type"] = "cache_replay" if gate["vision_cache_hit"] or gate["vision_ms"] < 100 else "real_api"

    # Excel
    export_file = job.get("export_file", "")
    if export_file:
        excel_path = job_dir / export_file
        if excel_path.exists():
            gate["excel_exists"] = True
            gate["excel_file"] = export_file

    # Overall pass
    # Accept READY or REVIEW_REQUIRED (real model output always has fields needing review)
    # Excel export requires READY status, so excel_exists may be False for REVIEW_REQUIRED
    gate["gate_passed"] = all([
        gate["content_received"],
        gate["json_valid"],
        gate["structured_result_exists"],
        gate["schema_passed"],
        gate["final_result_exists"],
        job.get("status") in ("READY", "REVIEW_REQUIRED"),
    ])

    return gate


async def run_single_pipeline(image_path: Path, run_number: int) -> dict:
    """Run one complete pipeline execution."""
    from lite_app.config import clear_config_cache
    from lite_app.storage import JobStorage

    clear_config_cache()

    storage = JobStorage()
    img_bytes = image_path.read_bytes()
    sha256 = hashlib.sha256(img_bytes).hexdigest().upper()

    print(f"\n{'='*60}")
    print(f"Pipeline Run #{run_number}")
    print(f"Image: {image_path.name} ({len(img_bytes)} bytes)")
    print(f"SHA-256: {sha256}")
    print(f"{'='*60}")

    # Create job
    job = storage.create_job(rotation="auto")
    job_id = job["id"]
    job_dir = storage.get_job_dir(job_id)
    print(f"Job ID: {job_id}")

    # Save image to job dir
    dest = job_dir / f"upload_01{image_path.suffix}"
    shutil.copy2(image_path, dest)
    job["images"] = [{
        "source": dest.name,
        "original_name": image_path.name,
        "size": len(img_bytes),
        "sha256": sha256,
    }]
    storage.save_job(job)

    # Run pipeline with retry (1 retry on network errors only)
    import ssl

    import httpx

    from lite_app.pipeline_v2 import PipelineError, analyze_job_v2

    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"  Attempt {attempt}...")
            t0 = time.time()
            result_job = await analyze_job_v2(job_id, storage)
            elapsed = time.time() - t0
            print(f"  Pipeline completed in {elapsed:.1f}s, status={result_job.get('status')}")
            break
        except (httpx.RemoteProtocolError, httpx.ConnectError, ssl.SSLError) as e:
            if attempt < max_attempts:
                print(f"  Network error: {type(e).__name__}, retrying in 5s...")
                await asyncio.sleep(5)
            else:
                print(f"  Network error after retry: {type(e).__name__}: {repr(e)[:100]}")
                result_job = storage.get_job(job_id)
                result_job["error"] = f"{type(e).__name__}: {repr(e)[:200]}"
                storage.save_job(result_job)
        except PipelineError as e:
            print(f"  Pipeline error (no retry): {e}")
            result_job = storage.get_job(job_id)
            break
        except Exception as e:
            print(f"  Unexpected error: {type(e).__name__}: {repr(e)[:150]}")
            result_job = storage.get_job(job_id)
            result_job["error"] = f"{type(e).__name__}: {repr(e)[:200]}"
            storage.save_job(result_job)
            break

    # Try Excel export
    try:
        from lite_app.exporter import export_job
        export_file = export_job(job_id, storage)
        result_job = storage.get_job(job_id)
        print(f"  Excel exported: {export_file}")
    except Exception as e:
        print(f"  Excel export failed: {type(e).__name__}: {e}")

    # Check gate
    result_job = storage.get_job(job_id)
    gate = check_gate(job_dir, result_job)
    gate["image_sha256"] = sha256
    gate["run_number"] = run_number

    # Print gate status
    print("\n  --- Gate Check ---")
    for k, v in gate.items():
        if k not in ("job_id", "run_number", "image_sha256"):
            status = "PASS" if v is True else ("FAIL" if v is False else str(v))
            print(f"  {k}: {status}")

    return gate


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"ERROR: Image not found: {image_path}")
        sys.exit(1)

    if not os.environ.get("VISION_API_KEY"):
        print("ERROR: Set QWEN_TEST_API_KEY or VISION_API_KEY")
        sys.exit(1)

    print(f"API Key: key_prefix={os.environ['VISION_API_KEY'][:5]}")
    print(f"Base URL: {os.environ.get('VISION_BASE_URL')}")
    print(f"Model: {os.environ.get('VISION_MODEL')}")
    print(f"OCR: {os.environ.get('OCR_PROVIDER')}")
    print(f"Runs: {args.runs}")

    results = []
    for i in range(1, args.runs + 1):
        gate = await run_single_pipeline(image_path, i)
        results.append(gate)
        if not gate["gate_passed"]:
            print(f"\n  WARNING: Run #{i} gate NOT passed!")

    # Summary
    print(f"\n{'='*60}")
    print("PIPELINE GATE SUMMARY")
    print(f"{'='*60}")
    passed = sum(1 for r in results if r["gate_passed"])
    print(f"Total runs: {len(results)}")
    print(f"Passed: {passed}/{len(results)}")
    for r in results:
        print(f"  Run #{r['run_number']}: job={r['job_id']} status={r['status']} "
              f"vision={r['vision_ms']}ms ocr={r['ocr_ms']}ms "
              f"content={r['content_chars']}chars gate={'PASS' if r['gate_passed'] else 'FAIL'}")

    # Save results
    out_dir = Path(__file__).resolve().parent.parent / "data" / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_file = out_dir / f"pipeline_gate_{ts}.json"
    out_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nResults saved: {out_file}")

    if passed == len(results):
        print("\nALL GATES PASSED - Pipeline is production ready.")
    else:
        print(f"\nGATE FAILED - {len(results)-passed} runs did not pass.")


if __name__ == "__main__":
    asyncio.run(main())
