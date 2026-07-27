import secrets

from django.db import models
from django.conf import settings
from django.utils import timezone
# Create your models here.

User = settings.AUTH_USER_MODEL


def generate_invite_token():
    return secrets.token_urlsafe(32)

class Group(models.Model):
    name = models.CharField(max_length=50)
    
    desc = models.TextField(blank=True)

    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="created_groups")

    created_at = models.DateTimeField(auto_now_add=True)


    def __str__(self):
        return self.name
    

class GroupMember(models.Model):

    ROLE_CHOICES = (
        ("admin","Admin"),
        ("member", "Member"),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="group_members")

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="members")

    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default="member")

    joined_at = models.DateTimeField(auto_now_add=True)


    class Meta:
        unique_together = ("user", "group")
    
    def __str__(self):
        return f"{self.user} is a {self.role} in {self.group}"
    


class GroupInvitaion(models.Model):

    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("rejected", "Rejected"),
    )

    group = models.ForeignKey(Group, on_delete=models.CASCADE)

    invited_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="group_invitaions")

    invited_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sent_group_invitations")

    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="pending")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("group", "invited_user")

    def __str__(self):
        return f"{self.invited_user} is invited by {self.invited_by} to {self.group} group, invitaion status is {self.status}"


class GroupInviteToken(models.Model):

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="invite_tokens")

    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="created_invite_tokens")

    token = models.CharField(max_length=64, unique=True, default=generate_invite_token)

    created_at = models.DateTimeField(auto_now_add=True)

    expires_at = models.DateTimeField()

    max_uses = models.PositiveIntegerField(null=True, blank=True)

    uses = models.PositiveIntegerField(default=0)

    revoked = models.BooleanField(default=False)

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_exhausted(self):
        return self.max_uses is not None and self.uses >= self.max_uses

    def __str__(self):
        return f"invite token for {self.group} created by {self.created_by}"