import { Injectable, InternalServerErrorException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
import { v4 as uuidv4 } from 'uuid';
import { extname } from 'path';
import 'multer';

@Injectable()
export class StorageService {
  private s3Client: S3Client;
  private bucketName: string;

  constructor(private configService: ConfigService) {
    this.bucketName = this.configService.get<string>('MINIO_BUCKET') || 'documents';
    
    this.s3Client = new S3Client({
      region: 'us-east-1',
      endpoint: this.configService.get<string>('MINIO_ENDPOINT') || 'http://localhost:9000',
      credentials: {
        accessKeyId: this.configService.get<string>('MINIO_ACCESS_KEY') || 'minioadmin',
        secretAccessKey: this.configService.get<string>('MINIO_SECRET_KEY') || 'minioadminpassword',
      },
      forcePathStyle: true, 
    });
  }

  async uploadFile(file: Express.Multer.File): Promise<string> {
    // สุ่มชื่อไฟล์ด้วย UUID ป้องกันชื่อซ้ำ
    const fileExt = extname(file.originalname);
    const fileName = `${uuidv4()}${fileExt}`;

    try {
      await this.s3Client.send(
        new PutObjectCommand({
          Bucket: this.bucketName,
          Key: fileName,
          Body: file.buffer,
          ContentType: file.mimetype,
        }),
      );
      return fileName;
    } catch (error) {
      console.error(error);
      throw new InternalServerErrorException('เกิดข้อผิดพลาดในการบันทึกไฟล์ลง MinIO');
    }
  }
}