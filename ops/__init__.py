"""Operational plumbing: Celery tasks that keep the background pipeline honest.

This app intentionally has **no models**, so it adds no migrations and no
tables. It exists only so that Celery's conventional ``tasks.py`` discovery and
Django's management-command discovery both have a home that is not a business
app.
"""
