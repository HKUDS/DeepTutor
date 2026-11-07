#!/usr/bin/env python
"""
Knowledge Base Management Tool - Standalone Entry Script
Can be run directly: python knowledge_init/kb.py [command]
"""

from pathlib import Path
import sys

# Ensure project root is in sys.path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Import main function from startup script
from src.knowledge.manager import KnowledgeBaseManager as KnowledgeBase
from src.knowledge.start_kb import main

__all__ = ["KnowledgeBase"]

if __name__ == "__main__":
    main()
