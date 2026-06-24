# LLM Pipeline for Cement Compressive-Strength Extraction

This pipeline is designed for the 200-paper cement/concrete literature set. It uses the 20 human-confirmed annotation workbooks as gold examples, then calls an LLM API paper-by-paper to produce review-ready annotation workbooks and database-ready CSV/SQLite outputs.

The target property is `compressive_strength`.

## 0. Design Goal

The pipeline separates three classes of data:

1. **Direct insert candidates**
   - Exact compressive-strength values from tables or explicit text.
   - Mixture ID, age, value, unit, and evidence are all mapped.
   - High confidence, usually `>= 0.90`.

2. **Review queue**
   - Figure-only values, ambiguous table headers, missing age/unit, unclear mixture mapping, inferred values, or graph digitization needs.
   - These are useful but should not be inserted as gold until reviewed.

3. **Excluded non-target data**
   - Flexural strength, splitting tensile strength, modulus, density, porosity, permeability, shrinkage, chloride diffusion, etc.

## 1. Recommended Directory Layout

```text
cement_database_project/
  cbm_papers_subset_200/
    *.pdf
  annotation/
    CBM0008_..._clean_annotation_for_review.xlsx
    ...
  llm_extraction_pipeline/
    README.md
    prompts/
      extract_paper.md
    schemas/
      cement_extraction.schema.json
    scripts/
      prepare_packets.py
      call_openai_responses.py
      build_workbooks.py
      validate_and_score.py
      merge_to_database.py
  llm_run/
    packets/
      CBM0001/context_packet.json
    raw_llm_json/
      CBM0001/extraction.json
    workbooks/
      CBM0001_..._llm_annotation_for_review.xlsx
    csv/
      paper.csv
      mixture_components.csv
      strength_results.csv
      conditions.csv
      figures.csv
      evidence.csv
      review_queue.csv
    database/
      cement_strength_llm_candidates.db
    reports/
      run_summary.csv
      validation_report.md
```

## 2. Inputs

Required:

- `cbm_papers_subset_200/*.pdf`
- 20 human-confirmed workbooks in `annotation/*.xlsx`
- JSON schema: `llm_extraction_pipeline/schemas/cement_extraction.schema.json`
- Prompt template: `llm_extraction_pipeline/prompts/extract_paper.md`

Optional but recommended:

- Page images for pages that include compressive-strength figures.
- Table CSVs extracted by `pdfplumber`, Camelot, Tabula, or a comparable table extractor.
- A manually curated few-shot set from the 20 gold papers.

## 3. Paper Packet Preparation

For each PDF, create a compact `context_packet.json`.

Recommended packet structure:

```json
{
  "paper_id": "CBM0001",
  "pdf_filename": "10.1016_j.conbuildmat.2009.11.010.pdf",
  "doi": "10.1016/j.conbuildmat.2009.11.010",
  "title": "...",
  "pages": [
    {
      "page": 2,
      "reason": ["mix proportion table"],
      "text": "..."
    }
  ],
  "tables": [
    {
      "table_id": "T002_01",
      "page": 2,
      "caption": "Table 4. Mix proportions...",
      "text": "...",
      "csv_path": "tables/T002_01.csv"
    }
  ],
  "figures": [
    {
      "figure_id": "F8",
      "page": 6,
      "caption": "Fig. 8. 28-day mechanical properties...",
      "image_path": "pages/page_006.png",
      "reason": ["compressive strength figure"]
    }
  ]
}
```

### Page Selection Rules

Always include:

- First page: title, abstract, keywords.
- Pages containing `compressive strength`, `cube strength`, `cylinder strength`, `compressive stress`, or `strength tests`.
- Pages containing `mix proportion`, `mixture`, `cement`, `water`, `aggregate`, `binder`, `w/c`, `water-to-cement`, `replacement`.
- Pages containing figure/table captions near compressive strength.
- Methods pages with curing/testing/specimen information.

For long papers, do not send the full PDF text by default. Send the selected packet first, then do a second pass only if the model asks for missing evidence.

## 4. LLM Extraction Call

Use structured outputs with a strict JSON Schema. OpenAI documentation says Structured Outputs can be supplied with `text.format` or `response_format` using `type = json_schema` and `strict = true`, and recommends clear schema key names/descriptions for quality.

Call one paper per request for normal use. For cost-efficient large runs, use Batch API with `/v1/responses` if latency is not important.

### Recommended Model Strategy

Use two tiers:

1. **High-accuracy extraction model**
   - Use for the final extraction JSON.
   - Best for complex tables, figure interpretation, and long scientific context.

2. **Cheaper verifier model or rule verifier**
   - Checks JSON validity, field completeness, impossible values, duplicated IDs, and whether direct insert candidates have evidence.

Do not tune the whole workflow around a single hardcoded model name. Keep `MODEL_EXTRACT` and `MODEL_VERIFY` as environment variables.

## 5. Prompt Contract

The prompt must tell the model:

- Extract only `compressive_strength`.
- Each component is one row in `mixture_components`.
- Table/text exact values can be direct insert candidates.
- Figure-only values must be approximate or review queue.
- Every data row must cite evidence IDs.
- Missing or ambiguous data goes to `review_queue`.
- Output only JSON matching the schema.

Use:

- `prompts/extract_paper.md`
- `schemas/cement_extraction.schema.json`

## 6. Validation After LLM

Run deterministic validation before creating workbooks.

### JSON/schema validation

Reject or retry if:

- JSON does not match schema.
- Required sheets are missing.
- `evidence_ids` reference nonexistent evidence.
- IDs are duplicated.

### Scientific validation

Flag for review if:

- Compressive strength is outside a plausible range, e.g. `< 0.1 MPa` or `> 250 MPa`.
- Age is missing for a direct insert candidate.
- Unit is not MPa and no conversion note exists.
- `value_status` is exact but `is_approximate = true`.
- Figure-derived values have no figure/page evidence.
- A direct value has confidence `< 0.90`.
- Same paper/mixture/age has conflicting values.

### Database rule

Only insert automatically into the confirmed table when:

```text
value_status in {"exact_table_value", "explicit_text_value"}
confidence >= 0.90
mixture_id not blank
age_days not blank
unit == "MPa"
evidence_ids not blank
no validator errors
```

Everything else remains in `review_queue`.

## 7. Workbook Generation

For each paper, generate one `.xlsx` with the same sheets as your gold workbooks:

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

Formatting requirements:

- First row of every sheet is a visible header.
- Freeze first row.
- Add filters.
- Include `confidence`.
- Keep `human_decision`, `final_value`, and `corrected_amount` blank for human review.

## 8. Review Workflow

Recommended human review order:

1. Open `review_queue`.
2. Resolve high-priority items:
   - figure digitization
   - ambiguous mixture mapping
   - missing age/unit
   - table header ambiguity
3. Check `strength_results`.
4. Check `mixture_components`.
5. Fill:
   - `human_decision = accept | correct | reject | uncertain`
   - `final_value`
   - `corrected_amount`
   - notes

After review, rebuild gold CSV/SQLite using only accepted/corrected rows.

## 9. Evaluation Against the 20 Gold Papers

Before processing all 200 papers with an API, run the pipeline on the 20 gold papers and compare against your human-confirmed outputs.

Minimum metrics:

- `strength_results` precision/recall:
  - match by paper ID, property, age, unit, and numeric value within tolerance.
  - report with `±0.5 MPa`, `±1.0 MPa`, and `±2.0 MPa`.
- `mixture_components` precision/recall:
  - match by paper ID, mixture ID, normalized component, amount, and unit.
- Review queue quality:
  - count how many gold records appear as review candidates rather than direct candidates.

Target for useful production:

- Direct strength precision: `>= 0.90`
- Direct strength recall: ideally `>= 0.70`
- Figure candidate recall: high enough that figure-derived values are not missed.
- Review queue false positives: manageable for human workload.

## 10. Batch API Strategy

For 200 papers, you can run synchronous one-paper calls while developing. For a larger batch, create a JSONL file where each line is one request.

Batch is useful when:

- You do not need immediate responses.
- You want cheaper/asynchronous processing.
- You can tolerate retrying failed lines.

Each JSONL line should include:

- `custom_id`: paper ID.
- endpoint: `/v1/responses`.
- request body with model, prompt, packet text, and JSON schema.

## 11. Error Handling and Retries

Retry once with a narrower prompt when:

- Schema validation fails.
- JSON is truncated.
- Evidence links are missing.
- Direct insert candidates have insufficient evidence.

Second retry strategy:

- Provide only the problematic sheet/table/page.
- Ask the model to repair the existing JSON rather than re-extract the whole paper.

Do not silently accept repaired outputs without validator checks.

## 12. Data Privacy and Copyright Notes

Using an API sends selected paper text/tables/images to the API provider. Reduce exposure by:

- Sending selected packets rather than full PDFs.
- Avoiding unnecessary full-page text.
- Keeping evidence snippets short.
- Storing only extracted structured data and short evidence snippets.

## 13. Recommended Run Plan

1. Build packets for the 20 gold papers.
2. Run API extraction on the 20 gold papers.
3. Evaluate precision/recall against gold.
4. Tune prompt/schema.
5. Run 20 more non-gold papers.
6. Manually review 5-10 outputs.
7. Run all remaining papers by Batch API.
8. Validate and create workbooks.
9. Merge direct candidates into candidate database.
10. Human-review queue items.

## 14. Key OpenAI API References

- Structured Outputs: use strict JSON Schema output for reliable machine-readable extraction.
- Responses API: create model responses from text/image inputs and produce text or JSON outputs.
- Batch API: supports `/v1/responses` for asynchronous large-batch processing.
