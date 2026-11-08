# ruff: noqa: ANN201
"""Signup gate: DJANGO_ACCOUNT_ALLOW_REGISTRATION decides whether accounts can be created."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test import override_settings
from django.urls import reverse

SIGNUP_DATA = {
    "username": "newbie",
    "email": "newbie@example.com",
    "password1": "x-Strong-pass-1234",
    "password2": "x-Strong-pass-1234",
}


class TestSignupGate(TestCase):
    @override_settings(ACCOUNT_ALLOW_REGISTRATION=False)
    def test_closed_signup_rejects_new_account(self):
        response = self.client.post(reverse("account_signup"), SIGNUP_DATA)

        assert not get_user_model().objects.filter(username="newbie").exists()
        self.assertTemplateUsed(response, "account/signup_closed.html")

    @override_settings(ACCOUNT_ALLOW_REGISTRATION=True)
    def test_open_signup_creates_account(self):
        self.client.post(reverse("account_signup"), SIGNUP_DATA)

        assert get_user_model().objects.filter(username="newbie").exists()
