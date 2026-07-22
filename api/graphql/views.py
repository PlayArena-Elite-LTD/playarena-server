from django.contrib.auth.models import AnonymousUser
from django.conf import settings
from django.http import JsonResponse
from strawberry.django.views import GraphQLView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError


class JWTGraphQLView(GraphQLView):
    """GraphQL view that accepts the same Bearer JWTs as the REST API."""

    authentication = JWTAuthentication()

    def dispatch(self, request, *args, **kwargs):
        max_bytes = getattr(settings, "GRAPHQL_MAX_REQUEST_BYTES", 20000)
        try:
            content_length = int(request.META.get("CONTENT_LENGTH") or 0)
        except (TypeError, ValueError):
            content_length = 0
        if max_bytes and content_length > max_bytes:
            return JsonResponse(
                {"errors": [{"message": "GraphQL request body is too large."}]},
                status=413,
            )

        request.user = getattr(request, "user", AnonymousUser())

        try:
            auth_result = self.authentication.authenticate(request)
        except (InvalidToken, TokenError) as exc:
            return JsonResponse(
                {"errors": [{"message": str(exc)}]},
                status=401,
            )

        if auth_result is not None:
            request.user, request.auth = auth_result

        return super().dispatch(request, *args, **kwargs)

    def render_graphql_ide(self, request):
        response = super().render_graphql_ide(request)
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response
