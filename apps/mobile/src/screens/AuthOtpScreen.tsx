import React from 'react';
import { Alert, StyleSheet, Text, View } from 'react-native';

import { api } from '../api';
import { useAuth } from '../auth/AuthContext';
import { Button } from '../components/Button';
import { Input } from '../components/Input';
import { Screen } from '../components/Screen';
import { theme } from '../theme';

export function AuthOtpScreen({ route }: { route: any }) {
  const { email } = route.params as { email: string };
  const { setToken } = useAuth();

  const [code, setCode] = React.useState('');
  const [loading, setLoading] = React.useState(false);

  const verify = async () => {
    const c = code.replace(/\D/g, '').slice(0, 6);
    if (c.length !== 6) {
      Alert.alert('Enter the 6-digit code', 'Check your email and try again.');
      return;
    }

    setLoading(true);
    try {
      const res = await api.authVerifyOtp({ email, code: c });
      await setToken(res.accessToken);
    } catch (err: any) {
      Alert.alert('Invalid code', err?.message ?? 'Try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Screen style={styles.screen}>
      <View style={styles.header}>
        <Text style={styles.title}>Check your email</Text>
        <Text style={styles.sub}>We sent a 6-digit code to {email}</Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.label}>Code</Text>
        <Input
          value={code}
          onChangeText={(v) => setCode(v.replace(/\D/g, '').slice(0, 6))}
          keyboardType="number-pad"
          placeholder="123456"
          returnKeyType="done"
          onSubmitEditing={verify}
        />
        <View style={{ height: theme.spacing(2) }} />
        <Button title={loading ? 'Verifying…' : 'Continue'} onPress={verify} disabled={loading} />
        <View style={{ height: theme.spacing(2) }} />
        <Text style={styles.hint}>If you don’t see it, check spam. Codes expire in 10 minutes.</Text>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: {
    padding: theme.spacing(2),
  },
  header: {
    paddingTop: theme.spacing(4),
    paddingBottom: theme.spacing(3),
  },
  title: {
    color: theme.colors.text,
    fontSize: 26,
    fontWeight: '800',
    letterSpacing: -0.3,
  },
  sub: {
    marginTop: theme.spacing(1),
    color: theme.colors.subtext,
    fontSize: 14,
    lineHeight: 19,
  },
  card: {
    borderRadius: theme.radii.card,
    borderWidth: 1,
    borderColor: theme.colors.stroke,
    backgroundColor: theme.colors.bg2,
    padding: theme.spacing(2),
  },
  label: {
    color: theme.colors.subtext,
    fontSize: 12,
    marginBottom: theme.spacing(1),
    fontWeight: '700',
    letterSpacing: 0.3,
    textTransform: 'uppercase',
  },
  hint: {
    color: theme.colors.subtext,
    fontSize: 12,
    lineHeight: 16,
  },
});
