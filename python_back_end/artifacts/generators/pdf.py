"""
PDF generator using weasyprint (HTML to PDF)
"""

import os
import uuid
import logging
from typing import Dict, Any, List
import html

logger = logging.getLogger(__name__)

# Try to import weasyprint, fall back to reportlab if not available
try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False
    logger.warning("weasyprint not available, PDF generation will use fallback")

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


def generate_pdf(content: Dict[str, Any], output_dir: str) -> str:
    """
    Generate PDF file from manifest content.

    Args:
        content: PDF content dict with 'sections' key
        output_dir: Directory to save the file

    Returns:
        Full path to generated file

    Expected content format (same as document):
    {
        "sections": [
            {"type": "heading", "level": 1, "content": "Title"},
            {"type": "paragraph", "content": "Text content"},
            {"type": "table", "rows": [["Header1", "Header2"], ["Data1", "Data2"]]},
            {"type": "list", "items": ["Item 1", "Item 2"]}
        ],
        "title": "Document Title",
        "author": "Harvis AI",
        "styles": {  # optional custom CSS
            "font_family": "Arial",
            "font_size": "12pt"
        }
    }
    """
    os.makedirs(output_dir, exist_ok=True)

    if WEASYPRINT_AVAILABLE:
        return _generate_pdf_weasyprint(content, output_dir)
    elif REPORTLAB_AVAILABLE:
        return _generate_pdf_reportlab(content, output_dir)
    else:
        raise ImportError("Neither weasyprint nor reportlab is available for PDF generation")


def _generate_pdf_weasyprint(content: Dict[str, Any], output_dir: str) -> str:
    """Generate PDF using weasyprint (HTML to PDF)"""
    html_content = _content_to_html(content)

    # Default CSS for nice formatting
    styles = content.get("styles", {})
    font_family = styles.get("font_family", "Arial, sans-serif")
    font_size = styles.get("font_size", "12pt")

    css = CSS(string=f'''
        @page {{
            size: letter;
            margin: 1in;
        }}
        body {{
            font-family: {font_family};
            font-size: {font_size};
            line-height: 1.6;
            color: #333;
        }}
        h1 {{ font-size: 24pt; color: #1a1a1a; margin-bottom: 16pt; }}
        h2 {{ font-size: 18pt; color: #2a2a2a; margin-bottom: 12pt; }}
        h3 {{ font-size: 14pt; color: #3a3a3a; margin-bottom: 10pt; }}
        p {{ margin-bottom: 10pt; }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 16pt 0;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 8pt;
            text-align: left;
        }}
        th {{
            background-color: #366092;
            color: white;
        }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
        ul, ol {{ margin-left: 20pt; margin-bottom: 10pt; }}
        li {{ margin-bottom: 4pt; }}
        blockquote {{
            border-left: 3px solid #ccc;
            padding-left: 16pt;
            color: #666;
            font-style: italic;
            margin: 16pt 0;
        }}
        pre, code {{
            font-family: 'Courier New', monospace;
            background-color: #f4f4f4;
            padding: 8pt;
            border-radius: 4pt;
            font-size: 10pt;
        }}
        pre {{ display: block; white-space: pre-wrap; }}
    ''')

    filename = f"artifact_{uuid.uuid4().hex[:16]}.pdf"
    filepath = os.path.join(output_dir, filename)

    HTML(string=html_content).write_pdf(filepath, stylesheets=[css])
    logger.info(f"Generated PDF (weasyprint): {filepath}")

    return filepath


def _generate_pdf_reportlab(content: Dict[str, Any], output_dir: str) -> str:
    """Generate PDF using reportlab (fallback)"""
    filename = f"artifact_{uuid.uuid4().hex[:16]}.pdf"
    filepath = os.path.join(output_dir, filename)

    doc = SimpleDocTemplate(filepath, pagesize=letter,
                           rightMargin=72, leftMargin=72,
                           topMargin=72, bottomMargin=72)

    styles = getSampleStyleSheet()
    story = []

    sections = content.get("sections", [])

    for section in sections:
        section_type = section.get("type", "paragraph")

        if section_type == "heading":
            level = section.get("level", 1)
            style_name = f"Heading{min(level, 6)}" if level <= 6 else "Heading6"
            story.append(Paragraph(html.escape(section.get("content", "")), styles[style_name]))
            story.append(Spacer(1, 12))

        elif section_type == "paragraph":
            text = html.escape(section.get("content", ""))
            if section.get("bold"):
                text = f"<b>{text}</b>"
            if section.get("italic"):
                text = f"<i>{text}</i>"
            story.append(Paragraph(text, styles["Normal"]))
            story.append(Spacer(1, 6))

        elif section_type == "table":
            rows = section.get("rows", [])
            if rows:
                table = Table(rows)
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.Color(0.21, 0.38, 0.57)),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 12),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                    ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
                    ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 1), (-1, -1), 10),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ]))
                story.append(table)
                story.append(Spacer(1, 12))

        elif section_type == "list":
            items = section.get("items", [])
            for item in items:
                story.append(Paragraph(f"&bull; {html.escape(str(item))}", styles["Normal"]))
            story.append(Spacer(1, 6))

        elif section_type == "quote":
            quote_style = ParagraphStyle(
                'Quote',
                parent=styles['Normal'],
                leftIndent=36,
                fontName='Helvetica-Oblique',
                textColor=colors.gray
            )
            story.append(Paragraph(html.escape(section.get("content", "")), quote_style))
            story.append(Spacer(1, 6))

        elif section_type == "code":
            code_style = ParagraphStyle(
                'Code',
                parent=styles['Normal'],
                fontName='Courier',
                fontSize=9,
                leftIndent=18,
                backColor=colors.Color(0.95, 0.95, 0.95)
            )
            story.append(Paragraph(html.escape(section.get("content", "")), code_style))
            story.append(Spacer(1, 6))

    doc.build(story)
    logger.info(f"Generated PDF (reportlab): {filepath}")

    return filepath


def _content_to_html(content: Dict[str, Any]) -> str:
    """Convert content sections to HTML for weasyprint"""
    sections = content.get("sections", [])
    title = content.get("title", "Document")

    html_parts = [
        "<!DOCTYPE html>",
        "<html>",
        "<head>",
        f"<title>{html.escape(title)}</title>",
        "<meta charset='utf-8'>",
        "</head>",
        "<body>"
    ]

    for section in sections:
        section_type = section.get("type", "paragraph")
        section_content = section.get("content", "")

        if section_type == "heading":
            level = min(max(section.get("level", 1), 1), 6)
            html_parts.append(f"<h{level}>{html.escape(section_content)}</h{level}>")

        elif section_type == "paragraph":
            text = html.escape(section_content)
            if section.get("bold"):
                text = f"<strong>{text}</strong>"
            if section.get("italic"):
                text = f"<em>{text}</em>"
            html_parts.append(f"<p>{text}</p>")

        elif section_type == "table":
            rows = section.get("rows", [])
            if rows:
                html_parts.append("<table>")
                for i, row in enumerate(rows):
                    html_parts.append("<tr>")
                    tag = "th" if i == 0 else "td"
                    for cell in row:
                        html_parts.append(f"<{tag}>{html.escape(str(cell))}</{tag}>")
                    html_parts.append("</tr>")
                html_parts.append("</table>")

        elif section_type == "list":
            items = section.get("items", [])
            style = section.get("style", "bullet")
            tag = "ol" if style == "numbered" else "ul"
            html_parts.append(f"<{tag}>")
            for item in items:
                html_parts.append(f"<li>{html.escape(str(item))}</li>")
            html_parts.append(f"</{tag}>")

        elif section_type == "quote":
            html_parts.append(f"<blockquote>{html.escape(section_content)}</blockquote>")

        elif section_type == "code":
            html_parts.append(f"<pre><code>{html.escape(section_content)}</code></pre>")

    html_parts.extend(["</body>", "</html>"])

    return "\n".join(html_parts)
