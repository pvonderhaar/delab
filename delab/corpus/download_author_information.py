# TODO download the author names, location etc. for the given authors
"""
 use this endpoint (also in magic https) GET https://api.twitter.com/2/users/253257813?user.fields=location,username,name
"""
import logging
import time

import requests
from TwitterAPI import TwitterRequestError, TwitterConnectionError
from annoying.functions import get_object_or_None
from django.db import IntegrityError
from django.db.models import Q

from delab.magic_http_strings import USER_URL
from delab.models import Tweet, TweetAuthor
from delab.tw_connection_util import TwitterConnector

logger = logging.getLogger(__name__)


def get_author_from_twitter(tweet, connector):
    params = {"user.fields": "name,username,location,public_metrics"}

    json_result = connector.get_from_twitter(USER_URL.format(tweet.author_id), params, True)
    # logger.info(json.dumps(json_result, indent=4, sort_keys=True))
    return json_result


def update_authors(simple_request_id=-1):
    if simple_request_id < 0:
        tweets = Tweet.objects.filter(Q(tw_author__isnull=True)).all()
    else:
        tweets = Tweet.objects.filter(Q(tw_author__isnull=True)
                                      & Q(simple_request_id=simple_request_id)).all()
    # create only one connector for quote reasons
    connector = TwitterConnector(1)

    for tweet in tweets:
        try:
            author = get_object_or_None(TweetAuthor, twitter_id=tweet.author_id)
            if author:
                tweet.tw_author = author
                tweet.save(update_fields=["tw_author"])
            else:
                author_payload = get_author_from_twitter(tweet, connector=connector)
                # print(author_payload)
                if "data" in author_payload:
                    author = TweetAuthor(
                        twitter_id=author_payload["data"]["id"],
                        name=author_payload["data"]["name"],
                        screen_name=author_payload["data"]["username"],
                        location=author_payload["data"].get("location", "unknown"),
                        followers_count=author_payload["data"]["public_metrics"]["followers_count"],
                        tweet=tweet
                    )
                    author.full_clean()
                    author.save()

        except IntegrityError:
            logger.error("author already exists")

        except TwitterRequestError as e:
            # traceback.print_exc()
            logger.info(
                "############# TwitterRequestError: Rate limit was exceeded while downloading author info." +
                " Going to sleep for 15!")
            time.sleep(15 * 60)

        except TwitterConnectionError as e:
            # traceback.print_exc()
            logger.info("############# TwitterConnectionError Rate limit was exceeded. 169")

        except Exception as e:
            # traceback.print_exc()
            logger.info("############# Exception Rate limit was exceeded. 176")

        except requests.exceptions.Timeout:
            # traceback.print_exc()
            logger.error("Timeout occurred")
