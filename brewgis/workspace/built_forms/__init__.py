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
- All built-forms CRUD class-based views **MUST** use
  ``HtmxResponseMixin`` as the first base class before ``CreateView``,
  ``UpdateView``, or ``DeleteView``.
- Every view that uses ``HtmxResponseMixin`` **MUST** define
  ``success_url_name`` (a ``str`` — the URL pattern name for the redirect
  after success).
- The mixin handles htmx vs. non-htmx redirects automatically.  Subclasses
  only override ``form_valid`` when they have extra logic (e.g., triggering
  symbology generation), and **MUST** delegate to ``super().form_valid(form)``
  for the redirect.
"""
