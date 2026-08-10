# PaddleOCR Runner

Runner นี้ส่งไฟล์ PNG จาก Common PDF Renderer เข้า official PaddleOCR Python API
โดยตรง และเขียน raw recognized lines ตามลำดับที่ engine คืนมาเป็น UTF-8 `.txt`
พร้อม metadata `.json` ไม่มีการแก้คำ, spell correction หรือ text postprocessing

## Installation

ใช้ virtual environment แยกเพื่อไม่ให้ native dependencies ชนกับ EasyOCR:

```powershell
python -m venv .venv-paddleocr
.\.venv-paddleocr\Scripts\python.exe -m pip install -r `
  experiments/ocr-benchmark/runners/paddleocr/requirements.txt
```

Package versions ถูก pin ใน `requirements.txt` ส่วน official model files จะ download
อัตโนมัติในการ initialize ครั้งแรกไปที่ `.paddleocr-cache/` ซึ่งถูก `.gitignore`
ห้าม commit model cache หรือเปลี่ยนเป็น custom model

## Configuration

| Setting | Value |
| --- | --- |
| Language | `th` (Thai, English และตัวเลข) |
| OCR generation | `PP-OCRv5` |
| Detection model | `PP-OCRv5_mobile_det` official |
| Recognition model | `th_PP-OCRv5_mobile_rec` official |
| Device | CPU |
| MKL-DNN | disabled เพื่อเลี่ยง PaddlePaddle PIR/oneDNN error บน Windows |
| Document orientation | disabled |
| Document unwarping | disabled |
| Text-line orientation | disabled |
| Recognition score threshold | `0.0` |
| External image preprocessing | none |
| Text postprocessing | none |

การ resize/normalize ที่เป็นส่วนภายใน official detection/recognition model ยังคงเป็น
พฤติกรรมของ engine แต่ runner ไม่อ่านหรือแปลงภาพเอง

## Usage

ไฟล์เดียว:

```powershell
.\.venv-paddleocr\Scripts\python.exe `
  experiments/ocr-benchmark/runners/paddleocr/run_paddleocr.py `
  --input datasets/ocr-benchmark/images/document_007_page_004.png `
  --output experiments/ocr-benchmark/outputs/paddleocr
```

Pilot 3 เอกสารแรก:

```powershell
.\.venv-paddleocr\Scripts\python.exe `
  experiments/ocr-benchmark/runners/paddleocr/run_paddleocr.py `
  --input datasets/ocr-benchmark/images `
  --output experiments/ocr-benchmark/outputs/paddleocr `
  --limit 3
```

รันครบ 20 หลัง pilot ผ่าน โดยใช้ configuration เดิม:

```powershell
.\.venv-paddleocr\Scripts\python.exe `
  experiments/ocr-benchmark/runners/paddleocr/run_paddleocr.py `
  --input datasets/ocr-benchmark/images `
  --output experiments/ocr-benchmark/outputs/paddleocr `
  --overwrite
```

Runner ป้องกัน `.txt` และ `.json` เดิม หากต้องการรันซ้ำต้องระบุ `--overwrite`

## Output

```text
experiments/ocr-benchmark/outputs/paddleocr/
|-- document_007_page_004.txt
`-- document_007_page_004.json
```

Metadata มี document/engine/package versions, model configuration และ hashes,
input/output SHA-256, processing time, status, preprocessing state, confidence,
polygons และ boxes ตาม reading order ของ PaddleOCR

## Evaluation

ประเมิน pilot ด้วย evaluator เดิม:

```powershell
.\.venv\Scripts\python.exe experiments/ocr-benchmark/evaluation/evaluate_ocr.py `
  --manifest datasets/ocr-benchmark/manifests/manifest.csv `
  --ground-truth datasets/ocr-benchmark/ground-truth `
  --predictions experiments/ocr-benchmark/outputs/paddleocr `
  --output experiments/ocr-benchmark/outputs/evaluation `
  --engine paddleocr `
  --limit 3 `
  --overwrite
```

เมื่อต้องการประเมินครบ 20 ให้เอา `--limit 3` ออกและคง argument อื่นเดิม
Evaluator และ environment `.venv` เดิมทำให้ normalization, CER และ Thai-aware WER
ด้วย PyThaiNLP `newmm` ไม่เปลี่ยน

## Benchmark Conditions

- Input: PNG, 300 DPI, RGB ชุดเดียวกับ EasyOCR/Tesseract
- Dataset/Ground Truth: 20 เอกสารชุดเดิม
- External preprocessing: none
- Custom model/fine-tuning: none
- Evaluation: `evaluate_ocr.py`, normalization/CER/PyThaiNLP `newmm` ชุดเดิม

## Tests

```powershell
.\.venv-paddleocr\Scripts\python.exe -m py_compile `
  experiments/ocr-benchmark/runners/paddleocr/run_paddleocr.py `
  experiments/ocr-benchmark/runners/paddleocr/test_run_paddleocr.py

.\.venv-paddleocr\Scripts\python.exe `
  experiments/ocr-benchmark/runners/paddleocr/run_paddleocr.py --help

.\.venv-paddleocr\Scripts\python.exe -m unittest discover `
  -s experiments/ocr-benchmark/runners/paddleocr `
  -p 'test_*.py' -v
```
