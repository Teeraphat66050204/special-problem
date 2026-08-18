import { Injectable, ConflictException } from '@nestjs/common';
import { InjectRepository } from '@nestjs/typeorm';
import { Repository } from 'typeorm';
import { InjectQueue } from '@nestjs/bull';
import { type Queue } from 'bull';
import * as crypto from 'crypto';
import { Document, DocumentStatus } from './entities/document.entity';
import { StorageService } from '../storage/storage.service';

@Injectable()
export class DocumentsService {
  constructor(
    @InjectRepository(Document)
    private documentsRepository: Repository<Document>,
    private storageService: StorageService,
    @InjectQueue('ocr-queue') private ocrQueue: Queue, // เรียกใช้คิว
  ) {}

  async processUpload(file: Express.Multer.File) {
    // 1. คำนวณ SHA-256 จากเนื้อหาไฟล์
    const hashSum = crypto.createHash('sha256');
    hashSum.update(file.buffer);
    const sha256Hash = hashSum.digest('hex');

    // 2. เช็ก Database ว่ามีไฟล์ลายนิ้วมือนี้หรือยัง
    const existingDoc = await this.documentsRepository.findOne({ where: { sha256Hash } });
    if (existingDoc) {
      throw new ConflictException('ไฟล์นี้ถูกอัปโหลดเข้าระบบไปแล้ว');
    }

    // 3. เอาไฟล์โยนเข้า MinIO
    const savedFileName = await this.storageService.uploadFile(file);

    const utf8Name = Buffer.from(file.originalname, 'latin1').toString('utf8');
    
    // 4. บันทึกข้อมูลลง PostgreSQL
    const document = this.documentsRepository.create({
      fileName: savedFileName,
      originalName: utf8Name,
      mimeType: file.mimetype,
      size: file.size,
      sha256Hash: sha256Hash,
      status: DocumentStatus.UPLOADED, // กำหนดสถานะแรกเริ่ม
    });
    await this.documentsRepository.save(document);

    // 5. ส่งงาน (Job) เข้าคิว Redis เพื่อให้ Worker เอาไปทำต่อ
    await this.ocrQueue.add('extract-text', {
      documentId: document.id,
      fileName: document.fileName,
    });

    return document;
  }

  // ฟังก์ชันสำหรับเช็กสถานะจากข้างนอก
  async getDocumentStatus(id: string) {
    return this.documentsRepository.findOne({ where: { id } });
  }
}