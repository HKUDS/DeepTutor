# Data Generation Pipeline for Benchmark
#
# Modules:
#   - llm_utils: LLM calling utilities (prompt loading, JSON parsing)
#   - scope_generator: Generate knowledge scope from KB via RAG
#   - profile_generator: Generate student profiles
#   - gap_generator: Generate knowledge gaps
#   - task_generator: Generate learning tasks
#   - pipeline: Orchestrate the full pipeline

__all__ = ["DataGenerationPipeline", "generate_requests_main"]


def __getattr__(name: str):
    if name == "DataGenerationPipeline":
        from benchmark.data_generation.pipeline import DataGenerationPipeline

        return DataGenerationPipeline
    if name == "generate_requests_main":
        from benchmark.data_generation.request_pipeline import main as generate_requests_main

        return generate_requests_main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
