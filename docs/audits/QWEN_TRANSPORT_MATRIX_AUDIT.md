# Qwen Transport Matrix Audit

> 本文件为脱敏审计报告模板，实际数据由诊断脚本生成到 `data/diagnostics/`（gitignored）。

## 1. Executive conclusion

- 是否已找到稳定组合：**待测试**
- 是否完成完整Pipeline：**待测试**
- 是否允许处理PR #4：**否，Gate未通过**

## 2. Environment

| 项目 | 值 |
|------|-----|
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
| system_proxy_detected | **True** |
| DNS IP count | 6 |
| DNS latency | 771ms |

## 3. Small probe matrix

| client | trust_env | http2 | attempts | successes | failures | median_latency | exception_types |
|--------|-----------|-------|----------|-----------|----------|----------------|-----------------|
| 待测试 | | | | | | | |

## 4. Real image minimal matrix

待测试

## 5. MIME comparison

**已确认代码缺陷**: `lite_app/vision/openai_compatible.py` 第176行固定返回 `data:image/jpeg;base64,...`，不检测实际文件格式。

是否影响真实请求：**待诊断证明**

## 6. Size ladder

待测试

## 7. Root-cause ranking

| 候选原因 | 状态 |
|----------|------|
| 系统代理干扰 (trust_env=True 读取 Windows 代理) | 高度怀疑，待测试 |
| 请求体大小导致上传超时 | 可能，待测试 |
| MIME 类型错误 | 已确认代码问题，影响待测试 |
| HTTP/2 协商失败 | 可能，待测试 |
| TLS 中间链路/杀毒软件 | 可能，待测试 |
| 服务端限流/断连 | 可能，待测试 |

## 8. Production recommendation

待测试完成后填写。

## 9. Full pipeline Gate

| 检查项 | 状态 |
|--------|------|
| content | ❌ |
| JSON | ❌ |
| Schema | ❌ |
| structured_result | ❌ |
| FinalResult | ❌ |
| READY/REVIEW_REQUIRED | ❌ |
| Excel | ❌ |

## 10. PR decision

PR #4 保持 Draft，禁止合并、Tag、Release，直到完整 Gate 通过。
