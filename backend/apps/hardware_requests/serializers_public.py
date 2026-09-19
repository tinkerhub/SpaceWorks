"""Serializers for the PUBLIC request surface — submit and token-addressable status.

Split from `serializers.py` when that file crossed the repo's 300-line hard ceiling.
Kept apart from `serializers_admin` because the two have different audiences and
different disclosure rules: everything here is reachable without staff authority, so
a field added to this module is a field shown to the public.
"""

from rest_framework import serializers


class RequestItemInputSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, max_value=99)


class RequestSubmitSerializer(serializers.Serializer):
    CONTACT_FIELDS = ("contact_name", "contact_email", "contact_phone")

    website = serializers.CharField(required=False, allow_blank=True, write_only=True)
    contact_name = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=200,
        help_text="Required for an account-less submission.",
    )
    contact_email = serializers.EmailField(
        required=False,
        allow_blank=True,
        max_length=254,
        help_text="Required for an account-less submission; normalized to lowercase.",
    )
    contact_phone = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=32,
    )
    # Present only on the `checked_in` policy: which roster entry the caller
    # confirmed. Re-verified server-side against a fresh roster, so it is an
    # assertion to check, never a credential.
    checkin_mid = serializers.IntegerField(required=False, allow_null=True)
    # The name the caller typed to find themselves on the roster. Re-matched against
    # the entry that `checkin_mid` names, so neither half can be swapped for
    # someone else's. Named separately from `contact_name` because it is not contact
    # information -- it is a lookup key that must equal an upstream value.
    name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    requested_for = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=500,
    )
    items = serializers.ListField(
        child=RequestItemInputSerializer(),
        allow_empty=False,
        max_length=20,
    )

    def to_internal_value(self, data):
        if self.context.get("checkin_submission", False):
            # No contact name, email or phone is collected on this policy: identity
            # comes from the roster match. Dropping them before child validation
            # makes them genuinely ignored rather than silently stored, matching how
            # the authenticated branch below already treats them.
            data = data.copy()
            for field_name in self.CONTACT_FIELDS:
                data.pop(field_name, None)
            return super().to_internal_value(data)
        if not self.context.get("anonymous_submission", False):
            # Authenticated identity remains account-derived. Removing these fields
            # before child validation makes them genuinely ignored, including an
            # oversized spoof value that must not turn into a validation side channel.
            data = data.copy()
            for field_name in self.CONTACT_FIELDS:
                data.pop(field_name, None)
        return super().to_internal_value(data)

    def validate_contact_email(self, value):
        return value.strip().lower()

    def validate(self, attrs):
        attrs["website"] = attrs.get("website", "")
        if self.context.get("anonymous_submission", False):
            errors = {}
            if not attrs.get("contact_name", "").strip():
                errors["contact_name"] = "This field is required."
            if not attrs.get("contact_email", "").strip():
                errors["contact_email"] = "This field is required."
            if errors:
                raise serializers.ValidationError(errors)
        if self.context.get("checkin_submission", False):
            # Reported as a field error rather than left to fail verification: a blank
            # name would come back as "you are not currently checked in", which is both
            # wrong and unactionable.
            if not attrs.get("name", "").strip():
                raise serializers.ValidationError({"name": "This field is required."})
        product_ids = [item["product_id"] for item in attrs["items"]]
        if len(product_ids) != len(set(product_ids)):
            raise serializers.ValidationError(
                {"items": "Duplicate product_id values are not allowed."}
            )
        return attrs


class RequestSubmitResponseSerializer(serializers.Serializer):
    public_token = serializers.UUIDField(read_only=True)
    status = serializers.CharField(read_only=True)


class PublicRequestItemStatusSerializer(serializers.Serializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    requested_quantity = serializers.IntegerField(read_only=True)


class PublicRequestStatusSerializer(serializers.Serializer):
    # Public + token-addressable: deliberately omits requester_username. The check-in
    # identity may be a name / email / badge / student id (PII), and the requester does
    # not need their own identity echoed back to learn a request's status.
    status = serializers.CharField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    items = PublicRequestItemStatusSerializer(many=True, read_only=True)
