# Document Processing

This standalone package currently implements this pipeline:

```text
PDF
  -> Abstract Page Detection
  -> Text Layer Extraction
  -> Text Layer Quality Assessment
  -> Conditional OCR Fallback
  -> Unified Extracted Text
  -> Text Normalization
  -> Metadata Extraction
  -> Metadata Validation (next)
```

It does not depend on the API application, benchmark OCR runners, a database,
or a metadata validation pipeline.

## Installation

From the repository root:

```powershell
python -m pip install -r packages/document-processing/requirements.txt
```

## Algorithm

By default, the detector opens the PDF with PyMuPDF and reads the first 15
pages with `page.get_text("text", sort=True)`. Each page is normalized with
Unicode NFC, trimmed, and collapsed whitespace. No OCR or full metadata text
normalization is performed.

The detector ranks pages with a configurable scoring model. Positive evidence
includes:

- an exact `บทคัดย่อ` or `ABSTRACT` heading;
- Thai or English advisor labels;
- Thai or English keyword labels;
- a student ID pattern; and
- enough paragraph-like text to resemble an abstract body.

When an English abstract is confidently detected, the detector also checks
the preceding front-matter pages. A page with a front-matter page marker and
paragraph structure can remain a Thai structural candidate even when legacy
font encoding damages the Thai text layer. Vector line/rectangle structure is
used to reject approval/signature pages with tables. This is PDF structure
inspection only; it does not render or OCR the page.

Table-of-contents evidence reduces the score. Penalties cover an explicit
contents heading, many lines ending with page numbers, and many short numbered
headings. A heading alone is not sufficient: a page must also contain
supporting evidence and meet the score threshold.

All weights, structural limits, the threshold, and the confidence scale live
in the immutable `ScoringConfig` dataclass. Pass a modified configuration to
`detect_abstract_page()` when tuning is required; use one configuration for a
consistent run.

## Python Usage

Because the parent directory contains a hyphen, add it to `PYTHONPATH` when
importing from elsewhere in the repository:

```python
import sys

sys.path.insert(0, "packages/document-processing")

from abstract_detection import detect_abstract_page

result = detect_abstract_page("document.pdf", max_pages=15, top_k=5)
```

`page_number` is 1-based for people. `page_index` is 0-based for PyMuPDF.

- `primary_candidate` is only the highest-scoring qualifying page. It is a
  convenience value, not the complete pipeline input.
- `abstract_pages` contains every qualifying Thai, English, or structural
  abstract page. Downstream processing, including a future OCR fallback,
  should consume this list instead of only `primary_candidate`.
- `candidates` contains the top `top_k` ranked pages, including
  below-threshold pages for inspection and recall evaluation.

Every candidate contains `page_number`, `page_index`, `language`, `score`,
`confidence`, `matched_features`, `passed_threshold`, and `text_length`.
The legacy top-level `page_number`, `page_index`, `score`, and related fields
mirror `primary_candidate` for compatibility.

`confidence` is a deterministic score-to-range mapping for ranking and manual
review; it is not a statistically calibrated probability.

An abridged successful result looks like this. Candidate objects also include
`page_index`, `confidence`, `language`, `matched_features`,
`passed_threshold`, and `text_length`.

```json
{
  "primary_candidate": {
    "page_number": 4,
    "page_index": 3,
    "language": "thai",
    "score": 11.0,
    "matched_features": ["thai_abstract_heading", "thai_keywords"]
  },
  "page_number": 4,
  "page_index": 3,
  "score": 11.0,
  "confidence": 0.929,
  "matched_features": [
    "thai_abstract_heading",
    "thai_advisor",
    "thai_keywords",
    "long_paragraph_text"
  ],
  "language": "thai",
  "requires_manual_selection": false,
  "scanned_pages": 15,
  "document_page_count": 80,
  "candidates": [
    {
      "page_number": 4,
      "score": 11.0,
      "passed_threshold": true
    }
  ],
  "abstract_pages": [
    {
      "page_number": 4,
      "score": 11.0,
      "passed_threshold": true
    }
  ]
}
```

When no page passes the threshold, `page_number` and `page_index` are `null`,
`requires_manual_selection` is `true`, and ranked candidates remain available
for manual review.

## Text Layer Extraction and Quality

The text-layer stage calls Abstract Page Detection and processes every item in
`abstract_pages`; `primary_candidate` is retained only as detection context.
It extracts each page with PyMuPDF using `page.get_text("text", sort=True)`.

```python
import sys

sys.path.insert(0, "packages/document-processing")

from text_layer import analyze_abstract_text_layers

result = analyze_abstract_text_layers("document.pdf")
```

`extract_page_text(pdf_path, page_index)` can be used independently for one
zero-based page. `extract_abstract_text_layers(pdf_path, abstract_pages)`
accepts the complete Abstract Detection page list and preserves its order and
language labels.

Two text values are deliberately separate:

- `raw_text` is the exact string returned by PyMuPDF and is never rewritten.
- `normalized_for_quality_text` is an NFC-normalized assessment copy with
  normalized line endings, trimmed lines, and collapsed repeated whitespace.

Availability and usability are also separate. `available: true` only means
that non-whitespace text was extracted. A present but damaged layer can still
be `quality: "poor"` with `requires_ocr: true`.

The deterministic quality score combines four components configured in the
immutable `QualityConfig` dataclass:

- text amount: 0.25;
- readable character quality: 0.30;
- language plausibility for the candidate language: 0.25; and
- expected abstract structure: 0.20.

The structural component uses heading (0.30), advisor (0.15), keywords
(0.20), student ID (0.10), and paragraph-like text (0.25). The default
`good` threshold is 0.70. Empty text is always `missing`; other scores below
the threshold are `poor`. The assessment also applies configurable penalties
for replacement/control characters, unusual symbols, suspicious Latin
Extended characters, and non-Thai characters embedded inside Thai word
sequences. All weights, thresholds, and corruption penalties are centralized
in `QualityConfig`.

An abridged analyzed page looks like this:

```json
{
  "page_number": 4,
  "page_index": 3,
  "language": "thai",
  "text_layer": {
    "available": true,
    "raw_text": "...",
    "normalized_for_quality_text": "...",
    "quality_score": 0.62,
    "quality": "poor",
    "requires_ocr": true,
    "reasons": ["broken_thai_intraword_sequences"]
  }
}
```

## Conditional OCR Fallback

`ocr.process_abstract_pages()` consumes every page in `abstract_pages`, not
only `primary_candidate`. Pages classified as `good` use their untouched
`raw_text` and never invoke the renderer or OCR provider. Pages classified as
`poor` or `missing` are rendered individually with PyMuPDF as an in-memory
300 DPI RGB PNG with no preprocessing, then passed to an injected
`OCRProvider`:

```python
import sys

sys.path.insert(0, "packages/document-processing")

from ocr import TyphoonProvider, process_abstract_pages

result = process_abstract_pages(
    "document.pdf",
    ocr_provider=TyphoonProvider(),
)
```

The orchestration layer depends only on `provider.extract(page_image)`. The
provider returns an `OCRResult` containing provider-neutral fields such as
`success`, `text`, `raw_text`, `raw_format`, `processing_time_ms`, and a
structured error. Tests can inject a fake provider without network access,
and another OCR provider can be added without modifying fallback logic.

Every processed abstract page exposes one downstream `text` field:

- `text_source: "text_layer"` means `text` is original PyMuPDF text and OCR
  was not called.
- `text_source: "ocr"` means `text` is deterministic plain text converted
  from the provider response. Typhoon's original Markdown remains in
  `ocr.raw_text` with `ocr.raw_format: "markdown"`.
- `text_source: null` means OCR failed. The result sets
  `processing_status: "ocr_failed"`, `requires_manual_review: true`, and a
  structured `error`.

The pipeline never silently falls back to a text layer already classified as
`poor` or `missing` after OCR failure.

## Text Normalization

`normalization.normalize_text()` converts unified extracted text into a
canonical representation for future Metadata Extraction. Normalization is
formatting, not error correction: it never guesses Thai words, repairs OCR
spelling, applies document-specific substitutions, or removes content
punctuation.

```python
import sys

sys.path.insert(0, "packages/document-processing")

from normalization import normalize_processed_document, normalize_text

text_result = normalize_text("  Cafe\u0301\t title  \r\n")
print(text_result.normalized_text)

# `processing_result` is the complete Conditional OCR Fallback result.
normalized_document = normalize_processed_document(processing_result)
```

The default immutable `NormalizationConfig` applies these conservative rules:

- Unicode NFC normalization (never NFKC/NFKD by default);
- CRLF, CR, and Unicode line separators to LF;
- removal of BOM and selected stray zero-width characters, while retaining
  ZWNJ and ZWJ by default;
- NBSP and other horizontal Unicode space variants to regular spaces;
- tabs to spaces and repeated horizontal spaces to one space;
- per-line whitespace trimming, document-edge trimming, and no more than two
  consecutive blank lines.

Line order and paragraph breaks remain intact. The original unified page
`text` is never overwritten: a normalized page adds `normalized_text`,
`normalization_status`, and structured `normalization` metadata containing
operations, warnings, and length/line statistics. Thai and English abstract
pages are normalized separately and remain separate items in `abstract_pages`.

If OCR failed, processing was unsuccessful, or `text` is `null`, normalization
is skipped; `normalized_text` remains `null` and the page requires manual
review. Whitespace-only successful text is marked `empty` and also requires
review. Suspicious character-separated Thai can emit
`suspicious_thai_character_spacing`, but the text is deliberately not joined
or corrected.

Normalization is idempotent: applying it again to canonical text returns the
same text. Callers may replace the default config explicitly, including the
Unicode form, blank-line limit, tab handling, whitespace collapsing, and the
selected removable zero-width characters.

## Metadata Extraction

`metadata_extraction.extract_metadata()` consumes the output of
`normalize_processed_document()` directly. It reads every usable
`abstract_pages` item independently and never opens a PDF, performs OCR, calls
an external service, or mutates upstream raw/normalized text.

```python
import sys

sys.path.insert(0, "packages/document-processing")

from metadata_extraction import extract_metadata

extraction = extract_metadata(normalized_document)
metadata = extraction.metadata
```

The metadata schema contains `title_th`, `title_en`, a multi-item `students`
list of name/ID pairs, `degree`, `department`, `faculty`, `academic_year`,
`advisor`, `co_advisors`, `abstract_th`, `abstract_en`, and `keywords`. Missing
scalar fields are `null`; missing list fields are empty lists.

Extraction is deterministic and rule-based:

- centralized Thai/English label variants accept colons, attached values, and
  values on following lines;
- titles use explicit title labels or conservative top-of-page inference and
  stop before structurally clear student/front-matter sections;
- student IDs use a configurable 7–13 digit pattern and are paired with names
  only by same-line evidence or bounded line proximity;
- academic and advisor values use bounded label context and preserve prefixes,
  spelling, digits, and calendar representation from the source;
- abstract bodies start after an explicit abstract heading and stop before the
  keyword section or page end; and
- keywords split only on supported comma/semicolon variants, never whitespace
  alone, so multi-word English keywords remain intact.

Every field includes its selected value, deterministic confidence, source
page/language/line indexes, method, compact evidence, all candidates,
alternatives, and warnings. Thai/English page candidates are resolved in a
stable order. Conflicting values such as `2564` and `2021` are retained as
alternatives with `conflicting_<field>_candidates`; the extractor does not
perform translation, Buddhist/Gregorian conversion, spell correction, Thai
word reconstruction, master-data lookup, or semantic validation.

`extraction_status` is `success` when usable metadata has no review warnings,
`partial` when metadata is available but missing/ambiguous/conflicting or
upstream-suspicious, and `failed` when no normalized text or meaningful
metadata is available. Missing titles, students, or advisor produce explicit
warnings. Missing co-advisors are a normal empty list. Upstream normalization
warnings such as `suspicious_thai_character_spacing` are propagated and lower
candidate confidence without changing text.

### Typhoon Provider

The production Typhoon provider uses the official model and request
configuration validated by the benchmark runner while remaining independent
of `experiments/`. It reads the API key only from the server-side environment:

```powershell
$env:TYPHOON_OCR_API_KEY="<key>"
```

The key is never printed or included in result metadata. A missing key or
dependency is returned as a controlled provider error. Transient timeouts,
connection failures, HTTP 429, and HTTP 5xx responses use configurable bounded
exponential retries. Authentication failures, malformed requests, and other
permanent client errors are not retried. Request interval and concurrency are
configurable locally; a future backend job queue remains responsible for
multi-user scheduling.

## CLI

Abstract Page Detection:

```powershell
python packages/document-processing/abstract_detection/detect_abstract_page.py `
  --input datasets/ocr-benchmark/pdfs/document_007.pdf `
  --max-pages 15 `
  --top-k 5
```

The CLI writes the complete structured result as UTF-8 JSON, including page
numbers, scores, confidence values, matched features, and candidate status.

Text Layer Extraction and Quality Assessment:

```powershell
python packages/document-processing/text_layer/analyze_text_layer.py `
  --input datasets/ocr-benchmark/pdfs/document_007.pdf `
  --max-pages 15 `
  --top-k 5
```

Add `--json` to emit the complete structured result, including raw text,
quality features, reasons, and the page numbers currently marked
`requires_ocr`.

Conditional OCR Fallback:

```powershell
python packages/document-processing/ocr/process_document.py `
  --input datasets/ocr-benchmark/pdfs/document_007.pdf
```

Use `--json` for the complete provider-neutral result. Retry, timeout, request
interval, and concurrency settings are exposed as CLI options. The command
returns a nonzero exit code when any OCR-routed page fails.

Text Normalization from a UTF-8 file:

```powershell
python packages/document-processing/normalization/normalize_text.py `
  --input-text-file sample.txt
```

Omit `--input-text-file` to read stdin. Add `--json` to emit the original and
normalized text, preserved lines, operations, warnings, and statistics. This
standalone command never invokes an OCR provider.

Run offline normalization validation over the benchmark PDFs using production
Text Layer/Quality routing and the stored Thai reference text for OCR-routed
pages:

```powershell
python packages/document-processing/normalization/validate_normalization.py `
  --pdf-dir datasets/ocr-benchmark/pdfs `
  --manifest datasets/ocr-benchmark/manifests/manifest.csv `
  --precomputed-text-dir datasets/ocr-benchmark/ground-truth
```

The report separates text-layer and precomputed OCR inputs and includes
changed/unchanged/skipped counts, warnings, lengths, content-preservation
checks, and idempotence failures. It is normalization validation, not an OCR or
metadata accuracy measurement, and it never invokes an OCR API.

Metadata Extraction from a stored normalized pipeline result:

```powershell
python packages/document-processing/metadata_extraction/extract_metadata.py `
  --input-json normalized_document.json
```

Omit `--input-json` to read JSON from stdin. Output always includes metadata,
field-level confidence/evidence/candidates, warnings, status, and extraction
statistics. This command only parses supplied normalized text and cannot invoke
OCR.

## Benchmark Evaluation

`abstract_detection/benchmark_ground_truth.json` contains manually verified
Thai and English abstract start pages for the 20 benchmark PDFs. Thai pages
were checked against the rendered page images; English pages were checked from
the PDF front-matter `Title`/`Abstract` structure. The mappings were prepared
independently of detector output.

Run the evaluation from the repository root:

```powershell
python packages/document-processing/abstract_detection/evaluate_abstract_detection.py `
  --pdf-dir datasets/ocr-benchmark/pdfs `
  --max-pages 15
```

The report includes:

- Thai Abstract Detection Accuracy: expected Thai page appears in
  language-specific `abstract_pages`;
- English Abstract Detection Accuracy: expected English page appears in
  language-specific `abstract_pages`;
- Any Abstract Detection Accuracy: at least one expected abstract page is in
  `abstract_pages` for the document;
- Top-3 Recall: expected Thai and English pages found among the first three
  ranked `candidates`, measured over all expected abstract pages; and
- document-level expected/predicted pages for every miss.

## Metadata Extraction Evaluation

`metadata_extraction/benchmark_metadata_ground_truth.json` contains manual
metadata transcribed independently from the existing human-reviewed Thai
references and directly reviewed English PDF front matter for all 20 benchmark
documents. Extractor predictions were not copied into ground truth. Fields with
ambiguous keyword boundaries are omitted from keyword evaluation, and full
abstract bodies are not part of this first metadata ground truth.

Run the offline evaluator without calling an OCR API:

```powershell
python packages/document-processing/metadata_extraction/evaluate_metadata_extraction.py `
  --pdf-dir datasets/ocr-benchmark/pdfs `
  --manifest datasets/ocr-benchmark/manifests/manifest.csv `
  --precomputed-text-dir datasets/ocr-benchmark/ground-truth
```

Scalar Field Accuracy is exact matches divided by evaluable ground-truth
fields after evaluation-only NFC, case-folding, and whitespace collapse. It
does not translate, correct spelling, convert years, or remove punctuation.
Coverage is non-empty extractions divided by evaluable fields; verified empty
optional lists count as covered values. Students require exact `(name,
student_id)` pairs. Students, IDs, co-advisors, and keywords additionally
report global item precision, recall, and F1. List exact match is
order-independent. If future ground truth adds abstract bodies, the evaluator
also reports normalized exact match and supplementary character error rate.

The report includes every mismatch, categorized causes, review counts, and
local extraction time per document. Accuracy is intentionally reported before
any generic heuristic changes and must not be converted into document-specific
rules.

## Text Layer Quality Evaluation

`text_layer/benchmark_quality_ground_truth.json` contains manually assigned
`good`, `poor`, or `missing` usability labels for all 40 benchmark abstract
pages. Each label was assigned by comparing the visible PDF page with raw
PyMuPDF text; classifier output was not used to determine the label. Review
rationales are stored with every record and are not imported by production
quality logic.

Run the classification evaluation from the repository root:

```powershell
python packages/document-processing/text_layer/evaluate_text_layer_quality.py `
  --pdf-dir datasets/ocr-benchmark/pdfs
```

Add the existing Thai OCR references as supplementary CER evidence:

```powershell
python packages/document-processing/text_layer/evaluate_text_layer_quality.py `
  --pdf-dir datasets/ocr-benchmark/pdfs `
  --manifest datasets/ocr-benchmark/manifests/manifest.csv `
  --thai-reference-dir datasets/ocr-benchmark/ground-truth
```

The evaluator reports overall, Thai, and English multiclass accuracy. It also
treats `poor` and `missing` as a positive `requires_ocr` decision and reports
precision, recall, F1, false positives, false negatives, and every mismatch.
False negatives are operationally more serious because they allow damaged text
to continue to metadata extraction. CER reuses the existing OCR evaluator's
normalization and character-distance functions and remains supplementary; it
does not assign usability labels.

## Tests

From the repository root, run every Document Processing test with one command:

```powershell
python -m unittest discover `
  -s packages/document-processing `
  -p "test_*.py"
```

`document-processing` contains a hyphen and is therefore used as the unittest
discovery/import root rather than imported as a package name. Its five child
directories are regular Python packages. To run one suite while retaining the
same package import context, pass the explicit top-level directory:

```powershell
python -m unittest discover `
  -s packages/document-processing/abstract_detection `
  -t packages/document-processing `
  -p "test_*.py"

python -m unittest discover `
  -s packages/document-processing/text_layer `
  -t packages/document-processing `
  -p "test_*.py"

python -m unittest discover `
  -s packages/document-processing/ocr `
  -t packages/document-processing `
  -p "test_*.py"

python -m unittest discover `
  -s packages/document-processing/normalization `
  -t packages/document-processing `
  -p "test_*.py"

python -m unittest discover `
  -s packages/document-processing/metadata_extraction `
  -t packages/document-processing `
  -p "test_*.py"
```

## Limitations

- OCR is conditional on the current quality classifier. A quality false
  negative continues to use the text layer; fallback contains no
  document-specific overrides.
- OCR only applies after Abstract Page Detection. Scanned pages without useful
  detection evidence can still require manual page selection.
- The method is a structural heuristic, not a semantic classifier. Documents
  with unusual headings or very short abstracts may need tuned weights.
- Only the first `max_pages` pages are considered. Increase the value for
  documents whose front matter is unusually long.
- Reading order and extracted characters depend on the PDF text layer exposed
  by PyMuPDF.
- Quality scores are deterministic heuristics, not statistically calibrated
  probabilities. The labeled quality benchmark documents known mismatches,
  including false negatives that OCR fallback intentionally does not override.
- The Thai corruption heuristic detects recurring malformed character
  sequences but cannot identify every broken custom font encoding.
- `approximate_word_count` uses whitespace tokens and is not Thai linguistic
  tokenization.
- Structural recovery assumes the common academic front-matter pattern where
  a Thai abstract precedes a detected English abstract. Other templates may
  require configuration changes or manual review.
- Typhoon is an external paid service. Unit tests and routing validation inject
  fake providers; operators should restrict real smoke tests to the minimum
  pages needed and keep API keys outside source code and client output.
- Text normalization cannot repair corrupt font mappings, character-separated
  Thai, OCR spelling, reading order, or missing text. Those cases must be
  handled by Quality Assessment, OCR, or manual review rather than guessed by
  normalization.
- Metadata extraction is label- and structure-based, not semantic validation.
  Layouts flattened into one line, unknown label variants, bilingual
  translations, ambiguous whitespace-only keyword lists, and corrupt source
  text can produce alternatives, low confidence, partial output, or manual
  review. Metadata Validation, master-data checks, and correction remain out of
  scope.
