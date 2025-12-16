import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { ThrottlerModule } from '@nestjs/throttler';
import { ScheduleModule } from '@nestjs/schedule';

import { PrismaModule } from './common/providers/prisma.module';
import { HealthModule } from './common/providers/health.module';
import { AuthModule } from './auth/auth.module';
import { SwipeModule } from './swipe/swipe.module';
import { SlipModule } from './slip/slip.module';

@Module({
  imports: [
    ConfigModule.forRoot({ isGlobal: true }),
    ThrottlerModule.forRoot([
      {
        ttl: 60_000,
        limit: 120,
      },
    ]),
    ScheduleModule.forRoot(),
    PrismaModule,
    HealthModule,
    AuthModule,
    SwipeModule,
    SlipModule,
  ],
})
export class AppModule {}
