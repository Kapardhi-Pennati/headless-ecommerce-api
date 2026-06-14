import logging
from django.db import transaction
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from drf_spectacular.utils import extend_schema, OpenApiResponse

from core.throttling import CheckoutThrottle
from core.security import audit_log
from store.models import Order, Transaction
from .models import get_payment_setting
from .serializers import (
    PaymentConfigSerializer,
    InitializePaymentInputSerializer,
    VerifyPaymentInputSerializer
)
from .gateways import PaymentGatewayFactory

logger = logging.getLogger("payments")


class PaymentConfigView(APIView):
    """
    Get current active payment gateway settings.
    Allows frontends to check which methods (Razorpay, COD) are enabled.
    """
    permission_classes = [AllowAny]
    throttle_classes = [CheckoutThrottle]

    @extend_schema(
        summary="Retrieve Payment Configurations",
        description="Returns dynamic statuses and credentials for enabled payment gateways.",
        responses={200: PaymentConfigSerializer}
    )
    def get(self, request):
        razorpay_enabled = get_payment_setting("RAZORPAY_ENABLED", "false").lower() in ("true", "1", "yes")
        razorpay_key = get_payment_setting("RAZORPAY_KEY_ID", "")
        
        cod_enabled = get_payment_setting("COD_ENABLED", "true").lower() in ("true", "1", "yes")
        cod_fee = get_payment_setting("COD_EXTRA_FEE", "50.00")

        data = {
            "razorpay": {
                "enabled": razorpay_enabled,
                "key_id": razorpay_key if razorpay_enabled else "",
            },
            "cod": {
                "enabled": cod_enabled,
                "extra_fee": cod_fee,
            }
        }
        
        serializer = PaymentConfigSerializer(data)
        return Response(serializer.data, status=status.HTTP_200_OK)


class InitializePaymentView(APIView):
    """
    Initialize a payment transaction for a pending Order.
    For Razorpay, this generates a Razorpay Order ID.
    For COD, this confirms the order directly.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [CheckoutThrottle]

    @extend_schema(
        summary="Initialize Order Payment",
        description="Creates a payment session/order at the selected gateway.",
        request=InitializePaymentInputSerializer,
        responses={
            200: OpenApiResponse(description="Payment session successfully initialized."),
            400: OpenApiResponse(description="Invalid request or order state."),
            404: OpenApiResponse(description="Order not found.")
        }
    )
    def post(self, request):
        serializer = InitializePaymentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order_id = serializer.validated_data["order_id"]
        method = serializer.validated_data["method"]

        try:
            order = Order.objects.get(id=order_id, user=request.user)
        except Order.DoesNotExist:
            return Response({"error": "Order not found."}, status=status.HTTP_404_NOT_FOUND)

        if order.status != "pending":
            return Response(
                {"error": f"Order is already {order.status} and cannot be paid."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            gateway = PaymentGatewayFactory.get_gateway(method)
            payment_data = gateway.initialize_payment(order, request.data)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("Error initializing payment gateway:")
            return Response({"error": "Payment initialization failed."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Handle post-initialization flow for specific methods (e.g., COD confirms immediately)
        if method == "cod":
            from store.views import _deduct_order_stock
            with transaction.atomic():
                order = Order.objects.select_for_update().get(id=order.id)
                if order.status != "pending":
                    return Response({"error": "Order status changed during checkout."}, status=status.HTTP_400_BAD_REQUEST)

                # Deduct inventory stock
                ok, message = _deduct_order_stock(order)
                if not ok:
                    return Response({"error": message}, status=status.HTTP_409_CONFLICT)

                # Record transaction
                Transaction.objects.update_or_create(
                    order=order,
                    defaults={
                        "amount": order.total_amount,
                        "status": "pending_verification",
                        "admin_notes": "Cash on Delivery checkout completed."
                    }
                )

                # Transition order status
                order.status = "confirmed"
                order.save(update_fields=["status"])

                audit_log(
                    action="ORDER_COD_CONFIRMED",
                    user_id=request.user.id,
                    details={"order_id": order.id, "total": float(order.total_amount)},
                    severity="INFO"
                )

        return Response(payment_data, status=status.HTTP_200_OK)


class VerifyPaymentView(APIView):
    """
    Verify the payment details (e.g., Razorpay transaction signature).
    On successful signature verification, confirms order and marks transaction as paid.
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [CheckoutThrottle]

    @extend_schema(
        summary="Verify Payment Signature",
        description="Verify cryptographic signature for online gateways to confirm order.",
        request=VerifyPaymentInputSerializer,
        responses={
            200: OpenApiResponse(description="Payment verified and order confirmed."),
            400: OpenApiResponse(description="Verification failed.")
        }
    )
    def post(self, request):
        serializer = VerifyPaymentInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        order_id = serializer.validated_data["order_id"]
        method = serializer.validated_data["method"]

        try:
            order = Order.objects.get(id=order_id, user=request.user)
        except Order.DoesNotExist:
            return Response({"error": "Order not found."}, status=status.HTTP_404_NOT_FOUND)

        if order.status != "pending":
            # If order is already confirmed, treat as success (idempotent request)
            if order.status == "confirmed":
                return Response({"message": "Payment verified and order confirmed."}, status=status.HTTP_200_OK)
            return Response(
                {"error": f"Order status is {order.status} and cannot be verified."},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            gateway = PaymentGatewayFactory.get_gateway(method)
            verified = gateway.verify_payment(order, request.data)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("Error verifying payment:")
            return Response({"error": "Payment verification failure."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if not verified:
            return Response({"error": "Payment verification failed. Invalid signature."}, status=status.HTTP_400_BAD_REQUEST)

        # Successful verification: deduct stock, update transaction, and confirm order
        from store.views import _deduct_order_stock
        with transaction.atomic():
            order = Order.objects.select_for_update().get(id=order.id)
            if order.status != "pending":
                return Response({"message": "Order was already processed."}, status=status.HTTP_200_OK)

            # Deduct stock
            ok, message = _deduct_order_stock(order)
            if not ok:
                return Response({"error": message}, status=status.HTTP_409_CONFLICT)

            # Update/Create Transaction
            razorpay_payment_id = request.data.get("razorpay_payment_id", "")
            Transaction.objects.update_or_create(
                order=order,
                defaults={
                    "amount": order.total_amount,
                    "status": "paid",
                    "upi_reference_id": razorpay_payment_id,
                    "admin_notes": f"Verified automatically via Razorpay payment ID: {razorpay_payment_id}"
                }
            )

            # Confirm order
            order.status = "confirmed"
            order.save(update_fields=["status"])

            audit_log(
                action="ORDER_PAYMENT_VERIFIED",
                user_id=request.user.id,
                details={
                    "order_id": order.id,
                    "payment_id": razorpay_payment_id,
                    "total": float(order.total_amount)
                },
                severity="INFO"
            )

        return Response({"message": "Payment verified and order confirmed."}, status=status.HTTP_200_OK)
