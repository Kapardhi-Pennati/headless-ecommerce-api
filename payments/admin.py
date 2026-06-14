from django.contrib import admin
from .models import PaymentSetting

@admin.register(PaymentSetting)
class PaymentSettingAdmin(admin.ModelAdmin):
    list_display = ("key", "value", "description", "updated_at")
    search_fields = ("key", "value", "description")

