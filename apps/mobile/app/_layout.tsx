import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { AppSessionProvider, useAppSession } from '../src/appSession';
import { useTheme } from '../src/theme/useTheme';

const chatRouteId = () => 'chat';

function SessionStack() {
  const { phase } = useAppSession();
  const theme = useTheme();

  return (
    <>
      <StatusBar style="auto" />
      <Stack
        screenOptions={{
          contentStyle: { backgroundColor: theme.background },
          headerStyle: { backgroundColor: theme.surface },
          headerTintColor: theme.text,
        }}
      >
        <Stack.Screen name="index" options={{ headerShown: false }} />
        <Stack.Protected guard={phase === 'connect'}>
          <Stack.Screen name="server" options={{ headerShown: false }} />
        </Stack.Protected>
        <Stack.Protected guard={phase === 'login'}>
          <Stack.Screen name="login" options={{ headerShown: false }} />
        </Stack.Protected>
        <Stack.Protected guard={phase === 'chat'}>
          <Stack.Screen
            name="chat"
            dangerouslySingular={chatRouteId}
            options={{ headerShown: false }}
          />
          <Stack.Screen name="settings" options={{ title: 'Settings' }} />
        </Stack.Protected>
      </Stack>
    </>
  );
}

export default function RootLayout() {
  return (
    <AppSessionProvider>
      <SessionStack />
    </AppSessionProvider>
  );
}
