from rest_framework import serializers

from providers.crawl.http import check_public_url


def public_website_url(value: str) -> None:
    """DRF validator: the website must be on the public internet, not a local or private address.

    This is the early, friendly check. The crawler's guarded client is the real gate
    (docs/security-patterns.md §6), because a public-looking name can still resolve privately.

    Raises:
        serializers.ValidationError: the URL's host is local or a private IP literal.
    """
    if not value:
        return  # blank is allowed on the project; the onboarding field is required separately
    try:
        check_public_url(value)
    except ValueError as exc:
        raise serializers.ValidationError(str(exc)) from None
