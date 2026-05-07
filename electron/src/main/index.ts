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
      webviewTag: true,
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

  // Strip "Electron/..." from webview user agent so the embedded web app
  // runs as a standard browser — no custom traffic lights, no drag regions.
  // This matches nexu's architecture: the shell owns chrome, the webview is just content.
  mainWindow.webContents.on(
    "will-attach-webview",
    (_event, webPreferences, params) => {
      const cleanUserAgent =
        params.useragent || mainWindow!.webContents.getUserAgent();
      params.useragent = cleanUserAgent.replace(/\s*Electron\/[\d.]+\s*/, " ");
      webPreferences.sandbox = false;
    },
  );

  // Load the desktop shell, which embeds the web app in a webview
  if (is.dev) {
    mainWindow.loadFile(join(__dirname, "../../shell/index.html"));
  } else {
    mainWindow.loadFile(join(__dirname, "../shell/index.html"));
  }

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
