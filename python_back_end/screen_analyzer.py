import base64, io, pytesseract
from PIL import Image
from transformers import pipeline

# Load once
blip_model = pipeline("image-to-text", model="Salesforce/blip-image-captioning-base")
pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'  # Update this path as needed

def analyze_image_base64(image_b64: str) -> dict:
    try:
        image_data = image_b64.split(",")[-1]
        image = Image.open(io.BytesIO(base64.b64decode(image_data)))

        # Get BLIP caption
        caption = blip_model(image)[0]["generated_text"]

        # Get OCR text
        ocr_text = pytesseract.image_to_string(image)

        return {
            "caption": caption,
            "ocr_text": ocr_text[:500]  # Limit to first 500 chars for prompt
        }
    except Exception as e:
        return {"error": f"Screen analysis failed: {e}"}
