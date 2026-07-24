"""Qwen Transport Matrix diagnostic script.

Usage:
    python scripts/diagnose_qwen_transport.py --mode small-probe
    python scripts/diagnose_qwen_transport.py --mode real-minimal --image <path>
    python scripts/diagnose_qwen_transport.py --mode size-ladder --image <path>
    python scripts/diagnose_qwen_transport.py --mode client-matrix

Env vars:
    QWEN_TEST_API_KEY   - Required, API Key (sk-ws...)
    QWEN_TEST_BASE_URL  - Optional, default https://dashscope.aliyuncs.com/compatible-mode/v1
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import io
import json
import os
import platform
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


# === Safety ===

def get_api_key() -> str:
    key = os.environ.get("QWEN_TEST_API_KEY", "")
    if not key:
        print("ERROR: QWEN_TEST_API_KEY not set.")
        sys.exit(1)
    return key


def mask_key(key: str) -> str:
    return f"key_prefix={key[:5]}" if len(key) >= 5 else "key_prefix=???"


def get_base_url() -> str:
    return os.environ.get("QWEN_TEST_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")


# === Data ===

@dataclass
class ProbeResult:
    test_id: str = ""
    attempt: int = 0
    client: str = "httpx"
    trust_env: bool = True
    http2: bool = False
    image_bytes: int = 0
    request_body_bytes: int = 0
    total_ms: float = 0.0
    got_headers: bool = False
    http_status: int | None = None
    got_content: bool = False
    content_chars: int = 0
    marker_correct: bool | None = None
    exception_class: str = ""
    exception_repr: str = ""
    exception_cause: str = ""
    request_id: str = ""
    resp_server: str = ""
    resp_content_type: str = ""
    success: bool = False


# === Phase 1: Environment ===

def investigate_environment() -> dict[str, Any]:
    env_vars = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"]
    env_present = {f"{v}_PRESENT": bool(os.environ.get(v)) for v in env_vars}

    versions: dict[str, str] = {"python": platform.python_version(), "platform": platform.platform()}
    for mod, name in [("httpx", "httpx"), ("httpcore", "httpcore"), ("openai", "openai_sdk")]:
        try:
            m = __import__(mod)
            versions[name] = m.__version__
        except (ImportError, AttributeError):
            versions[name] = "NOT_INSTALLED"
    versions["openssl"] = ssl.OPENSSL_VERSION

    from urllib.parse import urlparse
    hostname = urlparse(get_base_url()).hostname or "dashscope.aliyuncs.com"
    try:
        t0 = time.perf_counter()
        ips = socket.getaddrinfo(hostname, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
        dns_ms = (time.perf_counter() - t0) * 1000
        dns_info = {"hostname": hostname, "ip_count": len({a[4][0] for a in ips}), "dns_ms": round(dns_ms, 1)}
    except Exception as e:
        dns_info = {"hostname": hostname, "error": str(e)}

    system_proxy = False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
        system_proxy = bool(proxy_enable)
        winreg.CloseKey(key)
    except Exception:
        pass

    return {**env_present, "versions": versions, "dns": dns_info, "system_proxy_detected": system_proxy}


# === Image helpers ===

def make_small_probe_image() -> bytes:
    from PIL import Image
    img = Image.new("RGB", (10, 10), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def detect_mime(data: bytes) -> str:
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    if data[:2] == b'\xff\xd8':
        return "image/jpeg"
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return "image/webp"
    return "image/jpeg"


def image_to_data_url(data: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def build_body(data_url: str, prompt: str, model: str = "qwen3.7-plus") -> dict:
    return {
        "model": model, "temperature": 0,
        "response_format": {"type": "json_object"},
        "enable_thinking": False,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": data_url}},
            {"type": "text", "text": prompt},
        ]}],
    }


SMALL_PROMPT = 'Return only valid JSON:\n{"marker":"VISION-7319"}'
REAL_PROMPT = 'Please look at the image and return only valid JSON:\n{"image_received":true,"has_visible_text":true,"summary":"max 30 chars"}'


# === HTTPX probe ===

async def probe_httpx(test_id: str, attempt: int, image_bytes: bytes, prompt: str,
                      trust_env: bool = True, http2: bool = False,
                      model: str = "qwen3.7-plus", mime: str | None = None) -> ProbeResult:
    import httpx
    api_key = get_api_key()
    url = f"{get_base_url().rstrip('/')}/chat/completions"
    if mime is None:
        mime = detect_mime(image_bytes)
    body = build_body(image_to_data_url(image_bytes, mime), prompt, model)
    r = ProbeResult(test_id=test_id, attempt=attempt, client="httpx",
                    trust_env=trust_env, http2=http2,
                    image_bytes=len(image_bytes),
                    request_body_bytes=len(json.dumps(body).encode()))
    timeout = httpx.Timeout(connect=30.0, read=300.0, write=60.0, pool=30.0)
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=trust_env, http2=http2) as client:
            resp = await client.post(url, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}, json=body)
            r.total_ms = (time.perf_counter() - t0) * 1000
            r.got_headers = True
            r.http_status = resp.status_code
            r.resp_server = resp.headers.get("server", "")
            r.resp_content_type = resp.headers.get("content-type", "")
            r.request_id = resp.headers.get("x-request-id", "")
            rj = resp.json()
            if not r.request_id:
                r.request_id = rj.get("request_id", "")
            choices = rj.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                if content:
                    r.got_content = True
                    r.content_chars = len(content)
                    try:
                        parsed = json.loads(content)
                        r.marker_correct = parsed.get("marker") == "VISION-7319"
                    except Exception:
                        pass
            r.success = resp.status_code == 200 and r.got_content
    except httpx.ConnectTimeout as e:
        r.total_ms = (time.perf_counter() - t0) * 1000
        r.exception_class = "httpx.ConnectTimeout"
        r.exception_repr = repr(e)[:200]
    except httpx.ReadTimeout as e:
        r.total_ms = (time.perf_counter() - t0) * 1000
        r.exception_class = "httpx.ReadTimeout"
        r.exception_repr = repr(e)[:200]
    except httpx.WriteTimeout as e:
        r.total_ms = (time.perf_counter() - t0) * 1000
        r.exception_class = "httpx.WriteTimeout"
        r.exception_repr = repr(e)[:200]
    except httpx.RemoteProtocolError as e:
        r.total_ms = (time.perf_counter() - t0) * 1000
        r.exception_class = "httpx.RemoteProtocolError"
        r.exception_repr = repr(e)[:200]
        if e.__cause__:
            r.exception_cause = repr(e.__cause__)[:200]
    except httpx.ConnectError as e:
        r.total_ms = (time.perf_counter() - t0) * 1000
        r.exception_class = "httpx.ConnectError"
        r.exception_repr = repr(e)[:200]
    except httpx.ProxyError as e:
        r.total_ms = (time.perf_counter() - t0) * 1000
        r.exception_class = "httpx.ProxyError"
        r.exception_repr = repr(e)[:200]
    except ssl.SSLError as e:
        r.total_ms = (time.perf_counter() - t0) * 1000
        r.exception_class = "ssl.SSLError"
        r.exception_repr = repr(e)[:200]
    except Exception as e:
        r.total_ms = (time.perf_counter() - t0) * 1000
        r.exception_class = type(e).__name__
        r.exception_repr = repr(e)[:200]
        if e.__cause__:
            r.exception_cause = repr(e.__cause__)[:200]
    return r


# === OpenAI SDK probe ===

async def probe_openai_sdk(test_id: str, attempt: int, image_bytes: bytes, prompt: str,
                           model: str = "qwen3.7-plus", mime: str | None = None) -> ProbeResult:
    api_key = get_api_key()
    if mime is None:
        mime = detect_mime(image_bytes)
    data_url = image_to_data_url(image_bytes, mime)
    r = ProbeResult(test_id=test_id, attempt=attempt, client="openai_sdk", image_bytes=len(image_bytes))
    try:
        from openai import AsyncOpenAI
    except ImportError:
        r.exception_class = "ImportError"
        r.exception_repr = "openai not installed"
        return r
    t0 = time.perf_counter()
    try:
        client = AsyncOpenAI(api_key=api_key, base_url=get_base_url())
        resp = await client.chat.completions.create(
            model=model, temperature=0,
            response_format={"type": "json_object"},
            extra_body={"enable_thinking": False},
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": prompt},
            ]}],
        )
        r.total_ms = (time.perf_counter() - t0) * 1000
        r.got_headers = True
        r.http_status = 200
        r.request_id = getattr(resp, "request_id", "") or ""
        if resp.choices and resp.choices[0].message.content:
            content = resp.choices[0].message.content
            r.got_content = True
            r.content_chars = len(content)
            try:
                r.marker_correct = json.loads(content).get("marker") == "VISION-7319"
            except Exception:
                pass
            r.success = True
    except Exception as e:
        r.total_ms = (time.perf_counter() - t0) * 1000
        r.exception_class = type(e).__name__
        r.exception_repr = repr(e)[:200]
        if e.__cause__:
            r.exception_cause = repr(e.__cause__)[:200]
    return r


# === curl probe ===

async def probe_curl(test_id: str, attempt: int, image_bytes: bytes, prompt: str,
                     model: str = "qwen3.7-plus", mime: str | None = None) -> ProbeResult:
    api_key = get_api_key()
    url = f"{get_base_url().rstrip('/')}/chat/completions"
    if mime is None:
        mime = detect_mime(image_bytes)
    body = build_body(image_to_data_url(image_bytes, mime), prompt, model)
    r = ProbeResult(test_id=test_id, attempt=attempt, client="curl",
                    image_bytes=len(image_bytes),
                    request_body_bytes=len(json.dumps(body).encode()))
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(body, f, ensure_ascii=False)
        body_file = f.name
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            ["curl.exe", "-s", "-w", "\n%{http_code}", "-X", "POST", url,
             "-H", f"Authorization: Bearer {api_key}",
             "-H", "Content-Type: application/json",
             "-d", f"@{body_file}",
             "--connect-timeout", "30", "--max-time", "300"],
            capture_output=True, text=True, timeout=310)
        r.total_ms = (time.perf_counter() - t0) * 1000
        lines = proc.stdout.strip().split("\n")
        if len(lines) >= 2:
            body_text = "\n".join(lines[:-1])
            code_str = lines[-1].strip()
            r.http_status = int(code_str) if code_str.isdigit() else None
            r.got_headers = r.http_status is not None
            if body_text:
                try:
                    rj = json.loads(body_text)
                    r.request_id = rj.get("request_id", "")
                    choices = rj.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "")
                        if content:
                            r.got_content = True
                            r.content_chars = len(content)
                            try:
                                r.marker_correct = json.loads(content).get("marker") == "VISION-7319"
                            except Exception:
                                pass
                            r.success = r.http_status == 200
                except json.JSONDecodeError:
                    r.exception_repr = f"not JSON: {body_text[:80]}"
        if proc.returncode != 0 and not r.success:
            r.exception_class = f"curl_exit_{proc.returncode}"
            if proc.stderr:
                r.exception_repr = proc.stderr[:200]
    except subprocess.TimeoutExpired:
        r.total_ms = (time.perf_counter() - t0) * 1000
        r.exception_class = "TimeoutExpired"
    except Exception as e:
        r.total_ms = (time.perf_counter() - t0) * 1000
        r.exception_class = type(e).__name__
        r.exception_repr = repr(e)[:200]
    finally:
        os.unlink(body_file)
    return r


# === Phase 2: Small probe ===

async def run_small_probe(attempts: int = 3) -> list[ProbeResult]:
    small_img = make_small_probe_image()
    configs = [("A1", True, False), ("A2", False, False), ("A3", True, True), ("A4", False, True)]
    results = []
    for tid, te, h2 in configs:
        print(f"  [{tid}] trust_env={te} http2={h2} ...")
        for att in range(1, attempts + 1):
            r = await probe_httpx(tid, att, small_img, SMALL_PROMPT, trust_env=te, http2=h2)
            s = "OK" if r.success else f"FAIL:{r.exception_class}"
            print(f"    #{att}: {r.total_ms:.0f}ms {s}")
            results.append(r)
    return results


# === Phase 3: Client matrix ===

async def run_client_matrix(attempts: int = 3) -> list[ProbeResult]:
    small_img = make_small_probe_image()
    results = []
    for tid, fn, kw in [
        ("B1", probe_httpx, {"trust_env": True, "http2": False}),
        ("B2", probe_openai_sdk, {}),
        ("B3", probe_curl, {}),
    ]:
        print(f"  [{tid}] {kw.get('client', tid)} ...")
        for att in range(1, attempts + 1):
            r = await fn(tid, att, small_img, SMALL_PROMPT, **kw)
            s = "OK" if r.success else f"FAIL:{r.exception_class}"
            print(f"    #{att}: {r.total_ms:.0f}ms {s}")
            results.append(r)
    return results


# === Phase 4: Real minimal ===

async def run_real_minimal(image_path: Path, attempts: int = 3) -> list[ProbeResult]:
    image_bytes = image_path.read_bytes()
    mime = detect_mime(image_bytes)
    sha = hashlib.sha256(image_bytes).hexdigest().upper()
    print(f"  Image: {image_path.name} ({len(image_bytes)} bytes, {mime})")
    print(f"  SHA-256: {sha}")
    results = []
    for tid, fn, kw in [
        ("C1", probe_httpx, {"trust_env": True, "http2": False}),
        ("C2", probe_openai_sdk, {}),
        ("C3", probe_curl, {}),
    ]:
        print(f"  [{tid}] ...")
        for att in range(1, attempts + 1):
            r = await fn(tid, att, image_bytes, REAL_PROMPT, **kw)
            s = "OK" if r.success else f"FAIL:{r.exception_class}"
            print(f"    #{att}: {r.total_ms:.0f}ms {s}")
            results.append(r)
    return results


# === Phase 6: Size ladder ===

async def run_size_ladder(image_path: Path, attempts: int = 1) -> list[ProbeResult]:
    from PIL import Image
    original = image_path.read_bytes()
    img = Image.open(io.BytesIO(original))
    ow, oh = img.size
    results = []
    for tid, max_side in [("E1", 512), ("E2", 1024), ("E3", 1600), ("E4", None)]:
        if max_side and max(ow, oh) > max_side:
            ratio = max_side / max(ow, oh)
            resized = img.resize((int(ow * ratio), int(oh * ratio)), Image.LANCZOS)
        else:
            resized = img
        buf = io.BytesIO()
        resized.save(buf, format="JPEG", quality=90)
        img_bytes = buf.getvalue()
        body = build_body(image_to_data_url(img_bytes), REAL_PROMPT)
        body_bytes = len(json.dumps(body).encode())
        w, h = resized.size
        print(f"  [{tid}] {w}x{h} file={len(img_bytes)}B body={body_bytes}B")
        for att in range(1, attempts + 1):
            r = await probe_httpx(tid, att, img_bytes, REAL_PROMPT, trust_env=True, http2=False)
            s = "OK" if r.success else f"FAIL:{r.exception_class}"
            print(f"    #{att}: {r.total_ms:.0f}ms {s}")
            results.append(r)
    return results


# === Save ===

def save_results(results: list[ProbeResult], env: dict, mode: str) -> Path:
    out_dir = Path(__file__).resolve().parent.parent / "data" / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out_file = out_dir / f"transport_{mode}_{ts}.json"
    data = {"mode": mode, "timestamp": ts, "key_info": mask_key(get_api_key()),
            "environment": env, "results": [asdict(r) for r in results],
            "summary": {"total": len(results), "success": sum(1 for r in results if r.success),
                        "failed": sum(1 for r in results if not r.success)}}
    out_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_file


# === Main ===

async def main():
    parser = argparse.ArgumentParser(description="Qwen Transport Matrix Diagnostic")
    parser.add_argument("--mode", required=True, choices=["env", "small-probe", "client-matrix", "real-minimal", "size-ladder", "full-prompt"])
    parser.add_argument("--image", type=str)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--base-url", type=str)
    parser.add_argument("--model", type=str, default="qwen3.7-plus")
    args = parser.parse_args()

    if args.base_url:
        os.environ["QWEN_TEST_BASE_URL"] = args.base_url

    if args.mode != "env":
        api_key = get_api_key()
        print(f"API Key: {mask_key(api_key)}")
    else:
        k = os.environ.get("QWEN_TEST_API_KEY", "")
        print(f"API Key: {mask_key(k) if k else 'NOT_SET'}")
    print(f"Base URL: {get_base_url()}")
    print(f"Model: {args.model}\n")

    print("=== Phase 1: Environment ===")
    env = investigate_environment()
    for k, v in env.items():
        if k not in ("versions", "dns"):
            print(f"  {k}: {v}")
    print(f"  versions: {json.dumps(env['versions'])}")
    print(f"  dns: {json.dumps(env['dns'])}\n")

    results: list[ProbeResult] = []

    if args.mode == "small-probe":
        print("=== Phase 2: Small Probe ===")
        results = await run_small_probe(args.attempts)
    elif args.mode == "client-matrix":
        print("=== Phase 3: Client Matrix ===")
        results = await run_client_matrix(args.attempts)
    elif args.mode == "real-minimal":
        if not args.image:
            print("ERROR: --image required"); sys.exit(1)
        p = Path(args.image)
        if not p.exists():
            print(f"ERROR: {p} not found"); sys.exit(1)
        print("=== Phase 4: Real Minimal ===")
        results = await run_real_minimal(p, args.attempts)
    elif args.mode == "size-ladder":
        if not args.image:
            print("ERROR: --image required"); sys.exit(1)
        p = Path(args.image)
        if not p.exists():
            print(f"ERROR: {p} not found"); sys.exit(1)
        print("=== Phase 6: Size Ladder ===")
        results = await run_size_ladder(p, args.attempts)

    if results:
        out = save_results(results, env, args.mode)
        print(f"\nResults saved: {out}")
        succ = sum(1 for r in results if r.success)
        print(f"\n=== Summary: {succ}/{len(results)} success ===")
        excs = [r.exception_class for r in results if r.exception_class]
        if excs:
            from collections import Counter
            print(f"  Exceptions: {dict(Counter(excs))}")


if __name__ == "__main__":
    asyncio.run(main())
