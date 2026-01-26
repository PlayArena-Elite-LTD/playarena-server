from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('matches/', include('matches.urls')),
    path('wallet/', include('wallet.urls')),
    path('alert/', include('alert.urls')),
    path('messenger/', include('messenger.urls')),
    path('panel/', include('panel.urls')),
    path('', TemplateView.as_view(template_name='index.html'), name='index'),
]

# Serve media files in development
# In production, serve media files through your web server (nginx, Apache, etc.)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
