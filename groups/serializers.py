from rest_framework import serializers
from .models import Group, GroupMember,GroupInvitaion, GroupInviteToken
from users.serializers import PublicUserSerializer

class GroupSerializer(serializers.ModelSerializer):
    members_count = serializers.IntegerField(read_only=True)
    created_by = PublicUserSerializer(read_only=True)
    class Meta:
        model = Group
        fields = [
            'id',
            'name',
            'desc',
            'created_by',
            'created_at',
            'members_count'
        ]
        read_only_fields = ['created_by']

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

    class Meta:
        model = Group
        fields = [
            'id',
            'name',
            'desc',
            'members_count'
        ]

    def get_members_count(self, obj):
        return obj.members.count()


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

    class Meta:
        model = GroupInviteToken
        fields = [
            'id',
            'group',
            'created_by',
            'token',
            'created_at',
            'expires_at',
            'max_uses',
            'uses',
            'revoked'
        ]
        read_only_fields = fields
