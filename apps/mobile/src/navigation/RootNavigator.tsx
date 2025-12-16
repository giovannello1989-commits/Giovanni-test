import React from 'react';
import { ActivityIndicator, View } from 'react-native';
import { NavigationContainer, DarkTheme } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';

import { useAuth } from '../auth/AuthContext';
import { theme } from '../theme';
import { AuthEmailScreen } from '../screens/AuthEmailScreen';
import { AuthOtpScreen } from '../screens/AuthOtpScreen';
import { MainTabs } from './Tabs';

const Stack = createNativeStackNavigator();

export function RootNavigator() {
  const { token, isLoading } = useAuth();

  if (isLoading) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', backgroundColor: theme.colors.bg }}>
        <ActivityIndicator />
      </View>
    );
  }

  return (
    <NavigationContainer
      theme={{
        ...DarkTheme,
        colors: {
          ...DarkTheme.colors,
          background: theme.colors.bg,
          card: theme.colors.bg2,
          text: theme.colors.text,
          border: theme.colors.stroke,
          primary: theme.colors.accent,
        },
      }}
    >
      <Stack.Navigator screenOptions={{ headerShown: false, animation: 'fade' }}>
        {token ? (
          <Stack.Screen name="Main" component={MainTabs} />
        ) : (
          <>
            <Stack.Screen name="AuthEmail" component={AuthEmailScreen} />
            <Stack.Screen name="AuthOtp" component={AuthOtpScreen} />
          </>
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
