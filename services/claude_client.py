"""
services/claude_client.py — Anthropic Claude API wrapper
=========================================================
No Streamlit dependency. Can be used from any Python context.

# PRODUCT-CANDIDATE: E_AI_CLIENT — This entire module.
"""

import json
import urllib.error
import urllib.request

CLAUDE_API_URL   = "https://api.anthropic.com/v1/messages"
CLAUDE_API_MODEL = "claude-sonnet-4-6"


def call_claude(
    api_key: str,
    user_msg: str,
    system_msg: str = "",
    max_tokens: int = 2000,
) -> str:
    """Send a message to the Claude API and return the text response.

    Args:
        api_key:    Anthropic API key (sk-ant-...).
        user_msg:   User turn content.
        system_msg: Optional system prompt.
        max_tokens: Maximum tokens in the response.

    Returns:
        Response text, or an error string starting with "API Error" / "Error".

    # PRODUCT-CANDIDATE: E_AI_CLIENT
    """
    payload: dict = {
        "model":      CLAUDE_API_MODEL,
        "max_tokens": max_tokens,
        "messages":   [{"role": "user", "content": user_msg}],
    }
    if system_msg:
        payload["system"] = system_msg

    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        CLAUDE_API_URL,
        data=data,
        headers={
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result["content"][0]["text"]
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            err = json.loads(body)
            return f"API Error {e.code}: {err.get('error', {}).get('message', body)}"
        except Exception:
            return f"API Error {e.code}: {body}"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"
