export interface CapabilityManifest {
  name?: string;
  description?: string;
  version?: string;
  [key: string]: unknown;
}

export interface CapabilityConfigSchema {
  type?: string;
  properties?: Record<string, CapabilityFieldSchema>;
  required?: readonly string[];
  additionalProperties?: boolean;
}

export interface CapabilityFieldSchema {
  type?: "string" | "number" | "integer" | "boolean" | string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: readonly unknown[];
  minimum?: number;
  maximum?: number;
}

export interface CapabilityDescriptor {
  id: string;
  kind: string;
  available: boolean;
  manifest: CapabilityManifest | null;
  configSchema: CapabilityConfigSchema | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function descriptorFrom(value: unknown): CapabilityDescriptor | null {
  if (typeof value === "string" && value.trim()) {
    return {
      id: value.trim(),
      kind: "capability",
      available: true,
      manifest: null,
      configSchema: null,
    };
  }
  if (!isRecord(value)) return null;
  const rawId = value.id ?? value.name;
  if (typeof rawId !== "string" || !rawId.trim()) return null;
  return {
    id: rawId.trim(),
    kind:
      typeof value.kind === "string" && value.kind ? value.kind : "capability",
    available: value.available !== false,
    manifest: isRecord(value.manifest) ? value.manifest : null,
    configSchema: isRecord(value.config_schema)
      ? (value.config_schema as CapabilityConfigSchema)
      : isRecord(value.configSchema)
        ? (value.configSchema as CapabilityConfigSchema)
        : null,
  };
}

export function parseCapabilityCatalogPayload(
  payload: unknown,
): CapabilityDescriptor[] {
  if (!isRecord(payload)) return [];
  const raw = payload.capabilities;
  if (!Array.isArray(raw)) return [];
  const result: CapabilityDescriptor[] = [];
  const seen = new Set<string>();
  for (const item of raw) {
    const descriptor = descriptorFrom(item);
    if (!descriptor || seen.has(descriptor.id)) continue;
    seen.add(descriptor.id);
    result.push(descriptor);
  }
  return result;
}

export type CapabilityConfigResult =
  | { ok: true; value: Record<string, string | number | boolean> }
  | { ok: false; errors: string[] };

function validatePrimitive(
  name: string,
  schema: CapabilityFieldSchema,
  value: unknown,
): string | null {
  if (
    schema.enum &&
    !schema.enum.some((candidate) => Object.is(candidate, value))
  ) {
    return `${name} is not an allowed value`;
  }
  if (schema.type === "boolean") {
    return typeof value === "boolean" ? null : `${name} must be a boolean`;
  }
  if (schema.type === "string") {
    return typeof value === "string" ? null : `${name} must be a string`;
  }
  if (schema.type === "number" || schema.type === "integer") {
    if (typeof value !== "number" || !Number.isFinite(value)) {
      return `${name} must be a number`;
    }
    if (schema.type === "integer" && !Number.isInteger(value)) {
      return `${name} must be an integer`;
    }
    if (typeof schema.minimum === "number" && value < schema.minimum) {
      return `${name} must be at least ${schema.minimum}`;
    }
    if (typeof schema.maximum === "number" && value > schema.maximum) {
      return `${name} must be at most ${schema.maximum}`;
    }
    return null;
  }
  return `${name} uses an unsupported schema type`;
}

export function sanitizeCapabilityConfig(
  schema: CapabilityConfigSchema | null,
  input: unknown,
): CapabilityConfigResult {
  if (
    !schema ||
    schema.type !== "object" ||
    !schema.properties ||
    !isRecord(input)
  ) {
    return {
      ok: false,
      errors: ["Capability configuration schema is unsupported"],
    };
  }
  const errors: string[] = [];
  const output: Record<string, string | number | boolean> = {};
  const required = new Set(schema.required ?? []);
  for (const name of required) {
    if (!(name in input)) errors.push(`${name} is required`);
  }
  for (const [name, value] of Object.entries(input)) {
    const field = schema.properties[name];
    if (!field) {
      errors.push(`${name} is not a recognized field`);
      continue;
    }
    const error = validatePrimitive(name, field, value);
    if (error) errors.push(error);
    else output[name] = value as string | number | boolean;
  }
  return errors.length ? { ok: false, errors } : { ok: true, value: output };
}
