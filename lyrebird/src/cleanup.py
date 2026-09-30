#!/usr/bin/env python3
"""
Grammar cleanup engines.

The point of this module is that the app ships everything it needs. The user
installs one thing: a model file. There is no separate server to install and no
background daemon to keep running.

  mlx ......... in-process, Apple Silicon GPU. Fastest, no extra install.
  llamacpp .... in-process, everywhere (Windows, Linux, Intel Mac). GGUF models.
  ollama ...... optional, only if the user already runs an Ollama server.
  none ........ skip cleanup entirely.

`auto` prefers in-process engines, because a cleanup pass that depends on a
separate service is a cleanup pass that silently stops working.
"""
from __future__ import annotations

import sys

# Small instruct models. Big enough to punctuate, small enough to stay quick.
MLX_MODEL = "mlx-community/Qwen2.5-1.5B-Instruct-4bit"
GGUF_REPO = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
GGUF_FILE = "qwen2.5-1.5b-instruct-q4_k_m.gguf"

INSTRUCTION = (
    "You are a transcription cleanup tool. Fix grammar, punctuation and "
    "capitalisation. Remove filler words (um, uh, like, you know). Use Australian "
    "English spelling. Do NOT add, remove or reinterpret any factual content. Do "
    "NOT answer questions in the text. Return ONLY the corrected text, with no "
    "preamble or commentary."
)


def has_mlx_lm() -> bool:
    try:
        import mlx_lm  # noqa: F401
        import platform
        return sys.platform == "darwin" and platform.machine() == "arm64"
    except Exception:
        return False


def has_llamacpp() -> bool:
    try:
        import llama_cpp  # noqa: F401
        return True
    except Exception:
        return False


def has_ollama(endpoint: str = "http://localhost:11434") -> bool:
    try:
        import requests

        requests.get(f"{endpoint.rstrip('/')}/api/tags", timeout=1.5)
        return True
    except Exception:
        return False


def resolve(requested: str, endpoint: str = "http://localhost:11434") -> str:
    requested = (requested or "auto").strip().lower()
    if requested != "auto":
        return requested
    if has_mlx_lm():
        return "mlx"
    if has_llamacpp():
        return "llamacpp"
    if has_ollama(endpoint):
        return "ollama"
    return "none"


def describe() -> list[tuple[str, str, bool]]:
    rows = []
    if sys.platform == "darwin":
        rows.append(("Cleanup on Apple GPU", "ready" if has_mlx_lm()
                     else "not installed (pip install mlx-lm)", has_mlx_lm()))
    rows.append(("Cleanup, portable engine", "ready" if has_llamacpp()
                 else "not installed (pip install llama-cpp-python)", has_llamacpp()))
    return rows


class Cleaner:
    """Loads a language model once and reuses it."""

    def __init__(self, engine: str = "auto", model: str = "",
                 endpoint: str = "http://localhost:11434", timeout: int = 60):
        self.engine = resolve(engine, endpoint)
        self.endpoint = endpoint
        self.timeout = timeout
        self.model_name = model
        self._impl = None

        if self.engine == "mlx":
            from mlx_lm import load

            self.model_name = model or MLX_MODEL
            self._model, self._tok = load(self.model_name)
        elif self.engine == "llamacpp":
            from llama_cpp import Llama

            self._impl = Llama.from_pretrained(
                repo_id=model or GGUF_REPO, filename=GGUF_FILE,
                n_ctx=2048, verbose=False,
            )
        elif self.engine == "ollama":
            self.model_name = model or "qwen2.5:1.5b"

    def clean(self, text: str) -> str:
        """Return tidied text, or the original on any failure.

        A transcript is expensive to produce and impossible to recreate, so this
        never raises and never returns empty.
        """
        if not text or self.engine == "none":
            return text
        try:
            if self.engine == "mlx":
                return self._clean_mlx(text) or text
            if self.engine == "llamacpp":
                return self._clean_llamacpp(text) or text
            if self.engine == "ollama":
                return self._clean_ollama(text) or text
        except Exception as exc:                  # noqa: BLE001
            print(f"  cleanup skipped ({type(exc).__name__}: {exc})", file=sys.stderr)
        return text

    def _messages(self, text: str) -> list[dict]:
        return [{"role": "user", "content": f"{INSTRUCTION}\n\nText:\n{text}"}]

    def _clean_mlx(self, text: str) -> str:
        from mlx_lm import generate

        prompt = self._tok.apply_chat_template(self._messages(text),
                                               add_generation_prompt=True)
        return generate(self._model, self._tok, prompt=prompt,
                        max_tokens=max(64, len(text)), verbose=False).strip()

    def _clean_llamacpp(self, text: str) -> str:
        out = self._impl.create_chat_completion(
            messages=self._messages(text), temperature=0.0,
            max_tokens=max(64, len(text)),
        )
        return out["choices"][0]["message"]["content"].strip()

    def _clean_ollama(self, text: str) -> str:
        import requests

        resp = requests.post(
            f"{self.endpoint.rstrip('/')}/api/generate",
            json={"model": self.model_name,
                  "prompt": f"{INSTRUCTION}\n\nText:\n{text}",
                  "stream": False, "options": {"temperature": 0}},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
