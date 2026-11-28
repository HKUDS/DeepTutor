import { useColorScheme } from 'react-native';

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 };
export const radius = { sm: 8, md: 12, lg: 16 };
export const textSize = { small: 14, body: 16, heading: 22, title: 28 };

// Match the warm Cream and Dark palettes in web/app/globals.css.
const light = {
  dark: false,
  background: '#fdfcf9',
  surface: '#ffffff',
  text: '#1c1816',
  muted: '#6d645a',
  primary: '#b0501e',
  onPrimary: '#ffffff',
  secondary: '#f5f2ea',
  border: '#e6decc',
  inputBorder: '#a99d8f',
  error: '#972d24',
  errorSurface: '#fceee9',
};

const dark: typeof light = {
  dark: true,
  background: '#1a1918',
  surface: '#242220',
  text: '#e8e4de',
  muted: '#aba39c',
  primary: '#e58b65',
  onPrimary: '#1a1918',
  secondary: '#2a2725',
  border: '#3a3634',
  inputBorder: '#827972',
  error: '#fca49a',
  errorSurface: '#3f2723',
};

export function useTheme() {
  return useColorScheme() === 'dark' ? dark : light;
}
