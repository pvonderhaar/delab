import json
from collections import defaultdict

import numpy as np
import pandas as pd
from bertopic import BERTopic
from django_pandas.io import read_frame
from numpy import NaN
from scipy import spatial
from tqdm import tqdm

from delab.models import Tweet, TopicDictionary, TWCandidate


def store_candidates(df_conversations, experiment_index):
    """
    :param df_conversations:
    :param experiment_index:
    :return:
    """
    TWCandidate.objects.filter(exp_id=experiment_index).delete()

    df_conversations = df_conversations[~df_conversations['moderator_index'].isnull()]
    df_conversations = df_conversations[df_conversations['moderator_index'].notna()]
    df_conversations.rename(columns={'id': 'tweet_id'}, inplace=True)
    df_conversations = df_conversations.assign(exp_id=experiment_index)
    df_conversations = df_conversations.assign(coder=None)
    df_conversations = df_conversations.assign(u_moderator_rating=None)
    df_conversations = df_conversations.assign(u_sentiment_rating=None)
    df_conversations = df_conversations.assign(u_author_topic_variance_rating=None)
    df_conversations = df_conversations.replace({np.nan: None})
    df_conversations = df_conversations[['tweet_id',
                                         'exp_id',
                                         'c_sentiment_value_norm',
                                         'sentiment_value_norm',
                                         'c_author_number_changed_norm',
                                         'c_author_topic_variance_norm',
                                         'coder',
                                         'moderator_index',
                                         'u_moderator_rating',
                                         'u_sentiment_rating',
                                         'u_author_topic_variance_rating'
                                         ]]

    df_conversation_records = df_conversations.to_dict('records')
    tw_candidates = [TWCandidate(**candidate) for candidate in df_conversation_records]
    TWCandidate.objects.bulk_create(tw_candidates)
    print("writting {} candidates to the candidates table".format(len(tw_candidates)))


def compute_moderator_index(experiment_index):
    qs = Tweet.objects.filter(tw_author__has_timeline=True, tw_author__timeline_bertopic_id__gt=0, language='en')
    df_conversations = read_frame(qs, fieldnames=["id", "text", "author_id", "bertopic_id", "bert_visual",
                                                  "conversation_id",
                                                  "sentiment_value", "created_at", "tw_author__timeline_bertopic_id"])

    df_conversations = df_conversations.sort_values(by=['conversation_id', 'created_at'])
    df_conversations.reset_index(drop=True, inplace=True)
    # for debugging keep n rows
    df_conversations = df_conversations.head(100)

    candidate_sentiment_values = compute_sentiment_change_candidate(df_conversations)
    df_conversations = df_conversations.assign(candidate_sentiment_value=candidate_sentiment_values)

    candidate_author_numbers = compute_number_of_authors_changed(df_conversations)
    df_conversations = df_conversations.assign(candidate_author_number_changed=candidate_author_numbers)

    # loading the bertopic model
    BERTOPIC_MODEL_LOCATION = "BERTopic"
    bertopic_model = BERTopic.load(BERTOPIC_MODEL_LOCATION,
                                   embedding_model="sentence-transformers/all-mpnet-base-v2")
    topic_info = bertopic_model.get_topic_info()

    # create topic-word map
    topic2word = compute_topic2word(bertopic_model, topic_info)

    # loading the word vectors from the database (maybe this needs filtering at some point)
    # word2vec = get_query_native(
    #    "SELECT word, ft_vector from delab_topicdictionary")
    qs = TopicDictionary.objects.all()
    word2vec = read_frame(qs, fieldnames=["word", "ft_vector"])

    candidate_author_topic_variance = compute_author_topic_variance(df_conversations, topic2word, word2vec)

    # normalizing the measures
    df_conversations = df_conversations.assign(
        c_sentiment_value_norm=normalize(df_conversations.candidate_sentiment_value))
    df_conversations = df_conversations.assign(
        c_author_number_changed_norm=normalize(df_conversations.candidate_author_number_changed))
    df_conversations = df_conversations.assign(c_author_topic_variance_norm=candidate_author_topic_variance)
    df_conversations = df_conversations.assign(sentiment_value_norm=normalize(df_conversations.sentiment_value))

    # summing up the measures without weights
    df_conversations = df_conversations.assign(moderator_index=df_conversations.c_author_number_changed_norm
                                                               + df_conversations.c_sentiment_value_norm
                                                               + df_conversations.c_author_topic_variance_norm
                                                               - abs(df_conversations.sentiment_value_norm)
                                               )

    store_candidates(df_conversations, experiment_index)
    candidates = df_conversations.nlargest(10, ["moderator_index"])
    return candidates


def compute_topic2word(bertopic_model, topic_info):
    topic2word = defaultdict(list)
    for topic_id in topic_info.Topic:
        topic_model = bertopic_model.get_topic(topic_id)
        words = topic2wordvec(topic_model)
        topic2word[topic_id] = topic2word[topic_id] + words
    return topic2word


def compute_sentiment_change_candidate(df):
    """
    :param sentiment_values: pandas series
    :return:
    """
    n = len(df.sentiment_value)
    result = []
    for index in range(n):
        candidate_sentiment_value = 0
        conversation_id = df.at[index, "conversation_id"]
        conversation_length = df[df["conversation_id"] == conversation_id].conversation_id.count()
        # print(conversation_length)
        # the candidate cannot be later in the conversation then the middle by definition
        for index_delta in range(conversation_length // 2):
            previous_tweets_index = index - index_delta
            following_tweets_index = index + index_delta
            # we assert that there are as many predecessors as there are followers
            if previous_tweets_index > 0 and following_tweets_index < n:
                if (df.at[previous_tweets_index, "conversation_id"] == conversation_id and
                        df.at[following_tweets_index, "conversation_id"] == conversation_id
                ):
                    candidate_sentiment_value -= df.at[previous_tweets_index, "sentiment_value"]
                    candidate_sentiment_value += df.at[following_tweets_index, "sentiment_value"]
        result.append(candidate_sentiment_value)
    return result


def compute_number_of_authors_changed(df):
    """
    :param sentiment_values: pandas series
    :return:
    """
    n = len(df.sentiment_value)
    result = []
    for index in range(n):
        candidate_number_authors_before = set()
        candidate_number_authors_after = set()
        conversation_id = df.at[index, "conversation_id"]
        conversation_length = df[df["conversation_id"] == conversation_id].conversation_id.count()
        # print(conversation_length)
        # the candidate cannot be later in the conversation then the middle by definition
        for index_delta in range(conversation_length // 2):
            previous_tweets_index = index - index_delta
            following_tweets_index = index + index_delta
            # we assert that there are as many predecessors as there are followers
            if previous_tweets_index > 0 and following_tweets_index < n:
                if (df.at[previous_tweets_index, "conversation_id"] == conversation_id and
                        df.at[following_tweets_index, "conversation_id"] == conversation_id
                ):
                    candidate_number_authors_before.add(df.at[previous_tweets_index, "author_id"])
                    candidate_number_authors_after.add(df.at[following_tweets_index, "author_id"])
        result.append(len(candidate_number_authors_after) - len(candidate_number_authors_before))
    return result


# a utility function for retrieving the words given a bertopic model
def topic2wordvec(topic_model):
    result = []
    for t_word in topic_model:
        str_w = t_word[0]
        result.append(str_w)
    return result


# a function that computes the cosine similarity betweent the word vectors of the topics
def get_topic_delta(topic_id_1, topic_id_2, topic2word, word2vec):
    words1 = topic2word.get(topic_id_1)
    words2 = topic2word.get(topic_id_2)
    if words1 is not None and words2 is not None:
        filtered_w2v1 = word2vec[word2vec["word"].isin(words1)]
        filtered_w2v2 = word2vec[word2vec["word"].isin(words2)]
        ft_vectors_1 = filtered_w2v1.ft_vector.apply(lambda x: pd.Series(json.loads(x)))
        ft_vectors_2 = filtered_w2v2.ft_vector.apply(lambda x: pd.Series(json.loads(x)))
        len1 = len(ft_vectors_1)
        len2 = len(ft_vectors_2)
        if len1 == 0 or len2 == 0:
            # print("vector was not loaded properly for words {}{}".format(words1[0], words2[0]))
            return np.NaN
        sum_v1 = (ft_vectors_1.sum(axis=0) / len1)  # we assume the vectors are embedded in a linear space
        sum_v2 = (ft_vectors_2.sum(axis=0) / len2)
        similarity = spatial.distance.cosine(sum_v1, sum_v2)
        return similarity
    else:
        return np.NaN


# similar to the above shown approaches we create a column that shows the quality of the candidates
# regarding this "topic variance" measure
def compute_author_topic_variance(df, topic2word, word2vec):
    """
    :param df:
    :param bert_topic_model:
    :return:
    """
    print("computing author timeline deltas... this might take a while\n")
    n = len(df.author_id)
    result = []
    indices = range(n)
    for index in tqdm(indices):
        authors_before = set()
        authors_after = set()
        conversation_id = df.at[index, "conversation_id"]
        conversation_length = df[df["conversation_id"] == conversation_id].conversation_id.count()
        # print(conversation_length)
        # the candidate cannot be later in the conversation then the middle by definition
        for index_delta in range(conversation_length // 2):
            previous_tweets_index = index - index_delta
            following_tweets_index = index + index_delta
            # we assert that there are as many predecessors as there are followers
            if previous_tweets_index > 0 and following_tweets_index < n:
                if (df.at[previous_tweets_index, "conversation_id"] == conversation_id and
                        df.at[following_tweets_index, "conversation_id"] == conversation_id
                ):
                    # authors_before.add(df.at[previous_tweets_index, "author_id"])
                    # authors_after.add(df.at[following_tweets_index, "author_id"])
                    authors_before.add(df.at[previous_tweets_index, "tw_author__timeline_bertopic_id"])
                    authors_after.add(df.at[following_tweets_index, "tw_author__timeline_bertopic_id"])

        author_topic_var_before = 0
        author_topic_var_after = 0
        n_author_before = len(authors_before)
        n_author_after = len(authors_after)
        if n_author_after > 0:
            author_before_pivot = authors_before.pop()
            for author in authors_before:
                delta = get_topic_delta(author_before_pivot, author, topic2word, word2vec)
                author_topic_var_before += delta
                author_before_pivot = author
            author_topic_var_before = author_topic_var_before / n_author_before

            author_after_pivot = authors_after.pop()
            for author in authors_after:
                delta = get_topic_delta(author_after_pivot, author, topic2word, word2vec)
                author_topic_var_after += delta
                author_after_pivot = author
            author_topic_var_after = author_topic_var_after / n_author_after

        result.append(author_topic_var_after - author_topic_var_before)
    return result


def normalize(sv):
    return (sv - sv.min()) / (sv.max() - sv.min())
