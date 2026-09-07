/**
 * One way to put text on the clipboard, and one way to learn that it failed.
 *
 * Two facts make this worth its own module.
 *
 * The async Clipboard API does not exist outside a secure context, and a
 * plain-http origin is an ordinary way to run DeepTutor rather than an exotic
 * one: the launcher binds the web app to `0.0.0.0` while printing a
 * `localhost` URL, so anyone opening the same instance from another machine
 * on the LAN gets `http://<lan-ip>:3782` — where `navigator.clipboard` is
 * `undefined` and touching `.writeText` throws a `TypeError` synchronously.
 * `document.execCommand("copy")` still works there, which is the whole reason
 * to keep a deprecated call around.
 *
 * And `writeText` rejects for reasons that have nothing to do with the caller
 * — the document lost focus, the permission was denied. Callers kept
 * swallowing those rejections next to a checkmark that said 已复制.
 *
 * So the contract here is: **this rejects when the text did not reach the
 * clipboard.** A caller that wants to stay quiet can catch; a caller that
 * tells the user it worked cannot do so without it having worked.
 */

/**
 * The pre-Clipboard-API path: put the text in an off-screen field, select it,
 * and let the browser copy the selection.
 *
 * It must stay synchronous. `execCommand` is only permitted while the user
 * activation from the click is still live, and an `await` before it can spend
 * that activation — which is why {@link copyText} decides whether to try the
 * async API *before* awaiting anything.
 */
function copyViaSelection(text: string): boolean {
  if (typeof document === "undefined" || !document.body) return false;

  const field = document.createElement("textarea");
  field.value = text;
  field.setAttribute("readonly", "");
  // Off-screen, but still laid out: an element that is `display:none` or
  // `visibility:hidden` cannot hold a selection, so the copy would quietly
  // succeed at copying nothing.
  field.style.position = "fixed";
  field.style.top = "0";
  field.style.left = "-9999px";
  field.style.opacity = "0";
  field.style.pointerEvents = "none";

  const previouslyFocused = document.activeElement;
  document.body.appendChild(field);
  try {
    field.select();
    field.setSelectionRange(0, text.length);
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    field.remove();
    // Duck-typed rather than `instanceof HTMLElement`: the check runs inside a
    // `finally`, and referencing a global that may not exist would replace the
    // real outcome with a ReferenceError.
    const focus = (previouslyFocused as { focus?: () => void } | null)?.focus;
    if (typeof focus === "function") focus.call(previouslyFocused);
  }
}

/**
 * Copy `text`, or reject saying why.
 *
 * Call it from inside the event handler for the user's click — both paths
 * depend on that click's user activation.
 */
export async function copyText(text: string): Promise<void> {
  if (!text.trim()) throw new Error("There is nothing to copy.");

  // Decided before the first `await`, deliberately — see `copyViaSelection`.
  const asyncApiAvailable =
    typeof navigator !== "undefined" &&
    Boolean(navigator.clipboard) &&
    typeof window !== "undefined" &&
    window.isSecureContext;

  if (asyncApiAvailable) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Focus lost, permission denied, or a policy block. The selection path
      // sometimes still works, so it is worth one try before giving up.
    }
  }

  if (!copyViaSelection(text)) {
    throw new Error("The clipboard is not available in this browser.");
  }
}
