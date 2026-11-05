type Translate = (key: string, options?: Record<string, unknown>) => string;

/**
 * Preset personas ship from the server with English names and descriptions.
 * A locale can name them its own way — "persona.<name>" for the display name
 * and "persona.<name>.desc" for the description — while anything untranslated
 * (custom personas, other languages) falls back to what the server sent. The
 * server value doubles as the i18n default: this app sets returnEmptyString
 * to false, so a missing key must fall back through defaultValue — an empty
 * default would make i18next return the key itself. The persona's stored
 * value is always the server's id; only the label is localized.
 */
export function personaDisplayName(t: Translate, name: string): string {
  return t(`persona.${name}`, { defaultValue: name }) || name;
}

export function personaDisplayDescription(
  t: Translate,
  persona: { name: string; description: string },
): string {
  return (
    t(`persona.${persona.name}.desc`, { defaultValue: persona.description }) ||
    persona.description
  );
}
