# How to Run the LLM Extraction Pipeline With an API Key

This runbook assumes you already have an OpenAI API key.

## 1. Set Environment Variables

From the project root:

```bash
cd "/Users/yanjie/Library/Mobile Documents/com~apple~CloudDocs/Academic/computing/260622 Cement database Journal"
export OPENAI_API_KEY="sk-..."
export MODEL_EXTRACT="gpt-5.5"
```

If you want to avoid writing the key into shell history, use:

```bash
read -s OPENAI_API_KEY
export OPENAI_API_KEY
export MODEL_EXTRACT="gpt-5.5"
```

## 2. Install/Check Python Dependencies

The scripts need:

```bash
python3 -m pip install openai jsonschema pypdf pdfplumber openpyxl pandas
```

If using the Codex bundled Python:

```bash
/Users/yanjie/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pip install openai jsonschema
```

## 3. Prepare Context Packets

For each PDF, create a compact packet:

```text
llm_run/packets/<paper_id>/context_packet.json
```

Each packet should contain:

- metadata: paper ID, DOI, title, PDF filename
- selected text pages
- candidate tables
- figure captions/page-image references
- evidence snippets

Start with the 20 gold papers first, not all 200.

## 4. Run One Paper First

Do a single-paper smoke test:

```bash
python llm_extraction_pipeline/scripts/call_openai_responses.py \
  --packet llm_run/packets/CBM0001/context_packet.json \
  --output llm_run/raw_llm_json/CBM0001/extraction.json
```

Check:

- JSON matches `schemas/cement_extraction.schema.json`
- `strength_results` only contains compressive strength
- every row has `confidence`
- every data row has `evidence_ids`
- uncertain figure/table values go to `review_queue`

## 5. Run the 20 Gold Papers

```bash
python llm_extraction_pipeline/scripts/call_openai_responses.py \
  --packet-dir llm_run/packets_gold20 \
  --output-dir llm_run/raw_llm_json_gold20
```

Then validate:

```bash
python llm_extraction_pipeline/scripts/validate_and_score.py \
  --pred-dir llm_run/raw_llm_json_gold20 \
  --gold-dir annotation \
  --report-dir llm_run/reports_gold20
```

Only continue to all 200 papers if precision/recall is acceptable.

Recommended minimum before full run:

- direct compressive-strength precision: `>= 0.90`
- direct compressive-strength recall: ideally `>= 0.70`
- review queue captures figure-derived/ambiguous cases

## 6. Generate Review Workbooks

After JSON validation:

```bash
python llm_extraction_pipeline/scripts/build_workbooks.py \
  --input-dir llm_run/raw_llm_json \
  --output-dir llm_run/workbooks
```

Each workbook should have:

```text
README
paper
mixture_components
strength_results
conditions
figures
evidence
review_queue
data_dictionary
table_preview
```

Each sheet must have a first-row header, frozen first row, filters, and confidence fields.

## 7. Full 200-Paper Run

For synchronous API calls:

```bash
python llm_extraction_pipeline/scripts/call_openai_responses.py \
  --packet-dir llm_run/packets \
  --output-dir llm_run/raw_llm_json \
  --resume
```

Use `--resume` so completed papers are skipped.

## 8. Batch API Option

For cheaper/asynchronous processing, build JSONL:

```bash
python llm_extraction_pipeline/scripts/build_batch_jsonl.py \
  --packet-dir llm_run/packets \
  --output llm_run/batch_requests/cement_extraction_requests.jsonl
```

Upload the JSONL file to the Batch API with endpoint `/v1/responses`.

After the batch completes:

```bash
python llm_extraction_pipeline/scripts/parse_batch_results.py \
  --batch-output llm_run/batch_results/output.jsonl \
  --output-dir llm_run/raw_llm_json
```

Then run validation and workbook generation.

## 9. Merge to Candidate Database

Only direct candidates go into the confirmed/candidate table automatically:

```text
value_status in {"exact_table_value", "explicit_text_value"}
confidence >= 0.90
mixture_id not blank
age_days not blank
unit == "MPa"
evidence_ids not blank
validator errors == 0
```

Everything else remains in `review_queue`.

## 10. Suggested Operating Order

1. Prepare 1 packet.
2. Run 1 API call.
3. Inspect 1 output JSON.
4. Build 1 workbook.
5. Run 20 gold papers.
6. Evaluate precision/recall.
7. Tune prompt/schema.
8. Run all remaining papers.
9. Build workbooks.
10. Human review.
11. Merge accepted/corrected data into database.

## 11. Cost-Control Tips

- Send selected pages/tables, not entire PDFs.
- Use 20 gold papers to tune before full run.
- Use Batch API for large asynchronous runs.
- Use a cheaper verifier after high-accuracy extraction.
- Cache every response by `paper_id`.
- Never rerun successful papers unless prompt/schema changes.
