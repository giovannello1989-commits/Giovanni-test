import { Injectable } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import nodemailer from 'nodemailer';

@Injectable()
export class EmailService {
  constructor(private readonly config: ConfigService) {}

  async sendOtpEmail(params: { to: string; code: string }) {
    const from = String(this.config.get('EMAIL_FROM') ?? 'no-reply@swipster.local');

    const host = this.config.get<string>('SMTP_HOST');
    const user = this.config.get<string>('SMTP_USER');
    const pass = this.config.get<string>('SMTP_PASS');
    const port = Number(this.config.get('SMTP_PORT') ?? 587);

    // V1-safe fallback: if SMTP isn’t configured, log only.
    if (!host || !user || !pass) {
      // eslint-disable-next-line no-console
      console.log(`[OTP] to=${params.to} code=${params.code}`);
      return;
    }

    const transporter = nodemailer.createTransport({
      host,
      port,
      secure: port === 465,
      auth: { user, pass },
    });

    await transporter.sendMail({
      from,
      to: params.to,
      subject: 'Your Swipster code',
      text: `Your code is: ${params.code}. It expires in 10 minutes.`,
    });
  }
}
