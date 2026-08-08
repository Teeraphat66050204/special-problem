# OCR Benchmark

This experiment will compare four OCR systems:

- EasyOCR
- Tesseract OCR
- PaddleOCR
- Typhoon OCR

## First Benchmark Round

The first round is a **Raw OCR Benchmark**. Every OCR system must receive the
same input image so the results can be compared fairly. PDF pages will be
converted by one Common PDF Renderer using these fixed settings:

- Output format: PNG
- Resolution: 300 DPI
- Color mode: RGB
- Preprocessing: none

The first round will not use Docling, spell correction, ensemble techniques,
or fallback logic. Those techniques may be considered only after a baseline
OCR system has been selected from the raw benchmark results.
