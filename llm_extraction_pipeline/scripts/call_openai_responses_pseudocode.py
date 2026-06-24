"""
Pseudocode for calling an LLM with the Responses API.

This file is intentionally not executed here. It shows the shape of the
API-backed extraction script you can implement later.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from openai import OpenAI


ROOT = Path("/path/to/cement_database_project")
SCHEMA_PATH = ROOT / "llm_extraction_pipeline/schemas/cement_extraction.schema.json"
PROMPT_PATH = ROOT / "llm_extraction_pipeline/prompts/extract_paper.md"
PACKET_DIR = ROOT / "llm_run/packets"
OUTPUT_DIR = ROOT / "llm_run/raw_llm_json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def build_input(prompt_template: str, packet: dict, few_shot_examples: list[dict]) -> str:
    selected_pages = []
    for page in packet.get("pages", []):
        selected_pages.append(
            f"PAGE {page.get('page')} | reason={page.get('reason')}\n{page.get('text', '')}"
        )

    tables = []
    for table in packet.get("tables", []):
        tables.append(
            f"{table.get('table_id')} | page={table.get('page')} | caption={table.get('caption')}\n{table.get('text', '')}"
        )

    figures = []
    for fig in packet.get("figures", []):
        figures.append(
            f"{fig.get('figure_id')} | page={fig.get('page')} | caption={fig.get('caption')} | image={fig.get('image_path')} | reason={fig.get('reason')}"
        )

    return (
        prompt_template
        .replace("{{paper_metadata_json}}", json.dumps(packet.get("paper", {}), ensure_ascii=False, indent=2))
        .replace("{{selected_page_text}}", "\n\n".join(selected_pages))
        .replace("{{candidate_tables_text}}", "\n\n".join(tables))
        .replace("{{figure_packet_text}}", "\n\n".join(figures))
        .replace("{{few_shot_examples_json}}", json.dumps(few_shot_examples, ensure_ascii=False, indent=2))
    )


def extract_one(packet_path: Path, few_shot_examples: list[dict]) -> dict:
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    schema = load_json(SCHEMA_PATH)
    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    packet = load_json(packet_path)

    user_input = build_input(prompt_template, packet, few_shot_examples)

    response = client.responses.create(
        model=os.environ.get("MODEL_EXTRACT", "gpt-5.5"),
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": user_input,
                    }
                ],
            }
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "cement_extraction",
                "schema": schema,
                "strict": True,
            }
        },
    )

    # Depending on SDK version, use the helper field if available; otherwise parse
    # the first output text item.
    data = json.loads(response.output_text)
    return data


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    few_shot_examples = load_json(ROOT / "llm_run/few_shot_examples.json")

    for packet_path in sorted(PACKET_DIR.glob("*/context_packet.json")):
        paper_id = packet_path.parent.name
        out_path = OUTPUT_DIR / paper_id / "extraction.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.exists():
            continue

        extraction = extract_one(packet_path, few_shot_examples)
        out_path.write_text(json.dumps(extraction, ensure_ascii=False, indent=2), encoding="utf-8")
        print(paper_id, out_path)


if __name__ == "__main__":
    main()
