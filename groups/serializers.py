from django.conf import settings
from rest_framework import serializers
from .models import Group, GroupMember,GroupInvitaion, GroupInviteToken, Message
from users.serializers import PublicUserSerializer
from core import errors, storage

class GroupSerializer(serializers.ModelSerializer):
    members_count = serializers.IntegerField(read_only=True)
    created_by = PublicUserSerializer(read_only=True)
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = [
            'id',
            'name',
            'desc',
            'created_by',
            'created_at',
            'members_count',
            'image_url'
        ]
        read_only_fields = ['created_by']

    def get_image_url(self, obj):
        return storage.group_image_url(obj)

class GroupMemberSerializer(serializers.ModelSerializer):
    user = PublicUserSerializer(read_only = True)
    class Meta:
        model = GroupMember
        fields = [
            'id',
            'user',
            'group',
            'role',
            'joined_at'
        ]
        read_only_fields = ['group', 'role', 'joined_at']


class InvitationGroupSerializer(serializers.ModelSerializer):
    members_count = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()

    class Meta:
        model = Group
        fields = [
            'id',
            'name',
            'desc',
            'members_count',
            'image_url'
        ]

    def get_members_count(self, obj):
        return obj.members.count()

    def get_image_url(self, obj):
        return storage.group_image_url(obj)


class GroupInvitaionSerializer(serializers.ModelSerializer):
    group = InvitationGroupSerializer(read_only=True)
    invited_by = PublicUserSerializer(read_only=True)
    invited_user = PublicUserSerializer(read_only=True)

    class Meta:
        model = GroupInvitaion
        fields = [
            'id',
            'group',
            'invited_user',
            'invited_by',
            'status',
            'created_at'
        ]
        read_only_fields = [
            'group',
            'invited_user',
            'invited_by',
            'status',
            'created_at',
        ]


class GroupInviteTokenSerializer(serializers.ModelSerializer):
    group = InvitationGroupSerializer(read_only=True)
    created_by = PublicUserSerializer(read_only=True)
    share_url = serializers.SerializerMethodField()

    class Meta:
        model = GroupInviteToken
        fields = [
            'id',
            'group',
            'created_by',
            'token',
            'code',
            'share_url',
            'created_at',
            'expires_at',
            'max_uses',
            'uses',
            'revoked'
        ]
        read_only_fields = fields

    def get_share_url(self, obj):
        base = settings.INVITE_LANDING_BASE_URL
        return f"{base}/invite/{obj.code}/" if base else None


class InvitePreviewSerializer(serializers.ModelSerializer):
    group = InvitationGroupSerializer(read_only=True)
    invited_by = PublicUserSerializer(source='created_by', read_only=True)
    valid = serializers.SerializerMethodField()
    reason = serializers.SerializerMethodField()

    class Meta:
        model = GroupInviteToken
        fields = [
            'group',
            'invited_by',
            'code',
            'expires_at',
            'valid',
            'reason',
        ]
        read_only_fields = fields

    def get_reason(self, obj):
        if obj.revoked:
            return errors.INVITE_TOKEN_REVOKED
        if obj.is_expired:
            return errors.INVITE_TOKEN_EXPIRED
        if obj.is_exhausted:
            return errors.INVITE_TOKEN_EXHAUSTED
        return None

    def get_valid(self, obj):
        return self.get_reason(obj) is None


class MessageSerializer(serializers.ModelSerializer):
    sender = PublicUserSerializer(read_only=True)

    class Meta:
        model = Message
        fields = [
            'id',
            'kind',
            'sender',
            'body',
            'payload',
            'created_at'
        ]
        read_only_fields = ['id', 'kind', 'sender', 'payload', 'created_at']
