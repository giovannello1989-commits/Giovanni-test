import { PrismaClient } from '@prisma/client';

const prisma = new PrismaClient();

async function main() {
  const now = new Date();
  const inHours = (h: number) => new Date(now.getTime() + h * 60 * 60 * 1000);

  // Create a couple of scheduled matches in the future
  const match1 = await prisma.match.create({
    data: {
      sport: 'Football',
      league: 'Demo League',
      teamOne: 'Lions FC',
      teamTwo: 'Tigers FC',
      startsAt: inHours(6),
      status: 'SCHEDULED',
    },
  });

  const match2 = await prisma.match.create({
    data: {
      sport: 'Basketball',
      league: 'Demo League',
      teamOne: 'City Hoops',
      teamTwo: 'Valley Stars',
      startsAt: inHours(10),
      status: 'SCHEDULED',
    },
  });

  await prisma.card.createMany({
    data: [
      { matchId: match1.id, isActive: true },
      { matchId: match2.id, isActive: true },
    ],
  });

  // Ensure settings row exists
  await prisma.appSettings.upsert({
    where: { id: 1 },
    create: { id: 1, maxSwipesPerDay: 20, maxSkipsPerDay: 3, creditsPerDay: 100 },
    update: {},
  });

  console.log('Seeded demo matches + cards.');
}

main()
  .catch((e) => {
    console.error(e);
    process.exit(1);
  })
  .finally(async () => {
    await prisma.$disconnect();
  });
