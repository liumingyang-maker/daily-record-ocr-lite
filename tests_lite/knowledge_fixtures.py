from __future__ import annotations

from pathlib import Path

from lite_app.knowledge.database import KnowledgeDB


def seed_dated_history(
    db_path: Path, source_jobs: tuple[str, str] = ("job-old", "job-new")
) -> tuple[int, int]:
    database = KnowledgeDB(db_path)
    database.initialize()
    connection = database._get_conn()
    customer_id = connection.execute(
        "INSERT INTO customers (name, aliases_json, usage_count) VALUES ('联创', '[]', 2)"
    ).lastrowid
    product_id = connection.execute(
        "INSERT INTO products (customer_id, name, aliases_json, usage_count) VALUES (?, 'G30A', '[]', 2)",
        (customer_id,),
    ).lastrowid
    material_id = connection.execute(
        """
        INSERT INTO materials
            (standard_name, category, default_unit, usage_count, created_at, updated_at)
        VALUES ('PA66', '', 'kg', 2, '2026-07-27T00:00:00Z', '2026-07-27T00:00:00Z')
        """
    ).lastrowid
    first = connection.execute(
        """
        INSERT INTO formulas (
            customer_id, product_id, title, formula_no, record_date, confirmed_at,
            source_job_id, source_formula_id, source_image_index, fingerprint
        ) VALUES (?, ?, '配方1', '配方1', '2026-07-27', '2026-07-27T08:00:00Z', ?, 'formula-old', 1, 'hash-old')
        """,
        (customer_id, product_id, source_jobs[0]),
    ).lastrowid
    second = connection.execute(
        """
        INSERT INTO formulas (
            customer_id, product_id, title, formula_no, record_date, confirmed_at,
            source_job_id, source_formula_id, source_image_index, fingerprint, revision_of_id
        ) VALUES (?, ?, '配方1', '配方1', '2026-07-28', '2026-07-28T08:00:00Z', ?, 'formula-new', 1, 'hash-new', ?)
        """,
        (customer_id, product_id, source_jobs[1], first),
    ).lastrowid
    for formula_id, amount, temperature in ((first, "60", "260"), (second, "62", "265")):
        connection.execute(
            """
            INSERT INTO formula_items
                (formula_id, seq, material_id, material_name, amount, normalized_amount, unit)
            VALUES (?, 1, ?, 'PA66', ?, ?, 'kg')
            """,
            (formula_id, material_id, amount, float(amount)),
        )
        connection.execute(
            """
            INSERT INTO formula_process_parameters (formula_id, seq, name, value, unit)
            VALUES (?, 1, '温度', ?, '℃')
            """,
            (formula_id, temperature),
        )
    connection.commit()
    database.close()
    return int(first), int(second)
