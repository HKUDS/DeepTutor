class UserIsolationManager:
    """
    Manages multi-user isolation for DeepTutor.
    Ensures that learning paths and notes are kept separate while sharing the Knowledge Base (#73).
    """
    def __init__(self):
        self.user_contexts = {}

    def get_user_context(self, user_id):
        if user_id not in self.user_contexts:
            self.user_contexts[user_id] = {
                "history": [],
                "notes": [],
                "progress": 0
            }
        return self.user_contexts[user_id]

    def add_note(self, user_id, note):
        ctx = self.get_user_context(user_id)
        ctx["notes"].append(note)
