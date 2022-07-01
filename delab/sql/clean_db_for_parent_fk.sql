delete
from delab_twcandidate cand
where cand.tweet_id in
      (SELECT distinct dt.id
       from delab_tweet dt
       where dt.tn_parent_id is not null
         and (dt.tn_parent_id not in
              (SELECT distinct twitter_id from delab_tweet)));

delete
from delab_tweet dt
where dt.tn_parent_id not in
      (SELECT distinct twitter_id from delab_tweet)
  and dt.tn_parent_id is not null;

delete
from delab_simplerequest sr
where sr.id not in (select distinct simple_request_id from delab_tweet);

delete from delab_tweet c where c.in_reply_to_user_id is not null and c.tn_parent_id is null;

delete from delab_tweet b where b.conversation_id in
(select distinct (a.conversation_id), count(a.text) as c from delab_tweet a
group by a.conversation_id having count(a.text) < 10);

delete from delab_tweet b where b.topic_id = 8;

select count(distinct author_id) from delab_tweet d where d.topic_id = 8;