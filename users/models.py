from django.db import models
from django.db.models.functions import Lower
from django.contrib.auth.models import AbstractUser
# Create your models here.


class User(AbstractUser):
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    display_name = models.CharField(max_length=50, blank=True)
    email = models.EmailField("email address", blank=True, null=True)

    class Meta(AbstractUser.Meta):
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="unique_user_email_ci",
                condition=models.Q(email__isnull=False),
            )
        ]

    def save(self, *args, **kwargs):
        if not self.email:
            self.email = None
        return super().save(*args, **kwargs)
