from django.urls import path
from .views import GroupsViewSet,GroupInvitationViewSet
from rest_framework.routers import DefaultRouter

router = DefaultRouter()

router.register(r'', GroupsViewSet,basename="group")
router.register(r'invitations', GroupInvitationViewSet,basename='invitations')


urlpatterns = router.urls