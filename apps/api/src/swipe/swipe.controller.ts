import { Controller, Get, Post, Query, UseGuards, Body } from '@nestjs/common';

import { JwtAuthGuard } from '../auth/jwt.guard';
import { CurrentUser, AuthUser } from '../common/decorators/user.decorator';
import { SwipeFeedQueryDto } from './dto/swipe-feed.dto';
import { SwipeActionDto } from './dto/swipe-action.dto';
import { SwipeService } from './swipe.service';

@Controller('swipe')
@UseGuards(JwtAuthGuard)
export class SwipeController {
  constructor(private readonly swipe: SwipeService) {}

  @Get('feed')
  async getFeed(@CurrentUser() user: AuthUser, @Query() query: SwipeFeedQueryDto) {
    return this.swipe.getFeed({ userId: user.sub, limit: query.limit });
  }

  @Post('action')
  async act(@CurrentUser() user: AuthUser, @Body() dto: SwipeActionDto) {
    return this.swipe.applyAction({ userId: user.sub, cardId: dto.cardId, action: dto.action });
  }
}
