#!/usr/bin/env python3
import sys
from precure_1draw import *
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
import numpy as np

screen_name = sys.argv[1]

with open('themes.yaml') as f:
    themes = yaml.load(f)

def fav_plus_rt(tweet):
    return tweet['tweet']['favorite_count'] + tweet['tweet']['retweet_count']

tweets = get_tweets()
frs = {}
imgs = []
for date in reversed(sorted(themes)):
    frs[date] = [fav_plus_rt(tweet) for tweet in tweets
                 if tweet['date'] == date and tweet['tweet']['favorite_count'] < 150]

    tweet = [tweet for tweet in tweets
           if tweet['date'] == date and tweet['tweet']['user']['screen_name'] == screen_name]
    if tweet:
        tweet = tweet[0]
        fav = fav_plus_rt(tweet)
    else:
        continue

    fig, ax = plt.subplots()
    n, bins, patches = plt.hist(frs[date], color='skyblue', bins=50)
    idx = (np.abs(bins - fav)).argmin()
    #plt.text(bins[idx]-2, -1, str(fav), color='palevioletred')
    patches[idx].set_facecolor('palevioletred')
    fp = FontProperties(fname='Hiragino Sans GB W3.otf')
    ax.set_xlabel('Fav+RT', fontproperties=fp)
    ax.set_ylabel('人数', fontproperties=fp)
    filename = '{}-{}.svg'.format(screen_name, date)
    plt.savefig(path.expanduser('~/www/') + filename)

    total = len(frs[date])
    rank = sorted(frs[date], reverse=True).index(fav)
    percent = int((rank / total) * 100)

    imgs.append('''<p style="margin-left: 4em;">{}{} - {}<br>Fav+RT: {}<br>Rank: {} / {} ({}%)</p>
    <img src="{tweet}" style="max-width: 500px;">
    <img id="{src}" src="{src}">'''.format(get_labels_html(tweet, extra_class='user-label'), date, themes[date]['theme'],
                                           fav, rank, total, percent, src=filename,
                                           tweet='precure/1draw-collections/img/{}/{}'.format(tweet['tweet']['user']['id'],
                                                                                       tweet['imgs'][0]['filename'])))
template = '''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<link href="//netdna.bootstrapcdn.com/bootstrap/3.1.1/css/bootstrap.min.css" rel="stylesheet">
<script src="/js/google-analytics.js"></script>
</head>
<style>
body{{text-align: center; margin-top: 4em;}}
img{{display: inline-block; vertical-align: middle; margin-top: 4em;}}
.label{{margin: 0.5em;}}
</style>
<body>
{}
<hr>
<p>最終更新日時: {last_update}</p>
</body>
</html>'''.format('\n<hr style="margin: 2em;">\n'.join(imgs), last_update=last_update())

with open(path.expanduser('~/www/{}-rank.html').format(screen_name), 'w') as f:
    f.write(template)

