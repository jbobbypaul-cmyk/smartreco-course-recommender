import json
from openai import OpenAI
from app.config import get_settings


class MeshClient:
    """The only gateway for all AI calls in SmartReco."""
    def __init__(self):
        s = get_settings()
        if not s.mesh_api_key:
            raise RuntimeError("MESH_API_KEY is required")
        self.settings = s
        self.client = OpenAI(base_url=s.mesh_base_url, api_key=s.mesh_api_key)

    def embed(self, texts: list[str]) -> list[list[float]]:
        result = self.client.embeddings.create(model=self.settings.mesh_embedding_model, input=texts)
        return [row.embedding for row in result.data]

    def persuasive_copy(self, profile: dict, products: list[dict]) -> dict:
        prompt = {
            "task": "Write grounded, ethical personalized recommendation copy.",
            "rules": ["Use only supplied products", "No invented claims", "No pressure or sensitive-trait inference", "Return JSON"],
            "profile": profile,
            "products": products,
            "schema": {"narrative": "2-4 sentences", "product_ids": ["integer IDs in ranked order"]},
        }
        result = self.client.chat.completions.create(
            model=self.settings.mesh_chat_model,
            messages=[{"role": "system", "content": "You are SmartReco. Output valid JSON only."}, {"role": "user", "content": json.dumps(prompt)}],
            response_format={"type": "json_object"}, temperature=0.35,
        )
        return json.loads(result.choices[0].message.content)

