import logging
import re
import time

import requests
from TwitterAPI import TwitterRequestError, TwitterConnectionError
from django.db import IntegrityError

from delab import tw_connection_util
from delab.TwConversationTree import TreeNode
from delab.corpus.download_exceptions import ConversationNotInRangeException
from delab.corpus.filter_conversation_trees import solve_orphans
from delab.magic_http_strings import TWEETS_SEARCH_All_URL
from delab.models import Tweet, TwTopic, SimpleRequest, PLATFORM, LANGUAGE
from delab.tw_connection_util import TwitterConnector
from django_project.settings import MAX_CANDIDATES
from util.abusing_lists import powerset

logger = logging.getLogger(__name__)


def download_conversations(topic_string, query_string, request_id=-1, language=LANGUAGE.ENGLISH, max_data=False,
                           fast_mode=False, conversation_filter=None, tweet_filter=None, platform=PLATFORM.TWITTER):
    """
    :param topic_string:
    :param query_string:
    :param request_id:
    :param language:
    :param max_data:
    :param fast_mode:
    :param conversation_filter:
    :param tweet_filter:
    :param platform:
    :return:
    """

    # create the topic and save it to the db
    topic, created = TwTopic.objects.get_or_create(
        title=topic_string
    )

    # save the request to the db in order to link the results in the view to the hashtags entered
    if request_id > 0:
        simple_request, created = SimpleRequest.objects.get_or_create(
            pk=request_id,
            topic=topic
        )
    else:
        # request_string = "#" + ' #'.join(hashtags)
        simple_request, created = SimpleRequest.objects.get_or_create(
            title=query_string,
            topic=topic
        )

    # create only one connector for quote reasons
    connector = TwitterConnector(1)

    # download the conversations
    if max_data:
        # this computes the powerset of the queried words
        pattern = r'[\(\)\[\]]'
        bag_of_words = re.sub(pattern, '', query_string).split(" ")
        combinations = list(powerset(bag_of_words))
        combinations_l = len(combinations) - 1
        combination_counter = 0
        for hashtag_set in combinations:
            if len(hashtag_set) > 0:
                combination_counter += 1
                new_query = " ".join(hashtag_set)
                filter_conversations(connector, new_query, topic, simple_request, platform, language=language,
                                     fast_mode=fast_mode, conversation_filter=conversation_filter,
                                     tweet_filter=tweet_filter)
                logger.debug("FINISHED combination {}/{}".format(combination_counter, combinations_l))
    else:
        # in case max_data is false we don't compute the powerset of the hashtags
        filter_conversations(connector, query_string, topic, simple_request, platform, language=language,
                             fast_mode=fast_mode, conversation_filter=conversation_filter,
                             tweet_filter=tweet_filter)

    connector = None  # precaution to terminate the thread and the http socket


def filter_conversations(connector,
                         query,
                         topic,
                         simple_request,
                         platform,
                         max_conversation_length=1000,
                         min_conversation_length=10,
                         language=LANGUAGE.ENGLISH,
                         max_number_of_candidates=MAX_CANDIDATES,
                         fast_mode=False,
                         conversation_filter=None,
                         tweet_filter=None):
    """
    :param connector:
    :param query:
    :param topic:
    :param simple_request:
    :param platform:
    :param max_conversation_length:
    :param min_conversation_length:
    :param language:
    :param max_number_of_candidates:
    :param fast_mode:
    :param conversation_filter:
    :param tweet_filter:
    :return:
    """
    if fast_mode:
        max_number_of_candidates = 100
        min_conversation_length = 3
        max_conversation_length = 100

    tweets_result = download_conversation_representative_tweets(connector, query, max_number_of_candidates,
                                                                min_conversation_length, language)
    candidates = tweets_result.get("data", [])
    downloaded_tweets = 0
    n_dismissed_candidates = 0
    for candidate in candidates:
        if candidate["public_metrics"]["reply_count"] > min_conversation_length / 2:
            try:
                logger.debug("selected candidate tweet {}".format(candidate))
                conversation_id = candidate["conversation_id"]

                root_node = download_conversation_as_tree(conversation_id, max_conversation_length)

                if conversation_filter is not None:
                    root_node = conversation_filter(root_node)

                if root_node is None:
                    logger.error("found conversation_id that could not be processed")
                    continue
                else:
                    flat_tree_size = root_node.flat_size()
                    logger.debug("found tree with size: {}".format(flat_tree_size))
                    logger.debug("found tree with depth: {}".format(root_node.compute_max_path_length()))
                    downloaded_tweets += flat_tree_size
                    if min_conversation_length < flat_tree_size:
                        save_tree_to_db(root_node, topic, simple_request, conversation_id, platform,
                                        tweet_filter=tweet_filter)
                        logger.debug("found suitable conversation and saved to db {}".format(conversation_id))
                        # for debugging you can ascii art print the downloaded conversation_tree
                        # root_node.print_tree(0)
            except TwitterRequestError as e:
                # traceback.print_exc()
                logger.info(
                    "############# TwitterRequestError: Rate limit was exceeded while downloading conversations info." +
                    " Going to sleep for 15!")
                time.sleep(15 * 60)

            except TwitterConnectionError as e:
                # traceback.print_exc()
                logger.info("############# TwitterConnectionError Rate limit was exceeded. 169")

            except ConversationNotInRangeException as e:
                logger.debug("downloading HUGE conversation with current size {}".format(e.conversation_size))

            except requests.exceptions.Timeout:
                # traceback.print_exc()
                logger.error("Timeout occurred")
        else:
            n_dismissed_candidates += 1
    logger.debug("{} of {} candidates were dismissed".format(n_dismissed_candidates, len(candidates)))


def download_conversation_representative_tweets(connector, query, max_results, min_conversation_length,
                                                language=LANGUAGE.ENGLISH, ):
    """ downloads the tweets matching the hashtag list.
        using https://api.twitter.com/2/tweets/search/all

        Keyword arguments:
        :param connector -- TwitterConnector
        :param query -- twitter query query
        :param max_results -- the number of max length the conversation should have
        :param language:
        :returns json_object with found tweets
    """
    twitter_accounts_query = query + " lang:" + language
    logger.debug(twitter_accounts_query)
    params = {'query': twitter_accounts_query, 'max_results': max_results,
              "tweet.fields": "conversation_id,author_id,public_metrics"}

    json_result = connector.get_from_twitter(TWEETS_SEARCH_All_URL, params, True)
    return json_result


def download_conversation_as_tree(conversation_id, max_replies):
    twarc = tw_connection_util.DelabTwarc()

    root_tweet = next(twarc.tweet_lookup(tweet_ids=[conversation_id]))["data"][0]
    result = next(twarc.search_all("conversation_id:{}".format(conversation_id)))
    tweets = result.get("data", [])
    tweets.sort(key=lambda x: x["created_at"], reverse=False)
    root = TreeNode(root_tweet, root_tweet["author_id"])

    orphans = []

    reply_count = 0
    for item in tweets:
        if reply_count == 10:
            logger.debug("downloading bigger conversation ...")
        if reply_count >= max_replies:
            raise ConversationNotInRangeException(reply_count)
        node_id = item["author_id"]
        parent_id = item["in_reply_to_user_id"]
        node = TreeNode(item, node_id, parent_id)
        # IF NODE CANNOT BE PLACED IN TREE, ORPHAN IT UNTIL ITS PARENT IS FOUND
        if not root.find_parent_of(node):
            orphans.append(node)
        reply_count += 1

    logger.error('{} orphaned tweets for conversation {} before resolution'.format(len(orphans), conversation_id))
    orphan_added, rest_orphans = solve_orphans(orphans, root)

    if len(orphans) > 0:
        logger.error('{} orphaned tweets for conversation {}'.format(len(rest_orphans), conversation_id))
        logger.error('{} downloaded tweets'.format(reply_count))

    return root


def save_tree_to_db(root_node, topic, simple_request, conversation_id, platform, parent=None, tweet_filter=None):
    """ This method persist a conversation tree in the database


        Parameters
        ----------
        :param root_node : TwConversationTree
        :param topic : the topic of the query
        :param simple_request: the query string in order to link the view
        :param conversation_id: the conversation id of the candidate tweet that was found with the request
        :param platform: this was added to allow for a "fake" delab platform to come in
        :param parent: TwConversationTree this is needed for the recursion, is None for root
        :param tweet_filter: a function that takes a tweet model object and validates it (returns None if not)

    """
    tn_parent = None
    if parent is not None:
        tn_parent = parent.data.get("id", None)

    # before = dt.now()
    tweet = Tweet(topic=topic,
                  text=root_node.data["text"],
                  simple_request=simple_request,
                  twitter_id=root_node.data["id"],
                  author_id=root_node.data["author_id"],
                  conversation_id=conversation_id,
                  created_at=root_node.data["created_at"],
                  in_reply_to_user_id=root_node.data.get("in_reply_to_user_id", None),
                  in_reply_to_status_id=root_node.data.get("in_reply_to_status_id", None),
                  tn_parent_id=tn_parent,
                  platform=platform,
                  # tn_priority=priority,
                  language=root_node.data["lang"])
    try:
        if tweet_filter is not None:
            tweet = tweet_filter(tweet)
            # the idea here is that the filter may have to save the tweet to create foreign keys
            # in this case the save method will fail because of an integrity error
            if tweet.pk is None:
                tweet.save()

        else:
            tweet.save()
    except IntegrityError:
        pass
    # after = dt.now()
    # logger.debug("a query took: {} milliseconds".format((after - before).total_seconds() * 1000))
    if not len(root_node.children) == 0:
        for child in root_node.children:
            save_tree_to_db(child, topic, simple_request, conversation_id, platform, parent,
                            tweet_filter=tweet_filter)
