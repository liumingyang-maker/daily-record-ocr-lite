"""Qwen Transport Matrix 诊断脚本。

用法:
    python scripts/diagnose_qwen_transport.py --mode small-probe
    python scripts/diagnose_qwen_transport.py --mode real-minimal --image <path>
    python scripts/diagnose_qwen_transport.py --mode size-ladder --image <path>
    python scripts/diagnose_qwen_transport.py --mode client-matrix --image <path>
    python scripts/diagnose_qwen_transport.py --mode full-prompt --image <path>

环境变量:
    QWEN_TEST_API_KEY   - 必需，API Key (sk-ws...)
    QWEN_TEST_BASE_URL  - 可选，默认 https://dashscope.aliyuncs.com/compatible-mode/v1
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

# ─── 安全约束 ──────────────────────────────────────────────────────────────────

def get_api_key() -> str:
    key = os.environ.get("QWEN_TEST_API_KEY", "")
    if not key:
        print("错误: 环境变量 QWEN_TEST_API_KEY 未设置。")
        print("请设置: set QWEN_TEST_API_KEY=sk-ws...")
        sys.exit(1)
    return key


def mask_key(key: str) -> str:
    if len(key) >= 8:
        return f"key_prefix={key[:5]}"
    return "key_prefix=???"


def get_base_url() -> str:
    return os.environ.get(
        "QWEN_TEST_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )


# ─── 数据结构 ──────────────────────────────────────────────────────────────────

@dataclass
class ProbeResult:
    test_id: str = ""
    attempt: int = 0
    client: str = "httpx"
    trust_env: bool = True
    http2: bool = False
    image_bytes: int = 0
    request_body_bytes: int = 0
    dns_ms: float | None = None
    connect_ms: float | None = None
    total_ms: float = 0.0
    got_headers: bool = False
    http_status: int | None = None
    got_content: bool = False
    content_chars: int = 0
    marker_correct: bool | None = None
    exception_class: str = ""
    exception_repr: str = ""
    exception_cause: str = ""
    exception_context: str = ""
    request_id: str = ""
    resp_server: str = ""
    resp_date: str = ""
    resp_content_type: str = ""
    tls_version: str = ""
    success: bool = False


# ─── 第一阶段：环境调查 ─────────────────────────────────────────────────────────

def investigate_environment() -> dict[str, Any]:
    """记录环境变量存在性和版本信息（不记录具体值）。"""
    env_vars = [
        "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
    ]
    env_present = {}
    for var in env_vars:
        env_present[f"{var}_PRESENT"] = bool(os.environ.get(var))

    # Python 和库版本
    versions: dict[str, str] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    try:
        import httpx
        versions["httpx"] = httpx.__version__
    except ImportError:
        versions["httpx"] = "NOT_INSTALLED"
    try:
        import httpcore
        versions["httpcore"] = httpcore.__version__
    except ImportError:
        versions["httpcore"] = "NOT_INSTALLED"
    try:
        import openai
        versions["openai_sdk"] = openai.__version__
    except ImportError:
        versions["openai_sdk"] = "NOT_INSTALLED"

    versions["openssl"] = ssl.OPENSSL_VERSION

    # DNS 解析
    base_url = get_base_url()
    from urllib.parse import urlparse
    hostname = urlparse(base_url).hostname or "dashscope.aliyuncs.com"
    try:
        t0 = time.perf_counter()
        ips = socket.getaddrinfo(hostname, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
        dns_ms = (time.perf_counter() - t0) * 1000
        unique_ips = list({addr[4][0] for addr in ips})
        dns_info = {"hostname": hostname, "ip_count": len(unique_ips), "dns_ms": round(dns_ms, 1)}
    except Exception as e:
        dns_info = {"hostname": hostname, "error": str(e)}

    # 系统代理检测 (Windows)
    system_proxy = False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings",
        )
        proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
        system_proxy = bool(proxy_enable)
        winreg.CloseKey(key)
    except Exception:
        pass

    return {
        **env_present,
        "versions": versions,
        "dns": dns_info,
        "system_proxy_detected": system_proxy,
        "base_url": base_url,
    }


# ─── 小图生成 ──────────────────────────────────────────────────────────────────

def make_small_probe_image() -> bytes:
    """生成 10x10 红色 JPEG 小图。"""
    from PIL import Image
    img = Image.new("RGB", (10, 10), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def image_to_data_url(image_bytes: bytes, mime: str = "image/jpeg") -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{mime};base64,{b64}"


def detect_mime(image_bytes: bytes) -> str:
    """根据文件头检测实际 MIME。"""
    if image_bytes[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    if image_bytes[:2] == b'\xff\xd8':
        return "image/jpeg"
    if image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
        return "image/webp"
    return "image/jpeg"  # 默认


# ─── 请求体构建 ─────────────────────────────────────────────────────────────────

def build_request_body(
    data_url: str,
    prompt: str,
    model: str = "qwen3.7-plus",
) -> dict[str, Any]:
    return {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "enable_thinking": False,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }


SMALL_PROMPT = 'Return only valid JSON:\n{"marker":"VISION-7319"}'

REAL_MINIMAL_PROMPT = """请查看图片并仅返回有效JSON：

{
  "image_received": true,
  "has_visible_text": true,
  "summary": "不超过30个汉字"
}"""


# ─── HTTPX 探测 ─────────────────────────────────────────────────────────────────

async def probe_httpx(
    test_id: str,
    attempt: int,
    image_bytes: bytes,
    prompt: str,
    trust_env: bool = True,
    http2: bool = False,
    model: str = "qwen3.7-plus",
    mime: str | None = None,
) -> ProbeResult:
    """执行单次 HTTPX 探测。"""
    import httpx

    api_key = get_api_key()
    base_url = get_base_url()
    url = f"{base_url.rstrip('/')}/chat/completions"

    if mime is None:
        mime = detect_mime(image_bytes)
    data_url = image_to_data_url(image_bytes, mime)
    body = build_request_body(data_url, prompt, model)
    body_bytes = len(json.dumps(body).encode("utf-8"))

    result = ProbeResult(
        test_id=test_id,
        attempt=attempt,
        client="httpx",
        trust_env=trust_env,
        http2=http2,
        image_bytes=len(image_bytes),
        request_body_bytes=body_bytes,
    )

    timeout = httpx.Timeout(connect=30.0, read=300.0, write=60.0, pool=30.0)

    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            trust_env=trust_env,
            http2=http2,
        ) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            result.total_ms = (time.perf_counter() - t0) * 1000
            result.got_headers = True
            result.http_status = resp.status_code
            result.resp_server = resp.headers.get("server", "")
            result.resp_date = resp.headers.get("date", "")
            result.resp_content_type = resp.headers.get("content-type", "")
            result.request_id = resp.headers.get("x-request-id", "")

            resp_json = resp.json()
            if not result.request_id:
                result.request_id = resp_json.get("request_id", "")

            choices = resp_json.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                if content:
                    result.got_content = True
                    result.content_chars = len(content)
                    # 检查 marker
                    try:
                        parsed = json.loads(content)
                        if parsed.get("marker") == "VISION-7319":
                            result.marker_correct = True
                        else:
                            result.marker_correct = False
                    except (json.JSONDecodeError, AttributeError):
                        result.marker_correct = None

            result.success = (
                resp.status_code == 200
                and result.got_content
            )

    except httpx.ConnectTimeout as e:
        result.total_ms = (time.perf_counter() - t0) * 1000
        result.exception_class = "httpx.ConnectTimeout"
        result.exception_repr = repr(e)[:200]
    except httpx.ReadTimeout as e:
        result.total_ms = (time.perf_counter() - t0) * 1000
        result.exception_class = "httpx.ReadTimeout"
        result.exception_repr = repr(e)[:200]
    except httpx.WriteTimeout as e:
        result.total_ms = (time.perf_counter() - t0) * 1000
        result.exception_class = "httpx.WriteTimeout"
        result.exception_repr = repr(e)[:200]
    except httpx.RemoteProtocolError as e:
        result.total_ms = (time.perf_counter() - t0) * 1000
        result.exception_class = "httpx.RemoteProtocolError"
        result.exception_repr = repr(e)[:200]
        if e.__cause__:
            result.exception_cause = repr(e.__cause__)[:200]
        if e.__context__:
            result.exception_context = repr(e.__context__)[:200]
    except httpx.ConnectError as e:
        result.total_ms = (time.perf_counter() - t0) * 1000
        result.exception_class = "httpx.ConnectError"
        result.exception_repr = repr(e)[:200]
    except httpx.ProxyError as e:
        result.total_ms = (time.perf_counter() - t0) * 1000
        result.exception_class = "httpx.ProxyError"
        result.exception_repr = repr(e)[:200]
    except httpx.NetworkError as e:
        result.total_ms = (time.perf_counter() - t0) * 1000
        result.exception_class = "httpx.NetworkError"
        result.exception_repr = repr(e)[:200]
    except ssl.SSLError as e:
        result.total_ms = (time.perf_counter() - t0) * 1000
        result.exception_class = "ssl.SSLError"
        result.exception_repr = repr(e)[:200]
    except Exception as e:
        result.total_ms = (time.perf_counter() - t0) * 1000
        result.exception_class = type(e).__name__
        result.exception_repr = repr(e)[:200]
        if e.__cause__:
            result.exception_cause = repr(e.__cause__)[:200]

    return result


# ─── OpenAI SDK 探测 ────────────────────────────────────────────────────────────

async def probe_openai_sdk(
    test_id: str,
    attempt: int,
    image_bytes: bytes,
    prompt: str,
    model: str = "qwen3.7-plus",
    mime: str | None = None,
) -> ProbeResult:
    """使用 OpenAI 官方 SDK 探测。"""
    api_key = get_api_key()
    base_url = get_base_url()

    if mime is None:
        mime = detect_mime(image_bytes)
    data_url = image_to_data_url(image_bytes, mime)

    result = ProbeResult(
        test_id=test_id,
        attempt=attempt,
        client="openai_sdk",
        image_bytes=len(image_bytes),
    )

    try:
        from openai import AsyncOpenAI
    except ImportError:
        result.exception_class = "ImportError"
        result.exception_repr = "openai SDK not installed"
        return result

    t0 = time.perf_counter()
    try:
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        resp = await client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            extra_body={"enable_thinking": False},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        result.total_ms = (time.perf_counter() - t0) * 1000
        result.got_headers = True
        result.http_status = 200
        result.request_id = getattr(resp, "request_id", "") or ""

        if resp.choices and resp.choices[0].message.content:
            content = resp.choices[0].message.content
            result.got_content = True
            result.content_chars = len(content)
            try:
                parsed = json.loads(content)
                result.marker_correct = parsed.get("marker") == "VISION-7319"
            except (json.JSONDecodeError, AttributeError):
                result.marker_correct = None
            result.success = True

    except Exception as e:
        result.total_ms = (time.perf_counter() - t0) * 1000
        result.exception_class = type(e).__name__
        result.exception_repr = repr(e)[:200]
        if e.__cause__:
            result.exception_cause = repr(e.__cause__)[:200]

    return result


# ─── curl 探测 ──────────────────────────────────────────────────────────────────

async def probe_curl(
    test_id: str,
    attempt: int,
    image_bytes: bytes,
    prompt: str,
    model: str = "qwen3.7-plus",
    mime: str | None = None,
) -> ProbeResult:
    """使用 Windows 原生 curl.exe 探测。"""
    api_key = get_api_key()
    base_url = get_base_url()
    url = f"{base_url.rstrip('/')}/chat/completions"

    if mime is None:
        mime = detect_mime(image_bytes)
    data_url = image_to_data_url(image_bytes, mime)
    body = build_request_body(data_url, prompt, model)

    result = ProbeResult(
        test_id=test_id,
        attempt=attempt,
        client="curl",
        image_bytes=len(image_bytes),
        request_body_bytes=len(json.dumps(body).encode("utf-8")),
    )

    # 写入临时文件避免命令行长度限制
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(body, f, ensure_ascii=False)
        body_file = f.name

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [
                "curl.exe", "-s", "-w", "\n%{http_code}\n%{time_total}",
                "-X", "POST", url,
                "-H", f"Authorization: Bearer {api_key}",
                "-H", "Content-Type: application/json",
                "-d", f"@{body_file}",
                "--connect-timeout", "30",
                "--max-time", "300",
            ],
            capture_output=True,
            text=True,
            timeout=310,
        )
        result.total_ms = (time.perf_counter() - t0) * 1000

        output_lines = proc.stdout.strip().split("\n")
        if len(output_lines) >= 3:
            body_text = "\n".join(output_lines[:-2])
            result.http_status = int(output_lines[-2]) if output_lines[-2].isdigit() else None
            result.got_headers = result.http_status is not None

            if body_text:
                try:
                    resp_json = json.loads(body_text)
                    result.request_id = resp_json.get("request_id", "")
                    choices = resp_json.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "")
                        if content:
                            result.got_content = True
                            result.content_chars = len(content)
                            try:
                                parsed = json.loads(content)
                                result.marker_correct = parsed.get("marker") == "VISION-7319"
                            except (json.JSONDecodeError, AttributeError):
                                pass
                            result.success = result.http_status == 200
                except json.JSONDecodeError:
                    result.exception_repr = f"curl output not JSON: {body_text[:100]}"
        else:
            result.exception_repr = f"curl unexpected output: {proc.stdout[:100]}"

        if proc.returncode != 0 and not result.success:
            result.exception_class = f"curl_exit_{proc.returncode}"
            if proc.stderr:
                result.exception_repr = proc.stderr[:200]

    except subprocess.TimeoutExpired:
        result.total_ms = (time.perf_counter() - t0) * 1000
        result.exception_class = "subprocess.TimeoutExpired"
    except Exception as e:
        result.total_ms = (time.perf_counter() - t0) * 1000
        result.exception_class = type(e).__name__
        result.exception_repr = repr(e)[:200]
    finally:
        os.unlink(body_file)

    return result


# ─── 第二阶段：小图稳定性基线 ────────────────────────────────────────────────────

async def run_small_probe(attempts: int = 3) -> list[ProbeResult]:
    """A1-A4: HTTPX 小图探针矩阵。"""
    small_img = make_small_probe_image()
    configs = [
        ("A1", True, False),
        ("A2", False, False),
        ("A3", True, True),
        ("A4", False, True),
    ]
    results = []
    for test_id, trust_env, http2 in configs:
        print(f"  [{test_id}] trust_env={trust_env} http2={http2} ...")
        for attempt in range(1, attempts + 1):
            r = await probe_httpx(
                test_id=test_id,
                attempt=attempt,
                image_bytes=small_img,
                prompt=SMALL_PROMPT,
                trust_env=trust_env,
                http2=http2,
            )
            status = "✓" if r.success else f"✗ {r.exception_class}"
            print(f"    attempt {attempt}: {r.total_ms:.0f}ms {status}")
            results.append(r)
    return results


# ─── 第三阶段：客户端对照 ────────────────────────────────────────────────────────

async def run_client_matrix(attempts: int = 3) -> list[ProbeResult]:
    """B1-B4: 不同客户端对照。"""
    small_img = make_small_probe_image()
    results = []

    # B1: 现有 HTTPX Provider (trust_env=True, http2=False)
    print("  [B1] HTTPX Provider ...")
    for attempt in range(1, attempts + 1):
        r = await probe_httpx("B1", attempt, small_img, SMALL_PROMPT, trust_env=True, http2=False)
        print(f"    attempt {attempt}: {r.total_ms:.0f}ms {'✓' if r.success else '✗ ' + r.exception_class}")
        results.append(r)

    # B2: OpenAI SDK
    print("  [B2] OpenAI SDK ...")
    for attempt in range(1, attempts + 1):
        r = await probe_openai_sdk("B2", attempt, small_img, SMALL_PROMPT)
        print(f"    attempt {attempt}: {r.total_ms:.0f}ms {'✓' if r.success else '✗ ' + r.exception_class}")
        results.append(r)

    # B3: curl
    print("  [B3] curl.exe ...")
    for attempt in range(1, attempts + 1):
        r = await probe_curl("B3", attempt, small_img, SMALL_PROMPT)
        print(f"    attempt {attempt}: {r.total_ms:.0f}ms {'✓' if r.success else '✗ ' + r.exception_class}")
        results.append(r)

    return results


# ─── 第四阶段：真实图片最小请求 ──────────────────────────────────────────────────

async def run_real_minimal(image_path: Path, attempts: int = 3) -> list[ProbeResult]:
    """C1-C3: 真实图片 + 极简 Prompt。"""
    image_bytes = image_path.read_bytes()
    actual_mime = detect_mime(image_bytes)
    sha256 = hashlib.sha256(image_bytes).hexdigest().upper()
    print(f"  图片: {image_path.name} ({len(image_bytes)} bytes, {actual_mime})")
    print(f"  SHA-256: {sha256}")

    results = []

    # C1: 最佳 HTTPX 组合
    print("  [C1] HTTPX (trust_env=True, http2=False) ...")
    for attempt in range(1, attempts + 1):
        r = await probe_httpx("C1", attempt, image_bytes, REAL_MINIMAL_PROMPT, trust_env=True, http2=False)
        print(f"    attempt {attempt}: {r.total_ms:.0f}ms {'✓' if r.success else '✗ ' + r.exception_class}")
        results.append(r)

    # C2: OpenAI SDK
    print("  [C2] OpenAI SDK ...")
    for attempt in range(1, attempts + 1):
        r = await probe_openai_sdk("C2", attempt, image_bytes, REAL_MINIMAL_PROMPT)
        print(f"    attempt {attempt}: {r.total_ms:.0f}ms {'✓' if r.success else '✗ ' + r.exception_class}")
        results.append(r)

    # C3: curl
    print("  [C3] curl.exe ...")
    for attempt in range(1, attempts + 1):
        r = await probe_curl("C3", attempt, image_bytes, REAL_MINIMAL_PROMPT)
        print(f"    attempt {attempt}: {r.total_ms:.0f}ms {'✓' if r.success else '✗ ' + r.exception_class}")
        results.append(r)

    return results


# ─── 第六阶段：请求体大小阶梯 ────────────────────────────────────────────────────

async def run_size_ladder(image_path: Path, attempts: int = 1) -> list[ProbeResult]:
    """E1-E4: 不同尺寸图片测试。"""
    from PIL import Image

    original_bytes = image_path.read_bytes()
    img = Image.open(io.BytesIO(original_bytes))
    orig_w, orig_h = img.size

    sizes = [
        ("E1", 512),
        ("E2", 1024),
        ("E3", 1600),
        ("E4", None),  # 原始
    ]

    results = []
    for test_id, max_side in sizes:
        if max_side and max(orig_w, orig_h) > max_side:
            ratio = max_side / max(orig_w, orig_h)
            new_w, new_h = int(orig_w * ratio), int(orig_h * ratio)
            resized = img.resize((new_w, new_h), Image.LANCZOS)
        else:
            resized = img
            new_w, new_h = orig_w, orig_h

        buf = io.BytesIO()
        resized.save(buf, format="JPEG", quality=90)
        img_bytes = buf.getvalue()
        b64_len = len(base64.b64encode(img_bytes))
        body = build_request_body(image_to_data_url(img_bytes), REAL_MINIMAL_PROMPT)
        body_bytes = len(json.dumps(body).encode("utf-8"))

        print(f"  [{test_id}] {new_w}x{new_h} | file={len(img_bytes)}B | b64={b64_len} | body={body_bytes}B")

        for attempt in range(1, attempts + 1):
            r = await probe_httpx(test_id, attempt, img_bytes, REAL_MINIMAL_PROMPT, trust_env=True, http2=False)
            print(f"    attempt {attempt}: {r.total_ms:.0f}ms {'✓' if r.success else '✗ ' + r.exception_class}")
            results.append(r)

    return results


# ─── 结果保存 ────────────────────────────────────────────────────────────────────

def save_results(results: list[ProbeResult], env_info: dict, mode: str) -> Path:
    """保存结果到 data/diagnostics/ (gitignored)。"""
    output_dir = Path(__file__).resolve().parent.parent / "data" / "diagnostics"
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    output_file = output_dir / f"transport_matrix_{mode}_{timestamp}.json"

    data = {
        "mode": mode,
        "timestamp": timestamp,
        "key_info": mask_key(get_api_key()),
        "environment": env_info,
        "results": [asdict(r) for r in results],
        "summary": {
            "total": len(results),
            "success": sum(1 for r in results if r.success),
            "failed": sum(1 for r in results if not r.success),
        },
    }

    output_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_file


# ─── 主入口 ──────────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Qwen Transport Matrix 诊断")
    parser.add_argument("--mode", required=True,
                        choices=["env", "small-probe", "client-matrix", "real-minimal",
                                 "size-ladder", "full-prompt"],
                        help="诊断模式")
    parser.add_argument("--image", type=str, help="真实图片路径")
    parser.add_argument("--attempts", type=int, default=3, help="每组尝试次数")
    parser.add_argument("--base-url", type=str, help="覆盖 Base URL")
    parser.add_argument("--model", type=str, default="qwen3.7-plus", help="模型名")
    args = parser.parse_args()

    if args.base_url:
        os.environ["QWEN_TEST_BASE_URL"] = args.base_url

    # 验证 API Key（env 模式除外）
    if args.mode != "env":
        api_key = get_api_key()
        print(f"API Key: {mask_key(api_key)}")
    else:
        api_key = os.environ.get("QWEN_TEST_API_KEY", "")
        if api_key:
            print(f"API Key: {mask_key(api_key)}")
        else:
            print("API Key: NOT_SET (env mode does not require it)")
    print(f"Base URL: {get_base_url()}")
    print(f"Model: {args.model}")
    print()

    # 环境调查（始终执行）
    print("═══ 第一阶段：环境调查 ═══")
    env_info = investigate_environment()
    for k, v in env_info.items():
        if k != "versions" and k != "dns":
            print(f"  {k}: {v}")
    print(f"  versions: {json.dumps(env_info['versions'], indent=4)}")
    print(f"  dns: {json.dumps(env_info['dns'])}")
    print()

    results: list[ProbeResult] = []

    if args.mode == "env":
        pass  # 仅环境调查

    elif args.mode == "small-probe":
        print("═══ 第二阶段：小图稳定性基线 ═══")
        results = await run_small_probe(args.attempts)

    elif args.mode == "client-matrix":
        print("═══ 第三阶段：客户端对照 ═══")
        results = await run_client_matrix(args.attempts)

    elif args.mode == "real-minimal":
        if not args.image:
            print("错误: --image 参数必需")
            sys.exit(1)
        image_path = Path(args.image)
        if not image_path.exists():
            print(f"错误: 图片不存在: {image_path}")
            sys.exit(1)
        print("═══ 第四阶段：真实图片最小请求 ═══")
        results = await run_real_minimal(image_path, args.attempts)

    elif args.mode == "size-ladder":
        if not args.image:
            print("错误: --image 参数必需")
            sys.exit(1)
        image_path = Path(args.image)
        if not image_path.exists():
            print(f"错误: 图片不存在: {image_path}")
            sys.exit(1)
        print("═══ 第六阶段：请求体大小阶梯 ═══")
        results = await run_size_ladder(image_path, args.attempts)

    elif args.mode == "full-prompt":
        print("═══ 第八阶段：完整业务 Prompt ═══")
        print("  (需要前置阶段全部通过后手动执行)")

    # 保存结果
    if results:
        output = save_results(results, env_info, args.mode)
        print(f"\n结果已保存: {output}")

        # 汇总
        success = sum(1 for r in results if r.success)
        total = len(results)
        print(f"\n═══ 汇总: {success}/{total} 成功 ═══")
        exceptions = [r.exception_class for r in results if r.exception_class]
        if exceptions:
            from collections import Counter
            print(f"  异常分布: {dict(Counter(exceptions))}")


if __name__ == "__main__":
    asyncio.run(main())
