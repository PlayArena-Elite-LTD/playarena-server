from rest_framework import generics, permissions
from .serializers import UserSerializer, MatchSerializer
from accounts.models import CustomUser
from matches.models import Match


class MeView(generics.RetrieveAPIView):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


class MyMatchesView(generics.ListAPIView):
    serializer_class = MatchSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return Match.objects.filter(creator=user) | Match.objects.filter(joiner=user)

from django.shortcuts import render

# Create your views here.
