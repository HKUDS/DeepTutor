import { app, shell, BrowserWindow, Tray, nativeImage } from "electron";
import { join } from "path";
import { electronApp, optimizer, is } from "@electron-toolkit/utils";
import log from "electron-log";
import { BackendManager } from "./backend";
import { setupIpcHandlers } from "./ipc-handlers";
import { createTray } from "./tray";
import { createMenu } from "./menu";

log.initialize();
log.info("DeepTutor Desktop starting...");

let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
const backend = new BackendManager();

function getIconPath(): string {
  if (is.dev) {
    return join(__dirname, "../../build/icon.png");
  }
  return join(__dirname, "../build/icon.png");
}

function getDesktopWebUrl(): string {
  const baseUrl =
    process.env.DEEPTUTOR_WEB_URL ||
    (is.dev ? "http://localhost:3000" : "http://localhost:8001");
  const url = new URL(baseUrl);
  url.searchParams.set("desktop", "1");
  url.searchParams.set("_t", Date.now().toString());
  return url.toString();
}

function stripElectronUserAgent(userAgent: string): string {
  return userAgent.replace(/\s*Electron\/[\d.]+\s*/, " ");
}

function createWindow(): void {
  const isMacOS = process.platform === "darwin";
  const iconPath = getIconPath();

  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    show: false,
    title: "DeepTutor",
    titleBarStyle: isMacOS ? "hiddenInset" : "default",
    trafficLightPosition: isMacOS ? { x: 18, y: 18 } : undefined,
    backgroundColor: isMacOS ? "#00000000" : "#0B1020",
    ...(isMacOS
      ? {
          transparent: true,
          vibrancy: "sidebar" as const,
          visualEffectState: "followWindow" as const,
        }
      : {}),
    webPreferences: {
      preload: join(__dirname, "../preload/index.js"),
      sandbox: false,
      contextIsolation: true,
      nodeIntegration: false,
    },
    icon: nativeImage.createFromPath(iconPath),
  });

  if (isMacOS) {
    mainWindow.setBackgroundColor("#00000000");
    mainWindow.setVibrancy("sidebar");
  }

  mainWindow.on("ready-to-show", () => {
    mainWindow?.show();
    log.info("Main window shown");
  });

  mainWindow.webContents.setWindowOpenHandler((details) => {
    shell.openExternal(details.url);
    return { action: "deny" };
  });

  // Load the web app directly. CSS app-region drag zones only reach the native
  // BrowserWindow from the main renderer; nesting the app in <webview> swallows
  // those drag events on macOS.
  mainWindow.webContents.setUserAgent(
    stripElectronUserAgent(mainWindow.webContents.getUserAgent()),
  );
  mainWindow.loadURL(getDesktopWebUrl());

  // Setup menu
  createMenu(mainWindow);

  // Setup IPC
  setupIpcHandlers(mainWindow);
}

app.whenReady().then(async () => {
  log.info("App ready");

  electronApp.setAppUserModelId("com.deeptutor.desktop");

  // Set macOS dock icon
  if (process.platform === "darwin" && app.dock) {
    app.dock.setIcon(getIconPath());
  }

  app.on("browser-window-created", (_, window) => {
    optimizer.watchWindowShortcuts(window);
  });

  // Start backend
  try {
    await backend.start();
    log.info("Backend started successfully");
  } catch (error) {
    log.error("Failed to start backend:", error);
  }

  createWindow();

  tray = createTray(mainWindow);

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  backend.stop();
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  backend.stop();
});
