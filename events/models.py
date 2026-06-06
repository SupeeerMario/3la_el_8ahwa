from django.db import models
from django.conf import settings
from groups.models import Group
from django.utils import timezone

# Create your models here.

User = settings.AUTH_USER_MODEL


class Event(models.Model):
    created_by = models.ForeignKey(User, on_delete= models.CASCADE, related_name="created_events")
    group = models.ForeignKey(Group, on_delete = models.CASCADE, related_name = "events")
    title = models.CharField(max_length = 100)
    text = models.TextField(blank = True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    radius_meters = models.IntegerField()
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add = True)


    @property
    def active(self):
        now = timezone.now()
        return self.start_time <= now <= self.end_time
    
    @property
    def finished(self):
        now = timezone.now()
        return self.end_time < now

    class Meta:
        ordering = ["start_time"]
        constraints = [
            models.UniqueConstraint(
                fields = ['created_by', 'title', 'latitude', 'longitude'],
                name = 'unique_event_per_user'
            )
        ]


    def __str__(self):
        return f"{self.title} by {self.group} and it's created by {self.created_by}"