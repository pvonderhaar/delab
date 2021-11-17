from delab.analytics.compute_moderator_index import compute_moderator_index

from delab.corpus.download_author_information import update_authors
from delab.models import PLATFORM, VERSION
from delab.sentiment.sentiment_classification import update_tweet_sentiments
from delab.topic.topic_data_preperation import update_timelines_from_conversation_users
from delab.topic.train_topic_model import classify_author_timelines, train_topic_model_from_db, classify_tweets


def run(*args):
    # Stores the trained sentiment model in {base}/model
    # train_sentiment_classification()
    # print("STEP 1: FINISHED training classifier")

    """
    This pipeline computes the full analysis of the downloaded tweets
    1. download the missing authordata and timelines (if that has not happened)
    2. analyse the sentiments of the tweets
    3. compute data for the candidate table

    It assumes that tweets have been downloaded using the web-interface or the script download_conversations.py!!
    """

    analysis_version = VERSION.v001
    platform = PLATFORM.REDDIT
    train_update_topics = True
    if len(args) > 0:
        analysis_version = args[0]
    if len(args) > 1:
        train_update_topics = bool(args[1] == "True")

    update_tweet_sentiments()
    print("STEP 1.1: updated tweet sentiments")
    # download the extended author data for those who are missing
    update_authors(platform=platform)
    print("STEP 2: FINISHED updating authors")
    # download the twitter timelines for those who are missing
    update_timelines_from_conversation_users(platform=platform)
    print("STEP 3: FINISHED updating author timelines")
    # 1. Trains the bertopic model on the timelines and the tweets and stores the trained bertopic model in "BERTopic"
    # 2. loads fasttextvectors for all bertopic models and stores them in topicdictionary
    train_topic_model_from_db(train=train_update_topics, store_vectors=train_update_topics, number_of_batches=50000,
                              platform=platform)
    print("STEP 4: FINISHED training the bertopic model")
    # classify the author timelines
    classify_author_timelines(update=train_update_topics, platform=platform)
    print("STEP 5: FINISHED classifying the author timelines")
    # classifying the tweets
    classify_tweets(update_topics=train_update_topics, platform=platform)
    print("STEP 6: FINISHED classifying the tweets in the conversation table")
    # compute the moderator index and store it in twcandidate table
    candidates = compute_moderator_index(analysis_version, platform=platform)
    print("STEP 7: FINISHED computing the moderator_index")
    if len(candidates) > 10:
        print(candidates.head(10))
