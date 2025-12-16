import { createParamDecorator, ExecutionContext } from '@nestjs/common';

export type AuthUser = { sub: string; email: string };

export const CurrentUser = createParamDecorator((_: unknown, ctx: ExecutionContext): AuthUser => {
  const req = ctx.switchToHttp().getRequest<{ user?: AuthUser }>();
  if (!req.user) throw new Error('Missing user on request');
  return req.user;
});
