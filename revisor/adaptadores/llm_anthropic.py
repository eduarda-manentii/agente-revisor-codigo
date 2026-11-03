"""Adaptador LLM da Anthropic. Para trocar de provedor, crie outra classe com `completar`."""
from __future__ import annotations

import anthropic


class LLMAnthropic:
    def __init__(self, api_key: str, modelo: str, max_tokens: int = 16000) -> None:
        self._cliente = anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=600)
        self._modelo = modelo
        self._max_tokens = max_tokens

    def completar(self, sistema: str, usuario: str) -> str:
        resposta = self._cliente.messages.create(
            model=self._modelo,
            max_tokens=self._max_tokens,
            system=sistema,
            messages=[{"role": "user", "content": usuario}],
        )
        return "".join(bloco.text for bloco in resposta.content if bloco.type == "text")
