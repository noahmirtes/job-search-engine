"""Ollama client helpers for structured rule classification."""

from __future__ import annotations

import json
from ollama import Client


OLLAMA_BASE_URL = "http://localhost:11434"


def classify_rule_result(
    *,
    model: str,
    job_text: str,
    question: str,
    result_options: list[str],
    max_retries: int,
    base_url: str = OLLAMA_BASE_URL,
    timeout_seconds: int = 90,
) -> str:
    """
    Classify one rule question against a job and return one allowed option.

    Retries if Ollama is unavailable or if response parsing/validation fails.
    """
    normalized_options = [_normalize_option(option) for option in result_options]
    if not normalized_options:
        raise ValueError("result_options must be a non-empty list.")
    if max_retries < 1:
        raise ValueError("max_retries must be >= 1.")

    prompt = _build_classification_prompt(
        question=question,
        result_options=result_options,
        job_text=job_text,
    )
    client = Client(host=base_url)

    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            raw_response = _call_ollama_generate(
                client=client,
                model=model,
                prompt=prompt,
                timeout_seconds=timeout_seconds,
            )
            parsed_result = _extract_result(raw_response)

            normalized_result = _normalize_option(parsed_result)
            if normalized_result in normalized_options:
                return normalized_result
            raise ValueError(
                f"Model returned '{parsed_result}', not in allowed options: {result_options}"
            )
        except Exception as exc:
            last_error = exc
            if attempt == max_retries:
                break

    raise RuntimeError(
        f"Ollama classification failed after {max_retries} attempts: {last_error}"
    )


def _build_classification_prompt(
    *,
    question: str,
    result_options: list[str],
    job_text: str,
) -> str:
    options_text = ", ".join(f'"{o}"' for o in result_options)
    return (
        "You are a closed-set classification system.\n"
        f"Allowed result values: [{options_text}]\n"
        "You must choose exactly one allowed result value.\n"
        "Do not invent new values.\n"
        "Do not explain your reasoning.\n"
        "Do not summarize the job.\n"
        "Do not return labels from the question.\n"
        "Return only valid JSON matching this exact schema:\n"
        '{"result":"<allowed value>"}\n'
        "The value of \"result\" must be exactly one of the allowed result values.\n\n"
        f"Question:\n{question}\n\n"
        f"Job text:\n{job_text}\n\n"
        "The value of \"result\" must be exactly one of the allowed result values.\n\n"
        f"Question:\n{question}\n\n"
    )


def _call_ollama_generate(
    *,
    client: Client,
    model: str,
    prompt: str,
    timeout_seconds: int,
) -> str:
    """Call Ollama generate and return the raw textual response body."""
    if not model.strip():
        raise ValueError("Ollama model name is required.")

    # Timeout is currently controlled by Ollama client defaults; we keep this
    # argument in the function signature to avoid breaking callers.
    _ = timeout_seconds

    payload = client.generate(
        model=model,
        prompt=prompt,
        stream=False,
        format="json",
        options={"temperature": 0},
    )
    output = payload.get("response")
    if not isinstance(output, str) or not output.strip():
        raise ValueError("Ollama response missing non-empty 'response' text.")
    return output


def _extract_result(raw_response: str) -> str:
    # First try strict JSON parse.
    try:
        payload = json.loads(raw_response)
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, str) and result.strip():
                return result
    except json.JSONDecodeError:
        pass

    # Fallback: try to recover the JSON object from surrounding text.
    first_brace = raw_response.find("{")
    last_brace = raw_response.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        snippet = raw_response[first_brace:last_brace + 1]
        try:
            payload = json.loads(snippet)
            if isinstance(payload, dict):
                result = payload.get("result")
                if isinstance(result, str) and result.strip():
                    return result
        except json.JSONDecodeError:
            pass

    raise ValueError("Could not parse JSON {\"result\": ...} from Ollama response.")


def _normalize_option(value: str) -> str:
    return value.strip().lower()
