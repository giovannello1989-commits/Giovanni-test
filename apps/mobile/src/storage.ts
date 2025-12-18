import AsyncStorage from '@react-native-async-storage/async-storage';

const KEY = 'swipster.auth.token';

export const storage = {
  getToken: () => AsyncStorage.getItem(KEY),
  setToken: (token: string) => AsyncStorage.setItem(KEY, token),
  clearToken: () => AsyncStorage.removeItem(KEY),
};
