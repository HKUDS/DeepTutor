# DeepTutor Mobile

This Android and iOS prototype connects to an existing DeepTutor API. It supports
connecting to a server, signing in when required, and starting a conversation
with streamed replies. The web and mobile clients use the same turn protocol
and transport. Expo SDK 57 and Expo Dev Client are integrated into the checked-in
React Native projects. Keep `android/` and `ios/` under source control.

## Run on Android

Install Node.js, JDK 17, and the Android SDK. The Gradle project declares its
required SDK, build tools, and NDK versions. Boot an Android Studio emulator,
then run these commands from `apps/mobile`:

```sh
npm ci
npm run android
```

If the API is already running on your computer, enter its port in
`http://10.0.2.2:<port>` in the emulator. For example, if you run
`deeptutor serve --host 127.0.0.1 --port 8001`, enter
`http://10.0.2.2:8001`. For a deployed server, enter its HTTPS origin. Local
HTTP is available only in development builds.

## Run on iOS

On macOS with Xcode and a simulator, run these commands from `apps/mobile`:

```sh
npm ci
bundle install
cd ios && bundle exec pod install && cd ..
npm run ios
```

The simulator can use `http://localhost:<port>` for an API running on the Mac.
For a physical iPhone, use the deployed server's HTTPS origin.

## Native builds and Metro

The npm launch scripts run the local Gradle or Xcode build through Expo CLI.
To build directly, run `./gradlew :app:assembleDebug` from `apps/mobile/android`
(`gradlew.bat :app:assembleDebug` on Windows). On macOS, open
`ios/DeepTutorMobile.xcworkspace` after installing pods and build the
`DeepTutorMobile` scheme. To restart Metro for an already installed
development build, run `npm start` from `apps/mobile`.

EAS Build is optional. To use it, link the app to your Expo project from
`apps/mobile` and run `eas build --profile development --platform android`
or `eas build --profile development-simulator --platform ios`. Keep the
repository-level `web/` directory in the build upload so Metro can resolve
the shared transport. Local builds do not require an Expo account.

## Server deployment

Use an existing DeepTutor deployment or the repository's Docker Compose
deployment with a model configured. Point the app at the HTTPS origin that
serves both `/api/auth/status` and `/ws`. Expo runs the mobile development
toolchain and does not provision a DeepTutor server.

## Verify

```sh
npm run typecheck
npm run lint
npm test -- --runInBand
```

The Mobile CI workflow checks TypeScript, ESLint and Jest, builds an Android
debug APK and compiles the iOS simulator target. On each platform, also run
this smoke test against the self-hosted API:

1. Connect to an authenticated server. Try an incorrect password, then sign
   in with the correct password and verify the chat screen connects.
2. Send two messages in the same chat. Verify replies stream and the second
   answer can refer to the first exchange.
3. Interrupt the network during a reply, then restore it. Verify the app
   reconnects and the replayed response has no duplicated fragments.
4. Try an unreachable address and verify the connection error is visible and
   the form can be retried.
