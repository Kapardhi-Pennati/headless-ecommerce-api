import abc
import base64
import hashlib
import hmac
import json
import logging
import urllib.request
import urllib.error
from django.db import transaction
from django.utils import timezone
from .models import get_payment_setting
from store.models import Transaction

logger = logging.getLogger("payments")

class BasePaymentGateway(abc.ABC):
    """
    Abstract Base Class for all Payment Gateways.
    Defines interface for initializing and verifying payments.
    """

    @abc.abstractmethod
    def initialize_payment(self, order, request_data) -> dict:
        """
        Initiate the payment process.
        Returns a dict payload to be returned to the client frontend.
        """
        pass

    @abc.abstractmethod
    def verify_payment(self, order, request_data) -> bool:
        """
        Verify the payment status/signature.
        Returns True if payment is successful, False otherwise.
        """
        pass


class RazorpayGateway(BasePaymentGateway):
    """
    Razorpay integration using native Python library (urllib) for API requests.
    Enforces secure SHA256 HMAC signature verification.
    """

    def initialize_payment(self, order, request_data) -> dict:
        key_id = get_payment_setting("RAZORPAY_KEY_ID", "")
        key_secret = get_payment_setting("RAZORPAY_KEY_SECRET", "")
        enabled = get_payment_setting("RAZORPAY_ENABLED", "false").lower() in ("true", "1", "yes")

        if not enabled:
            raise ValueError("Razorpay gateway is currently disabled.")

        if not key_id or not key_secret:
            raise ValueError("Razorpay API credentials are not configured.")

        # Razorpay expects amounts in the smallest currency unit (paise for INR)
        amount_in_paise = int(order.total_amount * 100)

        url = "https://api.razorpay.com/v1/orders"
        payload = {
            "amount": amount_in_paise,
            "currency": "INR",
            "receipt": f"receipt_order_{order.id}",
        }
        
        data = json.dumps(payload).encode("utf-8")
        auth_str = f"{key_id}:{key_secret}"
        auth_b64 = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")

        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Basic {auth_b64}"
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                return {
                    "status": "success",
                    "method": "razorpay",
                    "razorpay_order_id": res_data.get("id"),
                    "amount": res_data.get("amount"),
                    "currency": res_data.get("currency"),
                    "key_id": key_id,
                }
        except urllib.error.HTTPError as e:
            error_msg = e.read().decode("utf-8")
            logger.error(f"Razorpay Order creation API error: {error_msg}")
            raise RuntimeError(f"Razorpay API Error: {error_msg}")
        except Exception as e:
            logger.error(f"Failed to communicate with Razorpay: {str(e)}")
            raise RuntimeError(f"Razorpay Connection Error: {str(e)}")

    def verify_payment(self, order, request_data) -> bool:
        key_secret = get_payment_setting("RAZORPAY_KEY_SECRET", "")
        if not key_secret:
            logger.error("Razorpay secret key is missing in config during verification.")
            return False

        razorpay_order_id = request_data.get("razorpay_order_id")
        razorpay_payment_id = request_data.get("razorpay_payment_id")
        razorpay_signature = request_data.get("razorpay_signature")

        if not all([razorpay_order_id, razorpay_payment_id, razorpay_signature]):
            logger.error("Missing required signature fields in request data.")
            return False

        # Verify signature: HMAC-SHA256(order_id + "|" + payment_id, secret)
        msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
        key = key_secret.encode("utf-8")
        computed_signature = hmac.new(key, msg, hashlib.sha256).hexdigest()

        is_valid = hmac.compare_digest(computed_signature, razorpay_signature)
        if not is_valid:
            logger.warning(
                f"Invalid Razorpay signature for Order {order.id}. "
                f"Expected: {computed_signature}, Received: {razorpay_signature}"
            )
        return is_valid


class CODGateway(BasePaymentGateway):
    """
    Cash on Delivery payment adapter.
    """

    def initialize_payment(self, order, request_data) -> dict:
        enabled = get_payment_setting("COD_ENABLED", "true").lower() in ("true", "1", "yes")
        if not enabled:
            raise ValueError("Cash on Delivery (COD) is currently disabled.")

        extra_fee_str = get_payment_setting("COD_EXTRA_FEE", "50.00")
        try:
            extra_fee = float(extra_fee_str)
        except ValueError:
            extra_fee = 0.0

        return {
            "status": "success",
            "method": "cod",
            "message": "Cash on Delivery selected.",
            "extra_fee": f"{extra_fee:.2f}",
        }

    def verify_payment(self, order, request_data) -> bool:
        # Cash on Delivery does not have an upfront online signature verification.
        # It auto-confirms checkout immediately.
        return True


class PaymentGatewayFactory:
    """
    Factory to retrieve gateway implementations.
    """
    _gateways = {
        "razorpay": RazorpayGateway,
        "cod": CODGateway,
    }

    @classmethod
    def get_gateway(cls, method_name: str) -> BasePaymentGateway:
        gateway_class = cls._gateways.get(method_name.lower())
        if not gateway_class:
            raise ValueError(f"Unsupported payment method: {method_name}")
        return gateway_class()
