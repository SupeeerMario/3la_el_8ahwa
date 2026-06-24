from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from .views import UserViewSet

router = DefaultRouter()

router.register("", UserViewSet, basename="user")

urlpatterns = [
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
] + router.urls