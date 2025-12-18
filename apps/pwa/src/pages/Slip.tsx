import React from 'react';

import { api } from '../api/client';
import { useAuth } from '../auth/auth';
import { BottomNav, Button, Card, Shell, TopBar, Input } from '../components/ui';
import { theme } from '../styles/theme';

export function Slip() {
  const { token } = useAuth();
  const [slip, setSlip] = React.useState<any | null>(null);
  const [alloc, setAlloc] = React.useState<Record<string, string>>({});
  const [loading, setLoading] = React.useState(false);

  const load = React.useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await api.slipCurrent(token);
      setSlip(res.slip);
      const next: Record<string, string> = {};
      for (const it of res.slip?.items ?? []) next[it.slipItemId] = String(it.credits ?? 0);
      setAlloc(next);
    } finally {
      setLoading(false);
    }
  }, [token]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const total = Object.values(alloc).reduce((s, v) => s + (Number(v) || 0), 0);
  const required = slip?.creditsRequired ?? 0;
  const left = Math.max(0, required - total);

  const save = async () => {
    if (!token || !slip) return;
    try {
      await api.slipAllocate(token, {
        allocations: slip.items.map((it: any) => ({
          slipItemId: it.slipItemId,
          credits: Math.max(0, Number(alloc[it.slipItemId] ?? 0) || 0),
        })),
      });
      await load();
    } catch (err: any) {
      alert(err?.message ?? 'Could not update credits');
    }
  };

  return (
    <Shell>
      <TopBar title="Slip" right={<a href="/" style={{ color: theme.colors.subtext, fontWeight: 900, fontSize: 12 }}>Back</a>} />

      {!slip ? (
        <Card>
          <div style={{ fontWeight: 950, fontSize: 16 }}>{loading ? 'Loading…' : 'No picks yet'}</div>
          <div style={{ marginTop: 8, color: theme.colors.subtext, fontWeight: 800, fontSize: 13 }}>Swipe on Home to add picks.</div>
        </Card>
      ) : (
        <>
          <Card>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <div>
                <div style={{ color: theme.colors.subtext, fontSize: 12, fontWeight: 900, textTransform: 'uppercase' }}>Status</div>
                <div style={{ marginTop: 6, fontWeight: 950 }}>{slip.status}</div>
              </div>
              <div>
                <div style={{ color: theme.colors.subtext, fontSize: 12, fontWeight: 900, textTransform: 'uppercase' }}>Credits</div>
                <div style={{ marginTop: 6, fontWeight: 950 }}>
                  {total}/{required}
                </div>
              </div>
              <div>
                <div style={{ color: theme.colors.subtext, fontSize: 12, fontWeight: 900, textTransform: 'uppercase' }}>Left</div>
                <div style={{ marginTop: 6, fontWeight: 950, color: left === 0 ? theme.colors.good : theme.colors.warn }}>{left}</div>
              </div>
            </div>
          </Card>

          <div style={{ height: 12 }} />

          {slip.items.map((it: any) => (
            <div key={it.slipItemId} style={{ marginTop: 12 }}>
              <Card>
                <div style={{ fontWeight: 950, fontSize: 14 }}>
                  {it.match.teamOne} vs {it.match.teamTwo}
                </div>
                <div style={{ marginTop: 6, color: theme.colors.subtext, fontWeight: 900, fontSize: 12 }}>
                  Pick: {it.side === 'ONE' ? '1' : '2'}
                </div>
                <div style={{ height: 10 }} />
                <Input
                  value={alloc[it.slipItemId] ?? '0'}
                  onChange={(e) => setAlloc((p) => ({ ...p, [it.slipItemId]: e.target.value.replace(/\D/g, '').slice(0, 4) }))}
                  inputMode="numeric"
                />
              </Card>
            </div>
          ))}

          <div style={{ height: 14 }} />
          <Button disabled={loading} onClick={save}>
            Update credits
          </Button>
          <div style={{ height: 14 }} />
          <div style={{ color: theme.colors.subtext, fontSize: 12, lineHeight: 1.4 }}>
            Virtual credits only. Rewards are XP and leaderboard rank.
          </div>
        </>
      )}

      <div style={{ height: 90 }} />
      <BottomNav />
    </Shell>
  );
}
