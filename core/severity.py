def usgs_severity(properties: dict, config: dict) -> float:
    color_map = config["alert_color_severity"]
    sig_floor = config["sig_severity_floor"]

    alert = properties.get("alert")
    sig = properties.get("sig") or 0

    severity = color_map.get(alert, 0)
    if sig >= sig_floor:
        severity = max(severity, 4)

    return float(severity)
