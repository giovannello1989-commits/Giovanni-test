import React from 'react';
import { Alert, StyleSheet, Text, View } from 'react-native';

import { api } from '../api';
import { useAuth } from '../auth/AuthContext';
import { Screen } from '../components/Screen';
import { SwipeDeck } from '../components/SwipeDeck';
import { FeedCard } from '../components/MatchCard';
import { theme } from '../theme';

export function SwipeScreen() {
  const { token } = useAuth();
  const [cards, setCards] = React.useState<FeedCard[]>([]);
  const [loading, setLoading] = React.useState(false);

  const load = React.useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const res = await api.swipeFeed(token, 12);
      setCards(res.cards as FeedCard[]);
    } catch (err: any) {
      Alert.alert('Could not load picks', err?.message ?? 'Try again.');
    } finally {
      setLoading(false);
    }
  }, [token]);

  React.useEffect(() => {
    void load();
  }, [load]);

  const act = async (c: FeedCard, action: 'PICK_ONE' | 'PICK_TWO' | 'SKIP') => {
    if (!token) return;
    try {
      await api.swipeAction(token, { cardId: c.cardId, action });
    } catch (err: any) {
      // keep UX fast: we already advanced the deck
      Alert.alert('Action failed', err?.message ?? 'Try again.');
    }
  };

  return (
    <Screen>
      <View style={styles.top}>
        <Text style={styles.brand}>Swipster</Text>
        <Text style={styles.meta}>{loading ? 'Loading…' : 'Prematch picks only'}</Text>
      </View>

      <View style={styles.deck}>
        <SwipeDeck
          cards={cards}
          onPick1={(c) => void act(c, 'PICK_ONE')}
          onPick2={(c) => void act(c, 'PICK_TWO')}
          onSkip={(c) => void act(c, 'SKIP')}
        />
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  top: {
    paddingHorizontal: theme.spacing(2),
    paddingTop: theme.spacing(1),
    paddingBottom: theme.spacing(1),
    flexDirection: 'row',
    alignItems: 'flex-end',
    justifyContent: 'space-between',
  },
  brand: {
    color: theme.colors.text,
    fontSize: 18,
    fontWeight: '900',
    letterSpacing: -0.2,
  },
  meta: {
    color: theme.colors.subtext,
    fontSize: 12,
    fontWeight: '700',
  },
  deck: {
    flex: 1,
    paddingTop: 6,
  },
});
