from rest_framework import serializers
from .models import Group, GroupMember,GroupInvitaion
from users.serializers import UserSeriailizer

class GroupSerializer(serializers.ModelSerializer):
    members_count = serializers.IntegerField(read_only=True)
    created_by = UserSeriailizer(read_only=True)
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
    user = UserSeriailizer(read_only = True)
    class Meta:
        model = GroupMember
        fields = [
            'id',
            'user',
            'group',
            'role',
            'joined_at'
        ]



class GroupInvitaionSerializer(serializers.ModelSerializer):
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