from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('matches/', include('matches.urls')),
    path('alert/', include('alert.urls')),
    path('messenger/', include('messenger.urls')),
    path('panel/', include('panel.urls')),
    path('', TemplateView.as_view(template_name='index.html'), name='index'),
]
