import { fetch as nativeFetch } from 'expo/fetch';

export type ApiErrorKind =
  | 'aborted'
  | 'timeout'
  | 'network'
  | 'redirect'
  | 'unauthorized'
  | 'http'
  | 'invalid-response';

export class ApiError extends Error {
  constructor(
    readonly kind: ApiErrorKind,
    message: string,
    readonly status?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export type ApiMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE';

type ApiOptions = {
  method?: ApiMethod;
  body?: object;
  signal?: AbortSignal;
};

type ApiFetch = (
  url: string,
  init: {
    method: ApiMethod;
    credentials: 'include';
    redirect: 'manual';
    headers: Record<string, string>;
    body?: string;
    signal: AbortSignal;
  },
) => Promise<
  Pick<Response, 'ok' | 'status' | 'redirected'> & { json(): Promise<unknown> }
>;

const DEFAULT_TIMEOUT = 12_000;

export class ApiClient {
  constructor(
    private readonly origin: string,
    private readonly fetcher: ApiFetch = nativeFetch,
    private readonly timeoutMs = DEFAULT_TIMEOUT,
  ) {}

  async json<T>(
    path: `/api/${string}`,
    parse: (value: unknown) => T,
    { method = 'GET', body, signal }: ApiOptions = {},
  ): Promise<T> {
    // Path segments are alphanumeric plus `-_.%` so encoded identifiers survive,
    // and the optional query keeps session pagination on the same guard.
    if (
      !/^\/api\/(?:[A-Za-z0-9_.%-]+\/)*[A-Za-z0-9_.%-]+(?:\?[A-Za-z0-9_.%=&-]*)?$/.test(
        path,
      )
    ) {
      throw new ApiError('network', 'Invalid DeepTutor API path.');
    }
    if (signal?.aborted) {
      throw new ApiError('aborted', 'The request was cancelled.');
    }
    const controller = new AbortController();
    let rejectCancellation: (reason: ApiError) => void = () => {};
    const cancellation = new Promise<never>((_, reject) => {
      rejectCancellation = reject;
    });
    const cancel = (reason: ApiError) => {
      rejectCancellation(reason);
      controller.abort();
    };
    const abort = () =>
      cancel(new ApiError('aborted', 'The request was cancelled.'));
    signal?.addEventListener('abort', abort);
    const timer = setTimeout(
      () =>
        cancel(new ApiError('timeout', 'The server took too long to respond.')),
      this.timeoutMs,
    );

    try {
      return await Promise.race([
        cancellation,
        this.request(path, parse, method, body, controller.signal),
      ]);
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
    }
  }

  private async request<T>(
    path: string,
    parse: (value: unknown) => T,
    method: ApiMethod,
    body: object | undefined,
    signal: AbortSignal,
  ): Promise<T> {
    let response;
    try {
      // The native Expo implementation honors manual redirects on both platforms.
      // A login body or an HttpOnly cookie must never be forwarded to another origin.
      response = await this.fetcher(`${this.origin}${path}`, {
        credentials: 'include',
        redirect: 'manual',
        method,
        headers: body
          ? { Accept: 'application/json', 'Content-Type': 'application/json' }
          : { Accept: 'application/json' },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
        signal,
      });
    } catch {
      throw new ApiError('network', 'Could not reach the DeepTutor server.');
    }
    if (
      response.redirected ||
      (response.status >= 300 && response.status < 400)
    ) {
      throw new ApiError(
        'redirect',
        'Enter the final address of the DeepTutor server.',
        response.status,
      );
    }
    if (response.status === 401) {
      throw new ApiError('unauthorized', 'Sign-in is required.', 401);
    }
    if (!response.ok) {
      throw new ApiError(
        'http',
        `The server returned HTTP ${response.status}.`,
        response.status,
      );
    }
    try {
      return parse(await response.json());
    } catch {
      throw new ApiError(
        'invalid-response',
        'The server did not return a valid DeepTutor response.',
      );
    }
  }
}
