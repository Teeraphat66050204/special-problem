import { Controller, Post, Get, Param, UseInterceptors, UploadedFile, ParseFilePipe, MaxFileSizeValidator, FileTypeValidator, NotFoundException } from '@nestjs/common';
import { FileInterceptor } from '@nestjs/platform-express';
import { DocumentsService } from './documents.service';

@Controller('documents')
export class DocumentsController {
  constructor(private readonly documentsService: DocumentsService) {}

  @Post('upload')
  @UseInterceptors(FileInterceptor('file'))
  async uploadDocument(
    @UploadedFile(
      new ParseFilePipe({
        validators: [
          new MaxFileSizeValidator({ maxSize: 10 * 1024 * 1024 }), // จำกัดขนาดไฟล์ที่ 10MB
          new FileTypeValidator({ fileType: 'application/pdf' }), // บังคับรับเฉพาะ PDF
        ],
      }),
    ) file: Express.Multer.File,
  ) {
    const document = await this.documentsService.processUpload(file);
    return {
      message: 'อัปโหลดไฟล์และนำเข้าคิวสำเร็จ',
      data: document,
    };
  }

  // API สำหรับเช็กสถานะว่าตอนนี้งานถึงไหนแล้ว
  @Get(':id/status')
  async getStatus(@Param('id') id: string) {
    const document = await this.documentsService.getDocumentStatus(id);
    if (!document) throw new NotFoundException('ไม่พบเอกสารในระบบ');
    return {
      id: document.id,
      status: document.status,
    };
  }
}