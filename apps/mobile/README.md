# DeepTutor Mobile

This Android and iOS prototype connects to an existing DeepTutor API. It supports
connecting to a server, signing in when required, and starting a conversation
with streamed replies. The web and mobile clients use the same turn protocol
and transport.

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

## Verify

```sh
npm run typecheck
npm run lint
npm test -- --runInBand
```

With a model configured on the server, connect and send two messages in the
same conversation. Verify that replies arrive as they are generated and the
second message uses the same conversation.
