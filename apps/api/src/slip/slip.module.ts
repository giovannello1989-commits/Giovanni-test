import { Module } from '@nestjs/common';

import { SlipController } from './slip.controller';
import { SlipService } from './slip.service';

@Module({
  controllers: [SlipController],
  providers: [SlipService],
})
export class SlipModule {}
