#!/bin/zsh
pid=$(ps x | grep -i 1draw.py | grep -v ipython | grep -v grep | grep auto_retweet_stream | perl -pi -e 's/(\d+).+auto_retweet_stream.+/$1/')
time=$(date +%H%M)
genre=$1; shift

# if 2105 > time > 2100, kill the program
if [ $pid ] && [ 2110 -gt $time ] && [ $time -gt 2100 ]; then
    kill $pid
fi
# if not running, restart the program
if [ ! $pid ]; then
    1draw $genre 'auto_retweet_stream()' >> auto_retweet_stream-mongo.log
fi
