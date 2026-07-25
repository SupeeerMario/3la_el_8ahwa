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
        # role/group must never be client-writable: this serializer is
        # read-only today (list_group_members), but the moment it backs a
        # member-management endpoint, PATCH {"role": "admin"} would be
        # self-promotion.
        read_only_fields = ['group', 'role', 'joined_at']



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
        # Every field was writable. The default create route is currently
        # unreachable only by accident — groups/urls.py registers GroupsViewSet
        # at r'' first, so ^(?P<pk>[^/.]+)/$ shadows ^invitations/$ and POST
        # gets a 405. Reordering those two router.register lines (planned for
        # phase 4) would otherwise turn this into self-service group joining:
        #   POST /groups/invitations/ {"group": X, "invited_user": <me>, "status": "pending"}
        #   POST /groups/invitations/<id>/accept_invite/
        # Invitations are only ever created by send_invite, which does the
        # admin check, so nothing here needs to be writable.
        read_only_fields = [
            'group',
            'invited_user',
            'invited_by',
            'status',
            'created_at',
        ]