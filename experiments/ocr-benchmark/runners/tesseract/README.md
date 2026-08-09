# Tesseract OCR Runner

Runner นี้รับไฟล์ PNG ที่ Common PDF Renderer สร้างไว้แล้วและส่งไฟล์ต้นฉบับเข้า
Tesseract โดยตรง ผลลัพธ์เป็น raw OCR `.txt` และ metadata `.json` ในรูปแบบเดียวกับ
EasyOCR runner ไม่มีการ resize, grayscale, threshold, denoise, deskew, sharpen,
spell correction หรือ postprocessing ข้อความ

## Installation

ติดตั้ง Tesseract OCR สำหรับ Windows พร้อม standard language data จากโครงการ
Tesseract โดยค่าเริ่มต้น runner จะค้นหา `tesseract.exe` จาก `PATH` และตำแหน่ง:

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
C:\Program Files (x86)\Tesseract-OCR\tesseract.exe
```

ตรวจการติดตั้งจาก executable จริง:

```powershell
& 'C:\Program Files\Tesseract-OCR\tesseract.exe' --version
& 'C:\Program Files\Tesseract-OCR\tesseract.exe' --list-langs
```

Runner ใช้เฉพาะ directory `tessdata` ที่อยู่ข้าง `tesseract.exe`, ไม่รับ custom
`--tessdata-dir` และไม่ใช้ค่า `TESSDATA_PREFIX` การใช้ custom model จึงต้องวาง
traineddata ไว้ใน directory นี้และระบุชื่อผ่าน `--languages` อย่างชัดเจน

## Required Languages

ต้องมี official standard traineddata สองไฟล์นี้ใน `Tesseract-OCR\tessdata`:

```text
tha.traineddata
eng.traineddata
```

Runner ตรวจ language list ก่อน OCR และจะจบด้วย error ที่ระบุ model ที่ขาด ค่า default
คือ `tha+eng`; การรัน custom benchmark สามารถเปลี่ยนเป็น `ocr_train+eng` ได้โดยไม่
กระทบ default

## Configuration

Configuration นี้ถูกกำหนดตายตัวใน runner และเหมือนกันทุกเอกสาร:

| Setting | Value |
| --- | --- |
| Languages | `tha+eng` (default), เปลี่ยนได้ด้วย `--languages` |
| OCR Engine Mode | `--oem 1` (LSTM) |
| Page Segmentation Mode | `--psm 3` (automatic) |
| Input DPI | `--dpi 300` |
| Input format | PNG, RGB จาก Common PDF Renderer |
| Preprocessing | none |

## Usage

รันไฟล์เดียว:

```powershell
python experiments/ocr-benchmark/runners/tesseract/run_tesseract.py `
  --input datasets/ocr-benchmark/images/document_007_page_004.png `
  --output experiments/ocr-benchmark/outputs/tesseract
```

รันหลายไฟล์โดยระบุชื่อ:

```powershell
python experiments/ocr-benchmark/runners/tesseract/run_tesseract.py `
  --input `
    datasets/ocr-benchmark/images/document_007_page_004.png `
    datasets/ocr-benchmark/images/document_009_page_004.png `
    datasets/ocr-benchmark/images/document_022_page_004.png `
  --output experiments/ocr-benchmark/outputs/tesseract
```

รัน pilot 3 เอกสารแรกจาก directory:

```powershell
python experiments/ocr-benchmark/runners/tesseract/run_tesseract.py `
  --input datasets/ocr-benchmark/images `
  --output experiments/ocr-benchmark/outputs/tesseract `
  --limit 3
```

หลัง pilot ผ่านแล้ว รันครบ 20 เอกสารด้วย configuration เดิม โดยไม่ใส่ `--limit`:

```powershell
python experiments/ocr-benchmark/runners/tesseract/run_tesseract.py `
  --input datasets/ocr-benchmark/images `
  --output experiments/ocr-benchmark/outputs/tesseract `
  --overwrite
```

รัน legacy custom model ครบ 20 เอกสาร โดยคงค่าอื่นเหมือน baseline:

```powershell
python experiments/ocr-benchmark/runners/tesseract/run_tesseract.py `
  --input datasets/ocr-benchmark/images `
  --output experiments/ocr-benchmark/outputs/tesseract_legacy `
  --languages ocr_train+eng
```

ประเมิน custom output ด้วย evaluator เดิม:

```powershell
.\.venv\Scripts\python.exe experiments/ocr-benchmark/evaluation/evaluate_ocr.py `
  --manifest datasets/ocr-benchmark/manifests/manifest.csv `
  --ground-truth datasets/ocr-benchmark/ground-truth `
  --predictions experiments/ocr-benchmark/outputs/tesseract_legacy `
  --output experiments/ocr-benchmark/outputs/evaluation `
  --engine tesseract_legacy
```

หาก executable ไม่อยู่ในตำแหน่งมาตรฐาน ให้เพิ่ม:

```powershell
--tesseract 'D:\path\to\Tesseract-OCR\tesseract.exe'
```

Runner ป้องกันการเขียนทับทั้ง `.txt` และ `.json` โดยค่าเริ่มต้น ใช้ `--overwrite`
เฉพาะเมื่อตั้งใจรันซ้ำด้วย configuration เดิม

## Output

ตัวอย่าง input `document_007_page_004.png` จะสร้าง:

```text
experiments/ocr-benchmark/outputs/tesseract/
|-- document_007_page_004.txt
`-- document_007_page_004.json
```

ไฟล์ `.txt` เป็น raw UTF-8 bytes จาก stdout ของ Tesseract ส่วน metadata มี
`document_id`, engine/version, languages, input/output SHA-256, processing time,
status, executable, tessdata directory, traineddata SHA-256 และ configuration ที่ใช้

ประเมิน pilot ด้วย evaluator เดิมโดยไม่แก้ normalization, CER หรือ Thai-aware WER:

```powershell
.\.venv\Scripts\python.exe experiments/ocr-benchmark/evaluation/evaluate_ocr.py `
  --manifest datasets/ocr-benchmark/manifests/manifest.csv `
  --ground-truth datasets/ocr-benchmark/ground-truth `
  --predictions experiments/ocr-benchmark/outputs/tesseract `
  --output experiments/ocr-benchmark/outputs/evaluation `
  --engine tesseract `
  --limit 3 `
  --overwrite
```

## Benchmark Conditions

- Dataset: 20 documents จาก manifest ชุดเดียวกับ EasyOCR
- Pilot: `document_007`, `document_009`, `document_022`
- Input: PNG, 300 DPI, RGB จาก Common PDF Renderer
- OCR languages: `tha+eng` เป็น default; custom run ระบุ expression แยกต่างหาก
- Image preprocessing: none
- Text postprocessing: none
- Evaluation: evaluator เดิม, CER และ Thai-aware WER เดิม

## Tests

```powershell
python -m py_compile `
  experiments/ocr-benchmark/runners/tesseract/run_tesseract.py `
  experiments/ocr-benchmark/runners/tesseract/test_run_tesseract.py

python experiments/ocr-benchmark/runners/tesseract/run_tesseract.py --help

python -m unittest discover `
  -s experiments/ocr-benchmark/runners/tesseract `
  -p 'test_*.py' -v
```

Test suite ครอบคลุม missing executable, missing language, invalid input,
overwrite protection และ mocked OCR output ส่วน real OCR smoke test ใช้คำสั่งไฟล์เดียว
ในหัวข้อ Usage
