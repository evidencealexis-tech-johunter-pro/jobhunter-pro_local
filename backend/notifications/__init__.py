from .service import (
    add_notification,
    clear_user_notifications,
    get_user_notifications,
    mark_all_user_notifications_read,
)

clear_notifications_for_user = clear_user_notifications

__all__ = [
    "add_notification",
    "clear_notifications_for_user",
    "clear_user_notifications",
    "get_user_notifications",
    "mark_all_user_notifications_read",
]