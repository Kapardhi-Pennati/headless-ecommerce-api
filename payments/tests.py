import hmac
import hashlib
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from unittest.mock import patch, MagicMock

from accounts.models import User
from store.models import Order, Category, Product, Transaction, OrderItem
from payments.models import PaymentSetting, get_payment_setting


@override_settings(
    SECURE_SSL_REDIRECT=False,
    CELERY_TASK_ALWAYS_EAGER=True,
)
class PaymentAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username="customer",
            email="customer@example.com",
            password="customerpass123",
            role="customer"
        )
        self.client.force_authenticate(user=self.user)

        # Setup catalog
        self.category = Category.objects.create(name="Clothing", slug="clothing")
        self.product = Product.objects.create(
            name="Sari",
            slug="sari",
            price=1500.00,
            stock=10,
            category=self.category
        )

        # Setup order
        self.order = Order.objects.create(
            user=self.user,
            total_amount=1500.00,
            shipping_address="123 test street",
            phone="+919876543210"
        )
        self.order_item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            product_name=self.product.name,
            quantity=1,
            price_at_purchase=self.product.price
        )

        # Setup payment configuration
        PaymentSetting.objects.all().delete()
        PaymentSetting.objects.create(key="RAZORPAY_ENABLED", value="true")
        PaymentSetting.objects.create(key="RAZORPAY_KEY_ID", value="rzp_test_123")
        PaymentSetting.objects.create(key="RAZORPAY_KEY_SECRET", value="secret123")
        PaymentSetting.objects.create(key="COD_ENABLED", value="true")
        PaymentSetting.objects.create(key="COD_EXTRA_FEE", value="50.00")

    def test_payment_config_endpoint(self):
        url = reverse("payment-config")
        # Public config (AllowAny)
        self.client.logout()
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["razorpay"]["enabled"])
        self.assertEqual(response.data["razorpay"]["key_id"], "rzp_test_123")
        self.assertTrue(response.data["cod"]["enabled"])
        self.assertEqual(response.data["cod"]["extra_fee"], "50.00")

    @patch("urllib.request.urlopen")
    def test_initialize_payment_razorpay(self, mock_urlopen):
        # Mock Razorpay API response
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"id": "order_mock123", "amount": 150000, "currency": "INR"}'
        mock_urlopen.return_value.__enter__.return_value = mock_response

        url = reverse("payment-initialize")
        data = {
            "order_id": self.order.id,
            "method": "razorpay"
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertEqual(response.data["razorpay_order_id"], "order_mock123")
        self.assertEqual(response.data["key_id"], "rzp_test_123")

    def test_initialize_payment_cod(self):
        url = reverse("payment-initialize")
        data = {
            "order_id": self.order.id,
            "method": "cod"
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "success")
        self.assertEqual(response.data["method"], "cod")

        # Verify order has updated to confirmed and stock is deducted
        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.status, "confirmed")
        self.assertEqual(self.product.stock, 9)  # 10 - 1 = 9
        
        # Verify transaction created
        txn = Transaction.objects.get(order=self.order)
        self.assertEqual(txn.status, "pending_verification")

    def test_verify_payment_razorpay_success(self):
        # Calculate correct HMAC signature
        razorpay_order_id = "order_mock123"
        razorpay_payment_id = "pay_mock123"
        key_secret = "secret123"
        msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
        signature = hmac.new(key_secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()

        url = reverse("payment-verify")
        data = {
            "order_id": self.order.id,
            "method": "razorpay",
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": signature
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["message"], "Payment verified and order confirmed.")

        self.order.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(self.order.status, "confirmed")
        self.assertEqual(self.product.stock, 9)

        txn = Transaction.objects.get(order=self.order)
        self.assertEqual(txn.status, "paid")
        self.assertEqual(txn.upi_reference_id, "pay_mock123")

    def test_verify_payment_razorpay_bad_signature(self):
        url = reverse("payment-verify")
        data = {
            "order_id": self.order.id,
            "method": "razorpay",
            "razorpay_order_id": "order_mock123",
            "razorpay_payment_id": "pay_mock123",
            "razorpay_signature": "invalid_signature"
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "Payment verification failed. Invalid signature.")
