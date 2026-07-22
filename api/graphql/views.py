from django.contrib.auth.models import AnonymousUser
from django.http import JsonResponse
from strawberry.django.views import GraphQLView
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError


class JWTGraphQLView(GraphQLView):
    """GraphQL view that accepts the same Bearer JWTs as the REST API."""

    authentication = JWTAuthentication()

    def dispatch(self, request, *args, **kwargs):
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
