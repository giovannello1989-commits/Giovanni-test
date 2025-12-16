import { Body, Controller, Post, Req } from '@nestjs/common';
import type { Request } from 'express';

import { RequestOtpDto } from './dto/request-otp.dto';
import { VerifyOtpDto } from './dto/verify-otp.dto';
import { AuthService } from './auth.service';

@Controller('auth')
export class AuthController {
  constructor(private readonly auth: AuthService) {}

  @Post('request-otp')
  async requestOtp(@Body() dto: RequestOtpDto, @Req() req: Request) {
    await this.auth.requestOtp({
      email: dto.email,
      country: dto.country,
      timezone: dto.timezone,
      requestIp: req.ip,
    });
    // Always 200 to avoid email enumeration
    return { ok: true };
  }

  @Post('verify-otp')
  async verifyOtp(@Body() dto: VerifyOtpDto) {
    return this.auth.verifyOtp(dto);
  }
}
