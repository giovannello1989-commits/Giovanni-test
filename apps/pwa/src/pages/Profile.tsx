import { API_BASE_URL } from '../api/client';
import { useAuth } from '../auth/auth';
import { Card, Button, Shell, TopBar, BottomNav } from '../components/ui';
import { theme } from '../styles/theme';

export function Profile() {
  const { signOut } = useAuth();

  return (
    <Shell>
      <TopBar title="Profile" />
      <Card>
        <div style={{ color: theme.colors.subtext, fontSize: 12, fontWeight: 900, letterSpacing: 0.3, textTransform: 'uppercase' }}>API</div>
        <div style={{ marginTop: 10, fontWeight: 900, fontSize: 13 }}>{API_BASE_URL}</div>
        <div style={{ height: 14 }} />
        <Button variant="ghost" onClick={() => (confirm('Sign out?') ? signOut() : undefined)}>
          Sign out
        </Button>
        <div style={{ height: 14 }} />
        <div style={{ color: theme.colors.subtext, fontSize: 12, lineHeight: 1.4 }}>
          Swipster is a free skill game. Virtual credits only. No odds. Prematch only.
        </div>
      </Card>
      <div style={{ height: 90 }} />
      <BottomNav />
    </Shell>
  );
}
