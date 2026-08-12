"""
Tests for the notification system. This exists specifically because a
real problem occurred: scan progress happened silently while the user
was away, with no persistent record of what happened. These tests make
sure that record actually gets written, read, and cleared correctly.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as app_module


def test_notification_appears_after_being_added(client, temp_db_path):
    app_module.add_notification("Test scan finished", type="success")

    response = client.get("/api/notifications")
    assert response.status_code == 200
    data = response.json()
    assert data["unread_count"] == 1
    assert len(data["notifications"]) == 1
    assert data["notifications"][0]["message"] == "Test scan finished"
    assert data["notifications"][0]["type"] == "success"
    assert data["notifications"][0]["read"] is False


def test_mark_all_read_clears_unread_count(client, temp_db_path):
    app_module.add_notification("First", type="info")
    app_module.add_notification("Second", type="error")

    unread_before = client.get("/api/notifications").json()["unread_count"]
    assert unread_before == 2

    mark_response = client.post("/api/notifications/mark-all-read")
    assert mark_response.status_code == 200

    unread_after = client.get("/api/notifications").json()["unread_count"]
    assert unread_after == 0


def test_clear_all_notifications_empties_the_list(client, temp_db_path):
    app_module.add_notification("Something happened", type="info")
    assert len(client.get("/api/notifications").json()["notifications"]) == 1

    response = client.delete("/api/notifications")
    assert response.status_code == 200

    assert client.get("/api/notifications").json()["notifications"] == []


def test_notifications_sorted_most_recent_first(client, temp_db_path):
    app_module.add_notification("Oldest", type="info")
    app_module.add_notification("Newest", type="info")

    notifications = client.get("/api/notifications").json()["notifications"]
    assert notifications[0]["message"] == "Newest"
    assert notifications[1]["message"] == "Oldest"