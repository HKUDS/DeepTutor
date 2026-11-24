"""Create a deterministic synthetic Book for v1.6.1 documentation captures.

Run with the same ``DEEPTUTOR_HOME`` and source checkout as the disposable app:

    PYTHONPATH=/path/to/v1.6.1/source python scripts/seed-guide-book.py

This bypasses model generation but uses the release's public Book models and
storage layer. It never reads a developer's chats or knowledge bases.
"""

from __future__ import annotations

from urllib.parse import quote

from deeptutor.book.models import (
    Block,
    BlockStatus,
    BlockType,
    Book,
    BookInputs,
    BookProposal,
    BookStatus,
    Chapter,
    ContentType,
    Page,
    PageStatus,
    Progress,
    Spine,
)
from deeptutor.book.storage import BookStorage


BOOK_ID = "docs_fourier"


def ready(block_type: BlockType, block_id: str, payload: dict) -> Block:
    return Block(
        id=block_id,
        type=block_type,
        title="",
        status=BlockStatus.READY,
        payload=payload,
        metadata={"source": "documentation-demo"},
    )


def build_pages() -> list[Page]:
    svg = """<svg xmlns='http://www.w3.org/2000/svg' width='960' height='420' viewBox='0 0 960 420'>
<defs><linearGradient id='g' x1='0' x2='1'><stop stop-color='#dbeafe'/><stop offset='1' stop-color='#ede9fe'/></linearGradient></defs>
<rect width='960' height='420' rx='24' fill='url(#g)'/>
<path d='M70 230 C150 80 230 80 310 230 S470 380 550 230 S710 80 790 230 S870 380 930 250' fill='none' stroke='#2563eb' stroke-width='8'/>
<circle cx='310' cy='230' r='11' fill='#7c3aed'/><circle cx='550' cy='230' r='11' fill='#7c3aed'/>
<text x='55' y='70' font-family='sans-serif' font-size='34' fill='#172554'>A signal decomposed into frequencies</text>
<text x='55' y='115' font-family='sans-serif' font-size='20' fill='#475569'>Amplitude and phase describe each sinusoidal component.</text>
</svg>"""
    animation_url = "data:image/svg+xml," + quote(svg)

    interactive = """<!doctype html><html><head><meta charset='utf-8'><style>
body{font-family:system-ui;margin:0;background:#f8fafc;color:#172554}.card{padding:22px}
h2{margin:0 0 8px}.plot{height:130px;border-radius:14px;background:linear-gradient(90deg,#dbeafe,#ede9fe);display:grid;place-items:center;margin:18px 0;font-size:34px;color:#2563eb}
input{width:100%}.row{display:flex;justify-content:space-between;color:#475569}
</style></head><body><div class='card'><h2>Explore sampling frequency</h2><p>Move the slider to compare the sample rate with a 20 Hz signal.</p><div id='plot' class='plot'>5 × signal frequency</div><input id='rate' type='range' min='1' max='10' value='5'><div class='row'><span>20 Hz signal</span><strong id='label'>100 Hz sampling</strong></div></div><script>
const r=document.querySelector('#rate'),p=document.querySelector('#plot'),l=document.querySelector('#label');r.oninput=()=>{p.textContent=r.value+' × signal frequency';l.textContent=(20*r.value)+' Hz sampling'};
</script></body></html>"""

    return [
        Page(
            id="pg_foundations",
            book_id=BOOK_ID,
            chapter_id="ch_foundations",
            title="From signals to spectra",
            learning_objectives=[
                "Connect a waveform with its frequency components",
                "Interpret amplitude and phase",
            ],
            content_type=ContentType.THEORY,
            status=PageStatus.READY,
            order=0,
            blocks=[
                ready(
                    BlockType.SECTION,
                    "blk_intro",
                    {
                        "intro": "The Fourier transform gives us a second view of the same signal: not how it changes over time, but which frequencies build it.",
                        "subsections": [
                            {
                                "body": "## Two complementary views\n\nA time-domain plot makes transients easy to see. A frequency-domain plot makes periodic structure, bandwidth, and filtering easier to reason about. Neither view replaces the other.",
                            }
                        ],
                        "key_takeaway": "A Fourier transform changes the representation, not the underlying signal.",
                    },
                ),
                ready(
                    BlockType.QUIZ,
                    "blk_quiz",
                    {
                        "questions": [
                            {
                                "question_id": "book-q1",
                                "question": "What does a peak in the magnitude spectrum indicate?",
                                "question_type": "multiple_choice",
                                "options": {
                                    "A": "A prominent frequency component",
                                    "B": "A missing time sample",
                                    "C": "A change in units",
                                    "D": "A guaranteed phase shift",
                                },
                                "correct_answer": "A",
                                "explanation": "Magnitude shows how strongly each frequency contributes.",
                                "difficulty": "introductory",
                            }
                        ]
                    },
                ),
            ],
        ),
        Page(
            id="pg_visual",
            book_id=BOOK_ID,
            chapter_id="ch_visual",
            title="A visual transform pipeline",
            learning_objectives=["Follow the path from samples to a spectrum"],
            content_type=ContentType.CONCEPT,
            status=PageStatus.READY,
            order=1,
            blocks=[
                ready(
                    BlockType.FIGURE,
                    "blk_mermaid",
                    {
                        "render_type": "mermaid",
                        "code": {
                            "language": "mermaid",
                            "content": "flowchart LR\n  A[Sampled signal] --> B[Window]\n  B --> C[FFT]\n  C --> D[Magnitude spectrum]\n  C --> E[Phase spectrum]",
                        },
                        "description": "A compact map of the transform workflow.",
                    },
                ),
                ready(
                    BlockType.ANIMATION,
                    "blk_animation",
                    {
                        "video_url": animation_url,
                        "description": "An animation block can make periodic structure and phase relationships concrete.",
                    },
                ),
            ],
        ),
        Page(
            id="pg_interactive",
            book_id=BOOK_ID,
            chapter_id="ch_interactive",
            title="Sampling without aliasing",
            learning_objectives=["Apply the Nyquist criterion"],
            content_type=ContentType.PRACTICE,
            status=PageStatus.READY,
            order=2,
            blocks=[
                ready(
                    BlockType.INTERACTIVE,
                    "blk_interactive",
                    {
                        "code": {"language": "html", "content": interactive},
                        "description": "Adjust the sampling-rate ratio and observe the resulting scale.",
                    },
                ),
                ready(
                    BlockType.CALLOUT,
                    "blk_callout",
                    {
                        "label": "Nyquist checkpoint",
                        "body": "Sample above twice the highest frequency you need to preserve.",
                    },
                ),
            ],
        ),
    ]


def main() -> None:
    storage = BookStorage()
    if storage.book_exists(BOOK_ID):
        print(f"book already exists: {BOOK_ID}")
        return

    pages = build_pages()
    chapters = [
        Chapter(
            id="ch_foundations",
            title="From signals to spectra",
            order=0,
            content_type=ContentType.THEORY,
            learning_objectives=pages[0].learning_objectives,
            page_ids=[pages[0].id],
            summary="Build an intuitive time-to-frequency mental model.",
        ),
        Chapter(
            id="ch_visual",
            title="A visual transform pipeline",
            order=1,
            content_type=ContentType.CONCEPT,
            learning_objectives=pages[1].learning_objectives,
            page_ids=[pages[1].id],
            summary="See the FFT workflow as a sequence of transformations.",
        ),
        Chapter(
            id="ch_interactive",
            title="Sampling without aliasing",
            order=2,
            content_type=ContentType.PRACTICE,
            learning_objectives=pages[2].learning_objectives,
            page_ids=[pages[2].id],
            summary="Practice the Nyquist criterion with an interactive control.",
        ),
    ]
    storage.save_book(
        Book(
            id=BOOK_ID,
            title="Fourier Transform: An Interactive Primer",
            description="Signals, spectra, filtering, and sampling through explanations and interactive blocks.",
            status=BookStatus.READY,
            proposal=BookProposal(
                title="Fourier Transform: An Interactive Primer",
                description="A visual and practical introduction.",
                target_level="Undergraduate",
                estimated_chapters=3,
            ),
            language="en",
            page_count=len(pages),
            chapter_count=len(chapters),
            metadata={"source": "documentation-demo"},
        )
    )
    storage.save_inputs(
        BOOK_ID,
        BookInputs(
            user_intent="Learn the Fourier transform with visual and interactive examples.",
            language="en",
        ),
    )
    storage.save_spine(Spine(book_id=BOOK_ID, chapters=chapters))
    storage.save_progress(Progress(book_id=BOOK_ID, current_page_id=pages[0].id))
    for page in pages:
        storage.save_page(page)
    print(f"seeded book: {BOOK_ID}")


if __name__ == "__main__":
    main()
