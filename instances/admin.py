from django.contrib import admin

from . import models


@admin.register(models.ChallengeInstance)
class ChallengeInstanceAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'challenge',
        'status',
        'expires_at',
        'created_at',
        'stopped_at',
    )
    list_filter = ('status',)
    search_fields = ('user__username', 'user__email', 'challenge__title')
    readonly_fields = (
        'id',
        'user',
        'challenge',
        'created_at',
        'expires_at',
        'stopped_at',
        'internal_name',
        'internal_container_id',
        'internal_network_id',
        'failure_reason',
        'connection_meta',
    )
    fields = readonly_fields + ('status',)
    ordering = ('-created_at',)
