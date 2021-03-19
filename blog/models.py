from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User
from django.contrib.auth import get_user_model
from django.urls import reverse


class Post(models.Model):
    title = models.CharField(max_length=100)
    content = models.TextField()
    date_posted = models.DateTimeField(default=timezone.now)
    author = models.ForeignKey(User, on_delete=models.CASCADE)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('post-detail', kwargs={'pk': self.pk})


def get_sentinel_user():
    return get_user_model().objects.get_or_create(username='deleted')[0]


class Institution(models.Model):
    title = models.CharField(max_length=100)
    image = models.ImageField(default='default.jpg', upload_to='institution_pics')
    description = models.TextField()
    date_posted = models.DateTimeField(default=timezone.now)
    author = models.ForeignKey(User, on_delete=models.SET(get_sentinel_user))

    def __str__(self):
        return self.title

    def get_absolute_url(self):
       return reverse('institution-detail', kwargs={'pk': self.pk})


