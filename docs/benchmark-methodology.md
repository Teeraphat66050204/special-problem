# OCR Benchmark Methodology (Draft)

## Objective

Establish a fair and reproducible baseline comparison of EasyOCR, Tesseract
OCR, PaddleOCR, and Typhoon OCR before designing a proposed method.

## Benchmark Flow

1. Start with the existing ground-truth text.
2. Match each ground-truth file to its source PDF.
3. Identify the abstract page for each document.
4. Render that page through the Common PDF Renderer as PNG at 300 DPI in RGB
   mode, with no preprocessing.
5. Send the exact same rendered image to all four OCR systems.
6. Measure Character Error Rate (CER), Word Error Rate (WER), Field Accuracy,
   and Processing Time.
7. Perform error analysis to identify recurring failure patterns.
8. Select the Baseline OCR from the benchmark evidence.
9. Design the Proposed Method only after the baseline is established.

In summary:

```text
Existing Ground Truth
-> Match with PDF
-> Identify abstract page
-> Common PDF Renderer
-> Four OCR systems
-> CER / WER / Field Accuracy / Processing Time
-> Error Analysis
-> Select Baseline OCR
-> Design Proposed Method
```

## First-Round Constraints

The raw benchmark excludes preprocessing, Docling, spell correction, ensemble
methods, and fallback logic. OCR-specific runners and dependencies are also
outside this foundation task.
