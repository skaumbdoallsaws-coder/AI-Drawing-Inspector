"""Vision Language Model (Qwen) wrapper."""

import gc
import re
import json
from typing import Dict, Any, Optional

import torch
from PIL import Image

from ..config import default_config


class QwenVLM:
    """
    Wrapper for Qwen2.5-VL vision-language model.

    Handles model loading, inference, and JSON response parsing.
    Used for drawing classification, feature extraction, quality audit,
    BOM extraction, and manufacturing notes.

    Usage:
        vlm = QwenVLM()
        vlm.load()

        result = vlm.analyze(image, "Extract all features as JSON...")
        print(result)  # {'features': [...], 'material': '...'}

        vlm.unload()  # Free GPU memory

    Attributes:
        model_id: HuggingFace model ID
        model: Loaded model instance (None until load() called)
        processor: Loaded processor instance
    """

    def __init__(
        self,
        model_id: str = None,
        max_tokens: int = None,
        temperature: float = None,
    ):
        """
        Initialize VLM wrapper.

        Args:
            model_id: HuggingFace model ID (default from config)
            max_tokens: Maximum tokens to generate (default from config)
            temperature: Sampling temperature (default from config)
        """
        self.model_id = model_id or default_config.vlm_model_id
        self.max_tokens = max_tokens or default_config.vlm_max_tokens
        self.temperature = temperature or default_config.vlm_temperature

        self.model = None
        self.processor = None

    def load(self) -> None:
        """
        Load model and processor into GPU memory.

        Uses bfloat16 precision and automatic device mapping.
        Clears GPU cache before loading to maximize available memory.
        """
        from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor

        # Clear memory first
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        self.processor = AutoProcessor.from_pretrained(
            self.model_id,
            trust_remote_code=True,
        )

        self.model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
            self.model_id,
            torch_dtype=torch.bfloat16,
            device_map="auto",
            trust_remote_code=True,
        )

    def unload(self) -> None:
        """Release model from GPU memory."""
        if self.model is not None:
            del self.model
            self.model = None
        if self.processor is not None:
            del self.processor
            self.processor = None

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    @property
    def is_loaded(self) -> bool:
        """Check if model is loaded."""
        return self.model is not None

    @property
    def memory_gb(self) -> float:
        """Return model memory footprint in GB."""
        if self.model:
            return self.model.get_memory_footprint() / 1e9
        return 0.0

    def analyze(self, image: Image.Image, prompt: str) -> Dict[str, Any]:
        """
        Run analysis on an image with given prompt.

        Args:
            image: PIL Image to analyze
            prompt: Instruction prompt (should request JSON output)

        Returns:
            Parsed JSON response, or dict with raw_response and parse_error

        Raises:
            RuntimeError: If model not loaded
        """
        if not self.is_loaded:
            raise RuntimeError("Model not loaded. Call load() first.")

        from qwen_vl_utils import process_vision_info

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        text = self.processor.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        image_inputs, video_inputs = process_vision_info(messages)

        inputs = self.processor(
            text=[text],
            images=image_inputs,
            videos=video_inputs,
            padding=True,
            return_tensors="pt",
        ).to(self.model.device)

        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=self.max_tokens,
                temperature=self.temperature,
            )

        generated_ids = output_ids[0, inputs.input_ids.shape[1] :]
        response = self.processor.decode(generated_ids, skip_special_tokens=True)

        return self._parse_json_response(response)

    def _parse_json_response(self, response: str) -> Dict[str, Any]:
        """
        Parse JSON from model response, with repair fallback.

        Tries:
        1. Extract from ```json``` code block
        2. Extract bare JSON object
        3. Repair malformed JSON using json_repair

        Args:
            response: Raw model response text

        Returns:
            Parsed dict, or dict with raw_response and parse_error on failure
        """
        try:
            # Try ```json``` block first
            json_match = re.search(r"```json\s*([\s\S]*?)\s*```", response)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try bare JSON object
                json_match = re.search(r"\{[\s\S]*\}", response)
                json_str = json_match.group() if json_match else response

            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                # Try json_repair as fallback
                from json_repair import repair_json

                repaired = repair_json(json_str)
                return json.loads(repaired)

        except Exception as e:
            return {
                "raw_response": response[:1000],
                "parse_error": str(e),
            }
