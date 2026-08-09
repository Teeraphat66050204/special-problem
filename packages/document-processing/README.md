# Abstract Page Detection

This package detects likely Thai and English abstract pages from a PDF text
layer. It is standalone and does not depend on the API application or any OCR
runner.

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

## CLI

```powershell
python packages/document-processing/abstract_detection/detect_abstract_page.py `
  --input datasets/ocr-benchmark/pdfs/document_007.pdf `
  --max-pages 15 `
  --top-k 5
```

The CLI writes the complete structured result as UTF-8 JSON, including page
numbers, scores, confidence values, matched features, and candidate status.

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

## Tests

```powershell
python -m unittest discover `
  -s packages/document-processing/abstract_detection `
  -p "test_*.py"
```

## Limitations

- This branch reads the PDF text layer and basic vector layout structure only.
  It contains no OCR fallback. Scanned pages without useful structural
  evidence can still require manual selection.
- The method is a structural heuristic, not a semantic classifier. Documents
  with unusual headings or very short abstracts may need tuned weights.
- Only the first `max_pages` pages are considered. Increase the value for
  documents whose front matter is unusually long.
- Reading order and extracted characters depend on the PDF text layer exposed
  by PyMuPDF.
- Structural recovery assumes the common academic front-matter pattern where
  a Thai abstract precedes a detected English abstract. Other templates may
  require configuration changes or manual review.
