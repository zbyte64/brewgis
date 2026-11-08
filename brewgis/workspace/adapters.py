"""allauth adapter: gates signup on DJANGO_ACCOUNT_ALLOW_REGISTRATION."""

from allauth.account.adapter import DefaultAccountAdapter
from django.conf import settings
from django.http import HttpRequest


class AccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, _request: HttpRequest) -> bool:
        return settings.ACCOUNT_ALLOW_REGISTRATION
