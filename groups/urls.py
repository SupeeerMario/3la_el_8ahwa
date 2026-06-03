from django.urls import path
from .views import GroupsViewSet
from rest_framework.routers import DefaultRouter

router = DefaultRouter()

router.register('', GroupsViewSet,basename="group")


urlpatterns = router.urls