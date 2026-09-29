"""Built Forms (BuildingTypes and PlaceTypes) — land-use allocation models.

Developer Notes
===============

Fixture gotchas
---------------
- ``auto_now_add=True`` fields (like ``created_at``) require explicit values
  in fixture YAML/JSON — Django skips ``auto_now_add`` during deserialization
  but the database column is ``NOT NULL``.  Omitting the field causes an
  ``IntegrityError``.

Template ``_meta`` access
--------------------------
Accessing ``instance._meta.verbose_name`` in Django templates is forbidden
as of Django 5.x (it accesses a private API).  Use the
``model_verbose_name`` template filter instead (defined in ``builtin`` tags).

CRUD view conventions
---------------------
- The library has no page of its own: it is the map shell's Built Forms
  panel (``views.panels.panel_built_forms``). That panel opens
  ``views.built_forms``' create/edit forms into the map's right-hand drawer
  and POSTs its deletes back to the same module.
- Built-form create/edit views use ``BuiltFormPanelMixin`` (a
  ``HtmxResponseMixin``) so a save re-renders the drawer with a
  ``built-forms-changed`` event instead of redirecting to a page that no
  longer exists.  A non-htmx POST still redirects to the workspace map.
- Every view that uses ``HtmxResponseMixin`` **MUST** define
  ``success_url_name`` (a ``str`` — the URL pattern name for the redirect
  after success), and ``BuiltFormPanelMixin`` subclasses additionally define
  ``edit_url_name`` (the URL a just-created row is re-rendered against).
- ``HtmxResponseMixin`` handles htmx vs. non-htmx redirects automatically.
  Subclasses only override ``form_valid`` when they have extra logic, and
  **MUST** either delegate to ``super().form_valid(form)`` for the redirect
  or return one of their own (as ``BuiltFormPanelMixin`` does).
"""
