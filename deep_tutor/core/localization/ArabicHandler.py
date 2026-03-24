class ArabicHandler:
    """
    Handles Arabic language specific logic for DeepTutor.
    Enables RTL (Right-to-Left) support and Arabic prompting (#172).
    """
    def __init__(self):
        self.locale = "ar"
        self.system_prompt_suffix = "\n\nPlease respond in Arabic. Ensure the tone is pedagogical and supportive."

    def apply_rtl_styling(self):
        # Logic to return CSS/layout flags for RTL UI
        return {"direction": "rtl", "fontFamily": "Amiri, serif"}

    def format_prompt(self, base_prompt):
        return f"{base_prompt}{self.system_prompt_suffix}"
