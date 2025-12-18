import React from 'react';
import { Alert, StyleSheet, Text, View } from 'react-native';

import { api } from '../api';
import { Button } from '../components/Button';
import { Input } from '../components/Input';
import { Screen } from '../components/Screen';
import { theme } from '../theme';

export function AuthEmailScreen({ navigation }: { navigation: any }) {
  const [email, setEmail] = React.useState('');
  const [loading, setLoading] = React.useState(false);

  const request = async () => {
    const e = email.trim().toLowerCase();
    if (!e.includes('@')) {
      Alert.alert('Check your email', 'Please enter a valid email.');
      return;
    }

    setLoading(true);
    try {
      await api.authRequestOtp({
        email: e,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
      navigation.navigate('AuthOtp', { email: e });
    } catch (err: any) {
      Alert.alert('Could not send code', err?.message ?? 'Try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Screen style={styles.screen}>
      <View style={styles.header}>
        <Text style={styles.title}>Swipster</Text>
        <Text style={styles.sub}>Swipe picks. Earn XP. Climb the leaderboard.</Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.label}>Email</Text>
        <Input
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="email-address"
          placeholder="you@email.com"
          returnKeyType="done"
          onSubmitEditing={request}
        />
        <View style={{ height: theme.spacing(2) }} />
        <Button title={loading ? 'Sending…' : 'Send code'} onPress={request} disabled={loading} />
        <View style={{ height: theme.spacing(2) }} />
        <Text style={styles.legal}>
          No real money. No odds. Prematch only. Virtual credits + XP.
        </Text>
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
    fontSize: 40,
    fontWeight: '900',
    letterSpacing: -0.8,
  },
  sub: {
    marginTop: theme.spacing(1),
    color: theme.colors.subtext,
    fontSize: 15,
    lineHeight: 20,
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
  legal: {
    color: theme.colors.subtext,
    fontSize: 12,
    lineHeight: 16,
  },
});
