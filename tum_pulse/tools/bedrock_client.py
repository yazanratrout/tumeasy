"""Boto3 Bedrock wrapper for Claude invocations."""

import json
from typing import Optional

import boto3

from tum_pulse.config import (
    AWS_ACCESS_KEY_ID,
    AWS_REGION,
    AWS_SECRET_ACCESS_KEY,
    BEDROCK_MODEL_ID,
    BEDROCK_HAIKU_MODEL_ID,
)

# Expose model aliases for callers
SONNET = BEDROCK_MODEL_ID
HAIKU = BEDROCK_HAIKU_MODEL_ID


class BedrockClient:
    """Thin wrapper around the Bedrock Runtime InvokeModel API."""

    def __init__(self) -> None:
        self.client = boto3.client(
            service_name="bedrock-runtime",
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY or None,
        )
        self.model_id = BEDROCK_MODEL_ID

    def invoke(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 2000,
        model: Optional[str] = None,
    ) -> str:
        """Call Claude via the Messages API and return the response text.

        Args:
            prompt: The user message to send.
            system: Optional system prompt.
            max_tokens: Maximum tokens in the response.
            model: Model ID override — pass HAIKU or SONNET from this module,
                   or a full Bedrock model ID string. Defaults to Sonnet.

        Returns:
            The assistant's text response.
        """
        model_id = model or self.model_id
        messages = [{"role": "user", "content": prompt}]

        body: dict = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": messages,
        }
        if system:
            body["system"] = system

        try:
            response = self.client.invoke_model(
                modelId=model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read())
            return result["content"][0]["text"]
        except Exception as exc:
            return f"[BedrockClient error] {exc}"


if __name__ == "__main__":
    client = BedrockClient()
    reply = client.invoke("Say hello in exactly one sentence.", model=HAIKU)
    print("Haiku response:", reply)
    reply2 = client.invoke("Say hello in exactly one sentence.")
    print("Sonnet response:", reply2)
