# Typhoon OCR Runner

Runner นี้ส่ง PNG 300 DPI RGB จาก Common PDF Renderer เข้า official Typhoon OCR API
โดยเก็บ raw Markdown ที่ API คืนมาแบบไม่แก้ไข และสร้าง plain UTF-8 `.txt` แบบ
deterministic สำหรับ evaluator เดิม

## Installation

```powershell
.\.venv\Scripts\python.exe -m pip install -r `
  experiments/ocr-benchmark/runners/typhoon/requirements.txt
```

ตั้ง API key ใน environment โดยไม่เขียนลงไฟล์หรือ command line:

```powershell
$env:TYPHOON_OCR_API_KEY = '<API key>'
```

Runner รองรับ `TYPHOON_OCR_API_KEY`, `TYPHOON_API_KEY` และ `OPENAI_API_KEY`
ตามลำดับ แต่ metadata เก็บเฉพาะชื่อ environment variable ไม่เก็บ secret

## Input Contract

ทุก PNG ต้องมี `.render.json` จาก Common PDF Renderer อยู่ข้างกัน Runner จะตรวจ:

- `dpi = 300`
- `color_space = RGB`
- `format = PNG`
- `preprocessing = false`
- filename และ SHA-256 ตรงกับ PNG
- width/height metadata มีค่าและไฟล์มี PNG signature

Runner encode bytes ของ PNG ต้นฉบับเป็น `data:image/png;base64,...` โดยตรง ไม่ใช้
`ocr_document()` helper เนื่องจาก helper รุ่น 0.4.1 resize และ encode image เป็น JPEG

## Configuration

| Setting | Value |
| --- | --- |
| API | `https://api.opentyphoon.ai/v1` |
| Model | `typhoon-ocr` (Typhoon OCR 1.5) |
| Task/prompt | official `get_prompt("v1.5")` |
| Figure language | Thai |
| Max tokens | 16384 |
| Temperature | 0.1 |
| Top-p | 0.6 |
| Repetition penalty | 1.1 |
| Input | original PNG bytes, 300 DPI RGB |
| Preprocessing | none |

## Raw Markdown And Plain Text

แต่ละ document มี output สามไฟล์:

```text
experiments/ocr-benchmark/outputs/typhoon/
|-- document_007_page_004.md
|-- document_007_page_004.txt
`-- document_007_page_004.json
```

`.md` เป็น response string จาก API แบบ UTF-8 โดยไม่เติม newline ส่วน `.txt` สร้างด้วย
algorithm `commonmark-html-text-v1` และ `markdown-it-py==4.2.0`:

1. Parse Markdown ด้วย CommonMark และเปิด table rule
2. Map `<page_number>` wrapper เป็น valid HTML span แล้วอ่าน visible text nodes ตามลำดับ
3. เก็บ text ใน headings, paragraphs, lists, code, figures และ page numbers
4. คั่น table cells ด้วย tab และ block/rows ด้วย newline
5. ตัด whitespace หัว/ท้ายแต่ละบรรทัดและตัดบรรทัดว่าง
6. เติม newline ท้าย `.txt` เมื่อมีข้อความ

ไม่มี spell correction, Unicode normalization, การแก้คำ หรือ accuracy postprocessing
SHA-256 ของทั้ง raw `.md` และ evaluator `.txt` ถูกบันทึกใน metadata

## Usage

ไฟล์เดียว:

```powershell
.\.venv\Scripts\python.exe `
  experiments/ocr-benchmark/runners/typhoon/run_typhoon.py `
  --input datasets/ocr-benchmark/images/document_007_page_004.png `
  --output experiments/ocr-benchmark/outputs/typhoon
```

Pilot 3 เอกสารแรก:

```powershell
.\.venv\Scripts\python.exe `
  experiments/ocr-benchmark/runners/typhoon/run_typhoon.py `
  --input datasets/ocr-benchmark/images `
  --output experiments/ocr-benchmark/outputs/typhoon `
  --limit 3
```

รันครบ 20 หลัง pilot ผ่าน:

```powershell
.\.venv\Scripts\python.exe `
  experiments/ocr-benchmark/runners/typhoon/run_typhoon.py `
  --input datasets/ocr-benchmark/images `
  --output experiments/ocr-benchmark/outputs/typhoon `
  --overwrite
```

ค่า request interval เริ่มต้น 3.1 วินาทีเพื่ออยู่ภายใน rate limit 20 requests/minute
ของ model ใช้ `--request-interval-seconds` เฉพาะเมื่อ quota ที่ได้รับแตกต่างออกไป

## Evaluation

```powershell
.\.venv\Scripts\python.exe experiments/ocr-benchmark/evaluation/evaluate_ocr.py `
  --manifest datasets/ocr-benchmark/manifests/manifest.csv `
  --ground-truth datasets/ocr-benchmark/ground-truth `
  --predictions experiments/ocr-benchmark/outputs/typhoon `
  --output experiments/ocr-benchmark/outputs/evaluation `
  --engine typhoon `
  --limit 3 `
  --overwrite
```

Evaluator อ่านเฉพาะ `.txt`; raw `.md` ไม่ถูกแก้หรือส่งผ่าน normalization ของ runner

## Tests

```powershell
.\.venv\Scripts\python.exe -m py_compile `
  experiments/ocr-benchmark/runners/typhoon/run_typhoon.py `
  experiments/ocr-benchmark/runners/typhoon/test_run_typhoon.py

.\.venv\Scripts\python.exe `
  experiments/ocr-benchmark/runners/typhoon/run_typhoon.py --help

.\.venv\Scripts\python.exe -m unittest discover `
  -s experiments/ocr-benchmark/runners/typhoon `
  -p 'test_*.py' -v
```
