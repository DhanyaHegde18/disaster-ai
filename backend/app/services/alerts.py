"""Glue between risk results, the drafter and the database. One alert per taluk."""
from .. import config, database, notify
from .alert_drafter import draft_alert
from .risk_view import all_taluk_risks


def draft_for(taluk_risk: dict, simulated: bool = False) -> dict:
    return database.create_alert(taluk_risk, draft_alert(taluk_risk), simulated=simulated)


def generate_for_snapshot(snapshot: dict, taluk_ids: set[str] | None = None) -> list[dict]:
    """Draft one alert per taluk at an alert level (all of Karnataka, or only `taluk_ids`), unless
    it already has a pending or approved alert today. Returns the alerts created."""
    created = []
    for risk in all_taluk_risks(snapshot, taluk_ids):
        if risk["level"] in config.ALERT_LEVELS and not database.open_alert_today(risk["taluk_id"]):
            alert = draft_for(risk)
            created.append(alert)
            notify.notify_pending_alert(alert)      # that taluk's Gram Panchayat phones: "alert waiting"
    return created
