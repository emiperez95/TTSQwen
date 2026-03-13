import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from config import SUMMARIZER_MODEL, SUMMARIZER_SYSTEM_PROMPT


class Summarizer:
    def __init__(self):
        print(f"Loading summarizer: {SUMMARIZER_MODEL}")
        self.tokenizer = AutoTokenizer.from_pretrained(SUMMARIZER_MODEL)
        self.model = AutoModelForCausalLM.from_pretrained(
            SUMMARIZER_MODEL,
            torch_dtype=torch.bfloat16,
            device_map="cuda:0",
        )
        self.model.eval()
        print("Summarizer ready.")

    def summarize(self, text: str) -> str:
        messages = [
            {"role": "system", "content": SUMMARIZER_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
        input_text = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer(input_text, return_tensors="pt").to(self.model.device)

        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=512,
                do_sample=False,
            )

        # Decode only the newly generated tokens
        new_tokens = output_ids[0][inputs["input_ids"].shape[1] :]
        return self.tokenizer.decode(new_tokens, skip_special_tokens=True).strip()
