(() => {
    "use strict";

    const treeRoot = document.getElementById("knowledge-tree");
    if (!treeRoot) return;
    const detailRoot = document.getElementById("knowledge-detail");
    const search = document.getElementById("knowledge-search");
    const compareButton = document.getElementById("compare-formulas");
    const feedback = document.getElementById("knowledge-feedback");
    const selected = new Set();
    let searchTimer;

    function node(tag, className, text) {
        const result = document.createElement(tag);
        if (className) result.className = className;
        if (text !== undefined) result.textContent = String(text);
        return result;
    }

    async function getJson(url, options) {
        const response = await fetch(url, options);
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || "读取失败");
        return payload;
    }

    function showError(error) {
        feedback.hidden = false;
        feedback.className = "feedback feedback-error";
        feedback.textContent = error.message;
    }

    async function loadTree() {
        const data = await getJson(`/api/knowledge/tree?q=${encodeURIComponent(search.value.trim())}`);
        treeRoot.replaceChildren();
        if (!data.customers.length) {
            treeRoot.append(node("p", "empty", "没有找到配方记录，请换一个关键词。"));
            return;
        }
        data.customers.forEach((customer) => {
            const customerBlock = node("section", "history-customer");
            customerBlock.append(node("h3", "", customer.name));
            customer.products.forEach((product) => {
                const productBlock = node("div", "history-product");
                productBlock.append(node("h4", "", `${product.name} · ${product.formula_count} 条`));
                product.formulas.forEach((formula) => productBlock.append(formulaButton(formula)));
                customerBlock.append(productBlock);
            });
            treeRoot.append(customerBlock);
        });
    }

    function formulaButton(formula) {
        const row = node("div", "history-row");
        const checkbox = node("input");
        checkbox.type = "checkbox";
        checkbox.ariaLabel = "选择用于比较";
        checkbox.checked = selected.has(formula.id);
        checkbox.addEventListener("change", () => {
            if (checkbox.checked && selected.size >= 2) {
                checkbox.checked = false;
                return;
            }
            if (checkbox.checked) selected.add(formula.id);
            else selected.delete(formula.id);
            compareButton.disabled = selected.size !== 2;
            compareButton.textContent = selected.size === 2 ? "比较配方" : `比较配方（已选 ${selected.size}/2）`;
        });
        const open = node(
            "button",
            "history-open",
            `${formula.record_date || "历史数据未记录日期"} · ${formula.formula_no}`,
        );
        open.type = "button";
        open.addEventListener("click", () => loadDetail(formula.id));
        row.append(checkbox, open);
        return row;
    }

    async function loadDetail(id) {
        try {
            const detail = await getJson(`/api/knowledge/formulas/${id}`);
            renderDetail(detail);
        } catch (error) {
            showError(error);
        }
    }

    function renderDetail(detail) {
        detailRoot.replaceChildren();
        detailRoot.append(
            node("p", "eyebrow", `${detail.customer} / ${detail.product}`),
            node("h2", "", `${detail.record_date || "历史数据未记录日期"} · ${detail.formula_no}`),
        );
        if (detail.evidence_image_url) {
            const figure = node("figure", "knowledge-evidence");
            const image = node("img");
            image.src = detail.evidence_image_url;
            image.alt = "该配方的原图证据";
            figure.append(image, node("figcaption", "", "原图证据"));
            detailRoot.append(figure);
        }
        detailRoot.append(renderRows("材料与数量", detail.materials, "amount"));
        if (detail.process.length) detailRoot.append(renderRows("工艺", detail.process, "value"));
    }

    function renderRows(title, rows, valueKey) {
        const section = node("section", "history-values");
        section.append(node("h3", "", title));
        rows.forEach((item) => {
            const row = node("div", "history-value-row");
            row.append(
                node("span", "", item.name),
                node("strong", "", `${item[valueKey]}${item.unit ? ` ${item.unit}` : ""}`),
            );
            section.append(row);
        });
        return section;
    }

    compareButton.addEventListener("click", async () => {
        if (selected.size !== 2) return;
        try {
            const [left, right] = [...selected];
            const comparison = await getJson(`/api/knowledge/compare?left=${left}&right=${right}`);
            detailRoot.replaceChildren(node("h2", "", "配方变化对比"));
            detailRoot.append(renderComparison("材料与数量", comparison.materials));
            detailRoot.append(renderComparison("工艺", comparison.process));
        } catch (error) {
            showError(error);
        }
    });

    function renderComparison(title, values) {
        const section = node("section", "history-values");
        section.append(node("h3", "", title));
        Object.entries(values).forEach(([name, change]) => {
            const row = node("div", "comparison-row");
            row.append(
                node("strong", "", name),
                node("span", "comparison-before", change.before || "未记录"),
                node("span", "comparison-arrow", "→"),
                node("span", "comparison-after", change.after || "未记录"),
            );
            section.append(row);
        });
        return section;
    }

    search.addEventListener("input", () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => loadTree().catch(showError), 300);
    });

    document.getElementById("material-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const aliases = document.getElementById("mat-aliases").value
            .split(",").map((item) => item.trim()).filter(Boolean);
        try {
            await getJson("/knowledge/materials", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    name: document.getElementById("mat-name").value.trim(),
                    category: document.getElementById("mat-category").value.trim(),
                    unit: document.getElementById("mat-unit").value.trim(),
                    aliases,
                }),
            });
            window.location.reload();
        } catch (error) {
            showError(error);
        }
    });

    document.getElementById("import-form").addEventListener("submit", async (event) => {
        event.preventDefault();
        const file = document.getElementById("import-file").files[0];
        if (!file) return;
        const body = new FormData();
        body.append("file", file);
        try {
            const response = await fetch("/knowledge/import", {method: "POST", body});
            if (!response.ok) throw new Error("导入失败，请检查文件格式。" );
            window.location.reload();
        } catch (error) {
            showError(error);
        }
    });

    loadTree().catch(showError);
})();
