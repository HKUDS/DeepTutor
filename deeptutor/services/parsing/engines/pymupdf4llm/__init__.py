"""PyMuPDF4LLM engine — lightweight, pure-Python, image-capable.

Converts PDF / e-book formats to Markdown via PyMuPDF (fitz). No model
downloads and no CUDA, so it runs on low-end / GPU-less machines. Unlike the
text-only and markitdown engines it can also extract embedded images and
rendered vector graphics into the parse's ``images/`` dir. Produces ``markdown``
only (no structured ``content_list``).
"""
