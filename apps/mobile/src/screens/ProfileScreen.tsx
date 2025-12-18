import React from 'react';
import { Alert, StyleSheet, Text, View } from 'react-native';

import { API_BASE_URL } from '../api';
import { useAuth } from '../auth/AuthContext';
import { Button } from '../components/Button';
import { Screen } from '../components/Screen';
import { theme } from '../theme';

export function ProfileScreen() {
  const { signOut } = useAuth();

  return (
    <Screen>
      <View style={styles.top}>
        <Text style={styles.title}>Profile</Text>
        <Text style={styles.sub}>Founder V1</Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.k}>API</Text>
        <Text style={styles.v} numberOfLines={2}>
          {API_BASE_URL}
        </Text>

        <View style={{ height: theme.spacing(2) }} />
        <Button
          title="Sign out"
          tone="ghost"
          onPress={() =>
            Alert.alert('Sign out?', 'You can log back in with your email code.', [
              { text: 'Cancel', style: 'cancel' },
              { text: 'Sign out', style: 'destructive', onPress: () => void signOut() },
            ])
          }
        />

        <View style={{ height: theme.spacing(2) }} />
        <Text style={styles.legal}>Swipster is a free skill game. Virtual credits only. No odds. No real money.</Text>
      </View>
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
  card: {
    margin: theme.spacing(2),
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
    marginTop: 6,
    color: theme.colors.text,
    fontSize: 13,
    fontWeight: '800',
  },
  legal: {
    color: theme.colors.subtext,
    fontSize: 12,
    lineHeight: 16,
  },
});
