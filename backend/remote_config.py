import json
import os
import time
import requests
from threading import Lock

REMOTE_CONFIG_URL = os.getenv("REMOTE_CONFIG_URL", "")
CACHE_TTL = 3600  # 1 hour

# This whole block is the ONLY place provider info lives right now.
# Later, if you want changes to reach already-installed copies of the
# app without a reinstall, you host this same structure as a JSON file
# on your own server and point REMOTE_CONFIG_URL at it.
FALLBACK = {
    "provider_prefixes": {
        "sk-ant": "anthropic",
        "sk-proj-": "openai",
        "sk-": "openai",
        "xai-": "grok",
        "AIza": "gemini",
    },
    "default_models": {
        "gemini": "gemini/gemini-3.5-flash-lite",
        "openai": "openai/gpt-4o-mini",
        "anthropic": "anthropic/claude-3-haiku-20240307",
        "grok": "xai/grok-4.3",   # confirmed current flagship - double check
                                  # against xAI's docs before changing this
        "local": "ollama/phi3:mini",
    },
    
    "providers": [
        {"id": "gemini",    "label": "Google Gemini",      "needs_base_url": False},
        {"id": "openai",    "label": "OpenAI",             "needs_base_url": False},
        {"id": "anthropic", "label": "Anthropic (Claude)", "needs_base_url": False},
        {"id": "grok",      "label": "xAI (Grok)",         "needs_base_url": False},
        {"id": "local",     "label": "Local (Ollama)",     "needs_base_url": False},
        {"id": "custom",    "label": "Other / Custom",     "needs_base_url": True},
    ],
    "supported_providers": ["gemini", "openai", "anthropic", "grok", "local", "custom"],
}

_config_cache = None
_cache_ts = 0
_lock = Lock()

def load_config():
    global _config_cache, _cache_ts
    with _lock:
        now = time.time()
        if _config_cache and (now - _cache_ts) < CACHE_TTL:
            return _config_cache

        if not REMOTE_CONFIG_URL:
            _config_cache = FALLBACK
            _cache_ts = now
            return _config_cache

        try:
            resp = requests.get(REMOTE_CONFIG_URL, timeout=5)
            resp.raise_for_status()
            remote = resp.json()
            merged = {
                "provider_prefixes": {**FALLBACK["provider_prefixes"], **remote.get("provider_prefixes", {})},
                "default_models": {**FALLBACK["default_models"], **remote.get("default_models", {})},
                "providers": remote.get("providers", FALLBACK["providers"]),
                "supported_providers": remote.get("supported_providers", FALLBACK["supported_providers"]),
            }
            _config_cache = merged
            _cache_ts = now
            return merged
        except Exception as e:
            print(f"Remote config fetch failed: {e}")
            return _config_cache or FALLBACK