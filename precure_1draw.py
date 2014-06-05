#!/usr/bin/env python3
# precure-1draw.py
#   - Retweet all the tweets with the hashtag and image(including 'http').
#   - Store tweets data.
#   - Generate html gallery which show images.

import re
import sys
import os
import time
import json
import locale
import datetime
import pytz
import pandas
from os import path
from dateutil.parser import parse
from io import BytesIO
from pprint import pprint

import requests
from bs4 import BeautifulSoup
from twython import Twython
from twython import TwythonStreamer
from twython import TwythonError
from PIL import Image

def auth():
    '''Authenticate the account and return the twitter instance.'''
    # read app credentials
    with open(cred_file) as f:
        app_key, app_secret, oauth_token, oauth_secret = \
                                                         [x.strip() for x in f]
    t = Twython(app_key, app_secret, oauth_token, oauth_secret)
    return t

def stream_auth():
    '''Authenticate the account and return the twitter stream instance.'''
    # read app credentials
    with open(cred_file) as f:
        app_key, app_secret, oauth_token, oauth_secret = \
                                                         [x.strip() for x in f]
    t = MyStreamer(app_key, app_secret, oauth_token, oauth_secret)
    return t

def auto_retweet_stream():
    '''Retweet all the tweet which have the hash_tag by stream.'''
    stream.statuses.filter(track=hash_tag + ' ' + triger)

class MyStreamer(TwythonStreamer):
    def on_success(self, tweet):
        if 'text' in tweet:
            log('{},{},{}(@{}),{}'.format(tweet['id'], str(datetime.datetime.now()), tweet['user']['name'], tweet['user']['screen_name'], tweet['text']))
            try:
                if not test:
                    retweet(tweet)
            except TwythonError as e:
                log(e)

    def on_error(self, status_code, tweet):
        log(str(datetime.datetime.now()) + ': sleep')
        time.sleep(3)

def auto_retweet_rest(past=2, not_retweet=False):
    '''Retweet all the tweet which have the hash_tag by rest.'''
    with open(stream_db_file) as f:
        stream_db = json.load(f)

    max_id=''
    for i in range(past):
        res = t.search(q=hash_tag + ' -RT', count=100, result_type='recent', max_id=max_id)
        tweets = res['statuses']
        max_id = tweets[-1]['id_str']
        for tweet in tweets:
            if (not tweet['id_str'] in stream_db) and (triger in tweet['text']):
                if not not_retweet:
                    retweet(tweet)
                else:
                    retweet(tweet, retweet=False)
        time.sleep(10)

def retweet(tweet='', id='', retweet=True):
    '''Retweet a tweet and record the json of the tweet.'''
    try:
        if not tweet:
            if id:
                tweet = t.show_status(id=id)
            else:
                print('Give a <tweet> or <id> argument.')
                return None
        else:
            id = tweet['id_str']
        with open('ignore_user.txt') as f:
            ignore_user = f.read().split()
        with open('ignore_word.txt') as f:
            ignore_word = f.read().split()
        with open('ignore_id.txt') as f:
            ignore_id = f.read().split()
        # filters to ignore
        if (tweet['user']['screen_name'] not in ignore_user) and (tweet['user']['id'] not in ignore_user) and (id not in ignore_id) and ([bool(re.search(x, tweet['text'])) for x in ignore_word].count(True) == 0) and (not tweet['entities']['user_mentions']) and (hash_tag in tweet['text']) and (triger in tweet['text']):
            with open(stream_db_file) as f:
                stream_db = json.load(f)

            if retweet and (id not in stream_db): # no "tweet['retweeted']": t.search does not this status
                t.retweet(id=id)
                #log('↻ this tweet is retweeted')

            stream_db[id] = tweet
            with open(stream_db_file, 'w') as f:
                json.dump(stream_db, f, indent=2)
            return tweet
        else:
            remove_from_db(id)
        
    except TwythonError as e:
        print('-'*8)
        if e.error_code == 404:
            print('*', e, id)
            print('Not found and delete:')
            remove_from_db(id)
        elif e.error_code == 403:
            print('*', e, id)
            print('Tweet has been locked and delete:')
            remove_from_db(id)
        elif e.error_code == 429: # API remaining = 0
            return stream_db[id]
        else:
            print('*', e)
            print('id:', id)
            pprint(tweet)
    
def log(message):
    with open('tweet.log', 'a') as f:
        f.write(message)
        f.write('\n--------\n')

def follow_back():
    '''Follow back all the followers who are not followed.'''
    followers = t.get_followers_list()['users']
    for user in followers:
        if not user['following']:
            t.create_friendship(screen_name=user['screen_name'])
            print('Follow back a new user:', user['screen_name'])

def store_image(tweet='', id=''):
    if not tweet:
        if id:
            try:
                tweet = t.show_status(id=id)
            except TwythonError as e:
                print(id, e)
                return
        else:
            print('Give a <tweet> or <id> argument.')
            return None
    with open(img_db_file) as f:
        img_db = json.load(f)
    img_db[tweet['id_str']] = []

    urls = []
    if 'media' in tweet['entities']: # tweet has official image 
        for url in tweet['entities']['media']:
            urls.append((url['media_url'], url['expanded_url']))
    else:
        for url in tweet['entities']['urls']:
            urls.append(url['expanded_url'])

    headers = {}
    for url in urls:
        if ['twimg.com' in x for x in url].count(True) != 0:
            (img_url, url) = url
        elif 'twitpic.com' in url:
            soup = BeautifulSoup(requests.get(url + '/full').text)
            img_url = soup('div', id='media-full')[0].img['src']
        elif 'photozou.jp' in url:
            soup = BeautifulSoup(requests.get(url).text)
            img_url = soup(itemprop='image')[0]['src']
        elif 'p.twipple.jp' in url:
            img_url = url.replace('p.twipple.jp/', 'p.twpl.jp/show/orig/')
        elif re.search(r'((jpeg)|(jpg)|(png)|(gif))(.*)$', url):
            img_url = url
        elif 'pixiv' in url:
            headers = {'referer': 'http://www.pixiv.net/'}
            soup = BeautifulSoup(requests.get(url).text)
            img_url = soup('img')[1]['src']
        elif 'togetter.com' in url:
            img_db[tweet['id_str']] = [{'url': url, 'img_url': False, 'filename': False}]
            continue
        elif re.search(r'twitter.com/.+?/status/', url):
            continue
        else:
            img_db[tweet['id_str']] = [{'url': url, 'img_url': False, 'filename': False}]
            continue

        img = requests.get(img_url, headers=headers).content

        # guess filename & extenstion
        # In [62]: re.search(r'(.+\.)(jpeg|jpg|png|gif)(.*)$', 'sample.png?extra').groups()
        # Out[62]: ('sample.', 'png', '?extra')
        # In [63]: re.search(r'(.+\.)(jpeg|jpg|png|gif)(.*)$', 'sample.png').groups()
        # Out[63]: ('sample.', 'png', '')

        match = re.search(r'(\.(jpeg|jpg|png|gif))', img_url)
        if match:
            filename = ''.join(re.search(r'(.+\.)(jpeg|jpg|png|gif)(.*)$', path.basename(img_url)).group(1,2))
        else:
            ext = Image.open(BytesIO(img)).format.lower()
            filename = path.basename(img_url) + '.' + ext

        # save image
        save_dir = img_dir + tweet['user']['id_str'] + '/'
        if not os.path.exists(save_dir):
            os.mkdir(save_dir)
        with open(save_dir + filename, 'wb') as f:
            f.write(img)
            print('Download: {} -> {}'.format(url, save_dir + filename))

        # update database
        img_db[tweet['id_str']] = [{'url': url, 'img_url': img_url, 'filename': filename}]

    with open(img_db_file, 'w') as f:
        json.dump(img_db, f, indent=2)

def redownload_all_images():
    with open(stream_db_file) as f:
        stream_db = json.load(f)
    for id, tweet in stream_db.items():
        store_image(tweet)

def get_search_remaining():
    api = t.get_application_rate_limit_status()['resources']['search']['/search/tweets']
    api_remaining = api['remaining']
    api_reset = datetime.datetime.fromtimestamp(api['reset'])
    return (api_remaining, api_reset)
        
def get_show_status_remaining():
    api = t.get_application_rate_limit_status()['resources']['statuses']['/statuses/show/:id']
    api_remaining = api['remaining']
    api_reset = datetime.datetime.fromtimestamp(api['reset'])
    return (api_remaining, api_reset)

def get_all_tweets():
    tweets = {}
    remaining, reset = get_search_remaining()

    max_id = ''
    count = 0
    while True:
        count += 1
        res = t.search(q=hash_tag + ' -RT', count=100, max_id=max_id)
        try:
            max_id = res['statuses'][-1]['id']
        except:
            break
        print('-'*8)
        print('max_id:', max_id)
        print('{}回目のsearchで{}まで取得'.format(count, get_date(res['statuses'][-1]['created_at'])))
        for tweet in res['statuses']:
            tweets[tweet['id_str']] = tweet
            print('Got:', tweet['id_str'])
        remaining, reset = get_search_remaining()
        print('API remaining: {}/180, reset: {}'.format(remaining, reset))
        time.sleep(30)
        if count == 20:
            break
    for id, tweet in tweets.items():
        retweet(tweet=tweet, retweet=False)

        # update database
        # remaining, reset = get_search_remaining()
        # now = datetime.datetime.now()
        # if remaining < 5:
        #     time.sleep((reset - now).seconds + 10)

def make_links_img_dir():
    stream = json.load(open('stream_db.json'))
    for id, tweet in stream.items():
        if not path.islink(img_dir + '-' + tweet['user']['screen_name']):
            os.symlink(os.getcwd() + '/' + img_dir + tweet['user']['id_str'],
                       os.getcwd() + '/' + img_dir + '-' + tweet['user']['screen_name'])
        
def get_date(time=''):
    '''
    Return a date as begins with 22:00.
    i.e. 2014-07-07 21:30 -> 2014-07-06
         2014-07-07 22:30 -> 2014-07-07

    Why 22:00?
      Because the theme is presented on 22:55,
      so if the threshold were 23:00,
      the theme is granted as the before day's.
      Further more, new illust never posted after 22:00.
      So it is safe.
    '''
    if not time:
        time = str(datetime.datetime.now().replace(tzinfo=pytz.timezone('Asia/Tokyo')))
    time = parse(time).astimezone(pytz.timezone('Asia/Tokyo'))
    if time.hour < 22:
        time = time.date() - datetime.timedelta(1)
    else:
        time = time.date()
    return str(time)

def update_theme():
    '''Get a new theme from the official account's tweets.'''
    themes = pandas.read_csv(themes_file, index_col=0)
    themes = themes.sort()

    tweets = t.get_user_timeline(screen_name='precure_1draw', count=100)
    for tweet in tweets:
        date = get_date(tweet['created_at'])
        if not date in themes:
            match = re.search(r'本日のテーマ.+“(.+)”', tweet['text'])
            if match:
                themes.loc[date, 'theme'] = match.group(1)
                if pandas.isnull(themes.loc[date, 'num']):
                    themes.loc[date, 'num'] = 0

    themes.to_csv(themes_file)
            
def add_to_db(id):
    '''Add a tweet manually from command line to the database by id.'''
    id = str(id)
    with open(stream_db_file) as f:
        stream_db = json.load(f)

    try:
        remaining, reset = get_show_status_remaining()
        now = datetime.datetime.now()
        if remaining == 0:
            time.sleep((reset - now).seconds + 10)
            print('API limit sleep to:', reset)
        tweet = t.show_status(id=id)
        stream_db[id] = tweet
        with open(stream_db_file, 'w') as f:
            json.dump(stream_db, f, indent=2)
        return tweet

    except TwythonError as e:
        if e.error_code == 404:
            print('404 Not found and delete:', id)
            remove_from_db(id)
        elif e.error_code == 403:
            print('403 Tweet has been locked and delete:', id)
            remove_from_db(id)
        elif e.error_code == 429: # API remaining = 0
            return stream_db[id]
        else:
            print('*', id, e)

def remove_from_db(id):
    id = str(id)
    '''Remove a specific id's tweet from two dbs, and add it to removed_stream_db.'''
    with open(stream_db_file) as f:
        stream_db = json.load(f)
    with open(removed_stream_db_file) as f:
        removed_stream_db = json.load(f)

    if id in stream_db:
        removed_stream_db[id] = stream_db.pop(id)

        with open(stream_db_file, 'w') as f:
            json.dump(stream_db, f, indent=2)
        with open(removed_stream_db_file, 'w') as f:
            json.dump(removed_stream_db, f, indent=2)

        print('Deleted a tweet:\nid: {}\n{}(@{})\n  {}\n--------'.format(id, removed_stream_db[id]['user']['name'], removed_stream_db[id]['user']['screen_name'], removed_stream_db[id]['text']))

def generate_date_html(date=''):
    '''Generate a specific date's html file.'''
    if not date:
        date = get_date()

    with open(stream_db_file) as f:
        stream_db = json.load(f)
    with open(img_db_file) as f:
        img_db = json.load(f)

    with open(date_html_template_file) as f:
        date_html_template = f.read()
    with open(tweet_html_template_file) as f:
        tweet_html_template = f.read()
    with open(tweet_admin_html_template_file) as f:
        tweet_admin_html_template = f.read()

    # generate html
    api = t.get_application_rate_limit_status()
    api_remaining = api['resources']['statuses']['/statuses/show/:id']['remaining']
    #api_limit = api['resources']['statuses']['/statuses/show/:id']['limit']
    #print('API Limit: {}/{}'.format(api_remaining, api_limit))
    # extract tweets of the specific date
    tweets = {}
    tweet_htmls = {}
    for id, tweet in stream_db.items(): 
        if get_date(tweet['created_at']) == date:
            tweets[id] = tweet

    count = 0
    for id, tweet in sorted(tweets.items()): # sort by time
        count += 1
        if api_remaining > len(tweets):
            #print('Updating #', count, ':', id)
            res = retweet(id=id, retweet=False)
            if res:
                tweet = res
            else:
                continue # skip if the tweet is removed
        if not id in img_db:
            store_image(stream_db[id])
            with open(img_db_file) as f:
                img_db = json.load(f)

        linked_text = tweet['text'].replace('#プリキュア版深夜の真剣お絵描き60分一本勝負', r'<a href="https://twitter.com/search?q=%23%E3%83%97%E3%83%AA%E3%82%AD%E3%83%A5%E3%82%A2%E7%89%88%E6%B7%B1%E5%A4%9C%E3%81%AE%E7%9C%9F%E5%89%A3%E3%81%8A%E7%B5%B5%E6%8F%8F%E3%81%8D60%E5%88%86%E4%B8%80%E6%9C%AC%E5%8B%9D%E8%B2%A0&amp;src=hash" data-query-source="hashtag_click" class="hashtag customisable" dir="ltr" rel="tag" data-scribe="element:hashtag">#<b>プリキュア版深夜の真剣お絵描き60分一本勝負</b></a>')

        # replace t.co to display_url and linkify
        if 'media' in tweet['entities']: # tweet has official image
            key = 'media'
        elif 'urls' in tweet['entities']:
            key = 'urls'
        else:
            continue
        for urls in tweet['entities'][key]:
            linked_text = linked_text.replace(urls['url'], '<a href="{}">{}</a>'.format(urls['expanded_url'], urls['display_url']))

        if not id in img_db:
            store_image(stream_db[id])
            with open(img_db_file) as f:
                img_db = json.load(f)

        if img_db[id][0]['filename']:
            img_src = img_dir + tweet['user']['id_str'] + '/' + img_db[id][0]['filename']
            img_style = ''
        else: # no image
            img_src = ''
            img_style='display: none;'

        time = parse(tweet['created_at'])
        for ribbon_name in ribbon_names:
            if ribbon_name == 'admin-':
                tweet_admin = tweet_admin_html_template.format(id=id, user_id=tweet['user']['id'])
            else:
                tweet_admin = ''
            tweet_html = tweet_html_template.format(id=id,
                                                    name=tweet['user']['name'],
                                                    screen_name=tweet['user']['screen_name'],
                                                    img_url=img_db[id][0]['url'],
                                                    img_src=img_src,
                                                    img_style=img_style,
                                                    icon_src=tweet['user']['profile_image_url_https'],
                                                    icon_src_bigger=tweet['user']['profile_image_url_https'].replace('_normal.', '_bigger.'),
                                                    text=linked_text,
                                                    time_iso=time.isoformat(),
                                                    time_utc=time.strftime('%Y年%m月%d日 %H:%M:%S (%Z)'),
                                                    time_jtc=time.astimezone(pytz.timezone('Asia/Tokyo')).strftime('%Y年%m月%d日 %I:%M %p'),
                                                    retweet_count=tweet['retweet_count'],
                                                    favorite_count=tweet['favorite_count'],
                                                    tweet_admin=tweet_admin)
            if ribbon_name not in tweet_htmls:
                tweet_htmls[ribbon_name] = []
            tweet_htmls[ribbon_name].append(tweet_html)
        
    #api = t.get_application_rate_limit_status()
    #api_remaining = api['resources']['statuses']['/statuses/show/:id']['remaining']
    #api_limit = api['resources']['statuses']['/statuses/show/:id']['limit']
    #print('API Limit: {}/{}'.format(api_remaining, api_limit))

    themes = pandas.read_csv(themes_file, index_col=0)
    theme = themes.loc[date, 'theme']
    for ribbon_name in ribbon_names:
        tweets = '\n\n'.join(tweet_htmls[ribbon_name])
        html = date_html_template.format(ribbon_name=ribbon_name[:-1],
                                     date=parse(date).strftime('%Y年%m月%d日'),
                                     theme=theme,
                                     tweets=tweets,
                                     last_update=datetime.datetime.now().strftime('%Y年%m月%d日 %H:%M:%S'))

        with open(html_dir + ribbon_name + date + '.html', 'w') as f:
            f.write(html)
            # print('Wrote a html:', date, theme)

    themes.to_csv(themes_file)

def update_num():
    '''Update work's number.'''
    themes = pandas.read_csv(themes_file, index_col=0).sort()
    with open(stream_db_file) as f:
        stream_db = json.load(f)

    nums = {}
    for date in themes.index:
        nums[date] = 0

    for id, tweet in stream_db.items():
        if not tweet['user']['screen_name'] == 'precure_1draw':
            nums[get_date(tweet['created_at'])] += 1
        
    for date, num in nums.items():
        if themes.loc[date, 'num'] != num:
            print('Update num of {}: {} -> {}'.format(date, int(themes.loc[date, 'num']), num))
        themes.loc[date, 'num'] = num
   
    themes.to_csv(themes_file)

def remove_no_url_tweets():
    with open(stream_db_file) as f:
        stream_db = json.load(f)
    ids = []
    for id, tweet in stream_db.items():
        if not triger in tweet['text']:
            print('Remove from stream_db:', id, tweet['text'])
            ids.append(id)
    for id in ids:
        stream_db.pop(id)
    with open(stream_db_file, 'w') as f:
        json.dump(stream_db, f)

def generate_index_html():
    locale.setlocale(locale.LC_ALL, '')
    with open(index_html_template_file) as f:
        index_html_template = f.read()
    themes = pandas.read_csv(themes_file, index_col=0).sort(ascending=0)
    for ribbon_name in ribbon_names:
        trs = []
        even = True
        for date, i in themes.iterrows():
            if even:
                row = 'even'
                even = False
            else:
                row = 'odd'
                even = True
            if path.exists(html_dir + ribbon_name + date + '.html'):
                link = '<a href="{ribbon_name}{date}.html">{theme}</a>'.format(ribbon_name=ribbon_name, date=date, theme=i['theme'])
            else:
                link = i['theme']
            if i['num'] == 0:
                num = ''
            else:
                num = int(i['num'])
            tr = '<tr class ="{row}"><td class="date">{date}</td><td>{link}</td><td class="num">{num}</td></tr>'.format(row=row, date=parse(date).strftime('%Y年%m月%d日(%a)'), link=link, theme=i['theme'], num=num)
            trs.append(tr)
        html = index_html_template.format(ribbon_name=ribbon_name[:-1],
                                          list=''.join(trs),
                                          last_update=datetime.datetime.now().strftime('%Y年%m月%d日 %H:%M:%S'))
             
        with open(html_dir + ribbon_name + 'index.html', 'w') as f:
            f.write(html)

def api_test():
    '''Test code for the time to revive API rate. -> max time = 15 min'''
    empty = False
    while True:
        api = t.get_application_rate_limit_status()
        api_remaining = api['resources']['statuses']['/statuses/show/:id']['remaining']
        api_limit = api['resources']['statuses']['/statuses/show/:id']['limit']
        for i in range(30):
            try:
                t.show_status(id=471760689229733889)
                if empty:
                    print(('{} {}/{}: ' + '|' * (api_remaining // 2)).format(datetime.datetime.now().time().strftime('%H:%M:%S'), api_remaining, api_limit))
                    empty = False
            except TwythonError:
                empty = True
                
        print(('{} {}/{}: ' + '|' * (api_remaining // 2)).format(datetime.datetime.now().time().strftime('%H:%M:%S'), api_remaining, api_limit))

        time.sleep(60)

if __name__ == '__main__':
    test = False

    stream_db_file = 'stream_db.json'
    removed_stream_db_file = 'removed_stream_db.json'
    img_db_file = 'img_db.json'
    themes_file = 'themes.csv'

    index_html_template_file = 'index_template.html'
    date_html_template_file = 'date_template.html'
    tweet_html_template_file = 'tweet_template.html'
    tweet_admin_html_template_file = 'tweet_admin_template.html'
    
    html_dir = 'html/'
    img_dir = 'img/'

    ribbon_names = ['', 'admin-']

    cred_file = '.credentials'

    t = auth()
    stream = stream_auth()
    
    if len(sys.argv) >= 2 and sys.argv[1] == 'test':
        sys.argv.pop(0)
        test = True
        stream_db_file = 'stream_db_test.json'
        removed_stream_db_file = 'removed_stream_db_test.json'
        img_db_file = 'img_db_test.json'
    hash_tag = sys.argv[1] # stream-search query
    triger = 'http'
    log('* track: {}, test: {}'.format(hash_tag + ' ' + triger, test))
    sys.argv.pop(0)

    if len(sys.argv) == 2:
        eval(sys.argv[1]) # run given name function
    else:
        print('''{} "#hash_tag" <command>
  auto_retweet_rest()    {}
  auto_retweet_stream()  {}
  follow_back()          {}
  store_image()          {}
  generate_date_html(date)    {}
  add_to_db(id)          {}
  remove_from_db(id)     {}
  retweet(tweet='', id='')            {}'''.format(sys.argv[0],
                                            auto_retweet_rest.__doc__,
                                            auto_retweet_stream.__doc__,
                                            follow_back.__doc__,
                                            store_image.__doc__,
                                            generate_date_html.__doc__,
                                            add_to_db.__doc__,
                                            remove_from_db.__doc__,
                                            retweet.__doc__))
