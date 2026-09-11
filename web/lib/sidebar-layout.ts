/**
 * Sidebar arrangement the user owns: the order features sit in, which of them
 * are folded away into the "More" group, and the order of the chat history.
 *
 * The arrangement is a *view* preference, not account data — it belongs to the
 * machine you arranged it on, so it lives in localStorage next to the existing
 * ``deeptutor.sidebar.*`` keys rather than in the profile. Every function here
 * is pure and SSR-safe; the two storage helpers are the only place that touches
 * ``window``.
 */

import { browserStorage } from "@/shared/storage";

export interface SidebarNavLayout {
  /**
   * Flat top-to-bottom order of every known feature, folded ones included.
   * Keeping folded entries in place is what lets "move out of More" put a
   * feature back where it used to live instead of at the bottom of the list.
   */
  order: string[];
  /** Features the user folded into the "More" group. */
  collapsed: string[];
}

export interface ResolvedNavLayout {
  /** Every known feature in one flat order, folded ones in place. Write this
   *  back with the next edit so the first drag has a full order to work from. */
  order: string[];
  /** Features shown in the main nav, in order. */
  visible: string[];
  /** Features folded into "More", in order. */
  collapsed: string[];
  /** True when the arrangement differs from the shipped default. */
  customized: boolean;
}

export const NAV_LAYOUT_STORAGE_KEY = "deeptutor.sidebar.navLayout";
export const SESSION_ORDER_STORAGE_KEY = "deeptutor.sidebar.sessionOrder";
export const COLLAPSED_GROUPS_STORAGE_KEY = "deeptutor.sidebar.collapsedGroups";

export const DEFAULT_NAV_LAYOUT: SidebarNavLayout = {
  order: [],
  collapsed: [],
};

/** Drop unknown and duplicate ids while keeping the first occurrence's place. */
function pruneIds(
  ids: readonly string[],
  known: ReadonlySet<string>,
): string[] {
  const seen = new Set<string>();
  const pruned: string[] = [];
  for (const id of ids) {
    if (!known.has(id) || seen.has(id)) continue;
    seen.add(id);
    pruned.push(id);
  }
  return pruned;
}

/**
 * Add every id of ``reference`` that ``base`` is missing, each one landing
 * directly after the nearest reference id already present.
 *
 * This is what keeps an arrangement meaningful when the set behind it moves:
 * a feature shipped after the arrangement was saved, or a conversation that
 * scrolled out of the window the user dragged in, ends up beside the entry it
 * belongs next to instead of dumped at one end of the list.
 */
function weaveMissing(
  base: readonly string[],
  reference: readonly string[],
): string[] {
  const woven = [...base];
  const present = new Set(woven);
  for (let index = 0; index < reference.length; index += 1) {
    const id = reference[index];
    if (present.has(id)) continue;
    let at = 0;
    for (let back = index - 1; back >= 0; back -= 1) {
      const anchor = woven.indexOf(reference[back]);
      if (anchor >= 0) {
        at = anchor + 1;
        break;
      }
    }
    woven.splice(at, 0, id);
    present.add(id);
  }
  return woven;
}

/**
 * Merge a saved arrangement with the features this build actually ships.
 *
 * Features added since the arrangement was saved land right after the
 * neighbour they were designed to follow — appending them to the bottom would
 * bury every new feature under the user's older picks, which is exactly where
 * nobody looks. Features that no longer exist simply drop out.
 */
export function resolveNavLayout(
  defaults: readonly string[],
  layout?: SidebarNavLayout | null,
): ResolvedNavLayout {
  const known = new Set(defaults);
  const order = weaveMissing(pruneIds(layout?.order ?? [], known), defaults);

  const folded = new Set(pruneIds(layout?.collapsed ?? [], known));
  const visible = order.filter((href) => !folded.has(href));
  const collapsed = order.filter((href) => folded.has(href));
  const customized =
    collapsed.length > 0 ||
    order.length !== defaults.length ||
    order.some((href, index) => href !== defaults[index]);

  return { order, visible, collapsed, customized };
}

/** Move ``ids[from]`` to index ``to``, returning a new array. */
export function moveItem(
  ids: readonly string[],
  from: number,
  to: number,
): string[] {
  if (
    from === to ||
    from < 0 ||
    to < 0 ||
    from >= ids.length ||
    to >= ids.length
  ) {
    return [...ids];
  }
  const next = [...ids];
  const [moved] = next.splice(from, 1);
  next.splice(to, 0, moved);
  return next;
}

/**
 * Rewrite only the slots ``section`` occupies, in the new order given.
 *
 * Everything outside the section keeps its exact index, which is what lets one
 * list be dragged without disturbing the entries interleaved with it — the
 * folded features in the nav order, the conversations outside the recents
 * window in the chat order. Returns null when the two do not describe the same
 * set, so a stale drag can be dropped rather than scramble the order.
 */
function refillSlots(
  order: readonly string[],
  section: ReadonlySet<string>,
  nextSection: readonly string[],
): string[] | null {
  const slots: number[] = [];
  order.forEach((id, index) => {
    if (section.has(id)) slots.push(index);
  });
  if (slots.length !== nextSection.length) return null;
  const filled = [...order];
  slots.forEach((slot, position) => {
    filled[slot] = nextSection[position];
  });
  return filled;
}

/**
 * Write one section's new order back into the flat layout order.
 *
 * The visible list and the "More" list are dragged on their own but are two
 * views of a single flat order, so folding and unfolding a feature never
 * disturbs anything else.
 */
export function reorderNavSection(
  layout: SidebarNavLayout,
  section: readonly string[],
  nextSection: readonly string[],
): SidebarNavLayout {
  const order = refillSlots(layout.order, new Set(section), nextSection);
  return order ? { ...layout, order } : layout;
}

/** Fold a feature into "More" (or unfold it), leaving its position untouched. */
export function setNavCollapsed(
  layout: SidebarNavLayout,
  href: string,
  collapsed: boolean,
): SidebarNavLayout {
  const folded = new Set(layout.collapsed);
  if (collapsed) folded.add(href);
  else folded.delete(href);
  return { ...layout, collapsed: [...folded] };
}

/**
 * Apply a hand-dragged order to a server-ordered list.
 *
 * Arranged rows fill the slots they already occupy in the server's list, in
 * the order the user gave them; rows the user never touched stay exactly where
 * recency put them. So a new conversation arrives at the top because it is the
 * newest — not because arranging the list once pushed everything else below
 * every future chat, which would quietly evict the arrangement from a recents
 * window a few chats later.
 */
export function applyManualOrder<T>(
  items: readonly T[],
  keyOf: (item: T) => string,
  order: readonly string[],
): T[] {
  if (order.length === 0) return [...items];
  const rank = new Map<string, number>();
  order.forEach((id, index) => rank.set(id, index));
  const arranged = items
    .filter((item) => rank.has(keyOf(item)))
    .sort((left, right) => rank.get(keyOf(left))! - rank.get(keyOf(right))!);
  let next = 0;
  return items.map((item) => (rank.has(keyOf(item)) ? arranged[next++] : item));
}

/**
 * Fold a freshly dragged order into the stored one.
 *
 * A drag only ever speaks for the rows that were on screen. Rows that were
 * filtered out or cut off by the recents window are still arranged, so they
 * survive the merge by rejoining next to the row they were stored beside.
 */
export function mergeManualOrder(
  stored: readonly string[],
  nextVisible: readonly string[],
): string[] {
  const visible = new Set(nextVisible);
  const storedIds = new Set(stored);
  const arranged = nextVisible.filter((id) => storedIds.has(id));
  const filled = refillSlots(stored, visible, arranged) ?? [...stored];
  // Rows dragged for the very first time join the order beside the row they
  // were dropped after.
  return weaveMissing(filled, nextVisible);
}

function readJson<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    const raw = browserStorage.readRaw("local", key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function writeJson(key: string, value: unknown) {
  if (typeof window === "undefined") return;
  try {
    browserStorage.writeRaw("local", key, JSON.stringify(value));
  } catch {
    // A full or disabled store costs the preference, never the sidebar.
  }
}

export function readNavLayout(): SidebarNavLayout {
  const stored = readJson<Partial<SidebarNavLayout>>(
    NAV_LAYOUT_STORAGE_KEY,
    DEFAULT_NAV_LAYOUT,
  );
  return {
    order: Array.isArray(stored?.order) ? stored.order.filter(isString) : [],
    collapsed: Array.isArray(stored?.collapsed)
      ? stored.collapsed.filter(isString)
      : [],
  };
}

export function writeNavLayout(layout: SidebarNavLayout) {
  writeJson(NAV_LAYOUT_STORAGE_KEY, layout);
}

export function readSessionOrder(): string[] {
  const stored = readJson<unknown>(SESSION_ORDER_STORAGE_KEY, []);
  return Array.isArray(stored) ? stored.filter(isString) : [];
}

export function writeSessionOrder(order: readonly string[]) {
  writeJson(SESSION_ORDER_STORAGE_KEY, order);
}

/** Headings the learner folded shut. Ids are a chat/course/topic/collection
 *  id, which never collide, so one list covers every kind of heading. */
export function readCollapsedGroups(): string[] {
  const stored = readJson<unknown>(COLLAPSED_GROUPS_STORAGE_KEY, []);
  return Array.isArray(stored) ? stored.filter(isString) : [];
}

export function writeCollapsedGroups(ids: readonly string[]) {
  writeJson(COLLAPSED_GROUPS_STORAGE_KEY, ids);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}
