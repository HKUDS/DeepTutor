import AsyncStorage from '@react-native-async-storage/async-storage';

const SERVER_ORIGIN_KEY = 'deeptutor:server-origin:v1';

export interface ServerStorage {
  read(): Promise<string | null>;
  write(origin: string | null): Promise<void>;
}

export const serverStorage: ServerStorage = {
  read: () => AsyncStorage.getItem(SERVER_ORIGIN_KEY),
  write: origin =>
    origin === null
      ? AsyncStorage.removeItem(SERVER_ORIGIN_KEY)
      : AsyncStorage.setItem(SERVER_ORIGIN_KEY, origin),
};
