class KnowledgeTracer:
    """
    Tracks learner mastery across concepts in the Knowledge Graph.
    Enables predictive assistance and eliminates pedagogical amnesia (#173).
    """
    def __init__(self):
        self.mastery_levels = {} # concept_id -> probabilistic_score

    def update_mastery(self, concept_id, interaction_result):
        # Bayesian Knowledge Tracing or similar logic
        current = self.mastery_levels.get(concept_id, 0.5)
        if interaction_result == "correct":
            self.mastery_levels[concept_id] = min(current + 0.1, 1.0)
        else:
            self.mastery_levels[concept_id] = max(current - 0.1, 0.0)

    def get_prerequisites_met(self, target_concept_id, prerequisite_ids):
        return all(self.mastery_levels.get(pid, 0) > 0.7 for pid in prerequisite_ids)
