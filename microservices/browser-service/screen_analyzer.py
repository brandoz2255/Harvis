import base64, io, pytesseract, tempfile, os
from PIL import Image
from vison_models.llm_connector import query_qwen

pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'  # Update this path as needed

def analyze_image_base64(image_b64: str) -> dict:
    try:
        image_data = image_b64.split(",")[-1]
        # Save the image to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_image:
            temp_image.write(base64.b64decode(image_data))
            temp_image_path = temp_image.name

        # Get Qwen2VL caption
        caption = query_qwen(temp_image_path, "Describe the image.")

        # Clean up the temporary file
        os.unlink(temp_image_path)

        # Get OCR text
        image = Image.open(io.BytesIO(base64.b64decode(image_data)))
        ocr_text = pytesseract.image_to_string(image)

        return {
            "caption": caption,
            "ocr_text": ocr_text[:500]  # Limit to first 500 chars for prompt
        }
    except Exception as e:
        return {"error": f"Screen analysis failed: {e}"}
