"""
Machine-learning endpoints of the REST API (/api/v1/ml/).

- GET  training-data/      every report and decided match (security/staff):
                           the source `manage.py fetch_api_data` reads
- GET  models/             the active models and their test metrics
- POST predict-match/      probability that a lost and a found report match
- POST predict-category/   category for a report's title and description
"""

from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from items.matching import calculate_match
from items.models import FoundItem, ItemCategory, LostItem
from ml import dataset, predictor
from ml.features import FEATURE_NAMES, pair_features
from ml.models import ModelVersion

from .permissions import IsOnboarded, IsReviewer


class ModelUnavailable(APIException):
    status_code = 503
    default_detail = "No trained model is available. Run `manage.py train_model`."
    default_code = "model_unavailable"


class PredictMatchRequest(serializers.Serializer):
    lost_item = serializers.IntegerField(help_text="Lost report id.")
    found_item = serializers.IntegerField(help_text="Found report id.")


class PredictMatchResponse(serializers.Serializer):
    lost_item = serializers.IntegerField()
    found_item = serializers.IntegerField()
    probability = serializers.FloatField(help_text="0-1, from the match model.")
    is_match = serializers.BooleanField(help_text="probability >= the model's threshold")
    rule_score = serializers.IntegerField(help_text="0-100, from the rule-based engine.")
    features = serializers.DictField(child=serializers.FloatField())
    model_version = serializers.CharField()


class PredictCategoryRequest(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, allow_blank=True, default="")


class TrainingDataView(APIView):
    permission_classes = [IsAuthenticated, IsOnboarded, IsReviewer]

    @extend_schema(tags=["ml"], responses={200: OpenApiTypes.OBJECT},
                   summary="Training data: all reports and decided matches (security/staff)")
    def get(self, request):
        return Response(dataset.export_training_data())


class ModelInfoView(APIView):
    @extend_schema(tags=["ml"], responses={200: OpenApiTypes.OBJECT},
                   summary="Active models, test metrics and feature importances")
    def get(self, request):
        return Response({
            kind: predictor.model_info(kind) for kind in ModelVersion.Kind.values
        })


class PredictMatchView(APIView):
    @extend_schema(tags=["ml"], request=PredictMatchRequest,
                   responses={200: PredictMatchResponse},
                   summary="Probability that a lost and a found report are the same item")
    def post(self, request):
        data = PredictMatchRequest(data=request.data)
        data.is_valid(raise_exception=True)
        lost = get_object_or_404(LostItem, pk=data.validated_data["lost_item"])
        found = get_object_or_404(FoundItem, pk=data.validated_data["found_item"])

        bundle = predictor.load(ModelVersion.Kind.MATCH)
        if bundle is None:
            raise ModelUnavailable()
        probability = predictor.match_probability(lost, found)
        rule_score, _ = calculate_match(lost, found)
        return Response({
            "lost_item": lost.pk,
            "found_item": found.pk,
            "probability": round(probability, 4),
            "is_match": probability >= bundle["meta"]["threshold"],
            "rule_score": rule_score,
            "features": dict(zip(FEATURE_NAMES, (round(v, 4) for v in pair_features(lost, found)))),
            "model_version": bundle["meta"]["version"],
        })


class PredictCategoryView(APIView):
    @extend_schema(tags=["ml"], request=PredictCategoryRequest,
                   responses={200: OpenApiTypes.OBJECT},
                   summary="Suggest a category for a report's title and description")
    def post(self, request):
        data = PredictCategoryRequest(data=request.data)
        data.is_valid(raise_exception=True)
        text = f"{data.validated_data['title']}. {data.validated_data['description']}"
        result = predictor.predict_category(text)
        if result is None:
            raise ModelUnavailable()
        category = ItemCategory.objects.filter(name__iexact=result["name"]).first()
        return Response({**result, "category_id": category.pk if category else None})
