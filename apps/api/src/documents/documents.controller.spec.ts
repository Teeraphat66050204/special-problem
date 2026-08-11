import { Test, TestingModule } from '@nestjs/testing';
import { DocumentsController } from './documents.controller';
import { StorageService } from '../storage/storage.service';

describe('DocumentsController', () => {
  let controller: DocumentsController;

  beforeEach(async () => {
    const module: TestingModule = await Test.createTestingModule({
      controllers: [DocumentsController],
      providers: [
        {
          provide: StorageService,
          useValue: {
            uploadFile: jest.fn(),
          },
        },
      ],
    }).compile();

    controller = module.get<DocumentsController>(DocumentsController);
  });

  it('should be defined', () => {
    expect(controller).toBeDefined();
  });
});
