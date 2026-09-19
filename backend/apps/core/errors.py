def validation_errors(exc) -> list[dict]:
    """Pydantic validation errors as JSON-safe dicts (the default includes raw exception objects)."""
    return [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]}
            for e in exc.errors(include_url=False, include_context=False)]
