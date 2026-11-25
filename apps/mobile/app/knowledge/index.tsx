import { useCallback, useMemo, useState } from 'react';
import { useRouter } from 'expo-router';
import { useAppSession } from '../../src/appSession';
import { useKnowledgeBases } from '../../src/features/knowledge/useKnowledgeBases';
import { useRefreshOnFocus } from '../../src/features/knowledge/useRefreshOnFocus';
import { KnowledgeListScreen } from '../../src/screens/knowledge/KnowledgeListScreen';
import { ApiClient } from '../../src/services/apiClient';
import {
  KnowledgeApi,
  messageFor,
} from '../../src/services/knowledgeApi';

export default function KnowledgeRoute() {
  const router = useRouter();
  const session = useAppSession();
  const [creating, setCreating] = useState(false);

  const api = useMemo(
    () =>
      session.origin ? new KnowledgeApi(new ApiClient(session.origin)) : null,
    [session.origin],
  );
  const list = useKnowledgeBases(api);
  // A base deleted from its detail page is gone by the time this screen is
  // visible again, so the catalogue is re-read rather than trusted.
  useRefreshOnFocus(list.refresh);

  const create = useCallback(
    async (name: string) => {
      if (!api) return 'This device is not connected to a server.';
      setCreating(true);
      try {
        const created = await api.create(name);
        await list.refresh();
        // The server answers with the name it registered. Every per-base route
        // resolves a name — the id the creation reply carries is scope-dependent
        // (`user:kb:` or `admin:kb:`), while the name works in both.
        router.push({ pathname: '/knowledge/detail', params: { ref: created } });
        return null;
      } catch (error) {
        return messageFor(error);
      } finally {
        setCreating(false);
      }
    },
    [api, list, router],
  );

  if (session.phase !== 'chat') return null;

  return (
    <KnowledgeListScreen
      bases={list.bases}
      status={list.status}
      refreshing={list.refreshing}
      error={list.error}
      creating={creating}
      onCreate={create}
      onOpen={ref => router.push({ pathname: '/knowledge/detail', params: { ref } })}
      onRefresh={() => {
        list.refresh().catch(() => {});
      }}
      onRetry={() => {
        list.refresh().catch(() => {});
      }}
      onBack={() => router.back()}
    />
  );
}
