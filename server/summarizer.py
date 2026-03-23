import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from config import SUMMARIZER_MODEL, SUMMARIZER_SYSTEM_PROMPT
from model_manager import ModelManager


class Summarizer:
    def __init__(self, manager: ModelManager):
        self._manager = manager

        manager.register(
            "summarizer",
            load_fn=self._load,
            pinned=True,
        )

        print("Summarizer registered.")

    @staticmethod
    def _load():
        print(f"Loading summarizer: {SUMMARIZER_MODEL}")
        tokenizer = AutoTokenizer.from_pretrained(SUMMARIZER_MODEL)
        model = AutoModelForCausalLM.from_pretrained(
            SUMMARIZER_MODEL,
            torch_dtype=torch.bfloat16,
            device_map="cuda:0",
        )
        model.eval()
        print("Summarizer loaded.")
        return tokenizer, model

    def summarize(self, text: str, language: str | None = None, prompt: str | None = None) -> str:
        tokenizer, model = self._manager.get("summarizer")

        system_prompt = prompt or SUMMARIZER_SYSTEM_PROMPT
        if language and language != "English":
            system_prompt += f"\n- You MUST write the summary in {language}. Do not translate to English."

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
        input_text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True,
            enable_thinking=False,
        )
        inputs = tokenizer(input_text, return_tensors="pt").to(model.device)

        with torch.no_grad():
            output_ids = model.generate(
                **inputs,
                max_new_tokens=512,
                do_sample=False,
            )

        # Decode only the newly generated tokens
        new_tokens = output_ids[0][inputs["input_ids"].shape[1] :]
        result = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

        # Strip any <think> blocks that may have leaked through
        if "<think>" in result:
            think_end = result.rfind("</think>")
            if think_end != -1:
                result = result[think_end + len("</think>"):].strip()
            else:
                result = result.split("<think>")[0].strip()

        return result
