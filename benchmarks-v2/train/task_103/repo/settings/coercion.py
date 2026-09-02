def coerce_value(name: str, value: object) -> object:
    if name == "timeout":
        return int(value)
    if name == "debug":
        return bool(value)
    if name == "region":
        return str(value)
    raise KeyError(name)
