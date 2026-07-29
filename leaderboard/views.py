from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from core import errors
from core.errors import error_response
from events.views import _as_int
from groups.models import Group, GroupMember
from users.serializers import PublicUserSerializer
from .services import group_member_standings, group_standings, user_standings

# Create your views here.


def _user_rows(standings):
    return [
        {
            'rank': row['rank'],
            'user': PublicUserSerializer(row['user']).data,
            'checkins': row['checkins'],
        }
        for row in standings
    ]


class LeaderboardViewSet(ViewSet):

    permission_classes = [IsAuthenticated]

    def list(self, request):
        group_id = _as_int(request.query_params.get('group'))

        if group_id is None:
            return error_response(
                errors.MISSING_FIELD,
                'A group query parameter is required',
                status.HTTP_400_BAD_REQUEST
            )

        try:
            group = Group.objects.get(pk=group_id, members__user=request.user)
        except Group.DoesNotExist:
            return error_response(
                errors.GROUP_NOT_FOUND,
                'Group not found',
                status.HTTP_404_NOT_FOUND
            )

        return Response({
            'group': group.id,
            'standings': _user_rows(group_member_standings(group)),
        })

    @action(detail=False, methods=['get'], url_path='users')
    def users(self, request):
        return Response({'standings': _user_rows(user_standings())})

    @action(detail=False, methods=['get'], url_path='groups')
    def groups(self, request):
        return Response({
            'standings': [
                {
                    'rank': row['rank'],
                    'group': {'id': row['group'].id, 'name': row['group'].name},
                    'checkins': row['checkins'],
                    'members': row['members'],
                    'events': row['events'],
                    'rate': row['rate'],
                }
                for row in group_standings()
            ]
        })
