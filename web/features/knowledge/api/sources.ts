export {
  addGitHubSource,
  addWebSource,
  linkFolder,
  listGitHubSources,
  listLinkedFolders,
  listWebSources,
  removeGitHubSource,
  removeWebSource,
  syncGitHubSources,
  syncLinkedFolder,
  syncWebSources,
  unlinkFolder,
} from "./client";

export type {
  AddGitHubSourcePayload,
  AddWebSourcePayload,
  FolderSyncResult,
  GitHubSource,
  GitHubSyncResult,
  LinkedFolderInfo,
  WebSource,
  WebSyncResult,
  WebSyncSourceResult,
} from "../model/types";
