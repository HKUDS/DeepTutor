// Minimal ambient typings for the File System Access API used by the chat
// import wizard. The DOM lib (TS 5.9) ships FileSystemDirectoryHandle /
// FileSystemFileHandle, but `Window.showDirectoryPicker` and the async-iterator
// helpers live in `dom.asynciterable`, which this project's `lib` does not
// include. Declare just the surface we use rather than widening the global lib.
export {};

declare global {
  interface FileSystemHandle {
    // Persisted-handle permission re-grant (used when refreshing an agent that
    // was picked in an earlier session). Not in this TS version's DOM lib.
    queryPermission?(descriptor?: {
      mode?: "read" | "readwrite";
    }): Promise<PermissionState>;
    requestPermission?(descriptor?: {
      mode?: "read" | "readwrite";
    }): Promise<PermissionState>;
  }

  interface FileSystemDirectoryHandle {
    values(): AsyncIterableIterator<FileSystemHandle>;
    entries(): AsyncIterableIterator<[string, FileSystemHandle]>;
  }

  interface Window {
    showDirectoryPicker?: (options?: {
      id?: string;
      mode?: "read" | "readwrite";
      startIn?: string;
    }) => Promise<FileSystemDirectoryHandle>;
  }
}
