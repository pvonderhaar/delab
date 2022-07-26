import datetime
from random import choice

from background_task.models import Task
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Q, Count
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import (
    ListView,
    CreateView,
    UpdateView, TemplateView
)

from delab.models import SimpleRequest, Tweet, TwTopic, TWCandidate, PLATFORM, TweetAuthor, TWCandidateIntolerance, \
    TWIntoleranceRating, IntoleranceAnswer, IntoleranceAnswerValidation
from django_project.settings import min_intolerance_answer_coders_needed, min_intolerance_coders_needed
from util.abusing_strings import convert_to_hash
from .tasks import get_tasks_status


# @method_decorator(csrf_exempt, name='dispatch')
class SimpleRequestListView(ListView):
    model = SimpleRequest
    template_name = 'delab/simple_request_list.html'
    context_object_name = 'requests'
    fields = ['created_at', 'title', 'language']
    paginate_by = 5


def simple_request_proxy(request, pk):
    """
    The idea is that if the download_process is still running in the background, the Task_Status_view shoudl be displayed.
    Otherwise, the downloaded conversations should be displayed!
    :param request:
    :param simple_request_id:
    :return:
    """
    running_tasks = get_tasks_status(pk)
    if len(running_tasks) > 0:
        return redirect('simple-request-status', pk=pk)
    else:
        return redirect('delab-conversations-for-request', pk=pk)


class ConversationListView(ListView):
    model = Tweet
    template_name = 'delab/tweet_list.html'  # <app>/<model>_<viewtype>.html
    context_object_name = 'tweets'
    fields = ['created_at', 'text', 'author_id', 'conversation_id']
    paginate_by = 5

    def get_queryset(self):
        simple_request = get_object_or_404(SimpleRequest, id=self.request.resolver_match.kwargs['pk'])
        return Tweet.objects.filter(Q(simple_request=simple_request) & Q(tn_parent__isnull=True)) \
            .order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super(ConversationListView, self).get_context_data(**kwargs)
        simple_request = get_object_or_404(SimpleRequest, id=self.request.resolver_match.kwargs['pk'])
        context['simple_request'] = simple_request
        return context


# @method_decorator(csrf_exempt, name='dispatch')
class ConversationView(ListView):
    model = Tweet
    template_name = 'delab/conversation.html'  # <app>/<model>_<viewtype>.html
    context_object_name = 'tweets'
    fields = ['created_at', 'text', 'author_id', 'sentiment', 'conversation_id', 'simple_request_id']
    paginate_by = 5

    def get_queryset(self):
        return Tweet.objects.filter(conversation_id=self.request.resolver_match.kwargs['conversation_id']) \
            .order_by("created_at")

    def get_context_data(self, **kwargs):
        context = super(ConversationView, self).get_context_data(**kwargs)
        # simple_request = get_object_or_404(SimpleRequest, id=self.request.resolver_match.kwargs['pk'])
        conversation_id = self.request.resolver_match.kwargs['conversation_id']
        topic = Tweet.objects.filter(conversation_id=conversation_id).first().topic.title
        context['topic'] = topic
        return context


# Create your views here.
##@method_decorator(csrf_exempt, name='dispatch')
class SimpleRequestCreateView(SuccessMessageMixin, CreateView):
    model = SimpleRequest
    fields = ['platform', 'version', 'topic', 'title', 'fast_mode', 'language']
    initial = {"title": "covid vaccination"}

    success_message = "Conversations with the request %(title)s are being downloaded now! \n" \
                      "You might have to refresh the page until we have build a loading screen!"


# Create your views here.
# #@method_decorator(csrf_exempt, name='dispatch')
class TopicCreateView(SuccessMessageMixin, CreateView):
    model = TwTopic
    fields = ['title']
    initial = {"title": "migration"}

    success_message = "The Topic has been created!"


class ModerationCreateView(SuccessMessageMixin, CreateView, LoginRequiredMixin):
    model = Tweet
    fields = ['text', 'd_comment', 'publish']
    # initial = {"title": "migration"}
    success_message = "The Moderation Suggestion has been created!"

    def form_valid(self, form):
        form.instance.author_id = self.request.user.id
        form.instance.platform = PLATFORM.DELAB
        parent_id = self.request.resolver_match.kwargs['reply_to_id']
        form.instance.tn_parent_id = parent_id
        parent_tweet = Tweet.objects.filter(twitter_id=parent_id).get()
        form.instance.in_reply_to_user_id = parent_tweet.author_id
        form.instance.conversation_id = parent_tweet.conversation_id
        form.instance.simple_request_id = parent_tweet.simple_request_id
        form.instance.topic_id = parent_tweet.topic_id
        form.instance.created_at = parent_tweet.created_at + datetime.timedelta(milliseconds=1)
        form.instance.language = parent_tweet.language
        form.instance.twitter_id = convert_to_hash(form.instance.text + str(parent_id))
        return super().form_valid(form)

    def get_success_url(self):
        parent_id = self.request.resolver_match.kwargs['reply_to_id']
        parent_tweet = Tweet.objects.filter(twitter_id=parent_id).get()
        return reverse('delab-conversation', kwargs={'conversation_id': parent_tweet.conversation_id})

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super(ModerationCreateView, self).get_context_data(**kwargs)
        parent_id = self.request.resolver_match.kwargs['reply_to_id']
        parent_tweet = Tweet.objects.filter(twitter_id=parent_id).get()
        context["parent"] = parent_tweet.text

        return context


# @method_decorator(csrf_exempt, name='dispatch')
class TaskStatusView(ListView):
    model = Task
    template_name = 'delab/task_status.html'
    context_object_name = 'tasks'
    fields = ['task_name', "task_params", "verbose_name", "last_error", "run_at"]

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super(TaskStatusView, self).get_context_data(**kwargs)
        simple_request = get_object_or_404(SimpleRequest, id=self.request.resolver_match.kwargs['pk'])
        context['simple_request'] = simple_request
        context['tweets_downloaded'] = simple_request.tweet_set.count()
        authors_downloaded = simple_request.tweet_set.filter(tw_author__isnull=False).count()
        context["authors_downloaded"] = authors_downloaded
        # timelines_not_downloaded = Tweet.objects.filter(
        #    ~Exists(Timeline.objects.filter(author_id=OuterRef("author_id")))).filter(
        #    simple_request_id=simple_request.id).count()
        # context["timelines_downloaded"] = context['tweets_downloaded'] - timelines_not_downloaded
        sentiments_analyzed = simple_request.tweet_set.filter(sentiment_value__isnull=False).count()
        context["sentiments_analyzed"] = sentiments_analyzed
        flows_analyzed = simple_request.tweet_set.filter(conversation_flow__isnull=False).count()
        context["flows_analyzed"] = flows_analyzed

        # tweet_ids = simple_request.tweet_set.values_list("id", flat=True)
        timelines_downloaded = TweetAuthor.objects.filter(has_timeline=True).count()
        context["timelines_downloaded"] = timelines_downloaded
        return context

    def get_queryset(self):
        pk = self.request.resolver_match.kwargs['pk']
        tasks = Task.objects.filter(verbose_name__contains=pk)
        return tasks

    def dispatch(self, request, *args, **kwargs):
        # check if there is some video onsite
        pk = self.request.resolver_match.kwargs['pk']
        tasks = Task.objects.filter(verbose_name__contains=pk)
        if tasks.count() == 0:
            return redirect("delab-conversations-for-request", pk=pk)
        else:
            return super(TaskStatusView, self).dispatch(request, *args, **kwargs)


class TWCandidateLabelView(LoginRequiredMixin, UpdateView, SuccessMessageMixin):
    model = TWCandidate
    fields = ['u_moderator_rating', 'u_author_topic_variance_rating', 'u_sentiment_rating']

    def form_valid(self, form):
        form.instance.coder = self.request.user
        return super().form_valid(form)

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super(TWCandidateLabelView, self).get_context_data(**kwargs)

        candidate_id = self.request.resolver_match.kwargs['pk']
        # candidate_id = self.query_pk_and_slug
        candidate = TWCandidate.objects.filter(id=candidate_id).get()
        tweet_text = candidate.tweet.text
        tweet_id = candidate.tweet.id
        # context["text"] = clean_corpus([tweet_text])[0]
        context["text"] = tweet_text
        context["tweet_id"] = tweet_id
        context_tweets = Tweet.objects.filter(conversation_id=candidate.tweet.conversation_id).order_by(
            '-created_at')

        full_conversation = list(context_tweets.values_list("text", flat=True))
        index = full_conversation.index(tweet_text)

        # full_conversation = clean_corpus(full_conversation)
        context["conversation"] = full_conversation[index - 2:index + 3]
        return context


def candidate_label_proxy(request):
    candidates = TWCandidate.objects.filter(
        Q(coder__isnull=True) & ~Q(coded_by=request.user)).all()
    if len(candidates) == 0:
        # raise Http404("There seems no more data to label!")
        return redirect('delab-label-moderation-nomore')
    candidate = choice(candidates)
    pk = candidate.pk
    return redirect('delab-label', pk=pk)


def downloads_view(request):
    return render(request, 'delab/downloads.html')


class TWCandidateIntoleranceLabelView(LoginRequiredMixin, CreateView, SuccessMessageMixin):
    """
    This is a classical create view. It allows for a user rating whether a tweet is intolerant
    to be registered.
    """
    model = TWIntoleranceRating
    fields = ['u_person_hate', 'u_clearness_rating', 'user_category', 'u_intolerance_rating', 'u_sentiment_rating',
              'u_political_correct_word']

    def get_initial(self):
        initial = super().get_initial()
        candidate_id = self.request.resolver_match.kwargs['pk']
        candidate = TWCandidateIntolerance.objects.filter(id=candidate_id).get()
        initial['u_political_correct_word'] = candidate.political_correct_word
        return initial

    def form_valid(self, form):
        form.instance.coder = self.request.user
        form.instance.candidate_id = self.request.resolver_match.kwargs['pk']
        candidate_political_correct_word = form.cleaned_data.get("u_political_correct_word", "")
        candidate = TWCandidateIntolerance.objects.filter(id=form.instance.candidate_id).get()
        candidate.political_correct_word = candidate_political_correct_word
        candidate.save(update_fields=["political_correct_word"])
        return super().form_valid(form)

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super(TWCandidateIntoleranceLabelView, self).get_context_data(**kwargs)

        candidate_id = self.request.resolver_match.kwargs['pk']

        candidate = TWCandidateIntolerance.objects.filter(id=candidate_id).get()

        tweet_text = candidate.tweet.text
        tweet_id = candidate.tweet.id
        # context["text"] = clean_corpus([tweet_text])[0]
        context["text"] = tweet_text
        context["tweet_id"] = tweet_id
        context_tweets = Tweet.objects.filter(conversation_id=candidate.tweet.conversation_id) \
            .order_by('-created_at')

        full_conversation = list(context_tweets.values_list("text", flat=True))
        index = full_conversation.index(tweet_text)

        # full_conversation = clean_corpus(full_conversation)
        context["conversation"] = full_conversation[index - 2:index + 3]
        return context


def intolerance_candidate_label_proxy(request):
    """
    This randomly selects candidates to be labeled from the candidatestable that were preselected based on a dictionary approach
    It then redirects to the create-view where the labeling of the candidate takes place.
    :param request:
    :return:
    """
    current_user = request.user
    candidates = TWCandidateIntolerance.objects \
        .annotate(num_coders=Count('twintolerancerating')) \
        .filter(num_coders__lt=min_intolerance_coders_needed) \
        .exclude(twintolerancerating__in=current_user.twintolerancerating_set.all()) \
        .all()
    if len(candidates) == 0:
        # raise Http404("There seems no more data to label!")
        return redirect('delab-label-intolerance-nomore')
    candidate = choice(candidates)
    pk = candidate.pk
    return redirect('delab-label-intolerance', pk=pk)


def intolerance_answer_validation_proxy(request):
    current_user = request.user
    candidates = IntoleranceAnswer.objects \
        .filter(twitter_id__isnull=True) \
        .annotate(num_coders=Count('intoleranceanswervalidation')) \
        .filter(num_coders__lt=min_intolerance_answer_coders_needed) \
        .exclude(intoleranceanswervalidation__in=current_user.intoleranceanswervalidation_set.all()) \
        .all()
    if len(candidates) == 0:
        # raise Http404("There seems no more answers to validate!")
        return redirect('delab-intolerance-answer-validation-nomore')
    candidate = choice(candidates)
    pk = candidate.pk
    return redirect('delab-intolerance-answer-validation', pk=pk)


class IntoleranceAnswerValidationView(LoginRequiredMixin, CreateView, SuccessMessageMixin):
    model = IntoleranceAnswerValidation
    fields = ["valid", "comment"]

    def form_valid(self, form):
        form.instance.coder = self.request.user
        form.instance.answer_id = self.request.resolver_match.kwargs['pk']
        return super().form_valid(form)

    def get_context_data(self, *, object_list=None, **kwargs):
        context = super(IntoleranceAnswerValidationView, self).get_context_data(**kwargs)

        answer_id = self.request.resolver_match.kwargs['pk']

        answer = IntoleranceAnswer.objects.filter(id=answer_id).get()

        tweet_text = answer.candidate.tweet.text
        tweet_id = answer.candidate.tweet.id

        context["text"] = tweet_text
        context["tweet_id"] = tweet_id

        # NOT SURE, whether the whole context should be displayed again (may not fit)
        # context_tweets = Tweet.objects.filter(conversation_id=answer.candidate.tweet.conversation_id).order_by(
        #    '-created_at')

        # full_conversation = list(context_tweets.values_list("text", flat=True))
        # index = full_conversation.index(tweet_text)

        # full_conversation = clean_corpus(full_conversation)
        # context["conversation"] = full_conversation[index - 2:index + 3]
        context["answer1"] = answer.answer1
        context["answer2"] = answer.answer2
        context["answer3"] = answer.answer3

        return context


class NoMoreIntolerantCandidatesView(TemplateView):
    template_name = "delab/nomore_intolerant_tweets_tolabel.html"


class NoMoreAnswersToValidateView(TemplateView):
    template_name = "delab/nomore_answers_tovalidate.html"


class NoMoreModeratingCandidatesView(TemplateView):
    template_name = "delab/nomore_moderations_tolabel.html"
