# DeepTutor Mobile

This Android and iOS prototype connects to an existing DeepTutor API. It supports
connecting to a server, signing in when required, and starting a conversation
with streamed replies. The web and mobile clients use the same turn protocol
and transport. Expo SDK 57 and Expo Dev Client are integrated into the checked-in
React Native projects. Keep `android/` and `ios/` under source control.

## Client architecture

- `app/` contains the Expo Router routes. The root layout exposes server setup,
  sign-in, or the authenticated stack according to the current server session.
  Removing access removes the corresponding screens from navigation history.
- `src/screens/`, `src/components/`, and `src/theme/` render native UI and own
  transient UI state such as drafts. They do not make API calls.
- `src/features/server/` and `src/features/auth/` own the selected origin and
  the result of the server's auth check. A stored origin is a preference. The
  server determines whether the user must sign in again.
- `src/services/` handles HTTP deadlines, cancellation, status and payload
  errors. `src/storage/` persists the selected origin using AsyncStorage.
  Passwords are used for sign-in only. Session cookies stay in the native
  cookie store and are scoped to the selected server.
- `src/features/chat/` owns the current conversation and live task. Its state
  belongs to the mounted chat route and resets when the app changes server or
  loses authorization. Settings can be opened without restarting that route.

The server session and chat runtime each expose a snapshot to React via
`useSyncExternalStore`. The server session handles the existing
`/api/auth/status`, `/api/auth/login`, and `/api/auth/logout` endpoints. The
chat runtime delegates sequencing, replay, and reconnects to the shared
`TurnRuntimeClient` on `/ws`. The server remains the authority for account and
conversation data.

Mobile's `@/` alias points to `web/`. It imports the protocol command builders,
wire types, parsers and transport without pulling in Next.js pages, DOM code,
or Web storage. Keep these imports narrow. If more clients need the same files,
move the tested contracts and transport into a shared package and retain Web
compatibility imports during migration.

## Recovery boundaries

The signed-in chat opens its last saved conversation on cold start. The
server transcript and active turn list are authoritative. If an assistant
message already belongs to the live turn, the app keeps that saved answer
and consumes replay for status and completion without appending old text.
This uses turn, assistant-message and parent IDs when present. A payload with
none of these IDs cannot reliably correlate an assistant row with the live
turn. A future protocol change could expose the turn ID and persisted sequence
on every assistant row to cover older or incomplete payloads.

The first event containing the turn and session IDs enables task recovery.
Before those IDs arrive, an unconfirmed start is not automatically resent.
On relaunch, an existing saved session can be opened and checked for a live
turn. A new session whose first frame never arrived has no client-visible
session ID. The public API has no lookup by `client_submission_id`, so that
start cannot be recovered automatically. A future design would persist the
submission ID before send and resolve it through an authenticated,
workspace-scoped lookup. It would also need an explicit idempotency contract
across storage implementations. Today an explicit same-session retry reuses
the ID in the same process, but the server's reservation behavior is
store-dependent and can restart a terminal failed or cancelled submission.

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

The checked-in Gradle and Xcode projects are the source of truth for native
settings. The URL scheme and app IDs match the manifest and Xcode settings,
and the Router plugin's native settings are reflected in the Podfile and
Info.plist. Expo Doctor's app-config sync check is disabled for this setup
because native configuration is maintained directly.

## Server deployment

Use an existing DeepTutor deployment or the repository's Docker Compose
deployment with a model configured. Point the app at the HTTPS origin that
serves both `/api/auth/status` and `/ws`. Expo runs the mobile development
toolchain and does not provision a DeepTutor server.

Enter the final origin configured by your HTTPS proxy. The client rejects
redirects on credentialed requests and does not follow Android WebSocket
handshake redirects. Development builds may connect to the emulator host or
loopback using HTTP. Use HTTPS with a trusted certificate on physical devices
and for deployed instances. If the server limits account login to a private
frontend host, use the approved proxy origin.

The current native links accept only the four static screen paths. The route
adapter drops unfamiliar URLs and query parameters before navigation. When
adding link parameters, validate the values the app accepts.
`package.json` pins the fixed `decode-uri-component` 0.5.1 for the SDK 57
router, and `patches/query-string+7.1.3.patch` bridges its ESM default export
for the older CommonJS consumer. The install applies that patch automatically.
Remove the override and patch when an SDK upgrade removes the old consumer.

## Verify

```sh
npm run typecheck
npm run lint
npm test -- --runInBand
npx expo install --check
npx expo-doctor
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
5. Send another message, send the app to the background, then reopen it. Verify
   replay completes without duplicate text. Try stopping a turn and doing a
   new turn after it stops.
6. Sign out or select another server. Returning to the old screen must require
   current authorization. Verify independently on Android and iOS, including
   updating the server port without changing its hostname.
