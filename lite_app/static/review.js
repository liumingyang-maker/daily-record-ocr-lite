(() => {
    "use strict";

    const workspace = document.getElementById("review");
    if (!workspace) return;

    const jobId = workspace.dataset.jobId;
    const root = document.getElementById("review-groups");
    const summary = document.getElementById("review-summary");
    const feedback = document.getElementById("review-feedback");
    const finalize = document.getElementById("review-finalize");
    const toggle = document.getElementById("toggle-formulas");
    let version = "";
    let saveChain = Promise.resolve();
    const timers = new WeakMap();

    function node(tag, className, text) {
        const result = document.createElement(tag);
        if (className) result.className = className;
        if (text !== undefined) result.textContent = String(text);
        return result;
    }

    function button(text, className, onClick) {
        const result = node("button", className || "btn", text);
        result.type = "button";
        result.addEventListener("click", onClick);
        return result;
    }

    function field(labelText, value, onSave, options = {}) {
        const label = node("label", "review-field");
        label.append(node("span", "review-field-label", labelText));
        const input = node("input", options.issue ? "field-issue" : "");
        input.type = options.type || "text";
        input.value = value || "";
        input.placeholder = options.placeholder || "";
        input.addEventListener("input", () => {
            clearTimeout(timers.get(input));
            timers.set(input, setTimeout(() => queueSave(() => onSave(input.value)), 450));
        });
        label.append(input);
        return label;
    }

    function showMessage(message, kind = "ok") {
        feedback.hidden = false;
        feedback.className = `feedback feedback-${kind}`;
        feedback.textContent = message;
    }

    async function api(path, options = {}) {
        const response = await fetch(path, {
            ...options,
            headers: {"Content-Type": "application/json", ...(options.headers || {})},
        });
        let payload = {};
        try {
            payload = await response.json();
        } catch (_error) {
            payload = {detail: "服务器没有返回可读结果"};
        }
        if (!response.ok) {
            const detail = typeof payload.detail === "string"
                ? payload.detail
                : payload.detail?.message || "保存失败";
            throw new Error(detail);
        }
        if (payload.version) version = payload.version;
        return payload;
    }

    function queueSave(operation, reloadAfter = false) {
        saveChain = saveChain
            .then(operation)
            .then((payload) => {
                if (payload?.undo_available) showUndo(payload.message);
                else if (payload?.message) showMessage(payload.message);
                if (reloadAfter) return loadReview();
                return payload;
            })
            .catch((error) => showMessage(error.message, "error"));
        return saveChain;
    }

    async function loadReview() {
        const view = await api(`/api/jobs/${encodeURIComponent(jobId)}/review`);
        version = view.version;
        render(view);
    }

    function render(view) {
        root.replaceChildren();
        summary.textContent = `共 ${view.summary.total_formulas} 条 · 待处理 ${view.summary.needs_confirmation} 条 · 已确认 ${view.summary.confirmed} 条`;
        renderFinalize(view.summary);
        if (!view.groups.length) {
            const template = document.getElementById("review-empty-template");
            root.append(template.content.cloneNode(true));
            return;
        }
        view.groups.forEach((group) => root.append(renderGroup(group)));
    }

    function renderFinalize(counts) {
        finalize.replaceChildren();
        const allConfirmed = counts.total_formulas > 0 && counts.confirmed === counts.total_formulas;
        finalize.hidden = !allConfirmed;
        if (!allConfirmed) return;
        finalize.append(
            node("p", "", "所有配方都已确认。加入知识库后即可导出 Excel。"),
            button("确认完成并加入知识库", "btn btn-primary", () => queueSave(
                () => api(`/api/jobs/${encodeURIComponent(jobId)}/finalize`, {
                    method: "POST",
                    body: JSON.stringify({}),
                }).then((payload) => {
                    window.location.reload();
                    return payload;
                }),
            )),
        );
    }

    function renderGroup(group) {
        const section = node("section", "review-group");
        const identity = node("div", "identity-row");
        let customerInput;
        let productInput;
        const saveIdentity = () => api(
            `/api/jobs/${encodeURIComponent(jobId)}/review/groups/${encodeURIComponent(group.id)}`,
            {
                method: "PATCH",
                body: JSON.stringify({
                    version,
                    customer: customerInput.querySelector("input").value,
                    product: productInput.querySelector("input").value,
                }),
            },
        );
        customerInput = field("客户", group.customer, saveIdentity);
        productInput = field("产品", group.product, saveIdentity);
        identity.append(customerInput, productInput);
        identity.append(button("增加配方", "btn btn-small", () => queueSave(
            () => api(
                `/api/jobs/${encodeURIComponent(jobId)}/review/groups/${encodeURIComponent(group.id)}/formulas`,
                {method: "POST", body: JSON.stringify({version})},
            ),
            true,
        )));
        section.append(identity);
        const formulas = node("div", "formula-list");
        group.formulas.forEach((formula) => formulas.append(renderFormula(formula)));
        section.append(formulas);
        return section;
    }

    function renderFormula(formula) {
        const card = node("details", `formula-card${formula.needs_confirmation ? " has-issue" : ""}`);
        card.open = !formula.collapsed;
        const heading = node("summary", "formula-card-heading");
        const title = node("span", "formula-title", `${formula.formula_no} · ${formula.date.value || "日期待补充"}`);
        const state = node(
            "span",
            formula.confirmed ? "review-chip confirmed" : formula.needs_confirmation ? "review-chip issue" : "review-chip",
            formula.confirmed ? "已确认" : formula.needs_confirmation ? "待处理" : "请确认",
        );
        heading.append(title, state);
        card.append(heading);

        if (formula.blocking_message) card.append(node("p", "blocking-message", formula.blocking_message));
        const layout = node("div", "formula-card-layout");
        layout.append(renderEvidence(formula.evidence), renderFormulaEditor(formula));
        card.append(layout);
        return card;
    }

    function renderEvidence(evidence) {
        const panel = node("figure", "evidence-card");
        const frame = node("div", "evidence-frame");
        if (evidence.image_url) {
            const image = node("img");
            image.src = evidence.image_url;
            image.alt = "原图证据";
            frame.append(image);
            if (evidence.rect) {
                const [x1, y1, x2, y2] = evidence.rect;
                const marker = node("span", "evidence-marker");
                marker.style.left = `${x1 * 100}%`;
                marker.style.top = `${y1 * 100}%`;
                marker.style.width = `${(x2 - x1) * 100}%`;
                marker.style.height = `${(y2 - y1) * 100}%`;
                frame.append(marker);
            }
        } else {
            frame.append(node("p", "empty", "没有可显示的原图"));
        }
        panel.append(frame, node("figcaption", "", "原图证据"));
        return panel;
    }

    function renderFormulaEditor(formula) {
        const editor = node("div", "formula-editor");
        const updateFormula = (changes) => api(
            `/api/jobs/${encodeURIComponent(jobId)}/review/formulas/${encodeURIComponent(formula.id)}`,
            {method: "PATCH", body: JSON.stringify({version, ...changes})},
        );
        const basics = node("div", "formula-basics");
        basics.append(
            field("配方", formula.formula_no, (value) => updateFormula({formula_no: value})),
            field("日期", formula.date.value, (value) => updateFormula({record_date: value}), {
                type: "date",
                issue: formula.date.needs_confirmation,
            }),
        );
        editor.append(basics);
        editor.append(renderMaterials(formula));
        editor.append(renderProcess(formula));
        editor.append(field("备注", formula.notes.value, (value) => updateFormula({notes: value})));

        const actions = node("div", "formula-actions");
        actions.append(button(
            formula.confirmed ? "这条配方已确认" : "确认这条配方",
            "btn btn-primary",
            () => queueSave(
                () => api(
                    `/api/jobs/${encodeURIComponent(jobId)}/review/formulas/${encodeURIComponent(formula.id)}/confirm`,
                    {method: "POST", body: JSON.stringify({version})},
                ),
                true,
            ),
        ));
        actions.append(button("删除配方", "btn btn-danger btn-small", () => {
            if (!window.confirm(`确定删除 ${formula.formula_no} 吗？`)) return;
            queueSave(
                () => api(
                    `/api/jobs/${encodeURIComponent(jobId)}/review/formulas/${encodeURIComponent(formula.id)}`,
                    {method: "DELETE", body: JSON.stringify({version, confirmed: true})},
                ),
                true,
            );
        }));
        editor.append(actions);
        return editor;
    }

    function renderMaterials(formula) {
        const section = node("section", "formula-subsection");
        section.append(node("h4", "", "材料与数量"));
        formula.materials.forEach((material, index) => {
            const row = node("div", "material-row");
            const save = (changes) => api(
                `/api/jobs/${encodeURIComponent(jobId)}/review/formulas/${encodeURIComponent(formula.id)}/materials/${encodeURIComponent(material.id)}`,
                {method: "PATCH", body: JSON.stringify({version, ...changes})},
            );
            row.append(
                field("材料", material.name.value, (value) => save({name: value}), {issue: material.name.needs_confirmation}),
                field("数量", material.amount.value, (value) => save({amount: value}), {issue: material.amount.needs_confirmation}),
                field("单位（可不填）", material.unit.value, (value) => save({unit: value})),
            );
            const controls = node("div", "row-actions");
            controls.append(
                button("上移", "btn btn-small", () => reorderMaterial(formula, index, -1)),
                button("下移", "btn btn-small", () => reorderMaterial(formula, index, 1)),
                button("删除", "btn btn-small btn-danger", () => deleteMaterial(formula.id, material.id)),
            );
            row.append(controls);
            section.append(row);
        });
        section.append(button("增加材料", "btn btn-small", () => queueSave(
            () => api(
                `/api/jobs/${encodeURIComponent(jobId)}/review/formulas/${encodeURIComponent(formula.id)}/materials`,
                {method: "POST", body: JSON.stringify({version, name: "", amount: "", unit: ""})},
            ),
            true,
        )));
        return section;
    }

    function reorderMaterial(formula, index, offset) {
        const target = index + offset;
        if (target < 0 || target >= formula.materials.length) return;
        const ids = formula.materials.map((item) => item.id);
        [ids[index], ids[target]] = [ids[target], ids[index]];
        queueSave(
            () => api(
                `/api/jobs/${encodeURIComponent(jobId)}/review/formulas/${encodeURIComponent(formula.id)}/materials/reorder`,
                {method: "POST", body: JSON.stringify({version, material_ids: ids})},
            ),
            true,
        );
    }

    function deleteMaterial(formulaId, materialId) {
        queueSave(
            () => api(
                `/api/jobs/${encodeURIComponent(jobId)}/review/formulas/${encodeURIComponent(formulaId)}/materials/${encodeURIComponent(materialId)}`,
                {method: "DELETE", body: JSON.stringify({version})},
            ),
            true,
        );
    }

    function renderProcess(formula) {
        const section = node("section", "formula-subsection");
        section.append(node("h4", "", "工艺（可不填）"));
        formula.process.forEach((parameter) => {
            const row = node("div", "material-row");
            const save = (changes) => api(
                `/api/jobs/${encodeURIComponent(jobId)}/review/formulas/${encodeURIComponent(formula.id)}/process/${encodeURIComponent(parameter.id)}`,
                {method: "PATCH", body: JSON.stringify({version, ...changes})},
            );
            row.append(
                field("工艺名称", parameter.name.value, (value) => save({name: value}), {issue: parameter.name.needs_confirmation}),
                field("工艺内容", parameter.value.value, (value) => save({value}), {issue: parameter.value.needs_confirmation}),
                field("单位（可不填）", parameter.unit.value, (value) => save({unit: value})),
                button("删除", "btn btn-small btn-danger", () => queueSave(
                    () => api(
                        `/api/jobs/${encodeURIComponent(jobId)}/review/formulas/${encodeURIComponent(formula.id)}/process/${encodeURIComponent(parameter.id)}`,
                        {method: "DELETE", body: JSON.stringify({version})},
                    ),
                    true,
                )),
            );
            section.append(row);
        });
        section.append(button("增加工艺", "btn btn-small", () => queueSave(
            () => api(
                `/api/jobs/${encodeURIComponent(jobId)}/review/formulas/${encodeURIComponent(formula.id)}/process`,
                {method: "POST", body: JSON.stringify({version, name: "", value: "", unit: ""})},
            ),
            true,
        )));
        return section;
    }

    function showUndo(message) {
        showMessage(message);
        const undo = button("撤销删除", "btn btn-small", () => queueSave(
            () => api(
                `/api/jobs/${encodeURIComponent(jobId)}/review/undo`,
                {method: "POST", body: JSON.stringify({version})},
            ),
            true,
        ));
        feedback.append(document.createTextNode(" "), undo);
    }

    toggle.addEventListener("click", () => {
        const cards = [...root.querySelectorAll("details.formula-card")];
        const shouldOpen = cards.some((card) => !card.open);
        cards.forEach((card) => { card.open = shouldOpen; });
        toggle.textContent = shouldOpen ? "折叠全部" : "展开全部";
    });

    loadReview().catch((error) => showMessage(error.message, "error"));
})();
