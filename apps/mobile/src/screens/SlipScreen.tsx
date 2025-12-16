import React from 'react';
import { Alert, ScrollView, StyleSheet, Text, View } from 'react-native';

import { api } from '../api';
import { useAuth } from '../auth/AuthContext';
import { Button } from '../components/Button';
import { Input } from '../components/Input';
import { Screen } from '../components/Screen';
import { theme } from '../theme';

type SlipResponse = {
  slip: null | {
    id: string;
    status: string;
    creditsRequired: number;
    creditsAllocated: number;
    items: Array<{
      slipItemId: string;
      side: 'ONE' | 'TWO';
      credits: number;
      match: { teamOne: string; teamTwo: string; startsAt: string };
    }>;
  };
};

export function SlipScreen() {
  const { token } = useAuth();
  const [data, setData] = React.useState<SlipResponse['slip']>(null);
  const [alloc, setAlloc] = React.useState<Record<string, string>>({});
  const [loading, setLoading] = React.useState(false);

  const load = React.useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await api.slipCurrent(token);
      setData(res.slip as any);
      const next: Record<string, string> = {};
      for (const it of (res.slip?.items ?? []) as any[]) next[it.slipItemId] = String(it.credits ?? 0);
      setAlloc(next);
    } catch (err: any) {
      Alert.alert('Could not load slip', err?.message ?? 'Try again.');
    } finally {
      setLoading(false);
    }
  }, [token]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const total = Object.values(alloc).reduce((s, v) => s + (Number(v) || 0), 0);
  const required = data?.creditsRequired ?? 0;
  const remaining = Math.max(0, required - total);

  const save = async () => {
    if (!token || !data) return;
    try {
      await api.slipAllocateCredits(token, {
        allocations: data.items.map((it) => ({
          slipItemId: it.slipItemId,
          credits: Math.max(0, Number(alloc[it.slipItemId] ?? 0) || 0),
        })),
      });
      await load();
    } catch (err: any) {
      Alert.alert('Could not update credits', err?.message ?? 'Try again.');
    }
  };

  return (
    <Screen>
      <View style={styles.top}>
        <Text style={styles.title}>Slip</Text>
        <Text style={styles.sub}>Use all credits to make it valid.</Text>
      </View>

      <ScrollView contentContainerStyle={styles.content}>
        {!data ? (
          <View style={styles.empty}>
            <Text style={styles.emptyTitle}>{loading ? 'Loading…' : 'No picks yet'}</Text>
            <Text style={styles.emptySub}>Swipe on Home to add picks.</Text>
          </View>
        ) : (
          <>
            <View style={styles.summary}>
              <View>
                <Text style={styles.k}>Status</Text>
                <Text style={styles.v}>{data.status}</Text>
              </View>
              <View>
                <Text style={styles.k}>Credits</Text>
                <Text style={styles.v}>
                  {total}/{required}
                </Text>
              </View>
              <View>
                <Text style={styles.k}>Left</Text>
                <Text style={[styles.v, { color: remaining === 0 ? theme.colors.good : theme.colors.warn }]}>
                  {remaining}
                </Text>
              </View>
            </View>

            {data.items.map((it) => (
              <View key={it.slipItemId} style={styles.item}>
                <Text style={styles.match} numberOfLines={1}>
                  {it.match.teamOne} vs {it.match.teamTwo}
                </Text>
                <Text style={styles.pick}>Pick: {it.side === 'ONE' ? '1' : '2'}</Text>
                <View style={{ height: theme.spacing(1) }} />
                <Input
                  value={alloc[it.slipItemId] ?? '0'}
                  onChangeText={(v) => setAlloc((p) => ({ ...p, [it.slipItemId]: v.replace(/\D/g, '').slice(0, 4) }))}
                  keyboardType="number-pad"
                  placeholder="0"
                />
              </View>
            ))}

            <View style={{ height: theme.spacing(2) }} />
            <Button title="Update credits" onPress={save} disabled={loading} />
            <View style={{ height: theme.spacing(2) }} />
            <Text style={styles.legal}>Virtual credits only. XP and ranking are the rewards.</Text>
          </>
        )}
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  top: {
    paddingHorizontal: theme.spacing(2),
    paddingTop: theme.spacing(2),
    paddingBottom: theme.spacing(1),
  },
  title: {
    color: theme.colors.text,
    fontSize: 24,
    fontWeight: '900',
    letterSpacing: -0.3,
  },
  sub: {
    marginTop: 4,
    color: theme.colors.subtext,
    fontSize: 12,
    fontWeight: '700',
  },
  content: {
    padding: theme.spacing(2),
    paddingBottom: 110,
  },
  summary: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    borderWidth: 1,
    borderColor: theme.colors.stroke,
    backgroundColor: theme.colors.bg2,
    borderRadius: theme.radii.card,
    padding: theme.spacing(2),
  },
  k: {
    color: theme.colors.subtext,
    fontSize: 11,
    fontWeight: '800',
    letterSpacing: 0.3,
    textTransform: 'uppercase',
  },
  v: {
    marginTop: 4,
    color: theme.colors.text,
    fontSize: 16,
    fontWeight: '900',
  },
  item: {
    marginTop: theme.spacing(2),
    borderWidth: 1,
    borderColor: theme.colors.stroke,
    backgroundColor: theme.colors.bg2,
    borderRadius: theme.radii.card,
    padding: theme.spacing(2),
  },
  match: {
    color: theme.colors.text,
    fontSize: 14,
    fontWeight: '900',
  },
  pick: {
    marginTop: 4,
    color: theme.colors.subtext,
    fontSize: 12,
    fontWeight: '800',
  },
  legal: {
    color: theme.colors.subtext,
    fontSize: 12,
    lineHeight: 16,
  },
  empty: {
    paddingTop: 50,
    alignItems: 'center',
  },
  emptyTitle: {
    color: theme.colors.text,
    fontSize: 18,
    fontWeight: '900',
  },
  emptySub: {
    marginTop: 8,
    color: theme.colors.subtext,
    fontSize: 13,
  },
});
