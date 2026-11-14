from django.contrib import admin

from .models import CategoryPrediction, ModelVersion


@admin.register(ModelVersion)
class ModelVersionAdmin(admin.ModelAdmin):
    list_display = ("version", "kind", "algorithm", "trained_at", "n_train", "n_real", "is_active")
    list_filter = ("kind", "is_active")
    readonly_fields = [f.name for f in ModelVersion._meta.fields]


@admin.register(CategoryPrediction)
class CategoryPredictionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "predicted_name", "confidence", "agrees", "model_version", "updated_at")
    list_filter = ("agrees", "predicted_name")
    readonly_fields = [f.name for f in CategoryPrediction._meta.fields]
