"""Persistent non-secret connections and model profiles; legacy defaults migrate once."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
import re
from urllib.parse import urlsplit

from agent.llm.router import ROLES, validate_config

KEY = "models.catalog.v1"


def validate_catalog(raw):
    if not isinstance(raw, dict) or set(raw) != {"connections", "profiles"}:
        raise ValueError("Model catalog requires connections and profiles")
    result = deepcopy(raw)
    connections, profiles = result["connections"], result["profiles"]
    if not isinstance(connections, list) or not isinstance(profiles, list) or len(connections) > 32 or len(profiles) > 256:
        raise ValueError("Catalog supports up to 32 connections and 256 profiles")
    def identifier(value):
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
            raise ValueError("Invalid connection/profile identifier")
    ids = set()
    for c in connections:
        if not isinstance(c, dict) or set(c) != {"connection_id", "display_name", "provider_type", "base_url", "credential_reference", "enabled"}:
            raise ValueError("Invalid provider connection fields")
        identifier(c["connection_id"])
        if c["connection_id"] in ids:
            raise ValueError("Duplicate connection identifier")
        ids.add(c["connection_id"])
        if c["provider_type"] not in {"ollama", "openai_compatible"} or not isinstance(c["enabled"], bool):
            raise ValueError("Invalid provider type/enabled flag")
        if not isinstance(c["display_name"], str) or not 1 <= len(c["display_name"].strip()) <= 200:
            raise ValueError("Connection display name is required")
        if not isinstance(c["base_url"], str) or len(c["base_url"]) > 2000:
            raise ValueError("Invalid connection URL")
        url = urlsplit(c["base_url"])
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("Use an HTTP(S) base URL without embedded credentials, query or fragment")
        c["base_url"] = c["base_url"].rstrip("/")
        ref = c["credential_reference"]
        if ref not in (None, "legacy-openai") and ref != "connection-" + c["connection_id"]:
            raise ValueError("Credential reference must belong to its connection")
    profile_ids = set()
    for p in profiles:
        fields = {"model_profile_id", "connection_id", "model_id", "display_name", "context_window", "max_output_tokens", "temperature", "pricing", "tool_mode"}
        if not isinstance(p, dict) or set(p) - fields or not {"model_profile_id", "connection_id", "model_id", "display_name"}.issubset(p):
            raise ValueError("Invalid model profile fields")
        identifier(p["model_profile_id"])
        if p["model_profile_id"] in profile_ids or p["connection_id"] not in ids:
            raise ValueError("Duplicate profile or missing connection")
        profile_ids.add(p["model_profile_id"])
        for k in ("model_id", "display_name"):
            if not isinstance(p[k], str) or not 1 <= len(p[k].strip()) <= 200:
                raise ValueError("Model ID and display name are required")
        p.setdefault("context_window", None)
        p.setdefault("max_output_tokens", 1024)
        p.setdefault("temperature", None)
        p.setdefault("pricing", None)
        p.setdefault("tool_mode", "auto")
        # Reuse the router's existing range/price validation.
        pricing = p["pricing"] or {}
        if not isinstance(pricing, dict) or set(pricing) - {"input_price", "output_price"}:
            raise ValueError("Pricing uses input_price/output_price per million tokens")
        validate_config({"roles": {"executor": {"model": p["model_id"], "context_window": p["context_window"],
            "output_limit": p["max_output_tokens"], "tool_mode": p["tool_mode"], **pricing}}})
        t = p["temperature"]
        if t is not None and (isinstance(t, bool) or not isinstance(t, (float, int)) or not math.isfinite(t) or not 0 <= t <= 2):
            raise ValueError("Temperature must be between 0 and 2")
    return result


class ModelCatalog:
    def __init__(self, store, settings):
        self.store, self.defaults = store, settings

    def load(self):
        raw = self.store.get_setting(KEY)
        if raw is not None:
            try:
                return validate_catalog(json.loads(raw))
            except (ValueError, TypeError, KeyError) as exc:
                raise ValueError("Model configuration could not be loaded; existing data was preserved. " + str(exc)) from exc
        # All migration inputs are read before either setting is changed.
        old = self.store.get_setting("orchestration.config")
        try:
            config = validate_config(json.loads(old) if old else None)
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("Legacy model migration failed; original configuration was preserved. " + str(exc)) from exc
        if config["strategy"] == "api-only":
            for binding in config["roles"].values():
                binding["route"] = "api"
        elif config["strategy"] == "single-agent":
            config["roles"]["executor"]["route"] = "api"
        settings = asdict(self.defaults)
        catalog = {"connections": [], "profiles": []}
        for route, provider, prefix in (("local", "ollama", "ollama"), ("api", "openai_compatible", "openai")):
            cid = "legacy-" + prefix
            catalog["connections"].append({"connection_id": cid, "display_name": "Ollama" if route == "local" else "OpenAI Compatible",
                "provider_type": provider, "base_url": settings[prefix + "_base_url"], "enabled": True,
                "credential_reference": "legacy-openai" if route == "api" else None})
            names = {settings[prefix + "_model"]} | {p["model"] for p in config["roles"].values() if p["route"] == route}
            for model in sorted(names - {""}):
                pid = cid + "-" + hashlib.sha256(model.encode()).hexdigest()[:16]
                old_profile = next((p for p in config["roles"].values() if p["model"] == model and p["route"] == route), {})
                catalog["profiles"].append({"model_profile_id": pid, "connection_id": cid, "model_id": model, "display_name": model,
                    "context_window": old_profile.get("context_window") or settings[prefix + "_context_window"],
                    "max_output_tokens": old_profile.get("output_limit", 1024), "temperature": settings[prefix + "_temperature"],
                    "tool_mode": old_profile.get("tool_mode", "auto"),
                    "pricing": {k: old_profile[k] for k in ("input_price", "output_price") if old_profile.get(k) is not None} or None})
            for role in ROLES:
                profile = config["roles"][role]
                if profile["route"] == route:
                    name = profile["model"] or settings[prefix + "_model"]
                    if name:
                        pid = cid + "-" + hashlib.sha256(name.encode()).hexdigest()[:16]
                        base = next(p for p in catalog["profiles"] if p["model_profile_id"] == pid)
                        variant = {**base, "context_window": profile["context_window"] or settings[prefix + "_context_window"],
                                   "max_output_tokens": profile["output_limit"], "tool_mode": profile["tool_mode"],
                                   "pricing": {k: profile[k] for k in ("input_price", "output_price") if profile[k] is not None} or None}
                        if variant != base:
                            variant["model_profile_id"] = pid + "-" + role
                            variant["display_name"] = name + " (" + role + ")"
                            catalog["profiles"].append(variant)
                            pid = variant["model_profile_id"]
                        profile["model_profile_id"] = pid
        catalog = validate_catalog(catalog)
        # One transaction, no partially migrated catalog/defaults.
        with self.store.connection:
            self.store.connection.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (KEY, json.dumps(catalog)))
            self.store.connection.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", ("orchestration.config", json.dumps(config)))
        return catalog

    def resolve(self, config, catalog=None):
        catalog = catalog if catalog is not None else self.load()
        result = deepcopy(config)
        for role, binding in result["roles"].items():
            # Unused legacy roles must not prevent a single online agent starting.
            if config["strategy"] == "single-agent" and role != "executor":
                continue
            pid = binding.get("model_profile_id")
            if not pid:  # Existing task/config compatibility; no rewriting historical tasks.
                continue
            profile = next((p for p in catalog["profiles"] if p["model_profile_id"] == pid), None)
            if profile is None:
                raise ValueError(f"{role}: model profile {pid} no longer exists")
            connection = next(c for c in catalog["connections"] if c["connection_id"] == profile["connection_id"])
            if not connection["enabled"]:
                raise ValueError(f"{role}: connection {connection['display_name']} is disabled")
            binding.update(model=profile["model_id"], route="local" if connection["provider_type"] == "ollama" else "api",
                context_window=profile["context_window"], output_limit=profile["max_output_tokens"],
                tool_mode=profile["tool_mode"], input_price=(profile["pricing"] or {}).get("input_price"),
                output_price=(profile["pricing"] or {}).get("output_price"), _connection=deepcopy(connection), temperature=profile["temperature"])
        return result
