import React from 'react';
import { StyleSheet, TextInput, View } from 'react-native';

import { theme } from '../theme';

export function Input(props: React.ComponentProps<typeof TextInput>) {
  return (
    <View style={styles.wrap}>
      <TextInput
        placeholderTextColor={theme.colors.subtext}
        {...props}
        style={[styles.input, props.style]}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    borderRadius: theme.radii.card,
    borderWidth: 1,
    borderColor: theme.colors.stroke,
    backgroundColor: theme.colors.bg2,
    paddingHorizontal: theme.spacing(2),
    paddingVertical: theme.spacing(1),
  },
  input: {
    color: theme.colors.text,
    fontSize: 16,
    paddingVertical: 10,
  },
});
