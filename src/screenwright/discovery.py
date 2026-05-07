"""
FastAPI auto-discovery — scaffold only.

TODO: Crawl a running FastAPI application's /openapi.json to discover routes, then
auto-generate a Screenwright flow definition that navigates to each route's corresponding
UI path and captures a screenshot.

Design challenges to resolve before implementing:
  - OpenAPI routes are API paths; the corresponding UI routes may differ (e.g., GET /users
    might map to /admin/users in the frontend). Need a mapping strategy or a convention.
  - Auth: most FastAPI apps require authentication. The discovery pass needs credentials
    or session injection before navigation.
  - Which routes to skip: non-GET endpoints, health/metrics paths, raw JSON endpoints
    with no corresponding HTML view.

Suggested interface (not yet implemented):

    screenwright discover http://localhost:8000 --output flows/discovered.toml

This would produce a TOML file that can be fed directly to `screenwright run`.
"""
