import { Module } from '@nestjs/common';
import { TypeOrmModule } from '@nestjs/typeorm';
import { BullModule } from '@nestjs/bull';
import { DocumentsController } from './documents.controller';
import { StorageModule } from '../storage/storage.module';
import { Document } from './entities/document.entity';
import { DocumentsService } from './documents.service';

@Module({
  imports: [
    TypeOrmModule.forFeature([Document]), // ลงทะเบียนตาราง
    BullModule.registerQueue({
      name: 'ocr-queue', // สร้างคิวสำหรับงาน OCR
    }),
    StorageModule,
  ],
  controllers: [DocumentsController],
  providers: [DocumentsService],
})
export class DocumentsModule {}