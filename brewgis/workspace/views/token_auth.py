"""Token-based authentication view for review/e2e tests.

Bypasses the browser login form during test setup by authenticating via
a pre-shared key.  Only enabled when settings.TOKEN_AUTH_KEY is set.
"""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.http import HttpResponseForbidden
from django.http import HttpResponseRedirect
from django.views.decorators.http import require_GET


@require_GET
def token_auth(request: HttpRequest) -> HttpResponseForbidden | HttpResponseRedirect:
    """Authenticate via a pre-shared key for test review/e2e test setup.

    Accepts:
      key      - pre-shared key matching settings.TOKEN_AUTH_KEY (required)
      username - which existing user to log in as (optional, default "testuser")

    On success, creates a session and redirects to ``/``.
    """
    expected_key = getattr(settings, "TOKEN_AUTH_KEY", None)

    if not expected_key:
        return HttpResponseForbidden("Token auth is not configured on this server")

    key = request.GET.get("key", "")
    if key != expected_key:
        return HttpResponseForbidden("Invalid token auth key")

    username = request.GET.get("username", "testuser")
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return HttpResponseForbidden(f"User '{username}' not found - create it first")

    login(
        request,
        user,
        backend="django.contrib.auth.backends.ModelBackend",
    )
    return HttpResponseRedirect("/")
