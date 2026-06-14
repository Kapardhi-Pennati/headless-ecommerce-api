import os
from django.db import models

class PaymentSetting(models.Model):
    """
    Key-Value configuration stored in the database for payment settings.
    Allows toggling gateways and keys in the Django Admin without server restarts.
    """
    key = models.CharField(max_length=50, unique=True, db_index=True)
    value = models.TextField(blank=True)
    description = models.TextField(blank=True, help_text="What this configuration does")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "payment_settings"
        ordering = ["key"]

    def __str__(self):
        return f"{self.key} = {self.value}"


def get_payment_setting(key: str, default: str = "") -> str:
    """
    Check the database for a setting. If it doesn't exist, fall back to
    environment variables or code-level default, and write the default
    into the database so the admin can manage it easily.
    """
    try:
        setting = PaymentSetting.objects.get(key=key)
        return setting.value
    except PaymentSetting.DoesNotExist:
        # Fall back to env variables, then to default
        env_value = os.getenv(key, default)
        
        # Populate the database with this value so admins can manage it going forward
        try:
            # Wrap in try-except in case DB migrations haven't run yet during early setup
            PaymentSetting.objects.create(
                key=key,
                value=env_value,
                description=f"Auto-generated configuration fallback for {key}"
            )
        except Exception:
            pass
        return env_value
