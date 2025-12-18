import crypto from 'node:crypto';

import { BadRequestException, Injectable, UnauthorizedException } from '@nestjs/common';
import { JwtService } from '@nestjs/jwt';

import { PrismaService } from '../common/providers/prisma.service';
import { EmailService } from './email.service';
import { VerifyOtpDto } from './dto/verify-otp.dto';

function normalizeEmail(email: string) {
  return email.trim().toLowerCase();
}

function hashOtp(code: string) {
  return crypto.createHash('sha256').update(code).digest('hex');
}

function generateOtp(): string {
  // 6-digit numeric code
  const n = crypto.randomInt(0, 1_000_000);
  return n.toString().padStart(6, '0');
}

@Injectable()
export class AuthService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly jwt: JwtService,
    private readonly email: EmailService,
  ) {}

  async requestOtp(params: { email: string; country?: string; timezone?: string; requestIp?: string }) {
    const email = normalizeEmail(params.email);

    // Ensure user exists (no password)
    const user = await this.prisma.user.upsert({
      where: { email },
      create: {
        email,
        country: params.country,
        timezone: params.timezone,
      },
      update: {
        country: params.country ?? undefined,
        timezone: params.timezone ?? undefined,
      },
    });

    const code = generateOtp();
    const expiresAt = new Date(Date.now() + 10 * 60 * 1000);

    await this.prisma.emailOtp.create({
      data: {
        email,
        codeHash: hashOtp(code),
        expiresAt,
        requestIp: params.requestIp,
        userId: user.id,
      },
    });

    await this.email.sendOtpEmail({ to: email, code });
  }

  async verifyOtp(dto: VerifyOtpDto) {
    const email = normalizeEmail(dto.email);
    const codeHash = hashOtp(dto.code);

    const otp = await this.prisma.emailOtp.findFirst({
      where: {
        email,
        codeHash,
        usedAt: null,
        expiresAt: { gt: new Date() },
      },
      orderBy: { createdAt: 'desc' },
    });

    if (!otp) throw new UnauthorizedException('Invalid code');

    await this.prisma.emailOtp.update({
      where: { id: otp.id },
      data: { usedAt: new Date() },
    });

    const user = await this.prisma.user.findUnique({ where: { email } });
    if (!user) throw new BadRequestException('User not found');

    const accessToken = await this.jwt.signAsync({ sub: user.id, email: user.email });

    return {
      accessToken,
      user: {
        id: user.id,
        email: user.email,
        country: user.country,
        timezone: user.timezone,
        xpTotal: user.xpTotal,
      },
    };
  }
}
