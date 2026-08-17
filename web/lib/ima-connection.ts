export const IMA_PROVIDER = "ima";

export type ImaConnectionMode = "automatic" | "manual";
export type ImaLookupStatus =
  | "idle"
  | "loading"
  | "ready"
  | "empty"
  | "error"
  | "manual_verified";

export interface ImaKnowledgeBaseOption {
  id: string;
  name: string;
  description: string | null;
}

export interface ImaManualVerification {
  ok: boolean;
  clientId: string;
  apiKey: string;
  knowledgeBaseId: string;
}

export interface ImaLookupState {
  status: ImaLookupStatus;
  knowledgeBases: ImaKnowledgeBaseOption[];
  selectedId: string;
  nextCursor: string;
  isEnd: boolean;
  manualVerification: ImaManualVerification | null;
  lastAutoName: string | null;
}

interface ProviderChoice {
  id: string;
  linkable?: boolean;
}

export const createProviders = <T extends ProviderChoice>(
  providers: T[],
): T[] => providers.filter((provider) => provider.id !== IMA_PROVIDER);

export const linkSourceEnabled = (provider: ProviderChoice): boolean =>
  provider.id === IMA_PROVIDER || Boolean(provider.linkable);

export const nextAutoName = (
  currentName: string,
  lastAutoName: string | null,
  selectedName: string,
): string =>
  !currentName.trim() || currentName === lastAutoName
    ? selectedName
    : currentName;

export const mergeImaKnowledgeBases = (
  existing: ImaKnowledgeBaseOption[],
  incoming: ImaKnowledgeBaseOption[],
): ImaKnowledgeBaseOption[] => {
  const merged = new Map(existing.map((item) => [item.id, item]));
  incoming.forEach((item) => merged.set(item.id, item));
  return Array.from(merged.values());
};

export const emptyImaLookupState = (): ImaLookupState => ({
  status: "idle",
  knowledgeBases: [],
  selectedId: "",
  nextCursor: "",
  isEnd: true,
  manualVerification: null,
  lastAutoName: null,
});

export const canConnectIma = (input: {
  mode: ImaConnectionMode;
  name: string;
  /** Credentials as submitted — empty when the account pair is used. */
  clientId: string;
  apiKey: string;
  /** Credentials resolve, either from this form or from the account pair. */
  credentialsReady: boolean;
  selectedId: string;
  manualKnowledgeBaseId: string;
  manualVerification: ImaManualVerification | null;
}): boolean => {
  const name = input.name.trim();
  const clientId = input.clientId.trim();
  const apiKey = input.apiKey.trim();
  if (!name || !input.credentialsReady) return false;
  if (input.mode === "automatic") return Boolean(input.selectedId.trim());

  // A manually typed id is only trusted once the verdict for *these* exact
  // credentials came back ok — editing either invalidates it.
  const knowledgeBaseId = input.manualKnowledgeBaseId.trim();
  const verified = input.manualVerification;
  return Boolean(
    knowledgeBaseId &&
    verified?.ok &&
    verified.clientId === clientId &&
    verified.apiKey === apiKey &&
    verified.knowledgeBaseId === knowledgeBaseId,
  );
};
