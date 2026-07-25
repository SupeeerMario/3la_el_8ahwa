from django.urls import path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenBlacklistView, TokenRefreshView
from .views import UserViewSet

router = DefaultRouter()

router.register("", UserViewSet, basename="user")

# Added the SimpleJWT refresh endpoint so clients can exchange a valid refresh
# token for a new access token without re-logging in. Listed before the router
# URLs so this explicit path is matched ahead of the router's catch-all routes.
urlpatterns = [
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    # Logout: rotation alone can't revoke a *stolen* refresh token, it only
    # invalidates one the legitimate client has already used. This gives
    # clients a way to blacklist a refresh token on demand.
    path("token/blacklist/", TokenBlacklistView.as_view(), name="token_blacklist"),
] + router.urls