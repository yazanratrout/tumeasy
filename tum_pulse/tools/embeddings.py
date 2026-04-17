"""Titan Embeddings v2 client and cosine similarity helpers."""

import json
import math
from typing import Optional

import boto3
import numpy as np

from tum_pulse.config import (
    AWS_ACCESS_KEY_ID,
    AWS_REGION,
    AWS_SECRET_ACCESS_KEY,
    EMBEDDINGS_MODEL_ID,
)


class EmbeddingsClient:
    """Wraps Amazon Titan Embeddings v2 via Bedrock Runtime."""

    def __init__(self) -> None:
        """Create the boto3 client using credentials from config."""
        self.client = boto3.client(
            service_name="bedrock-runtime",
            region_name=AWS_REGION,
            aws_access_key_id=AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY or None,
        )
        self.model_id = EMBEDDINGS_MODEL_ID

    def embed(self, text: str) -> list[float]:
        """Return the embedding vector for *text*.

        Args:
            text: The text to embed (max ~8 192 tokens for Titan v2).

        Returns:
            A list of floats representing the dense embedding.
        """
        body = json.dumps({"inputText": text})
        try:
            response = self.client.invoke_model(
                modelId=self.model_id,
                body=body,
                contentType="application/json",
                accept="application/json",
            )
            result = json.loads(response["body"].read())
            return result["embedding"]
        except Exception as exc:
            print(f"[EmbeddingsClient error] {exc}")
            # Return a zero vector so callers don't crash; similarity will be 0.
            return [0.0] * 1024

    @staticmethod
    def cosine_similarity(a: list[float], b: list[float]) -> float:
        """Compute cosine similarity between two vectors.

        Args:
            a: First embedding vector.
            b: Second embedding vector.

        Returns:
            A float in [-1, 1]; 1.0 means identical direction.
        """
        va = np.array(a, dtype=float)
        vb = np.array(b, dtype=float)
        norm_a = np.linalg.norm(va)
        norm_b = np.linalg.norm(vb)
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return float(np.dot(va, vb) / (norm_a * norm_b))


if __name__ == "__main__":
    client = EmbeddingsClient()
    vec1 = client.embed("machine learning and neural networks")
    vec2 = client.embed("deep learning and AI")
    vec3 = client.embed("medieval history of Europe")
    print(f"ML vs Deep Learning similarity: {EmbeddingsClient.cosine_similarity(vec1, vec2):.4f}")
    print(f"ML vs Medieval History similarity: {EmbeddingsClient.cosine_similarity(vec1, vec3):.4f}")
