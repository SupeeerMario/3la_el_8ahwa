from django.urls import path
from .views import EventLocationViewSet
from rest_framework.routers import DefaultRouter


router = DefaultRouter()

router.register(r'', EventLocationViewSet, basename='locations')


urlpatterns = router.urls
