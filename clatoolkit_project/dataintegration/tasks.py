from __future__ import absolute_import

from clatoolkit.models import UserProfile, LearningRecord, UnitOffering
from dataintegration import socialmediabuilder
from django.db import connections

import json
import requests
from pprint import pprint
import dateutil.parser
import ast
from twython import Twython
import json
from bs4 import BeautifulSoup
from urllib2 import urlopen

def injest_twitter(sent_hashtag, course_code):
    get_oldtweets(course_code, sent_hashtag)
    #print "sent_hashtag:", sent_hashtag

    # Setup Twitter API Keys
    app_key = ""
    app_secret = ""
    oauth_token = ""
    oauth_token_secret = ""

    twitter = Twython(app_key, app_secret, oauth_token, oauth_token_secret)

    # Add hash to start of hashtag
    # hashtag = '#' + hashtag
    # see https://dev.twitter.com/rest/reference/get/search/tweets for search options
    count = 0
    next_max_id = None
    results = None
    while True:
        try:
            if count==0:
                print "count 0"
                results = twitter.search(q=sent_hashtag,count=100, result_type='mixed')
            else:
                print "count +"
                results = twitter.search(q=sent_hashtag,count=100,max_id=next_max_id, result_type='mixed')
            #print results
            insert_twitter_lrs(results['statuses'], course_code)

            if 'next_results' not in results['search_metadata']:
                    break
            else:
                next_results_url_params    = results['search_metadata']['next_results']
                next_max_id = next_results_url_params.split('max_id=')[1].split('&')[0]
                print next_max_id
            count += 1
        except KeyError:
                # When there are no more pages (['paging']['next']), break from the
                # loop and end the script.
                break

def insert_tweet(tweet, course_code):
    platform = "Twitter"
    platform_url = "http://www.twitter.com/"
    message = tweet['text']
    #print message
    timestamp = dateutil.parser.parse(tweet['created_at'])
    username = tweet['user']['screen_name']
    #print username, message
    fullname = tweet['user']['name']
    post_id = platform_url + username + '/status/' + str(tweet['id'])
    retweeted = False
    retweeted_id = None
    retweeted_username = None
    if 'retweeted_status' in tweet:
        retweeted = True
        #print tweet['retweeted_status']
        retweeted_id = platform_url + username + '/status/' + str(tweet['retweeted_status']['id'])
        retweeted_username = tweet['retweeted_status']['user']['screen_name']
        # get hashtags
    tags = []
    hashtags = tweet['entities']['hashtags']
    for hashtag in hashtags:
        #print hashtag['text']
        tag = hashtag['text']
        tags.append(tag)
    # get @mentions
    # favorite_count
    mentions = []
    atmentions = tweet['entities']['user_mentions']
    for usermention in atmentions:
        mention = "@" + str(usermention['screen_name'])
        tags.append(mention)
    #print post_id
    print twitterusername_exists(username, course_code)
    if twitterusername_exists(username, course_code):
        usr_dict = get_userdetails_twitter(username)
        if retweeted:
            insert_share(usr_dict, post_id, retweeted_id, message,username,fullname, timestamp, course_code, platform, platform_url, tags=tags, shared_username=retweeted_username)
        else:
            print post_id
            insert_post(usr_dict, post_id,message,fullname,username, timestamp, course_code, platform, platform_url, tags=tags)

def insert_twitter_lrs(statuses, course_code):
    #print statuses
    for tweet in statuses:
        insert_tweet(tweet, course_code)

def injest_facebook(data, paging, course_code):
    """
    Sends formatted data to LRS
    1. Parses facebook feed
    2. Uses construct_tincan_statement to format data ready to send for the LRS
    3. Sends to the LRS and Saves to postgres json field
    :param data: Graph API query data
    :param paging: Graph API query paging data: next page (if there is one)
    :param course_code: The unit offering code
    :return:
    """
    while True:
        try:
            insert_facebook_lrs(fb_feed=data, course_code=course_code)
            fb_resp = requests.get(paging['next']).json()
            data = fb_resp['data']
            if 'paging' not in fb_resp:
                break
            else:
                paging = fb_resp['paging']
        except KeyError:
            # When there are no more pages (['paging']['next']), break from the
            # loop and end the script.
            break

def insert_facebook_lrs(fb_feed, course_code):
    """
    1. Parses facebook feed
    2. Uses construct_tincan_statement to format data ready to send for the LRS
    3. Sends to the LRS and Saves to postgres json field
    :param fb_feed: Facebook Feed as dict
    :param course_code: The unit offering code
    :return:
    """
    platform = "Facebook"
    platform_url = "http://www.facebook.com/"
    for pst in fb_feed:
        if 'message' in pst:
            post_type = pst['type']
            created_time = dateutil.parser.parse(pst['created_time'])
            from_uid = pst['from']['id']
            from_name = pst['from']['name']
            post_id = pst['actions'][0]['link']
            message = pst['message']
            if fbid_exists(from_uid, course_code):
                usr_dict = get_userdetails(from_uid)
                insert_post(usr_dict, post_id,message,from_name,from_uid, created_time, course_code, platform, platform_url)

            if 'likes' in pst:
                for like in pst['likes']['data']:
                    like_uid = like['id']
                    like_name = like['name']

                    if fbid_exists(like_uid, course_code):
                        usr_dict = get_userdetails(like_uid)
                        insert_like(usr_dict, post_id, like_uid, like_name, message, course_code, platform, platform_url)

            if 'comments' in pst:
                for comment in pst['comments']['data']:
                    comment_created_time = comment['created_time']
                    comment_from_uid = comment['from']['id']
                    comment_from_name = comment['from']['name']
                    comment_message = comment['message']
                    comment_id = comment['id']
                    if fbid_exists(comment_from_uid, course_code):
                        usr_dict = get_userdetails(comment_from_uid)
                        insert_comment(usr_dict, post_id, comment_id, comment_message, comment_from_uid, comment_from_name, comment_created_time, course_code, platform, platform_url, parentusername=from_uid)

def twitterusername_exists(screen_name, course_code):
    tw_id_exists = False
    usrs = UserProfile.objects.filter(twitter_id__iexact=screen_name)
    #print usrs
    if len(usrs) > 0:
        usr_prof = usrs[0]
        usr = usr_prof.user
        user_in_course = check_ifuserincourse(usr, course_code)
        if user_in_course:
            tw_id_exists = True
        else:
            tw_id_exists = False
    return tw_id_exists

def check_ifuserincourse(user, course_id):
    print "check_ifuserincourse", UnitOffering.objects.filter(code=course_id, users=user)
    if UnitOffering.objects.filter(code=course_id, users=user).count() > 0:
        return True
    else:
        return False

def get_userdetails_twitter(screen_name):
    usr_dict = {'screen_name':screen_name}
    try:
        usr = UserProfile.objects.filter(twitter_id__iexact=screen_name).get()
    except UserProfile.DoesNotExist:
        usr = None

    if usr is not None:
        usr_dict['email'] = usr.user.email
        #usr_dict['lrs_endpoint'] = usr.ll_endpoint
        #usr_dict['lrs_username'] = usr.ll_username
        #usr_dict['lrs_password'] = usr.ll_password
    else:
        tmp_user_dict = {'aneesha':'aneesha.bakharia@qut.edu.au','dannmallet':'dg.mallet@qut.edu.au', 'LuptonMandy': 'mandy.lupton@qut.edu.au', 'AndrewResearch':'andrew.gibson@qut.edu.au', 'KirstyKitto': 'kirsty.kitto@qut.edu.au' , 'skdevitt': 'kate.devitt@qut.edu.au' }
        if screen_name in tmp_user_dict:
            usr_dict['email'] = tmp_user_dict[screen_name]
        else:
            usr_dict['email'] = 'test@gmail.com'
    return usr_dict

def fbid_exists(fb_id, course_code):
    fb_id_exists = False
    usrs = UserProfile.objects.filter(fb_id__iexact=fb_id)
    if len(usrs) > 0:
        usr_prof = usrs[0]
        usr = usr_prof.user
        user_in_course = check_ifuserincourse(usr, course_code)
        if user_in_course:
            fb_id_exists = True
        else:
            fb_id_exists = False
    return fb_id_exists

def forumid_exists(forum_id, course_code):
    forumid_exists = False
    usrs = UserProfile.objects.filter(forum_id__iexact=forum_id)
    print "forumid_exists", usrs
    if len(usrs) > 0:
        usr_prof = usrs[0]
        usr = usr_prof.user
        print "forumid_exists_user", usr
        user_in_course = check_ifuserincourse(usr, course_code)
        if user_in_course:
            forumid_exists = True
        else:
            forumid_exists = False
    return forumid_exists

def get_userdetails_forum(screen_name):
    usr_dict = {'screen_name':screen_name}
    try:
        usr = UserProfile.objects.filter(forum_id__iexact=screen_name).get()
    except UserProfile.DoesNotExist:
        usr = None

    if usr is not None:
        usr_dict['email'] = usr.user.email
        #usr_dict['lrs_endpoint'] = usr.ll_endpoint
        #usr_dict['lrs_username'] = usr.ll_username
        #usr_dict['lrs_password'] = usr.ll_password
    else:
            usr_dict['email'] = 'test@gmail.com'
    return usr_dict

'''
Forum Scraper Code
'''

def make_soup(url):
    html = urlopen(url).read()
    return BeautifulSoup(html, "lxml")

def get_forumlinks(url):
    forums = []

    soup = make_soup(url)
    forum_containers = soup.findAll("ul", "forum")
    for forum_item in forum_containers:
        forum_link = forum_item.find("a", "bbp-forum-title").attrs['href']
        forum_title = forum_item.find("a", "bbp-forum-title").string
        forum_text = forum_item.find("div", "bbp-forum-content").string
        if forum_text is None:
            forum_text = ""
        forum_user = "admin"
        forum_dict = {'forum_link': forum_link, 'forum_title': forum_title, 'forum_text': forum_text }
        forums.append(forum_dict)
        #print forums

    return forums

def get_topiclinks(url):
    topics = []

    soup = make_soup(url)
    topic_containers = soup.findAll("ul", "topic")
    for topic_item in topic_containers:
        topic_link = topic_item.find("a", "bbp-topic-permalink").attrs['href']
        topic_title = topic_item.find("a", "bbp-topic-permalink").string
        topic_author = topic_item.find("a", "bbp-author-avatar").attrs['href']
        #print topic_title, topic_link, topic_author[0:-1]
        topic_dict = {'topic_link': topic_link, 'topic_title': topic_title, 'topic_author': topic_author }
        topics.append(topic_dict)

    return topics

def get_posts(topic_url):
    posts = []

    soup = make_soup(topic_url)

    posts_container = soup.findAll("ul", "forums")

    post_containers = posts_container[0].findAll("li")
    for post in post_containers:
        if post.find("span", "bbp-reply-post-date") is not None:
            post_date = post.find("span", "bbp-reply-post-date").string
            post_permalink = post.find("a", "bbp-reply-permalink").attrs['href']
            post_user_link = post.find("a", "bbp-author-avatar").attrs['href']
            post_content = str(post.find("div", "bbp-reply-content"))
            #print "post_content_div", post_content
            #post_content = post_content_div.renderContents() #post_content_div.string #post_content_div.find("p").string
            #print "renderContents", post_content.renderContents()
            post_dict = {'post_permalink': post_permalink, 'post_user_link': post_user_link, 'post_date': post_date, 'post_content': post_content }
            posts.append(post_dict)

    return posts

def ingest_forum(url, course_code):
    platform = "Forum"

    forums  = get_forumlinks(url)
    for forum in forums:
        forum_link = forum["forum_link"]
        forum_title = forum["forum_link"]
        forum_text = forum["forum_link"]
        forum_author = "admin"
        #forum_authorlink =
        # insert forum in xapi
        #print forum_author, forumid_exists(forum_author, course_code)
        if forumid_exists(forum_author, course_code):
            usr_dict = get_userdetails_forum(forum_author)
            insert_post(usr_dict, forum_link,forum_text,forum_author,forum_author, dateutil.parser.parse("1 July 2015 2pm"), course_code, platform, url)
            #print "insert_post"

        topics = get_topiclinks(forum_link)
        for topic in topics:
            topic_link = topic["topic_link"]

            posts = get_posts(topic_link)
            for post in posts:
                post_permalink = post["post_permalink"]
                post_user_link = post["post_user_link"]
                post_date = post["post_date"]
                post_date = dateutil.parser.parse(post_date.replace(" at "," "))
                post_content = post["post_content"]
                post_user_link = post_user_link[:-1]
                post_username = post_user_link[(post_user_link.rfind('/')+1):]
                # insert each post in xapi
                #print post_user_link, post_user_link.rfind('/'), post_username, post_date
                if forumid_exists(post_username, course_code):
                    usr_dict = get_userdetails_forum(post_username)
                    print post_permalink, post_content, post_user_link, post_date
                    insert_comment(usr_dict, forum_link, post_permalink, post_content, post_username, post_username, post_date, course_code, platform, url, shared_username=forum_author)
                    print "insert_comment"

'''

End Forum Scraper Code
'''

def get_userdetails(fb_id):
    usr_dict = {'fb_id':fb_id}
    try:
        usr = UserProfile.objects.filter(fb_id__iexact=fb_id).get()
    except UserProfile.DoesNotExist:
        usr = None

    if usr is not None:
        usr_dict['email'] = usr.user.email
        #usr_dict['lrs_endpoint'] = usr.ll_endpoint
        #usr_dict['lrs_username'] = usr.ll_username
        #usr_dict['lrs_password'] = usr.ll_password

    return usr_dict

def get_oldtweets(course_code,hashtag):
    cursor = connections['tweetimport'].cursor()
    sql = "SELECT tweet FROM tweets WHERE hashtag='%s';" %(hashtag)
    #print sql
    row_count = cursor.execute(sql);
    result = cursor.fetchall()
    for row in result:
        insert_tweet(json.loads(row[0]), course_code)

def check_ifnotinlocallrs(course_code, platform, platform_id):
    lrs_matchingstatements = LearningRecord.objects.filter(course_code=course_code, platform=platform, platformid=platform_id)
    print lrs_matchingstatements
    if len(lrs_matchingstatements)==0:
        return True
    else:
        return False

def insert_post(usr_dict, post_id,message,from_name,from_uid, created_time, course_code, platform, platform_url, tags=[]):
    if check_ifnotinlocallrs(course_code, platform, post_id):
        stm = socialmediabuilder.socialmedia_builder(verb='created', platform=platform, account_name=from_uid, account_homepage=platform_url, object_type='Note', object_id=post_id, message=message, timestamp=created_time, account_email=usr_dict['email'], user_name=from_name, course_code=course_code, tags=tags)
        jsn = ast.literal_eval(stm.to_json())
        stm_json = socialmediabuilder.pretty_print_json(jsn)
        lrs = LearningRecord(xapi=stm_json, course_code=course_code, verb='created', platform=platform, username=from_uid, platformid=post_id)
        lrs.save()

def insert_like(usr_dict, post_id, like_uid, like_name, message, course_code, platform, platform_url):
    if check_ifnotinlocallrs(course_code, platform, post_id):
        stm = socialmediabuilder.socialmedia_builder(verb='liked', platform=platform, account_name=like_uid, account_homepage=platform_url, object_type='Note', object_id='post_id', message=message, account_email=usr_dict['email'], user_name=like_name, course_code=course_code)
        jsn = ast.literal_eval(stm.to_json())
        stm_json = socialmediabuilder.pretty_print_json(jsn)
        lrs = LearningRecord(xapi=stm_json, course_code=course_code, verb='liked', platform=platform, username=like_uid, platformid=post_id)
        lrs.save()

def insert_comment(usr_dict, post_id, comment_id, comment_message, comment_from_uid, comment_from_name, comment_created_time, course_code, platform, platform_url, shared_username=None):
    if check_ifnotinlocallrs(course_code, platform, comment_id):
        stm = socialmediabuilder.socialmedia_builder(verb='commented', platform=platform, account_name=comment_from_uid, account_homepage=platform_url, object_type='Note', object_id=comment_id, message=comment_message, parent_id=post_id, parent_object_type='Note', timestamp=comment_created_time, account_email=usr_dict['email'], user_name=comment_from_name, course_code=course_code )
        jsn = ast.literal_eval(stm.to_json())
        stm_json = socialmediabuilder.pretty_print_json(jsn)
        lrs = LearningRecord(xapi=stm_json, course_code=course_code, verb='commented', platform=platform, username=comment_from_uid, platformid=comment_id, platformparentid=post_id, parentusername=shared_username)
        lrs.save()

def insert_share(usr_dict, post_id, share_id, comment_message, comment_from_uid, comment_from_name, comment_created_time, course_code, platform, platform_url, tags=[], shared_username=None):
    if check_ifnotinlocallrs(course_code, platform, share_id):
        stm = socialmediabuilder.socialmedia_builder(verb='shared', platform=platform, account_name=comment_from_uid, account_homepage=platform_url, object_type='Note', object_id=share_id, message=comment_message, parent_id=post_id, parent_object_type='Note', timestamp=comment_created_time, account_email=usr_dict['email'], user_name=comment_from_name, course_code=course_code, tags=tags )
        jsn = ast.literal_eval(stm.to_json())
        stm_json = socialmediabuilder.pretty_print_json(jsn)
        lrs = LearningRecord(xapi=stm_json, course_code=course_code, verb='shared', platform=platform, username=comment_from_uid, platformid=share_id, platformparentid=post_id, parentusername=shared_username)
        lrs.save()
