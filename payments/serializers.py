from rest_framework import serializers

class PaymentGatewayConfigSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    key_id = serializers.CharField(required=False, allow_blank=True)
    extra_fee = serializers.CharField(required=False)

class PaymentConfigSerializer(serializers.Serializer):
    razorpay = PaymentGatewayConfigSerializer()
    cod = PaymentGatewayConfigSerializer()


class InitializePaymentInputSerializer(serializers.Serializer):
    order_id = serializers.IntegerField(required=True, help_text="ID of the order to pay for")
    method = serializers.ChoiceField(
        choices=[("razorpay", "Razorpay"), ("cod", "Cash on Delivery")],
        required=True,
        help_text="Selected payment method"
    )


class VerifyPaymentInputSerializer(serializers.Serializer):
    order_id = serializers.IntegerField(required=True, help_text="ID of the order to verify")
    method = serializers.ChoiceField(
        choices=[("razorpay", "Razorpay")],
        required=True,
        help_text="Payment method to verify"
    )
    razorpay_order_id = serializers.CharField(required=False, allow_blank=True)
    razorpay_payment_id = serializers.CharField(required=False, allow_blank=True)
    razorpay_signature = serializers.CharField(required=False, allow_blank=True)
