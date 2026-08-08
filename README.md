# Special Project

เว็บแอปพลิเคชันสำหรับจัดเก็บ สกัดข้อมูล และสืบค้นเล่มปัญหาพิเศษ โดยพัฒนา
ระบบควบคู่กับงานวิจัยเพื่อคัดเลือก OCR ที่เหมาะสมสำหรับเอกสารภาษาไทย

> **Current Phase:** Semester 1 - OCR Research & Backend Development  
> **Current Status:** Repository foundation completed; Common PDF Renderer is
> the next task.

## Project Overview

โครงการแบ่งงานหลักเป็น 2 ส่วน ได้แก่ การทดลอง OCR แบบทำซ้ำได้เพื่อหา
Baseline OCR และการพัฒนา Backend สำหรับจัดเก็บ สกัด และสืบค้นข้อมูลเอกสาร
ส่วน Frontend ด้วย SvelteKit มีแผนพัฒนาใน Semester 2

## Repository Structure

```text
.
|-- apps/
|   |-- api/                     # NestJS Backend
|   `-- web/                     # SvelteKit Frontend (Semester 2)
|-- experiments/
|   `-- ocr-benchmark/
|       |-- renderer/            # Common PDF Renderer
|       |-- runners/             # OCR runners
|       |-- evaluation/          # Metrics และ error analysis
|       |-- configs/             # การตั้งค่าการทดลอง
|       `-- README.md
|-- datasets/
|   `-- ocr-benchmark/           # ข้อมูลสำหรับ benchmark (ไม่ commit ข้อมูลจริง)
|-- packages/
|   |-- database/                # Database schema และ migrations
|   |-- contracts/               # Shared API contracts และ DTOs
|   `-- shared/                  # Shared types และ utilities
|-- infrastructure/             # Infrastructure configuration
|-- docs/                        # เอกสารขอบเขตและการออกแบบระบบ
`-- README.md
```

## OCR Benchmark Flow

รอบแรกเป็น **Raw OCR Benchmark** เพื่อเปรียบเทียบ EasyOCR, Tesseract OCR,
PaddleOCR และ Typhoon OCR อย่างเป็นธรรม โดย OCR ทุกตัวต้องรับภาพเดียวกัน

```text
Existing Ground Truth
-> Match with PDF
-> Identify abstract page
-> Common PDF Renderer
-> EasyOCR / Tesseract OCR / PaddleOCR / Typhoon OCR
-> CER / WER / Field Accuracy / Processing Time
-> Error Analysis
-> Select Baseline OCR
-> Design Proposed Method
```

Common PDF Renderer ใช้ **PyMuPDF** แปลงหน้าจาก PDF เป็น **PNG, 300 DPI,
RGB และไม่ทำ preprocessing** ในรอบแรก เพื่อควบคุม input ให้เหมือนกันทั้งหมด

## Dataset Structure

```text
datasets/ocr-benchmark/
|-- pdfs/                         # PDF ต้นฉบับจริง
|-- images/                       # PNG จาก Common Renderer
|-- ground-truth/                 # ข้อความ Ground Truth
`-- manifests/
    |-- manifest.example.csv      # ตัวอย่างรูปแบบ manifest (commit ได้)
    `-- manifest.csv              # manifest จริง (ห้าม commit)
```

**ห้าม commit dataset จริงเข้า Git** รวมถึง PDF, rendered images, Ground
Truth และ `manifest.csv` เพราะอาจมีข้อมูลส่วนบุคคลและไฟล์ขนาดใหญ่
ไฟล์เหล่านี้ถูกกำหนดไว้ใน `.gitignore` แล้ว ให้ใช้เฉพาะข้อมูลสมมติในไฟล์
ตัวอย่างที่ commit เข้า repository

## Git Workflow

ใช้ branch ตามลำดับต่อไปนี้:

```text
feature/<task-name> -> develop -> main
```

- สร้าง feature branch จาก `develop` สำหรับแต่ละงาน
- เปิด Pull Request จาก feature branch เข้า `develop` เพื่อรวมและทดสอบงาน
- รวม `develop` เข้า `main` เมื่อ milestone พร้อมเผยแพร่เท่านั้น
- ห้ามพัฒนา, commit หรือ push งานเข้า `main` โดยตรง

## Getting Started

สำหรับสมาชิกที่ clone repository ครั้งแรก:

```bash
git clone https://github.com/Teeraphat66050204/special-problem.git
cd special-problem
git switch develop
git pull origin develop
git switch -c feature/<task-name>
```

จากนั้นอ่านเอกสารใน `docs/` และ README ของส่วนงานที่รับผิดชอบก่อนเริ่มพัฒนา
ขณะนี้ยังไม่ต้องติดตั้ง NestJS, SvelteKit หรือ OCR libraries จนกว่าจะเริ่มงาน
ในส่วนนั้นอย่างเป็นทางการ

## Current Development

- [x] จัดเตรียม repository foundation และ branch workflow
- [x] กำหนดโครง OCR benchmark, dataset และเอกสาร methodology
- [ ] พัฒนา Common PDF Renderer ด้วย PyMuPDF
- [ ] ตรวจสอบผล PNG ที่ 300 DPI, RGB และ no preprocessing
- [ ] พัฒนา OCR runners ทั้ง 4 ตัว
- [ ] พัฒนา evaluation สำหรับ CER, WER, Field Accuracy และ Processing Time
- [ ] เริ่มพัฒนา NestJS Backend
- [ ] เริ่มพัฒนา SvelteKit Frontend ใน Semester 2

## Planned Tech Stack

| ส่วนงาน | เทคโนโลยี |
| --- | --- |
| Backend | NestJS + TypeScript |
| Frontend | SvelteKit + TypeScript |
| Database | PostgreSQL + pgvector |
| Job Queue | Redis + BullMQ |
| OCR Benchmark | EasyOCR, Tesseract OCR, PaddleOCR, Typhoon OCR |
| Common Renderer | PyMuPDF, PNG 300 DPI, RGB, no preprocessing |

## Documentation

เอกสารหลักอยู่ใน [`docs/`](docs/):

- [`project-scope.md`](docs/project-scope.md) - ขอบเขตและเป้าหมายโครงการ
- [`database-schema.md`](docs/database-schema.md) - แบบร่างโครงสร้างฐานข้อมูล
- [`api-contract.md`](docs/api-contract.md) - แบบร่าง API contract
- [`benchmark-methodology.md`](docs/benchmark-methodology.md) - วิธีดำเนินการ OCR benchmark
