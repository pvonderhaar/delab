import re
import time
from datetime import datetime as dt
import logging
import traceback
from functools import reduce

import pandas as pd
import requests
from TwitterAPI import TwitterRequestError, TwitterConnectionError, TwitterPager
from django.db import IntegrityError
from django.db.backends import sqlite3

from delab.TwConversationTree import TreeNode
from delab.corpus.download_exceptions import ConversationNotInRangeException
from delab.magic_http_strings import TWEETS_SEARCH_All_URL
from delab.models import Tweet, TwTopic, SimpleRequest, PLATFORM, LANGUAGE
from delab.tw_connection_util import TwitterAPIWrapper
from delab.tw_connection_util import TwitterConnector
from django_project.settings import MAX_CANDIDATES
from util.abusing_lists import powerset

logger = logging.getLogger(__name__)


def download_conversations(topic_string, query_string, request_id=-1, language=LANGUAGE.ENGLISH, max_data=False,
                           fast_mode=False, conversation_filter=None, tweet_filter=None, platform=PLATFORM.TWITTER,
                           start_date=None, end_date=None):
    """ This downloads a random twitter conversation with the given hashtags.
        The approach is similar to https://cborchers.com/2021/03/23/notes-on-downloading-conversations-through-twitters-v2-api/
        The approach is to use the conversation id and api 2 to get the conversation, for API 1 this workaround
        was possible. https://stackoverflow.com/questions/24791980/is-there-any-work-around-on-fetching-twitter-conversations-using-latest-twitter/24799336

        Keyword arguments:
        topic_string -- the topic of the hashtags
        hashtags -- [hashtag1, hashtag2, ...], i.e. ["migration", "chainmigration"] (without the # symbol)
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
        pattern = r'[\(\)\[\]]'
        bag_of_words = re.sub(pattern, '', query_string).split(" ")
        combinations = list(powerset(bag_of_words))
        combinations_l = len(combinations) - 1
        combination_counter = 0
        for hashtag_set in combinations:
            if len(hashtag_set) > 0:
                combination_counter += 1
                new_query = " ".join(hashtag_set)
                get_matching_conversation(connector, new_query, topic, simple_request, platform, language=language,
                                          fast_mode=fast_mode, conversation_filter=conversation_filter,
                                          tweet_filter=tweet_filter, start_date=start_date, end_date=end_date)
                logger.debug("FINISHED combination {}/{}".format(combination_counter, combinations_l))
    else:
        # in case max_data is false we don't compute the powerset of the hashtags
        get_matching_conversation(connector, query_string, topic, simple_request, platform, language=language,
                                  fast_mode=fast_mode, conversation_filter=conversation_filter,
                                  tweet_filter=tweet_filter, start_date=start_date, end_date=end_date)

    connector = None  # precaution to terminate the thread and the http socket


def get_matching_conversation(connector,
                              query,
                              topic,
                              simple_request,
                              platform,
                              max_conversation_length=1000,
                              min_conversation_length=10,
                              language=LANGUAGE.ENGLISH,
                              max_number_of_candidates=MAX_CANDIDATES, fast_mode=False, conversation_filter=None,
                              tweet_filter=None, start_date=None, end_date=None):
    """ Helper Function that finds conversation_ids from the hashtags until the criteria are met.

        Keyword arguments:

        topic : the topic of the query
        simple_request: the query string in order to link the view
        max_conversation_length -- the max number of results
        min_conversation_length -- the min number of results
        max_number_of_candidates -- the number of candidates to look at,
                                    downloads num_candidates x max_conversation_length results (max results are 500)
                                    If a higher number of results are wanted, change the query or
                                    implement the streaming API. 
                                    The actual number of is the number of subsets from a given query 
                                    times the max_number of candidates given here!

    """
    if fast_mode:
        max_number_of_candidates = 10
        min_conversation_length = 3
        max_conversation_length = 100

    tweets_result = construct_query(connector, query, max_number_of_candidates, language, start_date=start_date,
                                    end_date=end_date)
    candidates = convert_tweet_result_to_list(tweets_result, topic, full_tweet=False)
    # deal_with_conversation_candidates_as_stream(candidates, hashtags, language, topic, min_results, max_results)
    downloaded_tweets = 0
    for candidate in candidates:
        try:
            logger.debug("selected candidate tweet {}".format(candidate))
            candidate_id = candidate.conversation_id

            root_node = retrieve_replies(candidate_id, max_conversation_length, language)

            if conversation_filter is not None:
                root_node = conversation_filter(root_node)

            if root_node is None:
                logger.error("found conversation_id that could not be processed")
                continue
            else:
                flat_tree_size = root_node.flat_size()
                logger.debug("retrieved node with number of children: {}".format(flat_tree_size))
                downloaded_tweets += flat_tree_size
                if min_conversation_length < flat_tree_size < max_conversation_length:
                    save_tree_to_db(root_node, topic, simple_request, candidate_id, platform, tweet_filter=tweet_filter)
                    logger.debug("found suitable conversation and saved to db {}".format(candidate_id))
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
    try:
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
        if tweet_filter is not None:
            tweet = tweet_filter(tweet)
            # the idea here is that the filter may have to save the tweet to create foreign keys
            # in this case the save method will fail because of an integrity error
            if tweet.pk is None:
                tweet.save()

        else:
            tweet.save()
        # after = dt.now()
        # logger.debug("a query took: {} milliseconds".format((after - before).total_seconds() * 1000))
        if not len(root_node.children) == 0:
            for child in root_node.children:
                save_tree_to_db(child, topic, simple_request, conversation_id, platform, parent,
                                tweet_filter=tweet_filter)
    except IntegrityError as e:
        raise ValueError("shittyy")
        # logger.debug("found tweet existing in database, not downloading the tree again")


def retrieve_replies(conversation_id, max_replies, language):
    """
    follows the tutorial from here https://towardsdatascience.com/mining-replies-to-tweets-a-walkthrough-9a936602c4d6

    Retrieves level 1 replies for a given conversation id
    Returns lists conv_id, child_id, text tuple which shows every reply's tweet_id and text in the last two lists

    """
    twapi = TwitterAPIWrapper.get_twitter_API()
    root = None

    # GET ROOT OF THE CONVERSATION
    r = twapi.request(f'tweets/:{conversation_id}',
                      {
                          'tweet.fields': 'author_id,conversation_id,created_at,in_reply_to_user_id,lang'
                      })

    for item in r:
        root = TreeNode(item, item["author_id"])
        # print(f'ROOT {root.id()}')

    # GET ALL REPLIES IN CONVERSATION

    pager = TwitterPager(twapi, 'tweets/search/recent',
                         {
                             'query': f'conversation_id:{conversation_id}',
                             'tweet.fields': 'author_id,conversation_id,created_at,in_reply_to_user_id,lang'
                         })
    orphans = []

    reply_count = 0
    for item in pager.get_iterator(wait=2):
        if reply_count == 10:
            logger.debug("downloading bigger conversation ...")
        if reply_count >= max_replies:
            raise ConversationNotInRangeException(reply_count)
        node_id = item["id"]
        parent_id = item["in_reply_to_user_id"]
        node = TreeNode(item, node_id, parent_id)

        # COLLECT ANY ORPHANS THAT ARE NODE'S CHILD
        orphans = [orphan for orphan in orphans if not node.find_parent_of(orphan)]
        # IF NODE CANNOT BE PLACED IN TREE, ORPHAN IT UNTIL ITS PARENT IS FOUND
        if root is not None:
            if not root.find_parent_of(node):
                orphans.append(node)
        reply_count += 1

    if len(orphans) > 0:
        logger.error('{} orphaned tweets for conversation {}'.format(len(orphans), conversation_id))
    return root


def reply_thread_maker(conv_ids):
    """
    Retrieves replies for a list of conversation ids (conv_ids Returns a dataframe with columns [conv_id, child_id,
    text] tuple which shows every reply's tweet_id and text in the last two columns
    """

    conv_id = []
    child_id = []
    text = []
    for id in conv_ids:
        conv_id1, child_id1, text1 = retrieve_replies(id)
        conv_id.extend(conv_id1)
        child_id.extend(child_id1)
        text.extend(text1)

    replies_data = {'conversation_id': conv_id,
                    'child_tweet_id': child_id,
                    'tweet_text': text}

    replies = pd.DataFrame(replies_data)
    return replies


def construct_query(connector, query, max_results, language=LANGUAGE.ENGLISH, start_date=None, end_date=None):
    """ downloads the tweets matching the hashtag list.
        using https://api.twitter.com/2/tweets/search/all

        Keyword arguments:
        :param connector -- TwitterConnector
        :param query -- twitter query query
        :param max_results -- the number of max length the conversation should have
        :param language:
        :returns json_object with found tweets
    """
    # twitter_accounts_query_1 = map(lambda x: "{} OR".format(x), hashtags)
    # twitter_accounts_query_1 = map(lambda x: "{} ".format(x), hashtags)
    # twitter_accounts_query_2 = reduce(lambda x, y: x + y, twitter_accounts_query_1)
    # twitter_accounts_query_3 = "(" + twitter_accounts_query_2 + ")"

    twitter_accounts_query = query + " lang:" + language
    logger.debug(twitter_accounts_query)
    params = {'query': twitter_accounts_query, 'max_results': max_results,
              "tweet.fields": "conversation_id,author_id"}
    if start_date is not None:
        params['start_time'] = start_date

    if end_date is not None:
        params['start_time'] = end_date

    json_result = connector.get_from_twitter(TWEETS_SEARCH_All_URL, params, True)
    # logger.info(json.dumps(json_result, indent=4, sort_keys=True))
    return json_result


def convert_tweet_result_to_list(tweets_result, topic, full_tweet=False, has_conversation_id=True):
    """ converts the raw data to python objects.

        Keyword arguments:
        tweets_result -- the json object
        topic -- the TwTopic object
        query -- the used query
        full_tweet -- a flag indicating whether author_id and other specific fields where queried
        has_conversation_id -- a flag if the conversation_id was added as a field

        returns [Tweet]
    """
    result_list = []
    if "data" not in tweets_result:
        return result_list
    else:
        twitter_data: list = tweets_result.get("data")
        for tweet_raw in twitter_data:
            tweet = Tweet()
            tweet.topic = topic
            tweet.text = tweet_raw.get("text")
            tweet.twitter_id = tweet_raw.get("id")
            if full_tweet:
                tweet.author_id = tweet_raw.get("author_id")
                tweet.created_at = tweet_raw.get("created_at")
            if has_conversation_id:
                tweet.conversation_id = tweet_raw.get("conversation_id")
            result_list.append(tweet)
    return result_list
