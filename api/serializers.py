from rest_framework import serializers
from accounts.models import CustomUser
from matches.models import Match


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email']


class MatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Match
        fields = ['id', 'game', 'device', 'amount', 'status', 'created_at']


