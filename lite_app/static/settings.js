(() => {
    "use strict";
    const page = document.getElementById("settings-page");
    if (!page) return;

    let visionHealthy = false;
    let ocrHealthy = false;
    let diagnostics = {};
    const byId = (id) => document.getElementById(id);
    const value = (id) => byId(id)?.value || "";

    async function call(url, method, payload) {
        const response = await fetch(url, {
            method,
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload || {}),
        });
        let data = {};
        try {
            data = await response.json();
        } catch (_error) {
            data = {error_category: "TRANSPORT", http_status: response.status};
        }
        if (!response.ok && !data.error_category) data.error_category = `HTTP_${response.status}`;
        return {response, data};
    }

    function visionPayload() {
        const payload = {
            provider: value("vision-provider") || "openai_compatible",
            base_url: value("vision-base-url"),
            endpoint: value("vision-endpoint") || "/chat/completions",
            model: value("vision-model"),
        };
        const key = value("vision-key");
        if (key) payload.api_key = key;
        return payload;
    }

    function ocrPayload() {
        return {
            provider: "paddleocr_v6",
            tier: value("ocr-tier") || "medium",
            device: value("ocr-device") || "cpu",
            minimum_score: Number(value("ocr-score") || 0.45),
        };
    }

    function resultMessage(data, ok) {
        if (ok) return {title: "测试通过", action: "当前服务可以用于真实识别。", icon: "✓"};
        const category = String(data.error_category || "").toUpperCase();
        if ([401, 403].includes(data.http_status) || category.includes("AUTH")) {
            return {title: "API Key 或服务权限不正确", action: "检查 API Key 和模型权限后重新测试。", icon: "!"};
        }
        if (category.includes("TIMEOUT")) {
            return {title: "AI 识别服务响应超时", action: "检查网络连接和服务状态后重新测试。", icon: "!"};
        }
        if (category.includes("JSON") || category.includes("SCHEMA")) {
            return {title: "AI 返回格式无法识别", action: "确认模型支持 JSON 输出后重新测试。", icon: "!"};
        }
        return {title: "无法连接 AI 识别服务", action: "检查服务地址和网络连接后重新测试。", icon: "!"};
    }

    function showResult(data, ok) {
        const card = byId("connection-result");
        const message = resultMessage(data, ok);
        card.hidden = false;
        card.className = `connection-result ${ok ? "connection-ok" : "connection-error"}`;
        byId("connection-icon").textContent = message.icon;
        byId("connection-title").textContent = message.title;
        byId("connection-action").textContent = message.action;
        diagnostics = {
            status: data.status ?? null,
            provider: data.provider ?? null,
            model: data.model ?? null,
            latency_ms: data.latency_ms ?? null,
            http_status: data.http_status ?? null,
            vision_capability: data.vision_capability ?? null,
            json_response_capability: data.json_response_capability ?? null,
            strict_json_capability: data.strict_json_capability ?? null,
            error_category: data.error_category ?? null,
            request_id: data.request_id ?? null,
        };
        const diagnostic = byId("diagnostics");
        diagnostic.hidden = false;
        byId("diagnostics-text").textContent = JSON.stringify(diagnostics, null, 2);
    }

    function updateReady() {
        if (!byId("ready-success")) return;
        const ready = visionHealthy && ocrHealthy;
        byId("ready-success").hidden = !ready;
        byId("ready-state").hidden = ready;
    }

    byId("save-vision")?.addEventListener("click", async () => {
        const {response, data} = await call(page.dataset.saveVision, "PUT", visionPayload());
        visionHealthy = false;
        showResult(data, response.ok);
        updateReady();
    });
    byId("test-vision")?.addEventListener("click", async () => {
        const {response, data} = await call(page.dataset.testVision, "POST", {});
        visionHealthy = response.ok && data.status === "OK"
            && data.vision_capability === true && data.json_response_capability === true;
        showResult(data, visionHealthy);
        updateReady();
    });
    byId("save-ocr")?.addEventListener("click", async () => {
        const {response, data} = await call("/api/settings/ocr", "PUT", ocrPayload());
        ocrHealthy = false;
        showResult(data, response.ok);
        updateReady();
    });
    byId("test-ocr")?.addEventListener("click", async () => {
        const {response, data} = await call("/api/settings/test-ocr", "POST", {});
        ocrHealthy = response.ok && data.status === "OK" && Number(data.token_count) > 0;
        showResult(data, ocrHealthy);
        const overlay = byId("ocr-overlay");
        if (overlay && data.overlay_url) {
            overlay.src = data.overlay_url;
            overlay.hidden = false;
        }
        updateReady();
    });
    byId("copy-diagnostics")?.addEventListener("click", async () => {
        await navigator.clipboard.writeText(JSON.stringify(diagnostics, null, 2));
        byId("copy-diagnostics").textContent = "已复制";
    });
    byId("disable-demo")?.addEventListener("click", async () => {
        const {response, data} = await call("/api/settings/demo/disable", "POST", {});
        showResult(data, response.ok);
        if (response.ok) window.location.reload();
    });
    byId("check-update")?.addEventListener("click", async () => {
        const status = byId("update-status");
        const release = byId("open-release");
        status.textContent = "正在检查最新稳定版…";
        release.hidden = true;
        try {
            const response = await fetch(page.dataset.checkUpdate);
            const data = await response.json();
            if (!response.ok || data.status !== "OK") throw new Error("update check failed");
            status.textContent = data.update_available
                ? `发现稳定版 v${data.latest_version}。${data.instructions}`
                : `当前已是最新稳定版。${data.instructions}`;
            if (data.release_url) {
                release.href = data.release_url;
                release.hidden = false;
            }
        } catch (_error) {
            status.textContent = "暂时无法检查更新，请稍后重试。";
        }
    });
    byId("import-existing-data")?.addEventListener("click", async () => {
        const status = byId("data-import-status");
        const sourcePath = value("legacy-data-path").trim();
        if (!sourcePath) {
            status.textContent = "请先填写现有项目或 data 目录。";
            return;
        }
        status.textContent = "正在复制本机数据…";
        const {response, data} = await call(page.dataset.importData, "POST", {
            source_path: sourcePath,
            confirm_non_empty: Boolean(byId("confirm-data-import")?.checked),
        });
        if (!response.ok) {
            status.textContent = data.detail || "导入失败，请检查所选目录。";
            return;
        }
        const total = Object.values(data.copied_file_counts || {})
            .reduce((sum, count) => sum + Number(count || 0), 0);
        status.textContent = `已安全导入 ${total} 个文件。原目录未修改。`;
    });

    async function refreshModelStatus() {
        if (!page.dataset.modelStatus) return;
        const response = await fetch(page.dataset.modelStatus);
        const data = await response.json();
        const status = byId("model-status");
        const progress = byId("model-progress");
        const button = byId("install-models");
        if (data.status === "READY") {
            status.textContent = "OCR 模型已下载并通过 SHA-256 校验。";
            progress.hidden = true;
            button.hidden = true;
            return;
        }
        if (data.status === "INSTALLING") {
            const downloaded = Number(data.downloaded_bytes || 0);
            const total = Number(data.total_bytes || 0);
            const percent = total > 0 ? Math.min(100, Math.round(downloaded * 100 / total)) : 0;
            progress.hidden = false;
            progress.value = percent;
            button.disabled = true;
            status.textContent = data.model
                ? `正在下载 ${data.model}：${percent}%`
                : "正在准备 OCR 模型下载…";
            window.setTimeout(refreshModelStatus, 1000);
            return;
        }
        button.hidden = false;
        button.disabled = false;
        progress.hidden = true;
        status.textContent = data.status === "FAILED"
            ? "模型下载或校验失败，可安全重试。"
            : "首次真实识别前需要下载约 146 MB 官方 OCR 模型。";
    }
    byId("install-models")?.addEventListener("click", async () => {
        byId("install-models").disabled = true;
        await call(page.dataset.installModels, "POST", {});
        await refreshModelStatus();
    });
    refreshModelStatus().catch(() => {
        if (byId("model-status")) byId("model-status").textContent = "暂时无法检查 OCR 模型。";
    });
    byId("enable-demo")?.addEventListener("click", async () => {
        if (!window.confirm("演示结果与上传图片无关，确认只体验演示模式？")) return;
        const {response, data} = await call("/api/settings/demo/enable", "POST", {});
        showResult(data, response.ok);
        if (response.ok) window.location.href = "/";
    });

    const services = {
        bailian: {base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1", endpoint: "/chat/completions"},
        ollama: {base_url: "http://127.0.0.1:11434/v1", endpoint: "/chat/completions"},
        custom: {base_url: "", endpoint: "/chat/completions"},
    };
    byId("vision-service")?.addEventListener("change", (event) => {
        const selected = services[event.target.value];
        byId("vision-base-url").value = selected.base_url;
        byId("vision-endpoint").value = selected.endpoint;
    });
})();
