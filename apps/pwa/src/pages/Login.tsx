import React from 'react';

import { api } from '../api/client';
import { Card, Button, Input, Shell } from '../components/ui';
import { theme } from '../styles/theme';

export function Login() {
  const [email, setEmail] = React.useState('');
  const [loading, setLoading] = React.useState(false);

  const send = async () => {
    const e = email.trim().toLowerCase();
    if (!e.includes('@')) return alert('Enter a valid email');

    setLoading(true);
    try {
      await api.requestOtp({ email: e, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone });
      location.href = `/otp?email=${encodeURIComponent(e)}`;
    } catch (err: any) {
      alert(err?.message ?? 'Could not send code');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Shell>
      <div style={{ paddingTop: theme.space(4), paddingBottom: theme.space(3) }}>
        <div style={{ fontSize: 44, fontWeight: 950, letterSpacing: -1 }}>Swipster</div>
        <div style={{ marginTop: theme.space(1), color: theme.colors.subtext, fontWeight: 800 }}>
          Swipe picks. Earn XP. Climb leaderboards.
        </div>
      </div>

      <Card>
        <div style={{ color: theme.colors.subtext, fontSize: 12, fontWeight: 900, letterSpacing: 0.3, textTransform: 'uppercase' }}>
          Email
        </div>
        <div style={{ height: 8 }} />
        <Input value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@email.com" autoComplete="email" />
        <div style={{ height: 14 }} />
        <Button disabled={loading} onClick={send}>
          {loading ? 'Sending…' : 'Send code'}
        </Button>
        <div style={{ height: 14 }} />
        <div style={{ color: theme.colors.subtext, fontSize: 12, lineHeight: 1.4 }}>
          No real money. No odds. Prematch only. Virtual credits + XP.
        </div>
      </Card>
    </Shell>
  );
}
