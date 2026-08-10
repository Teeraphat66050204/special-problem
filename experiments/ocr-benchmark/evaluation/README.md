# OCR Evaluation

Evaluator เปรียบเทียบ raw OCR prediction กับ Ground Truth ที่จับคู่ผ่าน
`manifest.csv` โดยคำนวณ Character Error Rate (CER) และ Thai-aware Word Error
Rate (WER) ด้วย configuration เดียวกันทุกเอกสาร

## CER Calculation

CER ใช้ character-level Levenshtein distance บนข้อความที่ผ่าน normalization:

```text
CER = character edits / reference characters
```

Character edits รวม insertion, deletion และ substitution ไม่มี spell
correction, case folding หรือการลบ punctuation

## Thai WER Calculation

WER ใช้ word-level Levenshtein distance:

```text
Thai WER = word edits / reference word tokens
```

ภาษาไทยมักเขียนคำต่อกันโดยไม่มีช่องว่าง การใช้ `text.split()` จึงอาจมองทั้ง
ประโยคเป็น token เดียวและทำให้ WER ไม่สะท้อนข้อผิดพลาดระดับคำ Evaluator จึง
tokenize ทั้ง Ground Truth และ OCR Prediction ด้วย configuration คงที่:

| Setting | Value |
| --- | --- |
| Tokenizer | `pythainlp.tokenize.word_tokenize` |
| Engine | `newmm` |
| `keep_whitespace` | `False` |
| PyThaiNLP | pin ใน `requirements.txt` |

## Normalization Policy

ใช้ policy เดียวกันกับ Ground Truth และ OCR Prediction ก่อนคำนวณทั้ง CER และ
Thai WER:

1. Normalize Unicode เป็น NFC
2. ตัด whitespace หัวและท้าย
3. รวม whitespace ต่อเนื่องเป็นหนึ่งช่องว่าง
4. ไม่แก้คำสะกด ไม่เปลี่ยน case และไม่ลบ punctuation

Summary JSON บันทึก normalization settings, tokenizer name, tokenizer engine,
`keep_whitespace` และ PyThaiNLP version ที่ใช้จริง เพื่อให้ทำซ้ำการทดลองได้

## Installation

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r experiments/ocr-benchmark/evaluation/requirements.txt
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover `
  -s experiments/ocr-benchmark/evaluation `
  -p "test_*.py" -v
```

Tests ครอบคลุมประโยคภาษาไทยที่ไม่มี whitespace เพื่อยืนยันว่า WER ใช้ Thai
word segmentation ไม่ใช่ whitespace tokenization

## Trial Usage

ประเมิน `document_007`, `document_009` และ `document_022` ซึ่งเป็น 3 แถวแรก
ใน manifest:

```powershell
.\.venv\Scripts\python.exe experiments/ocr-benchmark/evaluation/evaluate_ocr.py `
  --manifest datasets/ocr-benchmark/manifests/manifest.csv `
  --ground-truth datasets/ocr-benchmark/ground-truth `
  --predictions experiments/ocr-benchmark/outputs/easyocr `
  --output experiments/ocr-benchmark/outputs/evaluation `
  --engine easyocr `
  --limit 3 `
  --overwrite
```

เมื่อมี prediction ครบทุกเอกสารให้เอา `--limit` ออก หาก prediction ขาด
Evaluator จะจบด้วย non-zero exit code

## Outputs

```text
experiments/ocr-benchmark/outputs/evaluation/
|-- easyocr_metrics.csv
`-- easyocr_summary.json
```

CSV เก็บ metrics รายเอกสาร ส่วน JSON เก็บ metric definitions, tokenizer และ
normalization metadata, macro averages, corpus-level metrics, totals และผลราย
เอกสาร ค่าเริ่มต้นจะไม่เขียนทับ output เดิม ให้ใช้ `--overwrite` เพื่อประเมินซ้ำ
