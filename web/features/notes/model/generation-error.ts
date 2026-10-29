/** Keep provider payloads and account identifiers out of the writing surface. */
export function noteGenerationError(message: string) {
  if (/insufficient credits|HTTP 402|payment required/i.test(message))
    return 'The generation provider has insufficient credits. Add credits in its settings, then retry.'
  if (/No module named ['"]manim|manim.*not installed/i.test(message))
    return 'Animation rendering requires Manim. Install the animation dependencies, then retry.'
  if (/Configure distinct host and expert voices/i.test(message))
    return 'Configure distinct host and expert voices for the active TTS model.'
  if (/HTTP \d{3}|\{"error"|Traceback|Error code:/i.test(message))
    return 'The generation service could not complete this request. Check the provider settings and retry.'
  return message
}
