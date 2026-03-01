from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

# Register your custom User model with the built-in UserAdmin
@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    # Optionally, show the created_at field in list display
    list_display = ['username', 'email', 'is_staff', 'is_active', 'created_at']