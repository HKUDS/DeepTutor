type Translate = (key: string, options?: Record<string, unknown>) => string;

/**
 * Preset personas ship from the server with English names and descriptions.
 * A locale can name them its own way — "persona.<name>" for the display name
 * and "persona.<name>.desc" for the description — while anything untranslated
 * (custom personas, other languages) falls back to what the server sent. The
 * persona's stored value is always the server's id; only the label is local.
 */
export function personaDisplayName(t: Translate, name: string): string {
  return t(`persona.${name}`, { defaultValue: "" }) || name;
}

export function personaDisplayDescription(
  t: Translate,
  persona: { name: string; description: string },
): string {
  return t(`persona.${persona.name}.desc`, { defaultValue: "" }) || persona.description;
}
