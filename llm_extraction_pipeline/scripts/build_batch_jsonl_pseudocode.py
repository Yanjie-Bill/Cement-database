"""
Pseudocode for building a Batch API JSONL file.

Each JSONL line is one paper extraction request. Submit the resulting JSONL
to the Batch API with endpoint /v1/responses.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path("/path/to/cement_database_project")
SCHEMA_PATH = ROOT / "llm_extraction_pipeline/schemas/cement_extraction.schema.json"
PROMPT_PATH = ROOT / "llm_extraction_pipeline/prompts/extract_paper.md"
PACKET_DIR = ROOT / "llm_run/packets"
OUT_JSONL = ROOT / "llm_run/batch_requests/cement_extraction_requests.jsonl"


def build_request_body(packet: dict, prompt_text: str, schema: dict) -> dict:
    return {
        "model": os.environ.get("MODEL_EXTRACT", "gpt-5.5"),
        "input": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": prompt_text,
                    }
                ],
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "cement_extraction",
                "schema": schema,
                "strict": True,
            }
        },
    }


def main():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    prompt_template = PROMPT_PATH.read_text(encoding="utf-8")
    OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)

    with OUT_JSONL.open("w", encoding="utf-8") as f:
        for packet_path in sorted(PACKET_DIR.glob("*/context_packet.json")):
            paper_id = packet_path.parent.name
            packet = json.loads(packet_path.read_text(encoding="utf-8"))

            # In the real script, reuse the same build_input() helper from
            # call_openai_responses_pseudocode.py.
            prompt_text = prompt_template.replace(
                "{{paper_metadata_json}}",
                json.dumps(packet.get("paper", {}), ensure_ascii=False),
            )

            line = {
                "custom_id": paper_id,
                "method": "POST",
                "url": "/v1/responses",
                "body": build_request_body(packet, prompt_text, schema),
            }
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    print(OUT_JSONL)


if __name__ == "__main__":
    main()
