"""Generate the redistributable MinerU bridge fixture PDF."""

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

TARGET = Path(__file__).with_name("original.pdf")


def main() -> None:
    page = canvas.Canvas(str(TARGET), pagesize=letter, invariant=True)
    page.setTitle("DeepTutor LightRAG Bridge Fixture")
    page.setAuthor("DeepTutor contributors")
    page.setFont("Helvetica-Bold", 18)
    page.drawString(72, 720, "DeepTutor LightRAG Bridge Fixture")
    page.setFont("Helvetica", 11)
    page.drawString(72, 690, "A short paragraph preserves text and heading hierarchy.")
    page.setFont("Times-Italic", 18)
    page.drawCentredString(306, 650, "E = m c^2")

    page.setFont("Helvetica-Bold", 11)
    page.drawString(72, 610, "Table 1. Retrieval engine paths")
    columns = (72, 222, 372)
    rows = (590, 566, 542)
    for x in columns:
        page.line(x, rows[-1], x, rows[0])
    for y in rows:
        page.line(columns[0], y, columns[-1], y)
    page.setFont("Helvetica", 10)
    page.drawString(82, 574, "Engine")
    page.drawString(232, 574, "Path")
    page.drawString(82, 550, "LightRAG")
    page.drawString(232, 550, "Native")

    image = Image.new("RGB", (360, 160), "white")
    draw = ImageDraw.Draw(image)
    draw.line((35, 130, 330, 130), fill="black", width=3)
    draw.line((35, 20, 35, 130), fill="black", width=3)
    draw.line((50, 110, 140, 75, 230, 90, 315, 35), fill="#1f77b4", width=6)
    draw.text((85, 135), "Deterministic fixture chart", fill="black")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    page.drawImage(ImageReader(buffer), 72, 340, width=360, height=160, mask="auto")
    page.setFont("Helvetica", 10)
    page.drawString(72, 322, "Figure 1. Synthetic trend chart.")
    page.showPage()
    page.save()


if __name__ == "__main__":
    main()
