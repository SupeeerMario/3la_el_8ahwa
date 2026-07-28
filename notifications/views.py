from django.utils import timezone
from rest_framework import mixins, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from .models import Notification
from .serializers import NotificationSerializer

# Create your views here.


class NotificationViewSet(mixins.ListModelMixin,
                          mixins.RetrieveModelMixin,
                          GenericViewSet):

    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer
    lookup_value_regex = "[0-9]+"

    def get_queryset(self):
        qs = Notification.objects.filter(user=self.request.user)

        if self.action == 'list' and self.request.query_params.get('unread') == 'true':
            qs = qs.filter(read_at__isnull=True)

        return qs

    @action(detail=False, methods=['get'], url_path='unread_count')
    def unread_count(self, request):
        count = Notification.objects.filter(
            user=request.user, read_at__isnull=True
        ).count()
        return Response({'unread': count})

    @action(detail=True, methods=['post'], url_path='read')
    def mark_read(self, request, pk=None):
        notification = self.get_object()

        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=['read_at'])

        return Response(self.get_serializer(notification).data)

    @action(detail=False, methods=['post'], url_path='read_all')
    def mark_all_read(self, request):
        updated = Notification.objects.filter(
            user=request.user, read_at__isnull=True
        ).update(read_at=timezone.now())

        return Response({'marked_read': updated}, status=status.HTTP_200_OK)
