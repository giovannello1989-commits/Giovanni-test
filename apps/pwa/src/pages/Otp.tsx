import React from 'react';

import { api } from '../api/client';
import { useAuth } from '../auth/auth';
import { Card, Button, Input, Shell } from '../components/ui';
import { theme } from '../styles/theme';

function getEmail() {
  const p = new URLSearchParams(location.search);
  return p.get('email') ?? '';
}

export function Otp() {
  const email = getEmail();
  const { setToken } = useAuth();
  const [code, setCode] = React.useState('');
  const [loading, setLoading] = React.useState(false);

  const verify = async () => {
    const c = code.replace(/\D/g, '').slice(0, 6);
    if (c.length !== 6) return alert('Enter the 6-digit code');

    setLoading(true);
    try {
      const res = await api.verifyOtp({ email, code: c });
      setToken(res.accessToken);
      location.href = '/';
    } catch (err: any) {
      alert(err?.message ?? 'Invalid code');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Shell>
      <div style={{ paddingTop: theme.space(3), paddingBottom: theme.space(2) }}>
        <div style={{ fontSize: 26, fontWeight: 950, letterSpacing: -0.4 }}>Check your email</div>
        <div style={{ marginTop: 6, color: theme.colors.subtext, fontWeight: 800, fontSize: 13 }}>
          We sent a 6-digit code to <span style={{ color: theme.colors.text }}>{email}</span>
        </div>
      </div>

      <Card>
        <div style={{ color: theme.colors.subtext, fontSize: 12, fontWeight: 900, letterSpacing: 0.3, textTransform: 'uppercase' }}>
          Code
        </div>
        <div style={{ height: 8 }} />
        <Input
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
          placeholder="123456"
          inputMode="numeric"
        />
        <div style={{ height: 14 }} />
        <Button disabled={loading} onClick={verify}>
          {loading ? 'Verifying…' : 'Continue'}
        </Button>
        <div style={{ height: 14 }} />
        <div style={{ color: theme.colors.subtext, fontSize: 12, lineHeight: 1.4 }}>
          Codes expire in 10 minutes.
        </div>
      </Card>
    </Shell>
  );
}
