"""Glue between risk results, the drafter and the database."""
from .. import config, database
from .alert_drafter import draft_alert


def _village(village_id: str) -> dict:
    for v in config.rule_config()["villages"]:
        if v["village_id"] == village_id:
            return v
    return {}


def draft_for(risk: dict, simulated: bool = False) -> dict:
    draft = draft_alert(risk, _village(risk["village_id"]))
    return database.create_alert(risk, draft, simulated=simulated)


def generate_for_snapshot(snapshot: dict) -> list[dict]:
    """Draft one alert per village at an alert level, unless it already has a
    pending or approved alert today. Returns the alerts created."""
    created = []
    for risk in snapshot["villages"]:
        if risk["level"] in config.ALERT_LEVELS and not database.open_alert_today(risk["village_id"]):
            created.append(draft_for(risk))
    return created
