# Common PDF Renderer

Common PDF Renderer แปลงหน้า PDF หนึ่งหน้าเป็น PNG ตามเงื่อนไขคงที่
เพื่อให้ OCR ทุก engine ใน benchmark รับ input image เดียวกัน การใช้ renderer
ร่วมกันช่วยลดความแตกต่างที่เกิดจากวิธีแปลง PDF และทำให้เปรียบเทียบผลได้อย่าง
เป็นธรรม

Renderer นี้ทำเฉพาะการแปลง `PDF page -> PNG` และไม่สกัดข้อความจาก PDF

## Fixed Rendering Conditions

| รายการ | ค่า |
| --- | --- |
| Format | PNG |
| Resolution | 300 DPI |
| Color space | RGB |
| Alpha channel | `false` |
| Preprocessing | ไม่มี |

ไม่มี grayscale, thresholding, sharpening, denoise, deskew หรือ resize หลัง
render

## Installation

ต้องใช้ Python 3.10 ขึ้นไป แนะนำให้ติดตั้ง dependency ใน virtual environment:

```bash
python -m venv .venv
python -m pip install -r experiments/ocr-benchmark/renderer/requirements.txt
```

สำหรับ PowerShell สามารถเปิดใช้งาน virtual environment ก่อนติดตั้งได้ดังนี้:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r experiments/ocr-benchmark/renderer/requirements.txt
```

Renderer ใช้เพียง PyMuPDF (`pymupdf`) และ Python standard library ไม่มี OCR
library เป็น dependency

## Usage

เลขหน้าที่ส่งผ่าน `--page` เป็นแบบ 1-based เช่น page 1 จะถูกแปลงเป็น
PyMuPDF page index 0 ภายในโปรแกรม

ตัวอย่างสำหรับ shell ที่รองรับ backslash continuation:

```bash
python experiments/ocr-benchmark/renderer/render_pdf.py \
  --pdf datasets/ocr-benchmark/pdfs/document_007.pdf \
  --page 4 \
  --output datasets/ocr-benchmark/images/
```

ตัวอย่างสำหรับ Windows PowerShell:

```powershell
python experiments/ocr-benchmark/renderer/render_pdf.py `
  --pdf datasets/ocr-benchmark/pdfs/document_007.pdf `
  --page 4 `
  --output datasets/ocr-benchmark/images/
```

### Command Arguments

| Argument | Required | Description |
| --- | --- | --- |
| `--pdf PATH` | Yes | path ของ PDF ต้นฉบับ |
| `--page NUMBER` | Yes | เลขหน้าที่ต้องการ render แบบ 1-based |
| `--output DIRECTORY` | Yes | directory สำหรับ PNG และ metadata |
| `--overwrite` | No | อนุญาตให้แทนที่ output เดิม |

โปรแกรมจะสร้าง output directory ให้อัตโนมัติหากยังไม่มี

## Output Naming

ชื่อ output สร้างจากชื่อ PDF และเลขหน้าอย่าง deterministic โดยเติมเลขหน้า
อย่างน้อย 3 หลัก:

```text
document_007.pdf + page 4
-> document_007_page_004.png
-> document_007_page_004.render.json
```

## Render Metadata

ไฟล์ `.render.json` บันทึกเงื่อนไขการ render, ขนาดภาพ, PyMuPDF version และ
SHA-256 ของ PDF กับ PNG เพื่อให้ตรวจสอบ reproducibility ได้ โดยไม่บันทึก
absolute path ของเครื่องผู้ใช้

```json
{
  "source_pdf": "document_007.pdf",
  "source_pdf_sha256": "...",
  "page_number": 4,
  "page_index": 3,
  "dpi": 300,
  "color_space": "RGB",
  "format": "PNG",
  "alpha": false,
  "preprocessing": false,
  "width_px": 2480,
  "height_px": 3508,
  "output_file": "document_007_page_004.png",
  "output_sha256": "...",
  "renderer": "PyMuPDF",
  "pymupdf_version": "..."
}
```

SHA-256 คำนวณแบบอ่านไฟล์เป็น chunk เพื่อไม่โหลดไฟล์ขนาดใหญ่ทั้งหมดเข้า
หน่วยความจำพร้อมกัน

## Overwrite Behavior

ค่าเริ่มต้นจะหยุดด้วย error หาก PNG หรือ metadata ชื่อเดียวกันมีอยู่แล้ว
หากต้องการแทนที่ทั้งคู่ต้องระบุ `--overwrite`:

```powershell
python experiments/ocr-benchmark/renderer/render_pdf.py `
  --pdf path/to/document_007.pdf `
  --page 4 `
  --output path/to/images `
  --overwrite
```

## Error Behavior

เมื่อเกิดข้อผิดพลาด โปรแกรมจะแสดงข้อความที่อ่านเข้าใจง่ายทาง stderr และจบ
ด้วย non-zero exit code ตัวอย่างข้อผิดพลาดที่ตรวจสอบ ได้แก่:

- PDF ไม่มีอยู่หรือ path ไม่ใช่ไฟล์
- เปิด PDF ไม่ได้หรือ PDF ไม่มีหน้า
- page number น้อยกว่า 1 หรือเกินจำนวนหน้า
- output path ใช้งานไม่ได้
- render หรือเขียน output ไม่สำเร็จ
- output เดิมมีอยู่แต่ไม่ได้ระบุ `--overwrite`

หลัง render โปรแกรมจะตรวจว่า PNG ไม่มี alpha channel, เป็น RGB และมี width
กับ height มากกว่า 0
