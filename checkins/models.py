from django.db import models
from django.conf import settings
from events.models import Event
# Create your models here.

User = settings.AUTH_USER_MODEL

class CheckIn(models.Model):
    event = models.ForeignKey(Event, on_delete = models.CASCADE, related_name ="checkins" )
    user = models.ForeignKey(User, on_delete = models.CASCADE, related_name = "checkins" )
    latitude = models.FloatField()
    longitude = models.FloatField()
    is_valid = models.BooleanField(default = False)
    checked_in_at = models.DateTimeField(auto_now_add = True)


    class Meta:
        unique_together = ["event", "user"]
        ordering = ["-checked_in_at"]

    def __str__(self):
        return f"{self.user} checked in to {self.event}"