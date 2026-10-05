/** Local delivery uncertainty is not a server rejection (#1648). */
export const COMMAND_CONFIRMATION_FAILED =
  "Couldn't confirm your answer. Check your connection and retry.";

export class CommandDeliveryError extends Error {
  constructor() {
    super(COMMAND_CONFIRMATION_FAILED);
    this.name = "CommandDeliveryError";
  }
}
