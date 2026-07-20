"""
Trigger endpoints ([4.1], issue #23): alert webhook + schedule CRUD.

The webhook is token-gated (shared secret) rather than user-authed, since
it's called by external alerting systems. Schedules are managed through
authenticated calls (product-team config).
"""

from dataclasses import asdict

from flask import Blueprint, current_app, jsonify, request
from global_utils.helpers.apiargs import from_body, from_query
from webargs import fields

triggers_bp = Blueprint("triggers", __name__)


def _check_token() -> bool:
    from config.app_config import AppConfig
    expected = getattr(AppConfig.get_instance(), "trigger_webhook_token", "")
    if not expected:
        return True  # no token configured → open (dev/local)
    return request.headers.get("X-Trigger-Token", "") == expected


@triggers_bp.route("/webhook", methods=["POST"])
@from_body({
    "blueprint_id": fields.Str(data_key="blueprintId", required=True),
    "inputs": fields.Dict(data_key="inputs", load_default=lambda: {}),
})
def webhook_trigger(blueprint_id, inputs):
    """Launch a blueprint in response to an external event (e.g. an alert)."""
    if not _check_token():
        return jsonify({"error": "invalid or missing X-Trigger-Token"}), 401
    svc = getattr(current_app.container, "trigger_service", None)
    if svc is None:
        return jsonify({"error": "triggers are disabled"}), 501
    try:
        run_id = svc.launch(blueprint_id, inputs, source="webhook")
        return jsonify({"status": "launched", "runId": run_id}), 202
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@triggers_bp.route("/schedule.create", methods=["POST"])
@from_body({
    "blueprint_id": fields.Str(data_key="blueprintId", required=True),
    "cron": fields.Str(data_key="cron", load_default=None, allow_none=True),
    "interval_seconds": fields.Int(data_key="intervalSeconds", load_default=None, allow_none=True),
    "inputs": fields.Dict(data_key="inputs", load_default=lambda: {}),
})
def create_schedule(blueprint_id, cron, interval_seconds, inputs):
    store = getattr(current_app.container, "schedule_store", None)
    if store is None:
        return jsonify({"error": "scheduling is disabled"}), 501
    from mas.triggers.schedule import Schedule
    try:
        schedule = Schedule(blueprint_id=blueprint_id, cron=cron,
                            interval_seconds=interval_seconds, inputs=inputs)
        store.save(schedule)
        return jsonify({"status": "created", "scheduleId": schedule.schedule_id}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@triggers_bp.route("/schedule.list", methods=["GET"])
def list_schedules():
    store = getattr(current_app.container, "schedule_store", None)
    if store is None:
        return jsonify({"error": "scheduling is disabled"}), 501
    return jsonify({"schedules": [asdict(s) for s in store.list_all()]}), 200


@triggers_bp.route("/schedule.delete", methods=["POST"])
@from_body({"schedule_id": fields.Str(data_key="scheduleId", required=True)})
def delete_schedule(schedule_id):
    store = getattr(current_app.container, "schedule_store", None)
    if store is None:
        return jsonify({"error": "scheduling is disabled"}), 501
    deleted = store.delete(schedule_id)
    return jsonify({"status": "deleted" if deleted else "not_found"}), 200
