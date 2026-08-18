import { Entity, PrimaryGeneratedColumn, Column, CreateDateColumn, UpdateDateColumn } from 'typeorm';

// ระบบติดตามสถานะเอกสาร
export enum DocumentStatus {
  UPLOADED = 'uploaded',
  PROCESSING = 'processing',
  REVIEW = 'review',
  PUBLISHED = 'published',
  FAILED = 'failed',
}

@Entity('documents') 
export class Document {
  @PrimaryGeneratedColumn('uuid')
  id!: string;

  @Column()
  fileName!: string; 

  @Column()
  originalName!: string; 

  @Column()
  mimeType!: string; 

  @Column()
  size!: number; 

  @Column({ unique: true })
  sha256Hash!: string; 

  @Column({ type: 'enum', enum: DocumentStatus, default: DocumentStatus.UPLOADED })
  status!: DocumentStatus; 

  @CreateDateColumn()
  createdAt!: Date; 

  @UpdateDateColumn()
  updatedAt!: Date; 
}