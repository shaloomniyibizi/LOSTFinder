from django.db import models


class ModelVersion(models.Model):
    """One trained model, as recorded by `manage.py train_model`."""

    class Kind(models.TextChoices):
        MATCH = "match", "Match model"
        CATEGORY = "category", "Category model"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    version = models.CharField(max_length=60, unique=True)
    algorithm = models.CharField(max_length=100)
    trained_at = models.DateTimeField()
    metrics = models.JSONField(default=dict)
    n_train = models.PositiveIntegerField(default=0)
    n_test = models.PositiveIntegerField(default=0)
    n_real = models.PositiveIntegerField(default=0, help_text="Samples read from the API.")
    n_synthetic = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ["-trained_at"]

    def __str__(self):
        return self.version


class CategoryPrediction(models.Model):
    """The category model's guess for a saved report."""

    lost_item = models.OneToOneField(
        "items.LostItem", on_delete=models.CASCADE, null=True, blank=True,
        related_name="category_prediction",
    )
    found_item = models.OneToOneField(
        "items.FoundItem", on_delete=models.CASCADE, null=True, blank=True,
        related_name="category_prediction",
    )
    predicted_category = models.ForeignKey(
        "items.ItemCategory", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="+",
    )
    predicted_name = models.CharField(max_length=100)
    confidence = models.FloatField()
    agrees = models.BooleanField(help_text="The reporter chose the predicted category.")
    model_version = models.CharField(max_length=60)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    @property
    def item(self):
        return self.lost_item or self.found_item

    def __str__(self):
        return f"{self.item} -> {self.predicted_name} ({self.confidence:.0%})"
