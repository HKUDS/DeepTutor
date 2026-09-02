export type AppErrorScope =
  | "turn"
  | "session"
  | "runtime"
  | "settings"
  | "network";

export interface AppError {
  code: string;
  message: string;
  retryable: boolean;
  scope: AppErrorScope;
  correlationId?: string;
  status?: number;
}

export class ApiError extends Error {
  readonly appError: AppError;

  constructor(appError: AppError, options?: ErrorOptions) {
    super(appError.message, options);
    this.name = "ApiError";
    this.appError = appError;
  }

  get code(): string {
    return this.appError.code;
  }

  get retryable(): boolean {
    return this.appError.retryable;
  }

  get correlationId(): string | undefined {
    return this.appError.correlationId;
  }

  get status(): number | undefined {
    return this.appError.status;
  }
}

export function isApiError(error: unknown): error is ApiError {
  return error instanceof ApiError;
}
