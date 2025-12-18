import { IsEmail, IsOptional, IsString, MaxLength } from 'class-validator';

export class RequestOtpDto {
  @IsEmail()
  email!: string;

  @IsOptional()
  @IsString()
  @MaxLength(64)
  country?: string;

  @IsOptional()
  @IsString()
  @MaxLength(64)
  timezone?: string;
}
