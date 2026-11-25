import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useAppSession } from '../../src/appSession';
import { pickDocuments } from '../../src/features/knowledge/pickFiles';
import {
  knowledgeScope,
  useKnowledgeApi,
} from '../../src/features/knowledge/useKnowledgeApi';
import { useKnowledgeBase } from '../../src/features/knowledge/useKnowledgeBase';
import {
  useUploads,
  type UploadDestination,
} from '../../src/features/knowledge/useUploads';
import { KnowledgeDetailScreen } from '../../src/screens/knowledge/KnowledgeDetailScreen';
import {
  messageFor,
  type UploadPolicy,
} from '../../src/services/knowledgeApi';

export default function KnowledgeDetailRoute() {
  const router = useRouter();
  const session = useAppSession();
  const params = useLocalSearchParams<{ ref?: string }>();
  const ref = typeof params.ref === 'string' && params.ref ? params.ref : null;

  const api = useKnowledgeApi(session);
  const detail = useKnowledgeBase(api, ref, knowledgeScope(session));
  const [policy, setPolicy] = useState<UploadPolicy | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // The upload policy belongs to the active parser on this server, so it is
  // read from the server rather than hard-coded. A failure only means the form
  // cannot state the limits; the server still enforces them.
  useEffect(() => {
    if (!api) return undefined;
    let cancelled = false;
    api
      .policy()
      .then(next => {
        if (!cancelled) setPolicy(next);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [api]);

  /**
   * Where the files on this screen may go. It changes with the server, the
   * account and the base, and the upload queue treats every change as a reason
   * to retire what it was holding rather than re-address it.
   */
  const destination = useMemo<UploadDestination | null>(() => {
    if (session.phase !== 'chat' || !session.origin || !ref) return null;
    return {
      origin: session.origin,
      ref,
      accountId: session.status?.accountId ?? '',
    };
  }, [session.phase, session.origin, session.status?.accountId, ref]);

  const uploads = useUploads({
    destination,
    policy,
    onUploaded: () => {
      // A finished upload is the moment the server's run may begin; re-reading
      // the base is what starts the progress polling.
      detail.refresh().catch(() => {});
    },
  });

  const pick = useCallback(async () => {
    setActionError(null);
    try {
      const files = await pickDocuments();
      // If the screen left while the OS picker was open, `upload` sees an
      // unmounted hook and releases the copies instead of queueing them.
      if (files.length) uploads.upload(files);
    } catch {
      setActionError('Could not open the file picker on this device.');
    }
  }, [uploads]);

  const removeBase = useCallback(async () => {
    if (!api || !ref) return;
    setActionError(null);
    try {
      await api.remove(ref);
      router.back();
    } catch (error) {
      setActionError(messageFor(error));
    }
  }, [api, ref, router]);

  if (session.phase !== 'chat' || !ref) return null;

  return (
    <KnowledgeDetailScreen
      kb={detail.kb}
      files={detail.files}
      status={detail.status}
      error={actionError ?? detail.error}
      refreshing={detail.refreshing}
      retrying={detail.retrying}
      saving={detail.saving}
      policy={policy}
      uploads={uploads}
      onBack={() => router.back()}
      onRefresh={() => {
        detail.refresh().catch(() => {});
      }}
      onRetry={() => {
        detail.retry().catch(() => {});
      }}
      onPickFiles={pick}
      onDeleteFile={detail.removeFile}
      onSaveDescription={detail.saveDescription}
      onDeleteBase={() => {
        removeBase().catch(() => {});
      }}
    />
  );
}
