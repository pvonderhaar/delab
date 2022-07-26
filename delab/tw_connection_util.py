from typing import Callable

import praw
import tweepy
from TwitterAPI import TwitterAPI, TwitterRequestError
import os
import json
import yaml
import requests
from pathlib import Path
import time
import logging

from twarc import Twarc2

from delab.magic_http_strings import TWEETS_RULES_URL, TWEETS_STREAM_URL

logger = logging.getLogger(__name__)


class TwitterAPIWrapper:

    @staticmethod
    def get_twitter_API(api_version='2'):
        access_token, access_token_secret, bearer_token, consumer_key, consumer_secret = TwitterUtil.get_secret()
        api = TwitterAPI(consumer_key, consumer_secret, access_token, access_token_secret, api_version=api_version)
        return api


class TwitterUtil:

    @staticmethod
    def get_secret():
        settings_dir = os.path.dirname(__file__)
        project_root = Path(os.path.dirname(settings_dir)).absolute()
        keys_path = os.path.join(project_root, 'twitter/secret/keys_simple.yaml')
        # filename = "C:\\Users\\julia\\PycharmProjects\\djangoProject\\twitter\\secret\\keys_simple.yaml"
        filename = keys_path
        consumer_key = os.environ.get("CONSUMER_KEY")
        consumer_secret = os.environ.get("CONSUMER_SECRET")
        # access_token = ""
        # access_token_secret = ""
        # bearer_token = ""
        with open(filename) as f:
            my_dict = yaml.safe_load(f)
            if consumer_key != "":
                consumer_key = my_dict.get("consumer_key")
            if consumer_secret != "":
                consumer_secret = my_dict.get("consumer_secret")
            access_token = my_dict.get("access_token")
            access_token_secret = my_dict.get("access_token_secret")
            bearer_token = my_dict.get("bearer_token")
        return access_token, access_token_secret, bearer_token, consumer_key, consumer_secret

    @staticmethod
    def get_bot_secret():
        settings_dir = os.path.dirname(__file__)
        project_root = Path(os.path.dirname(settings_dir)).absolute()
        filename = os.path.join(project_root, 'twitter/secret/keys_bot.yaml')
        with open(filename) as f:
            my_dict = yaml.safe_load(f)
            consumer_key = my_dict.get("consumer_key")
            consumer_secret = my_dict.get("consumer_secret")
            access_token = my_dict.get("access_token")
            access_token_secret = my_dict.get("access_token_secret")
            bearer_token = my_dict.get("bearer_token")

        return access_token, access_token_secret, bearer_token, consumer_key, consumer_secret


@staticmethod
def get_reddit_secret():
    settings_dir = os.path.dirname(__file__)
    project_root = Path(os.path.dirname(settings_dir)).absolute()
    keys_path = os.path.join(project_root, 'twitter/secret/keys_simple.yaml')
    # filename = "C:\\Users\\julia\\PycharmProjects\\djangoProject\\twitter\\secret\\keys_simple.yaml"
    filename = keys_path
    reddit_secret = os.environ.get("reddit_secret")
    reddit_script_id = os.environ.get("reddit_script_id")

    with open(filename) as f:
        my_dict = yaml.safe_load(f)
        if reddit_secret != "":
            reddit_secret = my_dict.get("reddit_secret")
        if reddit_script_id != "":
            reddit_script_id = my_dict.get("reddit_script_id")
    return reddit_secret, reddit_script_id


class TwitterConnector:

    def __init__(self, instance_number=2):
        self.lines = None
        self.instance_number = instance_number

    def get_from_twitter(self, search_url, params, is_oauth2=True):
        if is_oauth2:
            headers = self.create_headers()
            json_response = self.__connect_to_endpoint(search_url, headers, params)
            return json_response
        else:
            # TODO implement other connection methods
            pass

    @staticmethod
    def create_headers():
        access_token, access_token_secret, bearer_token, consumer_key, consumer_secret = TwitterUtil.get_secret()
        headers = {"Authorization": "Bearer {}".format(bearer_token)}
        return headers

    @staticmethod
    def __connect_to_endpoint(search_url, headers, params):
        response = requests.request("GET", search_url, headers=headers, params=params)
        # print(response.status_code)
        if response.status_code != 200:
            if response.status_code == 429:  # too many requests
                raise TwitterRequestError()
            else:
                logger.error("{}{}".format(response.status_code, response.text))
        time.sleep(2)

        return response.json()


class TwitterStreamConnector:
    """ Get twitter corpus from rule based stream API.
        code adapted from the official example:
        https://github.com/twitterdev/Twitter-API-v2-sample-code/blob/main/Filtered-Stream/filtered_stream.py

        Keyword arguments:
        arg1 -- description
        arg2 -- description
    """

    @staticmethod
    def bearer_oauth(r):
        """
        Method required by bearer token authentication.
        """
        access_token, access_token_secret, bearer_token, consumer_key, consumer_secret = TwitterUtil.get_secret()
        r.headers["Authorization"] = f"Bearer {bearer_token}"
        r.headers["User-Agent"] = "v2FilteredStreamPython"
        return r

    def get_rules(self):
        response = requests.get(
            TWEETS_RULES_URL, auth=self.bearer_oauth
        )
        if response.status_code != 200:
            raise Exception(
                "Cannot get rules (HTTP {}): {}".format(response.status_code, response.text)
            )
        # print(json.dumps(response.json()))
        return response.json()

    def delete_all_rules(self, rules):
        if rules is None or "data" not in rules:
            return None

        ids = list(map(lambda rule: rule["id"], rules["data"]))
        payload = {"delete": {"ids": ids}}
        response = requests.post(
            TWEETS_RULES_URL,
            auth=self.bearer_oauth,
            json=payload
        )
        if response.status_code != 200:
            raise Exception(
                "Cannot delete rules (HTTP {}): {}".format(
                    response.status_code, response.text
                )
            )
        # print(json.dumps(response.json()))

    def set_rules(self, rules):
        """ description.

            Keyword arguments:
            arg1 -- the rules to filter the stream by

            # You can adjust the rules if needed
            sample_rules = [
                {"value": "dog has:images", "tag": "dog pictures"},
                {"value": "cat has:images -grumpy", "tag": "cat pictures"},
            ]
        """

        payload = {"add": rules}
        response = requests.post(
            TWEETS_RULES_URL,
            auth=self.bearer_oauth,
            json=payload,
        )
        if response.status_code != 201:
            raise Exception(
                "Cannot add rules (HTTP {}): {}".format(response.status_code, response.text)
            )
        # print(json.dumps(response.json()))

    def get_stream(self, query_params, callback: Callable = print):
        """ because the stream is ... well ... a stream, a delegate function is needed.

            Keyword arguments:
            query_params -- dictionary with the fields that are wanted from the result set
            callback -- a function that takes a json resultset as the only argument
                        should return FALSE if the connection is not needed anymore
        """
        response = requests.get(
            TWEETS_STREAM_URL, auth=self.bearer_oauth, stream=True, params=query_params
        )
        # print(response.status_code)
        if response.status_code != 200:
            raise Exception(
                "Cannot get stream (HTTP {}): {}".format(
                    response.status_code, response.text
                )
            )
        for response_line in response.iter_lines():
            if response_line == b'':
                break
            if response_line:
                json_response = json.loads(response_line)
                if json_response is None:
                    break
                should_continue = callback(json_response)
                if not should_continue:
                    break
                # print(json.dumps(json_response, indent=4, sort_keys=True))

    def get_from_twitter(self):
        pass


class DelabTwarc(Twarc2):
    def __init__(self):
        access_token, access_token_secret, bearer_token, consumer_key, consumer_secret = TwitterUtil.get_secret()
        super().__init__(consumer_key, consumer_secret, access_token, access_token_secret, bearer_token)


def get_praw():
    user_agent = "django_script:de.uni-goettingen.delab:v0.0.1 (by u/CalmAsTheSea)"
    reddit_secret, reddit_script_id = TwitterUtil.get_reddit_secret()
    reddit = praw.Reddit(client_id=reddit_script_id, client_secret=reddit_secret, user_agent=user_agent)
    return reddit


def send_tweet(text, tweet_id):
    # access_token, access_token_secret, bearer_token, consumer_key, consumer_secret = TwitterUtil.get_bot_secret()
    access_token, access_token_secret, bearer_token, consumer_key, consumer_secret = TwitterUtil.get_secret()
    auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
    auth.set_access_token(access_token, access_token_secret)
    # Creation of the actual interface, using authentication
    api = tweepy.API(auth)
    response = api.update_status(text, in_reply_to_status_id=tweet_id, auto_populate_reply_metadata=True)
    return response
