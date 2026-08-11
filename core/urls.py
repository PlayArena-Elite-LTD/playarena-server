from django.contrib import admin
from django.conf import settings
from django.urls import path, include, re_path
from django.views.generic import TemplateView
from django.views.generic.base import RedirectView
from django.views.static import serve as media_serve
from django.contrib.auth import views as auth_views
# Import to trigger admin customization
from core import admin as core_admin
from api.graphql.schema import schema
from api.graphql.views import JWTGraphQLView

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url='/static/favicon.svg', permanent=False)),
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),
    path(
        'api/graphql/',
        JWTGraphQLView.as_view(
            schema=schema,
            graphql_ide='graphiql' if settings.DEBUG else None,
        ),
        name='graphql',
    ),
    path('accounts/', include('accounts.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('matches/', include('matches.urls')),
    path('wallet/', include('wallet.urls')),
    path('alert/', include('alert.urls')),
    path('messenger/', include('messenger.urls')),
    path('panel/', include('panel.urls')),
    path('playarena/', TemplateView.as_view(template_name='index.html'), name='playarena'),
    path('', TemplateView.as_view(template_name='index.html'), name='index'),
]

# Serve user-uploaded media (evidence screenshots, etc.) from the app.
# WhiteNoise only handles static files, so media needs its own route. Low-volume
# use (evidence) makes Django's file server acceptable here.
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', media_serve, {'document_root': settings.MEDIA_ROOT}),
]

# Error handlers
handler403 = 'core.views.handler403'
handler404 = 'core.views.handler404'
handler500 = 'core.views.handler500'
