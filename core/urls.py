from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from django.views.generic.base import RedirectView
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('favicon.ico', RedirectView.as_view(url='/static/favicon.svg', permanent=False)),
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('matches/', include('matches.urls')),
    path('wallet/', include('wallet.urls')),
    path('alert/', include('alert.urls')),
    path('messenger/', include('messenger.urls')),
    path('panel/', include('panel.urls')),
    path('api/', include('api.urls')),
    path('', TemplateView.as_view(template_name='index.html'), name='index'),
]

# Serve media files in development only
# Security: Never use this in production - use proper storage service (S3, Cloudinary, etc.)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
