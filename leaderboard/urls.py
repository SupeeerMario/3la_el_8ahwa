from rest_framework.routers import DefaultRouter

from .views import LeaderboardViewSet


router = DefaultRouter()

router.register(r'', LeaderboardViewSet, basename='leaderboard')


urlpatterns = router.urls
