import React from 'react';
import { motion, useMotionValue, useTransform, animate } from 'framer-motion';

import { api } from '../api/client';
import { useAuth } from '../auth/auth';
import { BottomNav, Card, Shell, TopBar } from '../components/ui';
import { theme } from '../styles/theme';

type FeedCard = {
  cardId: string;
  teamOne: string;
  teamTwo: string;
  sport: string;
  league?: string | null;
  startsAt: string;
};

function kickoff(t: string) {
  const d = new Date(t);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function Swipe() {
  const { token } = useAuth();
  const [cards, setCards] = React.useState<FeedCard[]>([]);
  const [idx, setIdx] = React.useState(0);
  const [loading, setLoading] = React.useState(false);

  const x = useMotionValue(0);
  const y = useMotionValue(0);
  const rot = useTransform(x, [-260, 0, 260], [-12, 0, 12]);
  const like = useTransform(x, [0, 140, 240], [0, 0.45, 1]);
  const nope = useTransform(x, [-240, -140, 0], [1, 0.45, 0]);

  const top = cards[idx];
  const next = cards[idx + 1];

  const load = React.useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await api.feed(token, 14);
      setCards(res.cards as FeedCard[]);
      setIdx(0);
    } catch (err: any) {
      alert(err?.message ?? 'Could not load picks');
    } finally {
      setLoading(false);
    }
  }, [token]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const advance = React.useCallback(() => {
    x.set(0);
    y.set(0);
    setIdx((p) => p + 1);
  }, [x, y]);

  const act = React.useCallback(
    async (c: FeedCard, action: 'PICK_ONE' | 'PICK_TWO' | 'SKIP') => {
      if (!token) return;
      try {
        await api.action(token, { cardId: c.cardId, action });
      } catch {
        // keep it snappy
      }
    },
    [token],
  );

  const onDragEnd = async (_: any, info: { offset: { x: number; y: number } }) => {
    if (!top) return;

    const mx = info.offset.x;
    const throwX = 240;

    if (mx > throwX) {
      void act(top, 'PICK_ONE');
      await animate(x, 520, { duration: 0.18 });
      advance();
      return;
    }
    if (mx < -throwX) {
      void act(top, 'PICK_TWO');
      await animate(x, -520, { duration: 0.18 });
      advance();
      return;
    }

    await Promise.all([
      animate(x, 0, { type: 'spring', stiffness: 320, damping: 22 }),
      animate(y, 0, { type: 'spring', stiffness: 320, damping: 22 }),
    ]);
  };

  const pick1 = async () => {
    if (!top) return;
    void act(top, 'PICK_ONE');
    await animate(x, 520, { duration: 0.18 });
    advance();
  };
  const pick2 = async () => {
    if (!top) return;
    void act(top, 'PICK_TWO');
    await animate(x, -520, { duration: 0.18 });
    advance();
  };
  const skip = async () => {
    if (!top) return;
    void act(top, 'SKIP');
    await animate(y, 520, { duration: 0.18 });
    advance();
  };

  return (
    <Shell>
      <TopBar title="Swipe" right={<a href="/slip" style={{ color: theme.colors.subtext, fontWeight: 900, fontSize: 12 }}>Slip</a>} />

      <div style={{ position: 'relative', height: 640, maxHeight: '72vh' }}>
        {next ? (
          <div style={{ position: 'absolute', inset: 0, transform: 'scale(0.985) translateY(8px)' }}>
            <MatchCard card={next} />
          </div>
        ) : null}

        {top ? (
          <motion.div
            style={{
              position: 'absolute',
              inset: 0,
              x,
              y,
              rotate: rot,
              touchAction: 'none',
            }}
            drag
            dragMomentum={false}
            dragElastic={0.16}
            onDragEnd={onDragEnd}
          >
            <MatchCard card={top} />
            <motion.div style={{ position: 'absolute', top: 18, right: 16, opacity: like }}>
              <Badge text="PICK 1" color={theme.colors.good} />
            </motion.div>
            <motion.div style={{ position: 'absolute', top: 18, left: 16, opacity: nope }}>
              <Badge text="PICK 2" color={theme.colors.bad} />
            </motion.div>
          </motion.div>
        ) : (
          <Card>
            <div style={{ fontWeight: 950, fontSize: 16 }}>{loading ? 'Loading…' : 'You’re out of cards'}</div>
            <div style={{ marginTop: 8, color: theme.colors.subtext, fontWeight: 800, fontSize: 13 }}>
              Come back later for fresh picks.
            </div>
          </Card>
        )}
      </div>

      <div style={{ display: 'flex', gap: 10, marginTop: 14 }}>
        <Action label="Skip" tone="ghost" onClick={skip} />
        <Action label="Pick 2" tone="bad" onClick={pick2} />
        <Action label="Pick 1" tone="good" onClick={pick1} />
      </div>

      <div style={{ height: 90 }} />
      <BottomNav />
    </Shell>
  );
}

function MatchCard({ card }: { card: FeedCard }) {
  return (
    <div
      style={{
        height: '100%',
        borderRadius: theme.radii.card,
        border: `1px solid ${theme.colors.stroke2}`,
        background: theme.colors.bg2,
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      <div
        style={{
          position: 'absolute',
          inset: -120,
          background:
            'radial-gradient(circle at 20% 10%, rgba(29,155,240,0.20), transparent 50%), radial-gradient(circle at 90% 90%, rgba(255,77,109,0.16), transparent 55%)',
        }}
      />

      <div style={{ position: 'relative', height: '100%', padding: 16, display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ color: theme.colors.subtext, fontSize: 12, fontWeight: 900, letterSpacing: 0.3 }}>
            {card.sport}{card.league ? ` · ${card.league}` : ''}
          </div>
          <div
            style={{
              padding: '8px 12px',
              borderRadius: theme.radii.pill,
              border: `1px solid ${theme.colors.stroke}`,
              background: 'rgba(255,255,255,0.04)',
              fontSize: 12,
              fontWeight: 950,
            }}
          >
            Kickoff {kickoff(card.startsAt)}
          </div>
        </div>

        <div style={{ flex: 1, display: 'grid', placeItems: 'center', textAlign: 'center', padding: '0 10px' }}>
          <div>
            <div style={{ fontSize: 32, fontWeight: 980, letterSpacing: -0.6 }}>{card.teamOne}</div>
            <div style={{ margin: '10px 0', color: theme.colors.subtext, fontSize: 12, fontWeight: 950, letterSpacing: 1.4 }}>
              VS
            </div>
            <div style={{ fontSize: 32, fontWeight: 980, letterSpacing: -0.6 }}>{card.teamTwo}</div>
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'center', gap: 10, color: theme.colors.subtext, fontSize: 12, fontWeight: 900 }}>
          <div>Right: Pick 1</div>
          <div>·</div>
          <div>Left: Pick 2</div>
        </div>
      </div>
    </div>
  );
}

function Badge({ text, color }: { text: string; color: string }) {
  return (
    <div
      style={{
        padding: '8px 12px',
        borderRadius: theme.radii.pill,
        border: '1px solid rgba(255,255,255,0.14)',
        background: 'rgba(11,15,20,0.70)',
        fontWeight: 980,
        letterSpacing: 1.0,
        color,
        fontSize: 12,
      }}
    >
      {text}
    </div>
  );
}

function Action({
  label,
  tone,
  onClick,
}: {
  label: string;
  tone: 'good' | 'bad' | 'ghost';
  onClick: () => void;
}) {
  const bg = tone === 'good' ? 'rgba(35,209,139,0.16)' : tone === 'bad' ? 'rgba(255,77,109,0.16)' : 'rgba(255,255,255,0.06)';
  const border = tone === 'ghost' ? theme.colors.stroke2 : 'rgba(255,255,255,0.10)';
  const color = tone === 'good' ? theme.colors.good : tone === 'bad' ? theme.colors.bad : theme.colors.text;

  return (
    <button
      onClick={onClick}
      style={{
        flex: 1,
        height: 46,
        borderRadius: theme.radii.pill,
        border: `1px solid ${border}`,
        background: bg,
        color,
        fontWeight: 980,
        letterSpacing: 0.2,
        cursor: 'pointer',
      }}
    >
      {label}
    </button>
  );
}
