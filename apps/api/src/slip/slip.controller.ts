import { Body, Controller, Get, Post, UseGuards } from '@nestjs/common';

import { JwtAuthGuard } from '../auth/jwt.guard';
import { CurrentUser, AuthUser } from '../common/decorators/user.decorator';
import { SlipService } from './slip.service';
import { AllocateCreditsDto } from './dto/allocate-credits.dto';

@Controller('slip')
@UseGuards(JwtAuthGuard)
export class SlipController {
  constructor(private readonly slip: SlipService) {}

  @Get('current')
  async current(@CurrentUser() user: AuthUser) {
    return this.slip.getCurrentSlip({ userId: user.sub });
  }

  @Post('allocate-credits')
  async allocate(@CurrentUser() user: AuthUser, @Body() dto: AllocateCreditsDto) {
    return this.slip.allocateCredits({ userId: user.sub, allocations: dto.allocations });
  }
}
