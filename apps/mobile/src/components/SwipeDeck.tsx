import React from 'react';
import { Dimensions, StyleSheet, Text, View } from 'react-native';
import { Gesture, GestureDetector } from 'react-native-gesture-handler';
import Animated, {
  interpolate,
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withSpring,
  withTiming,
} from 'react-native-reanimated';
import * as Haptics from 'expo-haptics';

import { theme } from '../theme';
import { FeedCard, MatchCard } from './MatchCard';

const { width: W, height: H } = Dimensions.get('window');
const THROW_X = W * 0.55;
const ROT = 12; // degrees

export function SwipeDeck({
  cards,
  onPick1,
  onPick2,
  onSkip,
}: {
  cards: FeedCard[];
  onPick1: (card: FeedCard) => void;
  onPick2: (card: FeedCard) => void;
  onSkip: (card: FeedCard) => void;
}) {
  const [idx, setIdx] = React.useState(0);
  const top = cards[idx];
  const next = cards[idx + 1];

  const x = useSharedValue(0);
  const y = useSharedValue(0);

  const advance = React.useCallback(() => {
    x.value = 0;
    y.value = 0;
    setIdx((p) => p + 1);
  }, [x, y]);

  const doPick1 = React.useCallback(
    (c: FeedCard) => {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => undefined);
      onPick1(c);
      advance();
    },
    [advance, onPick1],
  );

  const doPick2 = React.useCallback(
    (c: FeedCard) => {
      Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => undefined);
      onPick2(c);
      advance();
    },
    [advance, onPick2],
  );

  const doSkip = React.useCallback(
    (c: FeedCard) => {
      Haptics.selectionAsync().catch(() => undefined);
      onSkip(c);
      advance();
    },
    [advance, onSkip],
  );

  const gesture = Gesture.Pan()
    .onUpdate((e) => {
      x.value = e.translationX;
      y.value = e.translationY;
    })
    .onEnd(() => {
      if (!top) return;

      if (x.value > THROW_X) {
        x.value = withTiming(W * 1.2, { duration: 180 }, () => runOnJS(doPick1)(top));
        y.value = withTiming(y.value, { duration: 180 });
        return;
      }
      if (x.value < -THROW_X) {
        x.value = withTiming(-W * 1.2, { duration: 180 }, () => runOnJS(doPick2)(top));
        y.value = withTiming(y.value, { duration: 180 });
        return;
      }

      x.value = withSpring(0, { damping: 16, stiffness: 180 });
      y.value = withSpring(0, { damping: 16, stiffness: 180 });
    });

  const topStyle = useAnimatedStyle(() => {
    const rotate = `${interpolate(x.value, [-W, 0, W], [-ROT, 0, ROT])}deg`;
    return {
      transform: [{ translateX: x.value }, { translateY: y.value }, { rotate }],
    };
  });

  const likeOpacity = useAnimatedStyle(() => ({
    opacity: interpolate(x.value, [0, THROW_X * 0.7, THROW_X], [0, 0.45, 1]),
  }));

  const nopeOpacity = useAnimatedStyle(() => ({
    opacity: interpolate(x.value, [-THROW_X, -THROW_X * 0.7, 0], [1, 0.45, 0]),
  }));

  const nextStyle = useAnimatedStyle(() => ({
    transform: [
      { scale: interpolate(Math.abs(x.value), [0, THROW_X], [0.98, 1]) },
      { translateY: interpolate(Math.abs(x.value), [0, THROW_X], [10, 0]) },
    ],
  }));

  if (!top) {
    return (
      <View style={styles.empty}>
        <Text style={styles.emptyTitle}>You’re out of cards</Text>
        <Text style={styles.emptySub}>Come back later for fresh picks.</Text>
      </View>
    );
  }

  return (
    <View style={styles.stage}>
      {next ? (
        <Animated.View style={[styles.card, styles.nextCard, nextStyle]}>
          <MatchCard card={next} />
        </Animated.View>
      ) : null}

      <GestureDetector gesture={gesture}>
        <Animated.View style={[styles.card, topStyle]}>
          <MatchCard card={top} />

          <Animated.View style={[styles.badge, styles.badgeRight, likeOpacity]}>
            <Text style={[styles.badgeText, { color: theme.colors.good }]}>PICK 1</Text>
          </Animated.View>

          <Animated.View style={[styles.badge, styles.badgeLeft, nopeOpacity]}>
            <Text style={[styles.badgeText, { color: theme.colors.bad }]}>PICK 2</Text>
          </Animated.View>
        </Animated.View>
      </GestureDetector>

      <View style={styles.actions}>
        <ActionPill title="Skip" tone="ghost" onPress={() => doSkip(top)} />
        <ActionPill title="Pick 2" tone="bad" onPress={() => doPick2(top)} />
        <ActionPill title="Pick 1" tone="good" onPress={() => doPick1(top)} />
      </View>
    </View>
  );
}

function ActionPill({
  title,
  onPress,
  tone,
}: {
  title: string;
  onPress: () => void;
  tone: 'good' | 'bad' | 'ghost';
}) {
  const bg =
    tone === 'good'
      ? 'rgba(35,209,139,0.16)'
      : tone === 'bad'
        ? 'rgba(255,77,109,0.16)'
        : 'rgba(255,255,255,0.06)';

  const border = tone === 'ghost' ? theme.colors.stroke2 : 'rgba(255,255,255,0.10)';

  const color = tone === 'good' ? theme.colors.good : tone === 'bad' ? theme.colors.bad : theme.colors.text;

  return (
    <View style={[styles.pill, { backgroundColor: bg, borderColor: border }]} onTouchEnd={onPress}>
      <Text style={[styles.pillText, { color }]}>{title}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  stage: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  card: {
    width: W - 28,
    height: Math.min(H * 0.72, 640),
    borderRadius: theme.radii.card,
    position: 'absolute',
  },
  nextCard: {
    top: 0,
  },
  badge: {
    position: 'absolute',
    top: 18,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: theme.radii.pill,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.14)',
    backgroundColor: 'rgba(11,15,20,0.72)',
  },
  badgeRight: {
    right: 16,
  },
  badgeLeft: {
    left: 16,
  },
  badgeText: {
    fontSize: 14,
    fontWeight: '900',
    letterSpacing: 0.8,
  },
  actions: {
    position: 'absolute',
    bottom: 18,
    flexDirection: 'row',
    gap: 10,
  },
  pill: {
    height: 44,
    paddingHorizontal: 16,
    borderRadius: theme.radii.pill,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
  },
  pillText: {
    fontSize: 13,
    fontWeight: '900',
    letterSpacing: 0.4,
  },
  empty: {
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
  },
  emptyTitle: {
    color: theme.colors.text,
    fontSize: 20,
    fontWeight: '900',
  },
  emptySub: {
    marginTop: 8,
    color: theme.colors.subtext,
    fontSize: 13,
    textAlign: 'center',
    lineHeight: 18,
  },
});
