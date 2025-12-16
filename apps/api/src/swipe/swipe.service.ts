import { BadRequestException, ForbiddenException, Injectable } from '@nestjs/common';
import { DateTime } from 'luxon';
import { PickSide, SlipStatus } from '@prisma/client';

import { PrismaService } from '../common/providers/prisma.service';
import { SwipeActionType } from './dto/swipe-action.dto';

function getUserDayStartUtc(timezone?: string | null) {
  const tz = timezone ?? 'UTC';
  const now = DateTime.now().setZone(tz);
  const start = now.startOf('day');
  return start.toUTC().toJSDate();
}

@Injectable()
export class SwipeService {
  constructor(private readonly prisma: PrismaService) {}

  async getFeed(params: { userId: string; limit?: number }) {
    const user = await this.prisma.user.findUnique({ where: { id: params.userId } });
    if (!user) throw new BadRequestException('User not found');

    const forDate = getUserDayStartUtc(user.timezone);
    const limit = params.limit ?? 10;

    const skipped = await this.prisma.skippedCard.findMany({
      where: { userId: user.id, forDate },
      select: { cardId: true },
    });
    const skippedIds = skipped.map((s) => s.cardId);

    const pickedItems = await this.prisma.slipItem.findMany({
      where: { slip: { userId: user.id, forDate } },
      select: { cardId: true },
    });
    const pickedIds = pickedItems.map((p) => p.cardId);

    const seenIds = Array.from(new Set([...skippedIds, ...pickedIds]));

    const cards = await this.prisma.card.findMany({
      where: {
        isActive: true,
        id: seenIds.length ? { notIn: seenIds } : undefined,
        match: {
          status: 'SCHEDULED',
          startsAt: { gt: new Date() },
        },
      },
      include: { match: true },
      orderBy: [{ createdAt: 'desc' }],
      take: limit,
    });

    return {
      cards: cards.map((c) => ({
        cardId: c.id,
        matchId: c.matchId,
        sport: c.match.sport,
        league: c.match.league,
        teamOne: c.match.teamOne,
        teamTwo: c.match.teamTwo,
        startsAt: c.match.startsAt,
        // UI rule: pick type is always "1 or 2". No draw.
        pickOptions: ['ONE', 'TWO'],
      })),
    };
  }

  async applyAction(params: { userId: string; cardId: string; action: SwipeActionType }) {
    const user = await this.prisma.user.findUnique({ where: { id: params.userId } });
    if (!user) throw new BadRequestException('User not found');

    const forDate = getUserDayStartUtc(user.timezone);

    // load settings (single row) with env fallbacks
    const settings = await this.prisma.appSettings.findUnique({ where: { id: 1 } });
    const maxSwipes = settings?.maxSwipesPerDay ?? Number(process.env.MAX_SWIPES_PER_DAY ?? 20);
    const maxSkips = settings?.maxSkipsPerDay ?? Number(process.env.MAX_SKIPS_PER_DAY ?? 3);
    const creditsPerDay = settings?.creditsPerDay ?? Number(process.env.CREDITS_PER_DAY ?? 100);

    const usage = await this.prisma.dailyUsage.upsert({
      where: { userId_forDate: { userId: user.id, forDate } },
      create: { userId: user.id, forDate },
      update: {},
    });

    // Ensure card exists and is pre-match
    const card = await this.prisma.card.findFirst({
      where: {
        id: params.cardId,
        isActive: true,
      },
      include: { match: true },
    });
    if (!card) throw new BadRequestException('Card not found');
    if (card.match.startsAt <= new Date()) throw new ForbiddenException('Match already started');

    // Ensure user hasn’t already acted on this card today
    const alreadyPicked = await this.prisma.slipItem.findFirst({ where: { slip: { userId: user.id, forDate }, cardId: card.id } });
    const alreadySkipped = await this.prisma.skippedCard.findUnique({ where: { userId_forDate_cardId: { userId: user.id, forDate, cardId: card.id } } });
    if (alreadyPicked || alreadySkipped) throw new BadRequestException('Already acted on this card');

    if (params.action === SwipeActionType.SKIP) {
      if (usage.skipsCount >= maxSkips) throw new ForbiddenException('Daily skip limit reached');

      await this.prisma.$transaction([
        this.prisma.skippedCard.create({ data: { userId: user.id, forDate, cardId: card.id } }),
        this.prisma.dailyUsage.update({
          where: { id: usage.id },
          data: { skipsCount: { increment: 1 } },
        }),
      ]);

      return { ok: true };
    }

    // Pick 1 or 2
    if (usage.swipesCount >= maxSwipes) throw new ForbiddenException('Daily swipe limit reached');

    const side = params.action === SwipeActionType.PICK_ONE ? PickSide.ONE : PickSide.TWO;

    await this.prisma.$transaction(async (tx) => {
      const slip = await tx.slip.upsert({
        where: { userId_forDate: { userId: user.id, forDate } },
        create: {
          userId: user.id,
          forDate,
          status: SlipStatus.PENDING,
          creditsRequired: creditsPerDay,
          creditsAllocated: 0,
        },
        update: {},
      });

      if (slip.status !== SlipStatus.PENDING) throw new ForbiddenException('Slip is locked or resolved');

      await tx.slipItem.create({
        data: {
          slipId: slip.id,
          cardId: card.id,
          side,
          credits: 0,
        },
      });

      await tx.dailyUsage.update({ where: { id: usage.id }, data: { swipesCount: { increment: 1 } } });
    });

    return { ok: true };
  }
}
