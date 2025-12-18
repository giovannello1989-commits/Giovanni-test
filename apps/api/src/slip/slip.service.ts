import { BadRequestException, ForbiddenException, Injectable } from '@nestjs/common';
import { DateTime } from 'luxon';
import { SlipStatus } from '@prisma/client';

import { PrismaService } from '../common/providers/prisma.service';

function getUserDayStartUtc(timezone?: string | null) {
  const tz = timezone ?? 'UTC';
  const now = DateTime.now().setZone(tz);
  return now.startOf('day').toUTC().toJSDate();
}

@Injectable()
export class SlipService {
  constructor(private readonly prisma: PrismaService) {}

  async getCurrentSlip(params: { userId: string }) {
    const user = await this.prisma.user.findUnique({ where: { id: params.userId } });
    if (!user) throw new BadRequestException('User not found');

    const forDate = getUserDayStartUtc(user.timezone);

    const slip = await this.prisma.slip.findUnique({
      where: { userId_forDate: { userId: user.id, forDate } },
      include: { items: { include: { card: { include: { match: true } } } } },
    });

    return {
      slip: slip
        ? {
            id: slip.id,
            forDate: slip.forDate,
            status: slip.status,
            creditsRequired: slip.creditsRequired,
            creditsAllocated: slip.creditsAllocated,
            items: slip.items.map((it) => ({
              slipItemId: it.id,
              cardId: it.cardId,
              side: it.side,
              result: it.result,
              credits: it.credits,
              match: {
                id: it.card.match.id,
                sport: it.card.match.sport,
                league: it.card.match.league,
                teamOne: it.card.match.teamOne,
                teamTwo: it.card.match.teamTwo,
                startsAt: it.card.match.startsAt,
              },
            })),
          }
        : null,
    };
  }

  async allocateCredits(params: { userId: string; allocations: { slipItemId: string; credits: number }[] }) {
    const user = await this.prisma.user.findUnique({ where: { id: params.userId } });
    if (!user) throw new BadRequestException('User not found');

    const forDate = getUserDayStartUtc(user.timezone);

    const slip = await this.prisma.slip.findUnique({ where: { userId_forDate: { userId: user.id, forDate } }, include: { items: true } });
    if (!slip) throw new BadRequestException('Slip not found');
    if (slip.status !== SlipStatus.PENDING) throw new ForbiddenException('Slip is locked or resolved');

    const itemIds = new Set(slip.items.map((i) => i.id));
    for (const a of params.allocations) {
      if (!itemIds.has(a.slipItemId)) throw new BadRequestException('Slip item not found');
      if (a.credits < 0) throw new BadRequestException('Credits must be >= 0');
    }

    await this.prisma.$transaction(async (tx) => {
      for (const a of params.allocations) {
        await tx.slipItem.update({ where: { id: a.slipItemId }, data: { credits: a.credits } });
      }

      const updated = await tx.slipItem.findMany({ where: { slipId: slip.id }, select: { credits: true } });
      const creditsAllocated = updated.reduce((sum, x) => sum + x.credits, 0);

      await tx.slip.update({
        where: { id: slip.id },
        data: {
          creditsAllocated,
          status: creditsAllocated === slip.creditsRequired ? SlipStatus.VALID : SlipStatus.PENDING,
        },
      });
    });

    return this.getCurrentSlip({ userId: user.id });
  }
}
