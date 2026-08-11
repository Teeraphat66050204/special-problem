import { Controller, Post, UseInterceptors, UploadedFile, BadRequestException } from '@nestjs/common';
import { FileInterceptor } from '@nestjs/platform-express';
import { StorageService } from '../storage/storage.service';

@Controller('documents')
export class DocumentsController {
  constructor(private readonly storageService: StorageService) {}

  @Post('upload')
  @UseInterceptors(FileInterceptor('file')) // รับไฟล์จาก Key ชื่อ 'file'
  async uploadDocument(@UploadedFile() file: Express.Multer.File) {
    if (!file) {
      throw new BadRequestException('กรุณาแนบไฟล์ PDF');
    }
    
    if (file.mimetype !== 'application/pdf') {
      throw new BadRequestException('ระบบรองรับเฉพาะไฟล์เอกสารรูปแบบ PDF เท่านั้น');
    }

    const savedFileName = await this.storageService.uploadFile(file);
    
    return {
      message: 'อัปโหลดไฟล์สำเร็จ',
      fileName: savedFileName,
      status: 'uploaded',
    };
  }
}