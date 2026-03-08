from django.db import models
from django.conf import settings

# Create your models here.

User = settings.AUTH_USER_MODEL

NOTIFICATION_TYPES = (
    ("group_invite", "Group_Invite"),
    ("invite_accepted", "Invite_Accepted"),
    ("new_member", "New_Member"),
    ("new_event", "New_Event"),
    ("event_reminder", "Event_Reminder")
)

class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    notification_type = models.CharField(max_length = 50, choices = NOTIFICATION_TYPES)
    payload = models.JSONField()
    is_read = models.BooleanField(default= False)
    created_at = models.DateTimeField(auto_now_add= True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.notification_type} for {self.user}" 