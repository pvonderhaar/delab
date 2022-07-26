import json

from delab.corpus.download_conversations import *
from delab.tw_connection_util import TwitterStreamConnector
from datetime import date

""" This is a django runscript, it can be started in the django home directory with
    $ python manage.py runscript [filename_no_ending]    
"""


def run():
    from_date = '2021-04-10T00:00:00.000-00:00'
    end_date = '2021-09-26T00:00:00.000-00:00'
    download_conversations("stud_schaefer",
                           "(from:AfD_Thueringen OR from:AfD_ThL OR from:BjoernHoecke OR from:AlternativeNRW OR from:AfD_FraktionNRW)",
                           max_data=False, fast_mode=True, start_date=from_date, end_date=end_date)

    #  download_conversations("migration", "chain OR wall", max_data=True)
    # download_conversations("Vaccination", ["covid_19", "vaccine", "getvaccienated", "vaccination"])
    # download_conversations("Migration", ["migration", "UNHCR"])
    # download_conversations("Impfung", ["rki_de"])
    # run_demo()
    # delete_rules_tests()


def delete_rules_tests():
    connector = TwitterStreamConnector()
    existing_rules = connector.get_rules()
    connector.delete_all_rules(existing_rules)


def pretty_print_stream(json_response):
    print(json.dumps(json_response, indent=4, sort_keys=True))
    return False


def run_demo():
    connector = TwitterStreamConnector()
    sample_rules = [
        {"value": "dog has:images", "tag": "dog pictures"},

    ]
    connector.delete_all_rules(sample_rules)
    sample_rules = [
        {"value": "#covid #vaccination lang:en"}
    ]
    connector.set_rules(sample_rules)
    query = {"tweet.fields": "created_at,", "expansions": "author_id", "user.fields": "created_at"}
    connector.get_stream(query, pretty_print_stream)
