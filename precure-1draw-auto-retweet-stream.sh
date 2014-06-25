#!/bin/zsh
pid=$(ps x | grep -i python | grep -v ipython | grep -v grep | grep auto_retweet_stream | perl -pi -e 's/(\d+).+auto_retweet_stream.+/$1/')
time=$(date +%H%M)
# if 2105 > time > 2100, kill the program
if [ $pid ] && [ 2105 -gt $time ] && [ $time -gt 2100 ]; then
    kill $pid
fi
# if not running, restart the program
if [ ! $pid ]; then
    cd /Users/shuuji/doc/pro/python/precure-1draw/
    ./precure_1draw.py 'auto_retweet_stream()' >> auto_retweet_stream.log
fi
