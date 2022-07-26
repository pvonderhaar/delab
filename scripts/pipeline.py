from delab.analytics.compute_moderator_index import compute_moderator_index

from delab.corpus.download_author_information import update_authors
from delab.models import PLATFORM, VERSION, LANGUAGE
from delab.sentiment.sentiment_classification import update_tweet_sentiments
from delab.topic.topic_data_preperation import update_timelines_from_conversation_users
from delab.topic.train_topic_model import classify_author_timelines, train_topic_model_from_db, classify_tweet_topics


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

    analysis_version = VERSION.v002
    platform = PLATFORM.TWITTER
    train_update_topics = True

    if len(args) > 0:
        analysis_version = args[0]
    if len(args) > 1:
        train_update_topics = bool(args[1] == "True")
    if len(args) > 2:
        if args[2] == PLATFORM.TWITTER or args[2] == PLATFORM.REDDIT:
            platform = args[2]
    print("using platform {}".format(platform))

    update_tweet_sentiments(language=LANGUAGE.ENGLISH)
    update_tweet_sentiments(language=LANGUAGE.GERMAN)
    print("STEP 1.1: updated tweet sentiments")
    # download the extended author data for those who are missing
    update_authors(platform=platform)
    print("STEP 2: FINISHED updating authors")
    # download the twitter timelines for those who are missing
    update_timelines_from_conversation_users(platform=platform)
    print("STEP 3: FINISHED updating author timelines")
    # 1. Trains the bertopic model on the timelines and the tweets and stores the trained bertopic model in "BERTopic"
    # 2. loads fasttextvectors for all bertopic models and stores them in topicdictionary
    train_topic_model_from_db(version=analysis_version,
                              train=train_update_topics,
                              store_vectors=train_update_topics,
                              number_of_batches=1000,
                              platform=platform,
                              language=LANGUAGE.ENGLISH)
    train_topic_model_from_db(version=analysis_version,
                              train=train_update_topics,
                              store_vectors=train_update_topics,
                              number_of_batches=1000,
                              platform=platform,
                              language=LANGUAGE.GERMAN)
    print("STEP 4: FINISHED training the bertopic model")
    # classify the author timelines
    classify_author_timelines(version=analysis_version, language=LANGUAGE.ENGLISH, update=train_update_topics, platform=platform)
    classify_author_timelines(version=analysis_version, language=LANGUAGE.GERMAN, update=train_update_topics, platform=platform)
    print("STEP 5: FINISHED classifying the author timelines")
    # classifying the tweets
    classify_tweet_topics(analysis_version, LANGUAGE.ENGLISH, update_topics=train_update_topics, platform=platform)
    classify_tweet_topics(analysis_version, LANGUAGE.GERMAN, update_topics=train_update_topics, platform=platform)
    print("STEP 6: FINISHED classifying the tweets in the conversation table")
    # compute the moderator index and store it in twcandidate table
    candidates = compute_moderator_index(analysis_version, platform=platform, language=LANGUAGE.ENGLISH)
    candidates_de = compute_moderator_index(analysis_version, platform=platform, language=LANGUAGE.GERMAN)
    print("STEP 7: FINISHED computing the moderator_index")
    n_candidates = len(candidates) + len(candidates_de)
    print("computed {} candidates".format(n_candidates))
