"""OCR extraction using LightOnOCR-2."""

import gc
from typing import List, Optional

import torch
from PIL import Image

from ..config import default_config
from ..models.page import PageArtifact


class LightOnOCR:
    """
    Wrapper for LightOnOCR-2-1B model.

    Handles model loading, inference, and text extraction from
    engineering drawing images.

    Usage:
        ocr = LightOnOCR(hf_token="your_token")
        ocr.load()

        lines = ocr.extract(image)
        print(lines)  # ['M6x1.0 THRU', 'R.125', ...]

        ocr.unload()  # Free GPU memory

    Attributes:
        model_id: HuggingFace model ID
        hf_token: HuggingFace API token (required for gated model)
        model: Loaded model instance (None until load() called)
        processor: Loaded processor instance
    """

    def __init__(
        self,
        model_id: str = None,
        hf_token: str = None,
        max_tokens: int = None,
    ):
        """
        Initialize OCR wrapper.

        Args:
            model_id: HuggingFace model ID (default from config)
            hf_token: HuggingFace API token for gated model access
            max_tokens: Maximum tokens to generate (default from config)
        """
        self.model_id = model_id or default_config.ocr_model_id
        self.hf_token = hf_token
        self.max_tokens = max_tokens or default_config.ocr_max_tokens

        self.model = None
        self.processor = None
        self.device = None
        self.dtype = None

    def load(self) -> None:
        """
        Load model and processor into GPU memory.

        Clears GPU cache before loading to maximize available memory.
        Requires transformers >= 5.0.0 for LightOnOCR support.
        """
        from transformers import (
            LightOnOcrForConditionalGeneration,
            LightOnOcrProcessor,
        )

        # Clear memory first
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.dtype = torch.bfloat16 if self.device == "cuda" else torch.float32

        self.processor = LightOnOcrProcessor.from_pretrained(
            self.model_id,
            token=self.hf_token,
        )

        self.model = LightOnOcrForConditionalGeneration.from_pretrained(
            self.model_id,
            torch_dtype=self.dtype,
            token=self.hf_token,
        ).to(self.device)

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

    @staticmethod
    def _resize_for_ocr(image: Image.Image, max_dim: int) -> Image.Image:
        """
        Resize image if it exceeds max_dim on the longest side.

        LightOnOCR's vision encoder uses variable tiling - large images
        create many tiles, dramatically slowing inference. Engineering
        callout crops at 300 DPI can be 500-2000px, but OCR accuracy
        remains excellent at 384px.

        Args:
            image: PIL Image to resize
            max_dim: Maximum dimension (width or height) in pixels

        Returns:
            Resized image (or original if already smaller than max_dim)
        """
        w, h = image.size
        longest = max(w, h)

        if longest <= max_dim:
            return image

        # Calculate scale factor
        scale = max_dim / longest
        new_w = int(w * scale)
        new_h = int(h * scale)

        return image.resize((new_w, new_h), Image.LANCZOS)

    def extract(
        self,
        image: Image.Image,
        max_tokens: Optional[int] = None,
        max_crop_dimension: Optional[int] = None,
    ) -> List[str]:
        """
        Extract text lines from image.

        Args:
            image: PIL Image to process
            max_tokens: Override max_new_tokens for this call (default: use self.max_tokens)
            max_crop_dimension: Override crop resize max dimension for this call

        Returns:
            List of text lines (stripped, non-empty)

        Raises:
            RuntimeError: If model not loaded
        """
        if not self.is_loaded:
            raise RuntimeError("Model not loaded. Call load() first.")

        # Resize image to prevent vision encoder from creating too many tiles
        resize_dim = max_crop_dimension or default_config.ocr_max_crop_dimension
        img = self._resize_for_ocr(image, resize_dim)
        img = img.convert("RGB")
        conversation = [{"role": "user", "content": [{"type": "image", "image": img}]}]

        inputs = self.processor.apply_chat_template(
            conversation,
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        )

        # Move inputs to device with correct dtype
        inputs = {
            k: v.to(device=self.device, dtype=self.dtype)
            if v.is_floating_point()
            else v.to(self.device)
            for k, v in inputs.items()
        }

        # Use override max_tokens if provided, otherwise use instance default
        max_new_tokens = max_tokens if max_tokens is not None else self.max_tokens

        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                repetition_penalty=1.2,
            )

        generated_ids = output_ids[0, inputs["input_ids"].shape[1] :]
        output_text = self.processor.decode(generated_ids, skip_special_tokens=True)

        # Split into lines, strip whitespace, remove empty
        return [line.strip() for line in output_text.split("\n") if line.strip()]

    def extract_from_pages(
        self,
        artifacts: List[PageArtifact],
        only_needing_ocr: bool = True,
    ) -> List[str]:
        """
        Extract text from multiple pages.

        Args:
            artifacts: List of PageArtifact to process
            only_needing_ocr: If True, skip pages where needs_ocr=False

        Returns:
            Combined list of text lines from all processed pages
        """
        all_lines = []

        for art in artifacts:
            if only_needing_ocr and not art.needs_ocr:
                continue

            page_lines = self.extract(art.image)
            all_lines.extend(page_lines)

        return all_lines
