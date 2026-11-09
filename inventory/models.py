from django.db import models


class Material(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    unit = models.CharField(max_length=30, default='عدد')

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f"{self.code} — {self.name}"