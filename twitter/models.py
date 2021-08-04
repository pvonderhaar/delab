from django.core.validators import RegexValidator
from django.db import models
from django.db.models import UniqueConstraint
from django.urls import reverse

from django.core.management import call_command
import twitter


# Create your models here.
class TwTopic(models.Model):
    title = models.CharField(max_length=200)

    class Meta:
        constraints = [
            UniqueConstraint(fields=['title'], name="unique_topic_constraint_title"),
        ]

    def __str__(self):
        return self.title

    @classmethod
    def create(cls, title):
        topic = cls(title=title)
        # do something with the book
        return topic


SIMPLE_REQUEST_VALIDATOR = RegexValidator("(^\#[a-zäöüA-ZÖÄÜ]+(\ \#[a-zA-ZÖÄÜ]+)*$)",
                                          'Please enter hashtags seperated by spaces!')


class SimpleRequest(models.Model):
    title = models.CharField(max_length=200, validators=[SIMPLE_REQUEST_VALIDATOR])
    created_at = models.DateTimeField(auto_now_add=True, blank=True)

    class Meta:
        constraints = [
            UniqueConstraint(fields=['title'], name="unique_simple_request_constraint_title"),
        ]

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        # TODO reverse this to a site that shows the queried tweets
        # return reverse('delab-simple-request-result', kwargs={'pk': self.pk})
        return reverse('delab-create-simple-request')


class Conversation(models.Model):
    conversation_id = models.IntegerField()
    simple_request = models.ForeignKey(SimpleRequest, on_delete=models.DO_NOTHING)

    @classmethod
    def create(cls, conversation_id):
        conversation = cls(conversation_id=conversation_id)
        # do something with the book
        return conversation


class Tweet(models.Model):
    twitter_id = models.IntegerField()
    text = models.TextField()
    user = models.CharField(max_length=200, null=True)
    author_id = models.IntegerField()
    in_reply_to_status_id = models.IntegerField(null=True)
    in_reply_to_user_id = models.IntegerField(null=True)
    created_at = models.DateTimeField(null=True)
    query_string = models.TextField(null=True)
    topic = models.ForeignKey(TwTopic, on_delete=models.DO_NOTHING)
    conversation = models.ForeignKey(Conversation, null=True, on_delete=models.DO_NOTHING)

    class Meta:
        constraints = [
            UniqueConstraint(fields=['twitter_id'], name="unique_tweet_constraint_id"),
            UniqueConstraint(fields=['text'], name="unique_tweet_constraint_text"),
        ]

    def __str__(self):
        return "Twitter_ID :{} Conversation_ID:{} Text:{} Autor:{}".format(self.twitter_id,
                                                                           self.conversation.conversation_id,
                                                                           self.text,
                                                                           self.author_id)
