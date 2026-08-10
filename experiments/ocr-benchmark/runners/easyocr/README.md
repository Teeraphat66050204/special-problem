# EasyOCR Runner

Runner นี้รับ PNG ที่สร้างจาก Common PDF Renderer และบันทึกผล EasyOCR แบบ
raw เป็นไฟล์ `.txt` และ `.json` โดยไม่มี spell correction, fallback,
ensemble หรือ postprocessing ข้อความ

## Installation

ติดตั้งใน virtual environment ของโปรเจกต์:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r experiments/ocr-benchmark/runners/easyocr/requirements.txt
```

การรันครั้งแรกอาจดาวน์โหลด EasyOCR model สำหรับภาษาไทยและอังกฤษผ่าน
อินเทอร์เน็ต model จะอยู่ใน cache ของ EasyOCR และไม่ควร commit เข้า repository

## Usage

ทดลอง 5 ภาพแรกบน CPU:

```powershell
.\.venv\Scripts\python.exe experiments/ocr-benchmark/runners/easyocr/run_easyocr.py `
  --input datasets/ocr-benchmark/images `
  --output experiments/ocr-benchmark/outputs/easyocr `
  --languages th en `
  --gpu cpu `
  --limit 5
```

รันภาพเดียว:

```powershell
.\.venv\Scripts\python.exe experiments/ocr-benchmark/runners/easyocr/run_easyocr.py `
  --input datasets/ocr-benchmark/images/document_007_page_004.png `
  --output experiments/ocr-benchmark/outputs/easyocr `
  --gpu cpu
```

## Arguments

| Argument | Description |
| --- | --- |
| `--input` | PNG หนึ่งไฟล์ หรือ directory ที่มี PNG |
| `--output` | directory สำหรับ `.txt` และ `.json` |
| `--languages` | language codes ของ EasyOCR; ค่าเริ่มต้น `th en` |
| `--gpu` | `auto`, `cpu` หรือ `cuda`; ค่าเริ่มต้น `auto` |
| `--limit` | รันเฉพาะ N ไฟล์แรกหลังเรียงตามชื่อ |
| `--overwrite` | อนุญาตให้เขียนทับ output เดิม |

ค่าเริ่มต้นจะหยุดก่อน initialize model หาก output ของไฟล์ใดมีอยู่แล้ว
ให้ระบุ `--overwrite` เมื่อต้องการรันซ้ำ

## Outputs

ตัวอย่าง input `document_007_page_004.png` จะได้:

```text
experiments/ocr-benchmark/outputs/easyocr/
|-- document_007_page_004.txt
`-- document_007_page_004.json
```

ไฟล์ `.txt` เก็บข้อความตามลำดับ detection ของ EasyOCR ส่วน `.json` เก็บ
ข้อความ, bounding boxes, confidence, SHA-256 ของ input/output, processing time,
เวอร์ชัน dependency, device และ settings ที่ใช้ ไฟล์ output ทั้งหมดถูก
`.gitignore` และไม่ควร commit เข้า repository
