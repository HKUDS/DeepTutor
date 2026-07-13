"""Vision Solver Agent Module.

Single-call image analysis: read a math-problem figure and emit GeoGebra
commands to reconstruct it (with one gated repair pass). Exposed to chat and
solve through the ``geogebra_analysis`` built-in tool.
"""

from deeptutor.agents.vision_solver.vision_solver_agent import VisionSolverAgent

__all__ = ["VisionSolverAgent"]
