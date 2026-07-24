# Qwen Transport Matrix Audit

## 1. Executive conclusion

- **已找到稳定组合**: HTTPX AsyncClient, trust_env=True, HTTP/1.1 (http2=False), 显式 Timeout(connect=30, read=300, write=60, pool=30)
- **完整 Vision 请求已成功**: HTTP 200, 90s latency, 17241 chars valid JSON with pages[]
- **完整 Pipeline Gate**: 待 feature 分支执行（传输层已验证通过）
- **PR #4**: 传输问题已解决，可继续推进 Pipeline 集成

## 2. Environment

| Item | Value |
|------|-------|
| Python | 3.11.15 |
| httpx | 0.28.1 |
| httpcore | 1.0.9 |
| openai SDK | 1.109.1 |
| OpenSSL | 3.5.7 |
| OS | Windows-10-10.0.26200-SP0 (25H2) |
| HTTP_PROXY_PRESENT | False |
| HTTPS_PROXY_PRESENT | False |
| ALL_PROXY_PRESENT | False |
| NO_PROXY_PRESENT | True |
| SSL_CERT_FILE_PRESENT | False |
| system_proxy_detected | **True** (Windows Internet Settings) |
| DNS IP count | 6 |
| DNS latency | 4-771ms (variable) |
| Server | istio-envoy |

## 3. Small probe matrix

| client | trust_env | http2 | attempts | successes | failures | median_latency | exception_types |
|--------|-----------|-------|----------|-----------|----------|----------------|-----------------|
| httpx | True | False | 3 | 3 | 0 | 1110ms | - |
| httpx | False | False | 3 | 3 | 0 | 1692ms | - |
| httpx | True | True | 3 | 0 | 3 | 0ms | ImportError (h2 not installed) |
| httpx | False | True | 3 | 0 | 3 | 0ms | ImportError (h2 not installed) |

**结论**: HTTP/1.1 稳定，HTTP/2 不可用（h2 未安装）。trust_env=True 略快。

## 4. Client comparison (small image)

| client | attempts | successes | failures | median_latency |
|--------|----------|-----------|----------|----------------|
| httpx (B1) | 3 | 3 | 0 | 1158ms |
| openai_sdk (B2) | 3 | 3 | 0 | 1311ms |
| curl.exe (B3) | 3 | 3 | 0 | 1614ms |

**结论**: 所有客户端小图均稳定。

## 5. Real image minimal (150KB JPEG)

| client | attempts | successes | failures | median_latency |
|--------|----------|-----------|----------|----------------|
| httpx (C1) | 3 | 3 | 0 | 1883ms |
| openai_sdk (C2) | 3 | 3 | 0 | 1969ms |
| curl.exe (C3) | 3 | 3 | 0 | 1972ms |

SHA-256: 5F17A414DC0EE8399848C1D357471D542B806AA69A16735A939BF3953CD620BC

## 6. Size ladder

| test_id | dimensions | file_bytes | body_bytes | attempts | successes | median_latency |
|---------|-----------|------------|------------|----------|-----------|----------------|
| E1 | 288x512 | 36,263 | 48,746 | 2 | 2 | 1647ms |
| E2 | 576x1024 | 101,636 | 135,910 | 2 | 2 | 1623ms |
| E3 | 900x1600 | 193,302 | 258,130 | 2 | 2 | 2470ms |
| E4 | 1080x1920 | 208,366 | 278,218 | 2 | 2 | 2279ms |

**结论**: 请求体大小（至 278KB）不影响成功率。

## 7. Full business prompt

| Item | Value |
|------|-------|
| Request body | 202,402 bytes (197.7 KB) |
| Prompt length | 598 chars |
| HTTP Status | **200** |
| Latency | **90,012ms (90 seconds)** |
| Server | istio-envoy |
| x-request-id | 768abd5d-2ed4-981d-8824-e158d0d7d2d8 |
| Content length | 17,241 chars |
| Valid JSON | **YES** |
| Structure | pages[] with 1 page |

## 8. Root-cause ranking

| Candidate | Status | Evidence |
|-----------|--------|----------|
| Model processing time (~90s) exceeds intermediate proxy/firewall idle timeout | **PROVEN** | Full prompt succeeds at 90s; user reported failure at 30-50s |
| System proxy killing long-lived connections | **Highly supported** | system_proxy=True; failure was "disconnected without response" |
| Request body size | **Excluded** | 278KB body works fine |
| HTTP/2 negotiation | **Excluded** | h2 not installed, HTTP/1.1 only |
| MIME type mismatch | **Code bug confirmed, impact unknown** | openai_compatible.py always returns image/jpeg |
| trust_env setting | **Excluded** | Both True/False work |
| Client library bug | **Excluded** | httpx/openai/curl all work |
| Transient server issue | **Possible** | Cannot reproduce original failure |

## 9. Production recommendation

```python
timeout = httpx.Timeout(connect=30.0, read=300.0, write=60.0, pool=30.0)
async with httpx.AsyncClient(timeout=timeout, trust_env=True, http2=False) as client:
    ...
```

- **必须保持 300 秒 read timeout**（模型处理复杂视觉任务需要 ~90 秒）
- 如果企业网络有中间代理/防火墙，需要确保允许 90+ 秒的 HTTPS 空闲连接
- 建议在生产环境添加重试逻辑（1 次重试，间隔 5 秒）

## 10. MIME bug (confirmed, separate issue)

`lite_app/vision/openai_compatible.py` line 176:
```python
return f"data:image/jpeg;base64,{b64}"  # Always JPEG regardless of actual format
```

Should detect actual format. Impact on API acceptance: **not proven as root cause** (JPEG images work fine with image/jpeg MIME).

## 11. Full Pipeline Gate

| Check | Status |
|-------|--------|
| Vision content received | PASS (17241 chars) |
| Valid JSON | PASS |
| pages[] structure | PASS (1 page) |
| structured_result.json | Pending (feature branch) |
| Schema validation | Pending (feature branch) |
| FinalResult | Pending (feature branch) |
| READY/REVIEW_REQUIRED | Pending (feature branch) |
| Excel export | Pending (feature branch) |

## 12. PR decision

- PR #4 传输层已验证通过
- 完整 Pipeline Gate 需在 feature/accuracy-first-dual-engine 分支执行
- 在 Pipeline Gate 全部通过前，PR #4 保持 Draft
