import React from 'react';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';

import { SwipeScreen } from '../screens/SwipeScreen';
import { SlipScreen } from '../screens/SlipScreen';
import { ProfileScreen } from '../screens/ProfileScreen';

const Tab = createBottomTabNavigator();

export function MainTabs() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerShown: false,
        tabBarStyle: { backgroundColor: 'rgba(15,22,32,0.98)' },
      }}
    >
      <Tab.Screen name="Swipe" component={SwipeScreen} />
      <Tab.Screen name="Slip" component={SlipScreen} />
      <Tab.Screen name="Profile" component={ProfileScreen} />
    </Tab.Navigator>
  );
}
