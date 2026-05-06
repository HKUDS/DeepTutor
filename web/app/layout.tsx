import type { Metadata } from "next";
import { Plus_Jakarta_Sans, Lora } from "next/font/google";
import Script from "next/script";
import "./globals.css";
import { AppShellProvider } from "@/context/AppShellContext";
import { I18nClientBridge } from "@/i18n/I18nClientBridge";

const fontSans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
});

const fontSerif = Lora({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-serif",
});

export const metadata: Metadata = {
  title: "DeepTutor",
  description: "Agent-native intelligent learning companion",
  icons: {
    icon: [
      { url: "/favicon-16x16.png", sizes: "16x16", type: "image/png" },
      { url: "/favicon-32x32.png", sizes: "32x32", type: "image/png" },
    ],
    apple: "/apple-touch-icon.png",
  },
};

const themeScript = `(function(){try{var s=localStorage.getItem('deeptutor-theme');document.documentElement.classList.remove('dark','theme-glass','theme-snow');if(s==='dark'){document.documentElement.classList.add('dark');}else if(s==='glass'){document.documentElement.classList.add('dark','theme-glass');}else if(s==='snow'){document.documentElement.classList.add('theme-snow');}else if(s==='light'){}else{if(window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches){document.documentElement.classList.add('dark');localStorage.setItem('deeptutor-theme','dark');}else{localStorage.setItem('deeptutor-theme','light');}}}catch(e){}})();`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      data-scroll-behavior="smooth"
      className={`${fontSans.variable} ${fontSerif.variable}`}
    >
      <head>
        <Script id="theme-init" strategy="beforeInteractive">
          {themeScript}
        </Script>
      </head>
      <body className="font-sans bg-[var(--background)] text-[var(--foreground)]">
        <AppShellProvider>
          <I18nClientBridge>{children}</I18nClientBridge>
        </AppShellProvider>
      </body>
    </html>
  );
}
