#!/usr/bin/env python3
"""Small local web app for collaborative cement extraction review."""

from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from import_data import DEFAULT_DB, import_directory

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DEFAULT_DB)
    conn.row_factory = sqlite3.Row
    return conn


def loads_json(value: str | None) -> dict:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}


def row_to_dict(row: sqlite3.Row) -> dict:
    item = dict(row)
    for key in ["data_json", "payload_json"]:
        if key in item:
            item[key.replace("_json", "")] = loads_json(item.pop(key))
    return item


def query_params(path: str) -> dict[str, str]:
    parsed = parse_qs(urlparse(path).query)
    return {k: v[-1] for k, v in parsed.items() if v}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.path = "/index.html"
            return super().do_GET()
        if parsed.path.startswith("/api/"):
            return self.handle_api_get(parsed.path, query_params(self.path))
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            return self.send_error(HTTPStatus.NOT_FOUND)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            payload = json.loads(body or "{}")
        except json.JSONDecodeError:
            return self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
        return self.handle_api_post(parsed.path, payload)

    def send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_csv(self, filename: str, rows: list[dict]) -> None:
        output = io.StringIO()
        if rows:
            fieldnames = sorted({key for row in rows for key in row.keys()})
            writer = csv.DictWriter(output, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        body = output.getvalue().encode("utf-8-sig")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_api_get(self, path: str, params: dict[str, str]) -> None:
        if path == "/api/summary":
            return self.summary()
        if path == "/api/papers":
            return self.papers()
        if path == "/api/paper":
            return self.paper(params)
        if path == "/api/review":
            return self.review(params)
        if path == "/api/records":
            return self.records(params)
        if path == "/api/answers":
            return self.answers(params)
        if path.startswith("/api/export/"):
            return self.export(path.rsplit("/", 1)[-1], params)
        return self.send_json({"error": "Unknown endpoint"}, HTTPStatus.NOT_FOUND)

    def handle_api_post(self, path: str, payload: dict) -> None:
        if path == "/api/answer":
            return self.submit_answer(payload)
        if path == "/api/review":
            return self.create_review(payload)
        if path == "/api/import":
            totals = import_directory()
            return self.send_json({"ok": True, **totals})
        return self.send_json({"error": "Unknown endpoint"}, HTTPStatus.NOT_FOUND)

    def summary(self) -> None:
        with connect() as conn:
            data = {
                "papers": conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
                "strength_results": conn.execute("SELECT COUNT(*) FROM records WHERE sheet='strength_results'").fetchone()[0],
                "mixture_components": conn.execute("SELECT COUNT(*) FROM records WHERE sheet='mixture_components'").fetchone()[0],
                "review_open": conn.execute("SELECT COUNT(*) FROM review_queue WHERE status='open'").fetchone()[0],
                "review_resolved": conn.execute("SELECT COUNT(*) FROM review_queue WHERE status!='open'").fetchone()[0],
                "answers": conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0],
                "last_import": conn.execute("SELECT MAX(imported_at) FROM source_workbooks").fetchone()[0],
            }
        self.send_json(data)

    def papers(self) -> None:
        sql = """
            SELECT p.paper_id, p.title, p.doi, p.year, p.journal, p.source_workbook,
                   SUM(CASE WHEN r.sheet='strength_results' THEN 1 ELSE 0 END) AS strength_count,
                   SUM(CASE WHEN r.sheet='mixture_components' THEN 1 ELSE 0 END) AS component_count,
                   (SELECT COUNT(*) FROM review_queue q WHERE q.paper_id=p.paper_id AND q.status='open') AS open_reviews
            FROM papers p
            LEFT JOIN records r ON r.paper_id=p.paper_id
            GROUP BY p.paper_id
            ORDER BY p.paper_id
        """
        with connect() as conn:
            rows = [dict(row) for row in conn.execute(sql)]
        self.send_json(rows)

    def paper(self, params: dict[str, str]) -> None:
        paper_id = params.get("paper_id", "")
        with connect() as conn:
            paper = conn.execute("SELECT * FROM papers WHERE paper_id=?", (paper_id,)).fetchone()
            if not paper:
                return self.send_json({"error": "Paper not found"}, HTTPStatus.NOT_FOUND)
            records = [
                row_to_dict(row)
                for row in conn.execute(
                    "SELECT * FROM records WHERE paper_id=? ORDER BY sheet, record_key", (paper_id,)
                )
            ]
            reviews = [
                row_to_dict(row)
                for row in conn.execute(
                    "SELECT * FROM review_queue WHERE paper_id=? ORDER BY status, id", (paper_id,)
                )
            ]
        self.send_json({"paper": row_to_dict(paper), "records": records, "reviews": reviews})

    def review(self, params: dict[str, str]) -> None:
        status = params.get("status", "open")
        paper_id = params.get("paper_id", "")
        q = f"%{params.get('q', '').lower()}%"
        limit = min(int(params.get("limit", "200")), 1000)
        where = []
        values: list[object] = []
        if status != "all":
            where.append("status = ?")
            values.append(status)
        if paper_id:
            where.append("paper_id = ?")
            values.append(paper_id)
        if params.get("q"):
            where.append("(lower(question) LIKE ? OR lower(notes) LIKE ? OR lower(data_json) LIKE ?)")
            values.extend([q, q, q])
        sql = "SELECT * FROM review_queue"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY CASE status WHEN 'open' THEN 0 ELSE 1 END, paper_id, id LIMIT ?"
        values.append(limit)
        with connect() as conn:
            rows = [row_to_dict(row) for row in conn.execute(sql, values)]
        self.send_json(rows)

    def records(self, params: dict[str, str]) -> None:
        sheet = params.get("sheet", "strength_results")
        paper_id = params.get("paper_id", "")
        limit = min(int(params.get("limit", "500")), 2000)
        values: list[object] = [sheet]
        sql = "SELECT * FROM records WHERE sheet=?"
        if paper_id:
            sql += " AND paper_id=?"
            values.append(paper_id)
        sql += " ORDER BY paper_id, record_key LIMIT ?"
        values.append(limit)
        with connect() as conn:
            rows = [row_to_dict(row) for row in conn.execute(sql, values)]
        self.send_json(rows)

    def answers(self, params: dict[str, str]) -> None:
        limit = min(int(params.get("limit", "500")), 2000)
        with connect() as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT a.*, q.paper_id, q.review_key, q.question
                    FROM answers a
                    JOIN review_queue q ON q.id=a.review_item_id
                    ORDER BY a.id DESC LIMIT ?
                    """,
                    (limit,),
                )
            ]
        self.send_json(rows)

    def submit_answer(self, payload: dict) -> None:
        required = ["review_item_id", "participant", "decision"]
        missing = [key for key in required if not str(payload.get(key, "")).strip()]
        if missing:
            return self.send_json({"error": f"Missing: {', '.join(missing)}"}, HTTPStatus.BAD_REQUEST)
        created_at = now_iso()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO answers(review_item_id, participant, decision, answer, corrected_value, comment, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["review_item_id"],
                    payload["participant"],
                    payload["decision"],
                    payload.get("answer"),
                    payload.get("corrected_value"),
                    payload.get("comment"),
                    created_at,
                ),
            )
            conn.execute(
                """
                UPDATE review_queue
                SET status='answered', final_decision=?, human_answer=?, notes=?, updated_at=?
                WHERE id=?
                """,
                (
                    payload["decision"],
                    payload.get("answer"),
                    payload.get("comment"),
                    created_at,
                    payload["review_item_id"],
                ),
            )
            conn.execute(
                "INSERT INTO events(event_type, payload_json, created_at) VALUES (?, ?, ?)",
                ("answer_submitted", json.dumps(payload, ensure_ascii=False), created_at),
            )
            conn.commit()
        self.send_json({"ok": True, "created_at": created_at})

    def create_review(self, payload: dict) -> None:
        paper_id = str(payload.get("paper_id", "")).strip()
        question = str(payload.get("question", "")).strip()
        if not paper_id or not question:
            return self.send_json({"error": "paper_id and question are required"}, HTTPStatus.BAD_REQUEST)
        created_at = now_iso()
        review_key = f"manual:{paper_id}:{created_at}"
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO review_queue(source_workbook, paper_id, review_key, target_sheet, target_record_ids,
                                         priority, question, suggested_action, status, notes, data_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
                """,
                (
                    "manual",
                    paper_id,
                    review_key,
                    payload.get("target_sheet"),
                    payload.get("target_record_ids"),
                    payload.get("priority", "normal"),
                    question,
                    payload.get("suggested_action"),
                    payload.get("notes"),
                    json.dumps(payload, ensure_ascii=False),
                    created_at,
                ),
            )
            conn.commit()
        self.send_json({"ok": True, "review_key": review_key})

    def export(self, table: str, params: dict[str, str]) -> None:
        allowed = {"answers", "review_queue", "papers", "records"}
        if table not in allowed:
            return self.send_json({"error": "Unsupported export table"}, HTTPStatus.BAD_REQUEST)
        with connect() as conn:
            rows = [row_to_dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
        flattened = []
        for row in rows:
            flat = {}
            for key, value in row.items():
                flat[key] = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
            flattened.append(flat)
        self.send_csv(f"{table}.csv", flattened)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not DEFAULT_DB.exists():
        import_directory()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving cement review site at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
