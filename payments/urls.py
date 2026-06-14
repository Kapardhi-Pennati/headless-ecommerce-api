from django.urls import path
from . import views

urlpatterns = [
    # Config and initialization
    path("config/", views.PaymentConfigView.as_view(), name="payment-config"),
    path("initialize/", views.InitializePaymentView.as_view(), name="payment-initialize"),
    path("verify/", views.VerifyPaymentView.as_view(), name="payment-verify"),
]
