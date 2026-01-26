import base64
import io
import logging
from typing import Optional

# Configure logger
logger = logging.getLogger(__name__)

def extract_text_from_file(file_data: str, file_type: str) -> Optional[str]:
    """
    Extract text from a file based on its type.
    
    Args:
        file_data: Base64 encoded file data
        file_type: MIME type or extension of the file
        
    Returns:
        Extracted text or None if extraction failed or type not supported
    """
    try:
        # Decode base64 data
        if ',' in file_data:
            _, encoded = file_data.split(',', 1)
        else:
            encoded = file_data
            
        decoded_data = base64.b64decode(encoded)
        file_bytes = io.BytesIO(decoded_data)
        
        # Determine extraction method based on type
        if 'pdf' in file_type.lower():
            return _extract_from_pdf(file_bytes)
        elif 'word' in file_type.lower() or 'docx' in file_type.lower():
            return _extract_from_docx(file_bytes)
        elif 'text' in file_type.lower() or 'txt' in file_type.lower() or 'md' in file_type.lower() or 'csv' in file_type.lower():
            return decoded_data.decode('utf-8', errors='replace')
        else:
            logger.warning(f"Unsupported file type for text extraction: {file_type}")
            return None
            
    except Exception as e:
        logger.error(f"Error processing file: {e}")
        return f"[Error extracting text from file: {str(e)}]"

def _extract_from_pdf(file_bytes: io.BytesIO) -> str:
    """Extract text from PDF BytesIO object."""
    try:
        import pypdf
        reader = pypdf.PdfReader(file_bytes)
        text = []
        for page in reader.pages:
            text.append(page.extract_text())
        return "\n".join(text)
    except ImportError:
        logger.error("pypdf is not installed")
        return "[Error: pypdf library is missing]"
    except Exception as e:
        logger.error(f"PDF extraction error: {e}")
        raise

def _extract_from_docx(file_bytes: io.BytesIO) -> str:
    """Extract text from DOCX BytesIO object."""
    try:
        import docx
        doc = docx.Document(file_bytes)
        return "\n".join([paragraph.text for paragraph in doc.paragraphs])
    except ImportError:
        logger.error("python-docx is not installed")
        return "[Error: python-docx library is missing]"
    except Exception as e:
        logger.error(f"DOCX extraction error: {e}")
        raise
