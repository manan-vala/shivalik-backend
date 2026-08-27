"""
The `api` app owns no models.

It is the home for cross-cutting concerns: the health probe
and the project-wide deployment checks in `checks.py`. Domain models live in
`inventory` and `staff_auth`.

This file is kept so the app layout matches every other Django app in the
project and nobody wonders whether it was deleted by accident.
"""
