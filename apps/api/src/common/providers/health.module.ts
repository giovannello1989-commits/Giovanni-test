import { Controller, Get, Module } from '@nestjs/common';

@Controller('health')
class HealthController {
  @Get()
  getHealth() {
    return { ok: true };
  }
}

@Module({
  controllers: [HealthController],
})
export class HealthModule {}
