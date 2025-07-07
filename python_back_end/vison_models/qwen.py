from transformers import AutoProcessor, AutoModelForVision2Seq
from PIL import Image
import torch

class Qwen2VL:
    def __init__(self, model_name="Qwen/Qwen2-VL-2B-Instruct"):
        self.processor = AutoProcessor.from_pretrained(model_name)
        self.model = AutoModelForVision2Seq.from_pretrained(
            model_name,
            torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
            device_map="auto"
        )

    def predict(self, image_path, prompt):
        image = Image.open(image_path)
        messages = [
            {"role": "system", "content": "You are a helpful assistant with vision abilities."},
            {"role": "user", "content": [
                {"type": "image", "image": image},
                {"type": "text", "text": prompt}
            ]}
        ]
        text = self.processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self.processor(
            text=[text],
            images=[image],
            padding=True,
            return_tensors="pt"
        ).to(self.model.device)
        with torch.no_grad():
            generated_ids = self.model.generate(**inputs, max_new_tokens=128)
        output_texts = self.processor.batch_decode(
            generated_ids, skip_special_tokens=True, clean_up_tokenization_spaces=False
        )
        return output_texts[0]