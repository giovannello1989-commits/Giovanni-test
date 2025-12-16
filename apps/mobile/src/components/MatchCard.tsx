import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';

import { theme } from '../theme';
import { formatKickoff } from '../utils/format';

export type FeedCard = {
  cardId: string;
  matchId: string;
  sport: string;
  league?: string | null;
  teamOne: string;
  teamTwo: string;
  startsAt: string;
};

export function MatchCard({ card }: { card: FeedCard }) {
  return (
    <LinearGradient
      colors={["rgba(29,155,240,0.12)", 'rgba(15,22,32,0.0)', 'rgba(255,77,109,0.10)']}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 1 }}
      style={styles.wrap}
    >
      <View style={styles.header}>
        <Text style={styles.meta}>
          {card.sport}{card.league ? ` · ${card.league}` : ''}
        </Text>
        <View style={styles.pill}>
          <Text style={styles.pillText}>Kickoff {formatKickoff(card.startsAt)}</Text>
        </View>
      </View>

      <View style={styles.center}>
        <Text numberOfLines={2} style={styles.team}>{card.teamOne}</Text>
        <Text style={styles.vs}>vs</Text>
        <Text numberOfLines={2} style={styles.team}>{card.teamTwo}</Text>
      </View>

      <View style={styles.footer}>
        <Text style={styles.footerText}>Swipe right: Pick 1</Text>
        <Text style={styles.footerDot}>·</Text>
        <Text style={styles.footerText}>Swipe left: Pick 2</Text>
      </View>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    borderRadius: theme.radii.card,
    borderWidth: 1,
    borderColor: theme.colors.stroke2,
    backgroundColor: theme.colors.bg2,
    padding: theme.spacing(2),
    overflow: 'hidden',
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  meta: {
    color: theme.colors.subtext,
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.3,
  },
  pill: {
    paddingHorizontal: theme.spacing(1.5),
    paddingVertical: theme.spacing(0.75),
    borderRadius: theme.radii.pill,
    borderWidth: 1,
    borderColor: theme.colors.stroke,
    backgroundColor: 'rgba(255,255,255,0.04)',
  },
  pillText: {
    color: theme.colors.text,
    fontSize: 12,
    fontWeight: '800',
  },
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: theme.spacing(1),
  },
  team: {
    color: theme.colors.text,
    fontSize: 28,
    fontWeight: '900',
    textAlign: 'center',
    letterSpacing: -0.4,
  },
  vs: {
    marginVertical: theme.spacing(1),
    color: theme.colors.subtext,
    fontSize: 12,
    fontWeight: '800',
    letterSpacing: 1.2,
    textTransform: 'uppercase',
  },
  footer: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    paddingBottom: theme.spacing(0.5),
  },
  footerText: {
    color: theme.colors.subtext,
    fontSize: 12,
    fontWeight: '700',
  },
  footerDot: {
    color: theme.colors.subtext,
    marginHorizontal: theme.spacing(1),
  },
});
